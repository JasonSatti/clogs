"""Context detection and rolling baseline suppression."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import CONTEXT_FIELDS, KNOWN_FIELDS
from .formatter import colorize, format_block


def detect_constant_fields(records: list[dict[str, Any]]) -> dict[str, str]:
    if not records:
        return {}

    first_extras = {k: str(v) for k, v in records[0].items() if k not in KNOWN_FIELDS}
    constant: dict[str, str] = {}
    for k, v in first_extras.items():
        if all(str(r.get(k, "")) == v for r in records[1:]):
            constant[k] = v
    return constant


@dataclass
class ContextState:
    shown: bool = False
    values: dict[str, str] = field(default_factory=dict)


def build_context_block(records: list[dict[str, Any]], state: ContextState) -> str | None:
    if state.shown or not records:
        return None
    state.shown = True

    ctx: dict[str, Any] = {}
    for key in ("service", "env", "region"):
        if key in records[0]:
            ctx[key] = records[0][key]

    for key in sorted(CONTEXT_FIELDS):
        if key in records[0]:
            ctx[key] = records[0][key]

    for k, v in detect_constant_fields(records).items():
        if k not in ctx and k not in CONTEXT_FIELDS:
            ctx[k] = v

    if not ctx:
        return None

    state.values = {k: str(v) for k, v in ctx.items()}
    note = colorize(
        f"  ↑ {len(ctx)} fields shown once above; repeats hidden until changed",
        "separator",
    )
    block_lines = format_block("context", ctx).split("\n")
    block_lines.insert(-1, note)
    return "\n".join(block_lines)
