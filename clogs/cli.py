"""Entrypoint and main processing loop."""
from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from clogs import __version__
from clogs.context import ContextTracker
from clogs.formatter import (
    colorize,
    format_json_line,
    format_passthrough,
    format_return_value,
    format_runtime_line,
    format_stdlib_line,
    format_warning,
)
from clogs.parser import LineType, ParsedLine, parse_line


def _format_parsed(parsed: ParsedLine, ctx: ContextTracker) -> str | None:
    lt = parsed.line_type
    if lt is LineType.BLANK or lt is LineType.NOISE:
        return None
    if lt is LineType.JSON_LOG:
        return format_json_line(parsed.record, ctx.context_values, ctx.verbose)
    if lt is LineType.LAMBDA_RUNTIME:
        return format_runtime_line(
            parsed.level, parsed.timestamp, parsed.location, parsed.message
        )
    if lt is LineType.PYTHON_STDLIB:
        return format_stdlib_line(parsed.level, parsed.location, parsed.message)
    if lt is LineType.WARNING or lt is LineType.FRAMEWORK_WARNING:
        return format_warning(parsed.message)
    if lt is LineType.PASSTHROUGH:
        return format_passthrough(parsed.message)
    return None


def _flush_json_buffer(buf: list[str]) -> str | None:
    raw = "\n".join(buf)
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return format_return_value(obj)
        return colorize(json.dumps(obj, indent=2), "non_json")
    except json.JSONDecodeError:
        return colorize(raw, "non_json")


def _flush_record_buffer(ctx: ContextTracker) -> list[str]:
    """Flush buffered records and pending pre-context lines."""
    if not ctx.buffering_records:
        return []
    ctx.buffering_records = False

    out: list[str] = []

    if not ctx.verbose and ctx.record_buffer:
        block = ctx.build_context_block()
        if block:
            if ctx.pre_buffer_lines:
                bar = colorize("─── ", "separator")
                title = colorize("startup", "block_header")
                trail = colorize(" ───", "separator")
                out.append(f"{bar}{title}{trail}")
                out.extend(ctx.pre_buffer_lines)
                ctx.pre_buffer_lines.clear()
                out.append("")
            out.append(block)

    out.extend(ctx.pre_buffer_lines)
    ctx.pre_buffer_lines.clear()

    for record in ctx.record_buffer:
        out.append(format_json_line(record, ctx.context_values, ctx.verbose))
    ctx.record_buffer.clear()

    return out


def _write(stdout: TextIO, text: str) -> None:
    stdout.write(text + "\n")
    stdout.flush()


def run(
    stdin: TextIO,
    stdout: TextIO,
    verbose: bool = False,
    context_size: int | None = None,
) -> None:
    """Format logs from stdin to stdout."""
    kwargs: dict[str, bool | int] = {"verbose": verbose}
    if context_size is not None:
        kwargs["context_size"] = context_size
    ctx = ContextTracker(**kwargs)

    try:
        for line in stdin:
            stripped = line.strip()

            if ctx.buffering_json:
                if ctx.append_json_line(stripped):
                    result = _flush_json_buffer(ctx.take_json_buffer())
                    if result:
                        _write(stdout, result)
                continue

            parsed = parse_line(line)

            if parsed.line_type is LineType.MULTILINE_JSON_START:
                ctx.start_json_buffer(stripped)
                continue

            # Buffering phase: collect JSON records for context detection
            if ctx.buffering_records:
                if parsed.line_type is LineType.JSON_LOG:
                    if ctx.add_record(parsed.record):
                        for out_line in _flush_record_buffer(ctx):
                            _write(stdout, out_line)
                    continue
                formatted = _format_parsed(parsed, ctx)
                if formatted:
                    ctx.pre_buffer_lines.append(formatted)
                continue

            formatted = _format_parsed(parsed, ctx)
            if formatted:
                _write(stdout, formatted)

        if ctx.buffering_records:
            for out_line in _flush_record_buffer(ctx):
                _write(stdout, out_line)
        if ctx.json_buffer:
            result = _flush_json_buffer(ctx.take_json_buffer())
            if result:
                _write(stdout, result)

    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass


def main() -> None:
    """Run the CLI."""
    parser = argparse.ArgumentParser(
        description="Colorized, condensed log formatting for Lambda and Python logs",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show all fields on every line (no suppression)",
    )
    parser.add_argument(
        "-c",
        "--context",
        type=int,
        default=None,
        metavar="N",
        help="number of JSON records to inspect for the context block (default: 5, 0 to disable)",
    )
    args = parser.parse_args()
    if args.context is not None and args.context < 0:
        parser.error("--context must be >= 0")
    run(sys.stdin, sys.stdout, verbose=args.verbose, context_size=args.context)
