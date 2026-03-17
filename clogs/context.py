"""Context tracking and buffering."""
from __future__ import annotations

import json

from clogs.config import CONTEXT_BUFFER_SIZE, JSON_BUFFER_MAX_LINES, KNOWN_FIELDS, PREFERRED_CONTEXT_FIELDS
from clogs.formatter import colorize, format_block


def detect_constant_fields(records: list[dict]) -> dict[str, str]:
    """Identify fields eligible for the context block using two-tier logic.

    Preferred fields only need a stable value across whichever records contain
    them. All other fields must appear in every record with the same value.
    Preferred fields are listed first in the result.

    Parameters
    ----------
    records : list of dict
        Buffered JSON log records.
    """
    if not records:
        return {}

    preferred: dict[str, str] = {}
    for k in sorted(PREFERRED_CONTEXT_FIELDS - KNOWN_FIELDS):
        values = [str(r[k]) for r in records if k in r]
        if values and len(set(values)) == 1:
            preferred[k] = values[0]

    # Keys present in every record (strict rule for non-preferred fields)
    common_keys = set(records[0].keys())
    for r in records[1:]:
        common_keys &= set(r.keys())

    common_keys -= KNOWN_FIELDS
    common_keys -= PREFERRED_CONTEXT_FIELDS

    strict: dict[str, str] = {}
    for k in sorted(common_keys):
        val = str(records[0][k])
        if all(str(r[k]) == val for r in records[1:]):
            strict[k] = val

    return {**preferred, **strict}


class ContextTracker:
    """Mutable state for one clogs run."""

    def __init__(self, verbose: bool = False, context_size: int = CONTEXT_BUFFER_SIZE):
        self.verbose = verbose
        self.context_size = context_size
        self.context_shown = False
        self.context_values: dict[str, str] = {}

        self.record_buffer: list[dict] = []
        self.buffering_records = not verbose and context_size > 0
        self.pre_buffer_lines: list[str] = []

        self.json_buffer: list[str] = []
        self.buffering_json = False

    def add_record(self, record: dict) -> bool:
        """Buffer a record. Returns True when the buffer is full."""
        self.record_buffer.append(record)
        return len(self.record_buffer) >= self.context_size

    def start_json_buffer(self, first_line: str) -> None:
        self.buffering_json = True
        self.json_buffer = [first_line]

    def append_json_line(self, line: str) -> bool:
        """Append a line. Returns True when the buffer is complete or hits the safety limit."""
        self.json_buffer.append(line)
        if line in ("}", "]") or len(self.json_buffer) > JSON_BUFFER_MAX_LINES:
            return True
        try:
            json.loads("\n".join(self.json_buffer))
            return True
        except json.JSONDecodeError:
            return False

    def take_json_buffer(self) -> list[str]:
        buf = self.json_buffer
        self.json_buffer = []
        self.buffering_json = False
        return buf

    def build_context_block(self) -> str | None:
        if self.context_shown or not self.record_buffer:
            return None
        self.context_shown = True

        ctx = detect_constant_fields(self.record_buffer)
        if not ctx:
            return None

        self.context_values = ctx.copy()

        note = colorize(
            f"  ↑ {len(ctx)} field{'s' if len(ctx) != 1 else ''} shown once above; repeats hidden until changed",
            "separator",
        )
        block = format_block("context", ctx)
        block_lines = block.split("\n")
        block_lines.insert(-1, note)
        return "\n".join(block_lines)
