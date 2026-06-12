"""Entrypoint and main processing loop."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import TextIO

from clogs import __version__, settings
from clogs.config import LEVEL_ALIASES
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
    set_badges,
    set_color_enabled,
    set_delta,
    set_grep,
)
from clogs.parser import LineType, ParsedLine, parse_line

_LEVEL_RANKS = {
    "trace": 5,
    "debug": 10,
    "info": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
}


def _level_rank(level: str) -> int:
    key = level.lower()
    return _LEVEL_RANKS.get(LEVEL_ALIASES.get(key, key), 20)


def _passes(ctx: ContextTracker, level: str | None, haystack: str) -> bool:
    """Apply the --level and --grep filters."""
    if level is not None and ctx.min_level_rank is not None:
        if _level_rank(level) < ctx.min_level_rank:
            return False
    if ctx.grep is not None and not ctx.grep.search(haystack):
        return False
    return True


def _record_passes(ctx: ContextTracker, record: dict) -> bool:
    haystack = " ".join(f"{k}={v}" for k, v in record.items())
    return _passes(ctx, str(record.get("level", "INFO")), haystack)


def _record_request_id(record: dict) -> str | None:
    rid = record.get("request_id") or record.get("function_request_id")
    return str(rid) if rid else None


def _invocation_divider(request_id: str) -> str:
    return "\n" + format_section_header(f"invocation {request_id}")


def _format_record(record: dict, ctx: ContextTracker) -> str | None:
    """Filter, then format a JSON record — prefixed with an invocation
    divider when its request id starts a new invocation."""
    if not _record_passes(ctx, record):
        return None
    out = format_json_line(record, ctx.context_values, ctx.verbose)
    if ctx.note_request_id(_record_request_id(record)):
        out = f"{_invocation_divider(ctx.last_request_id)}\n{out}"
    return out


def _format_parsed(parsed: ParsedLine, ctx: ContextTracker) -> str | None:
    lt = parsed.line_type
    if lt is LineType.BLANK or lt is LineType.NOISE:
        return None
    if lt is not LineType.PASSTHROUGH and lt is not LineType.TRACEBACK_START:
        ctx.in_traceback = False
    if lt is LineType.JSON_LOG:
        return _format_record(parsed.record, ctx)
    if lt is LineType.LAMBDA_START:
        ctx.note_request_id(parsed.message)
        return _invocation_divider(parsed.message)
    if lt is LineType.LAMBDA_REPORT:
        return format_block("report", parsed.record)
    if lt is LineType.LAMBDA_RUNTIME:
        if not _passes(ctx, parsed.level, f"{parsed.message} {parsed.location}"):
            return None
        return format_runtime_line(
            parsed.level, parsed.timestamp, parsed.location, parsed.message
        )
    if lt is LineType.PYTHON_STDLIB:
        if not _passes(ctx, parsed.level, f"{parsed.message} {parsed.location}"):
            return None
        return format_stdlib_line(
            parsed.level, parsed.location, parsed.message, parsed.timestamp
        )
    if lt is LineType.TRACEBACK_START:
        ctx.in_traceback = True
        if not _passes(ctx, None, parsed.message):
            return None
        return colorize(parsed.message, "message_error")
    if lt is LineType.WARNING or lt is LineType.FRAMEWORK_WARNING:
        if not _passes(ctx, None, parsed.message):
            return None
        return format_warning(parsed.message)
    if lt is LineType.PASSTHROUGH:
        in_traceback_tail = ctx.in_traceback and not parsed.message.startswith(
            (" ", "\t")
        )
        if in_traceback_tail:
            ctx.in_traceback = False
        if not _passes(ctx, None, parsed.message):
            return None
        if in_traceback_tail:
            return colorize(parsed.message, "message_error")
        if ctx.in_traceback:
            return colorize(parsed.message, "non_json")
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
            formatted = _format_record(item, ctx)
            if formatted:
                out.append(formatted)
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
    min_level: str | None = None,
    grep: "str | re.Pattern | None" = None,
    delta: bool = False,
) -> None:
    """Format logs from stdin to stdout.

    Note: color and badge styling are process-global formatter state
    (see set_color_enabled / set_badges); adaptive layout state is reset
    per call. The CLI configures styling before calling this.
    """
    kwargs: dict[str, bool | int] = {"verbose": verbose}
    if context_size is not None:
        kwargs["context_size"] = context_size
    ctx = ContextTracker(**kwargs)
    reset_layout()
    set_delta(delta)

    pattern = re.compile(grep, re.IGNORECASE) if isinstance(grep, str) else grep
    set_grep(pattern)
    ctx.grep = pattern
    ctx.min_level_rank = _level_rank(min_level) if min_level else None

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
            if ctx.buffering_json:
                # Keep indentation so a non-JSON fallback prints faithfully.
                if ctx.append_json_line(line.rstrip()):
                    ctx.stash_blob(ctx.take_json_buffer())
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
            # possibly an invoke return value. Same routing as multi-line
            # blobs so a terminal one renders as a return block at EOF.
            if parsed.line_type is LineType.JSON_OBJECT:
                ctx.stash_blob([parsed.message])
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
                    # Lifecycle output (START dividers, REPORT blocks) is
                    # structural, not startup chatter — it must not earn a
                    # `↑ startup` header. A START also closes any open
                    # startup section above it.
                    if parsed.line_type is LineType.LAMBDA_START and ctx.pre_record_streamed:
                        _write(stdout, _render_startup_header())
                        ctx.pre_record_streamed = False
                    _write(stdout, formatted)
                    if parsed.line_type not in (
                        LineType.LAMBDA_START,
                        LineType.LAMBDA_REPORT,
                    ):
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
    config_defaults = settings.apply(settings.load())
    parser = argparse.ArgumentParser(
        prog="clogs",
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
        action=argparse.BooleanOptionalAction,
        default=None,
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
    parser.add_argument(
        "--badges",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="render log levels as filled chips (Datadog status-chip style)",
    )
    parser.add_argument(
        "-l",
        "--level",
        default=None,
        metavar="LEVEL",
        help="minimum level to show (debug, info, warning, error, critical; 'all' clears a config default)",
    )
    parser.add_argument(
        "-g",
        "--grep",
        default=None,
        metavar="PATTERN",
        help="only show records matching PATTERN (case-insensitive regex); matches are highlighted",
    )
    parser.add_argument(
        "-d",
        "--delta",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="show elapsed time since the previous record",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        metavar="-- COMMAND",
        help="run COMMAND and format its merged stdout/stderr (avoids the 2>&1 dance)",
    )
    # Value options take config defaults directly — any CLI value overrides.
    # Booleans merge after parsing instead, so --no-X can override a config
    # `true` (set_defaults would make that impossible for store_true flags).
    parser.set_defaults(
        **{k: v for k, v in config_defaults.items() if k in ("color", "context", "level")}
    )
    args = parser.parse_args()

    verbose = args.verbose if args.verbose is not None else config_defaults.get("verbose", False)
    badges = args.badges if args.badges is not None else config_defaults.get("badges", False)
    delta = args.delta if args.delta is not None else config_defaults.get("delta", False)

    if args.context is not None and args.context < 0:
        parser.error("--context must be >= 0")
    level = args.level
    if level is not None and level.lower() == "all":
        level = None  # escape hatch for a config-file default
    if level is not None:
        key = level.lower()
        if LEVEL_ALIASES.get(key, key) not in _LEVEL_RANKS:
            parser.error(
                f"invalid level {level!r} (choose from: debug, info, warning, error, critical, all)"
            )
    grep = None
    if args.grep is not None:
        try:
            grep = re.compile(args.grep, re.IGNORECASE)
        except re.error as exc:
            parser.error(f"invalid --grep pattern: {exc}")

    if args.color == "always":
        set_color_enabled(True)
    elif args.color == "never":
        set_color_enabled(False)
    else:
        set_color_enabled(sys.stdout.isatty() and not os.environ.get("NO_COLOR"))

    set_badges(badges)

    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    proc = None
    source = sys.stdin
    if command:
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            parser.error(f"command not found: {command[0]}")
        assert proc.stdout is not None
        source = proc.stdout

    run(
        source,
        sys.stdout,
        verbose=verbose,
        context_size=args.context,
        min_level=level,
        grep=grep,
        delta=delta,
    )
    if proc is not None:
        sys.exit(proc.wait())


if __name__ == "__main__":
    main()
