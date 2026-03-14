"""CLI entry point for clogs."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from .config import CONTEXT_BUFFER_SIZE, CONTEXT_FIELDS, KNOWN_FIELDS
from .context import ContextState, build_context_block
from .formatter import colorize, format_block, format_level, format_location, format_message, format_tag, format_timestamp, wrap_message
from .parser import classify_line


@dataclass
class CliState:
    verbose: bool = False
    context: ContextState = field(default_factory=ContextState)
    record_buffer: list[dict[str, Any]] = field(default_factory=list)
    pre_buffer_lines: list[str] = field(default_factory=list)
    buffering_records: bool = True
    buffering_json: bool = False
    json_buffer: list[str] = field(default_factory=list)


def format_json_line(record: dict[str, Any], state: CliState) -> str:
    parts: list[str] = []
    if "timestamp" in record:
        parts.append(format_timestamp(record["timestamp"]))
    parts.append(format_level(record.get("level", "INFO")))
    if "location" in record:
        parts.append(format_location(record["location"]))
    parts.append(colorize("│", "separator"))
    parts.append(format_message(record.get("message", "")))

    lines = [" ".join(parts)]

    tag_dict: dict[str, Any] = {}
    for key in ("service", "env"):
        if key in record:
            if not state.verbose and state.context.values.get(key) == str(record[key]):
                continue
            tag_dict[key] = record[key]

    for key, value in record.items():
        if key in KNOWN_FIELDS:
            continue
        if not state.verbose and key in CONTEXT_FIELDS:
            continue
        sv = str(value)
        if not state.verbose and state.context.values.get(key) == sv:
            continue
        tag_dict[key] = value
        if not state.verbose:
            state.context.values[key] = sv

    if tag_dict:
        indent = " " * 40
        items = list(tag_dict.items())
        first_k, first_v = items[0]
        lines.append(indent + colorize("↳ ", "separator") + format_tag(first_k, first_v))
        for k, v in items[1:]:
            lines.append(indent + "  " + format_tag(k, v))

    return "\n".join(lines)


def render_parsed(line: str, state: CliState) -> str:
    parsed = classify_line(line)
    kind = parsed.kind
    if kind in {"empty", "suppressed"}:
        return ""
    if kind == "json_log":
        return format_json_line(parsed.data, state)
    if kind == "lambda_runtime":
        data = parsed.data
        parts = [
            format_timestamp(data["timestamp"]),
            format_level(data["level"]),
            format_location(data["location"]),
            colorize("│", "separator"),
            wrap_message(data["message"]),
        ]
        return " ".join(parts)
    if kind == "python_stdlib":
        data = parsed.data
        parts = [
            "        ",
            format_level(data["level"]),
            format_location(data["logger"]),
            colorize("│", "separator"),
            wrap_message(data["message"]),
        ]
        return " ".join(parts)
    if kind == "warning":
        return colorize(f"  ⚠ {parsed.data['warning']}: {parsed.data['message']}", "non_json")
    if kind == "serverless_warning":
        return colorize(f"  ⚠ {parsed.data}", "non_json")
    return colorize(parsed.data, "stderr")


def format_return_value(obj: Any) -> str:
    if isinstance(obj, dict):
        return "\n" + format_block("return", obj)
    return colorize(json.dumps(obj, indent=2), "non_json")


def flush_json_buffer(state: CliState) -> str:
    raw = "\n".join(state.json_buffer)
    state.json_buffer = []
    state.buffering_json = False
    try:
        return format_return_value(json.loads(raw))
    except json.JSONDecodeError:
        return colorize(raw, "non_json")


def flush_record_buffer(state: CliState) -> list[str]:
    if not state.buffering_records:
        return []
    state.buffering_records = False
    out: list[str] = []

    if not state.verbose and state.record_buffer:
        ctx = build_context_block(state.record_buffer, state.context)
        if ctx:
            if state.pre_buffer_lines:
                out.append(f"{colorize('─── ', 'separator')}{colorize('startup', 'block_header')}{colorize(' ───', 'separator')}")
                out.extend(state.pre_buffer_lines)
                state.pre_buffer_lines = []
                out.append("")
            out.append(ctx)

    out.extend(state.pre_buffer_lines)
    state.pre_buffer_lines = []
    out.extend(format_json_line(record, state) for record in state.record_buffer)
    state.record_buffer = []
    return out


def run(stdin: Any, stdout: Any, verbose: bool = False) -> None:
    state = CliState(verbose=verbose, buffering_records=not verbose)
    try:
        for line in stdin:
            stripped = line.strip()
            if state.buffering_json:
                state.json_buffer.append(stripped)
                if stripped == "}":
                    stdout.write(flush_json_buffer(state) + "\n")
                    stdout.flush()
                continue

            if stripped == "{":
                state.buffering_json = True
                state.json_buffer = [stripped]
                continue

            if state.buffering_records:
                parsed = classify_line(line)
                if parsed.kind == "json_log":
                    state.record_buffer.append(parsed.data)
                    if len(state.record_buffer) >= CONTEXT_BUFFER_SIZE:
                        for out_line in flush_record_buffer(state):
                            stdout.write(out_line + "\n")
                        stdout.flush()
                    continue
                rendered = render_parsed(line, state)
                if rendered:
                    state.pre_buffer_lines.append(rendered)
                continue

            rendered = render_parsed(line, state)
            if rendered:
                stdout.write(rendered + "\n")
                stdout.flush()

        if state.buffering_records:
            for out_line in flush_record_buffer(state):
                stdout.write(out_line + "\n")
        if state.json_buffer:
            stdout.write(flush_json_buffer(state) + "\n")
        stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        return


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Colorized structured log formatter for Lambda JSON logs"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show all fields on every line (no suppression)"
    )
    args = parser.parse_args()
    run(sys.stdin, sys.stdout, verbose=args.verbose)
