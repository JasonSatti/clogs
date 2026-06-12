"""Entrypoint and main processing loop."""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import TextIO

from clogs import __version__
from clogs.context import ContextTracker
from clogs.formatter import (
    colorize,
    format_block,
    format_json_line,
    format_passthrough,
    format_return_value,
    format_runtime_line,
    format_section_header,
    format_stdlib_line,
    format_warning,
    observe_record,
    reset_layout,
    set_color_enabled,
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


def _flush_json_buffer(buf: list[str], *, is_final: bool) -> str | None:
    raw = "\n".join(buf)
    try:
        obj = json.loads(raw)
        if is_final and isinstance(obj, dict):
            return format_return_value(obj)
        return colorize(json.dumps(obj, indent=2), "non_json")
    except json.JSONDecodeError:
        return colorize(raw, "non_json")


def _render_context_block(fields: dict[str, str]) -> str:
    note = colorize(
        f"  ↑ {len(fields)} field{'s' if len(fields) != 1 else ''} shown once above; repeats hidden until changed",
        "separator",
    )
    block = format_block("context", fields)
    lines = block.split("\n")
    lines.insert(-1, note)
    return "\n".join(lines)


def _render_startup_header() -> str:
    # Emitted after the chatter it labels (output streams immediately), so
    # the arrow points up at the startup section above.
    return format_section_header("↑ startup")


def _flush_record_buffer(ctx: ContextTracker, *, eof: bool = False) -> list[str]:
    if not ctx.buffering_records:
        return []
    ctx.buffering_records = False

    pending = ctx.pending_output
    out: list[str] = []

    # Pre-scan buffered records so the adaptive columns (location width,
    # timestamp presence) are sized before the first line renders.
    for item in pending:
        if isinstance(item, dict):
            observe_record(item)

    if ctx.has_records() and not ctx.verbose:
        fields = ctx.take_context()
        if fields:
            out.append(_render_context_block(fields))

    for i, item in enumerate(pending):
        if isinstance(item, dict):
            out.append(format_json_line(item, ctx.context_values, ctx.verbose))
        elif isinstance(item, list):
            # Terminal dict at EOF gets the return-block treatment; every
            # other multiline (mid-stream or non-dict) renders as generic.
            is_last = i == len(pending) - 1
            result = _flush_json_buffer(item, is_final=eof and is_last)
            if result:
                out.append(result)
        else:
            out.append(item)

    ctx.pending_output.clear()
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
    reset_layout()

    def _flush_held_as_generic() -> None:
        if ctx.held_multiline is None:
            return
        result = _flush_json_buffer(ctx.held_multiline, is_final=False)
        ctx.held_multiline = None
        if result:
            _write(stdout, result)
            if ctx.buffering_records:
                ctx.pre_record_streamed = True

    try:
        for line in stdin:
            stripped = line.strip()

            if ctx.buffering_json:
                # Keep indentation so a non-JSON fallback prints faithfully.
                if ctx.append_json_line(line.rstrip()):
                    buf = ctx.take_json_buffer()
                    if ctx.buffering_records and ctx.has_records():
                        # Inside the context window, after the first record.
                        # Queue in source order so flush can decide rendering.
                        ctx.add_multiline(buf)
                    else:
                        # Pre-record phase, verbose, or --context 0 — hold
                        # for one slot so a terminal invoke-return dict can
                        # still render as a return block at EOF.
                        ctx.held_multiline = buf
                continue

            parsed = parse_line(line)

            # A held multiline only loses its return-block eligibility when
            # the next line actually produces visible output. Blank lines
            # and suppressed noise (null, ddtrace spans) don't count.
            if (
                ctx.held_multiline is not None
                and parsed.line_type is not LineType.BLANK
                and parsed.line_type is not LineType.NOISE
            ):
                _flush_held_as_generic()

            if parsed.line_type is LineType.MULTILINE_JSON_START:
                ctx.start_json_buffer(line.rstrip())
                continue

            # A complete single-line JSON object with no message field —
            # possibly an invoke return value. Route it through the same
            # held/pending machinery as multi-line blobs so a terminal one
            # renders as a return block at EOF.
            if parsed.line_type is LineType.JSON_OBJECT:
                if ctx.buffering_records and ctx.has_records():
                    ctx.add_multiline([parsed.message])
                else:
                    ctx.held_multiline = [parsed.message]
                continue

            # Buffering phase: collect JSON records for context detection
            if ctx.buffering_records:
                if parsed.line_type is LineType.JSON_LOG:
                    # First record closes the pre-record streaming phase —
                    # emit the startup header retroactively if any chatter
                    # was streamed above.
                    if not ctx.has_records() and ctx.pre_record_streamed:
                        _write(stdout, _render_startup_header())
                    if ctx.add_record(parsed.record):
                        for out_line in _flush_record_buffer(ctx):
                            _write(stdout, out_line)
                    continue
                formatted = _format_parsed(parsed, ctx)
                if not formatted:
                    continue
                if ctx.has_records():
                    # Interleaved with buffered records — keep source order.
                    ctx.add_formatted(formatted)
                else:
                    # Pre-record chatter: stream immediately.
                    _write(stdout, formatted)
                    ctx.pre_record_streamed = True
                continue

            formatted = _format_parsed(parsed, ctx)
            if formatted:
                _write(stdout, formatted)

        # EOF handling. Any still-pending multiline at the very end is the
        # one case where we can prove it's terminal — render as return block.
        if ctx.held_multiline is not None:
            result = _flush_json_buffer(ctx.held_multiline, is_final=True)
            ctx.held_multiline = None
            if result:
                _write(stdout, result)
        if ctx.buffering_records:
            for out_line in _flush_record_buffer(ctx, eof=True):
                _write(stdout, out_line)
        if ctx.json_buffer:
            result = _flush_json_buffer(ctx.take_json_buffer(), is_final=True)
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
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="when to emit ANSI colors (default: auto — on for terminals, off when piped or NO_COLOR is set)",
    )
    args = parser.parse_args()
    if args.context is not None and args.context < 0:
        parser.error("--context must be >= 0")

    if args.color == "always":
        set_color_enabled(True)
    elif args.color == "never":
        set_color_enabled(False)
    else:
        set_color_enabled(sys.stdout.isatty() and not os.environ.get("NO_COLOR"))

    run(sys.stdin, sys.stdout, verbose=args.verbose, context_size=args.context)


if __name__ == "__main__":
    main()
