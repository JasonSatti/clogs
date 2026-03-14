#!/usr/bin/env python3
"""clogs — colorized structured log formatter for Lambda JSON logs.

Reads JSON log lines from stdin, formats them for human scanning.
Non-JSON lines pass through dimmed.

Usage:
    com sls invoke local -f clarity --stage prod --data '{}' | clogs
    com sls invoke local -f clarity --stage prod --data '{}' | clogs -v
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Color configuration — edit these to change the palette.
# Uses 256-color ANSI codes. Reference: https://256colors.com
# Set any value to "" to disable coloring for that element.
# ---------------------------------------------------------------------------
COLORS = {
    # Log levels
    "info": "\033[1;32m",        # green bold
    "warning": "\033[1;33m",     # yellow bold
    "error": "\033[1;31m",       # red bold
    "debug": "\033[38;5;245m",   # dim gray

    # Log content
    "message": "\033[0;37m",     # white — primary scan target
    "location": "\033[38;5;245m",     # dim gray — metadata, should recede
    "timestamp": "\033[38;5;240m",    # dark gray
    "tag": "\033[38;5;139m",           # muted purple — tag key=value
    "non_json": "\033[38;5;250m",     # light gray — warnings pass-through
    "stderr": "\033[38;5;240m",      # dark gray — generic stderr noise

    # Structural
    "separator": "\033[38;5;240m",    # dark gray — the pipes/dots between fields

    # Blocks (context header, return value)
    "block_header": "\033[38;5;173m",  # soft orange — block titles
    "block_key": "\033[38;5;245m",    # dim gray — block keys
    "block_value": "\033[38;5;252m",  # light white — block values
}

RESET = "\033[0m"

# Fixed width for level and location columns
LEVEL_WIDTH = 5
LOCATION_WIDTH = 22

# Known fields — extracted into the formatted layout
KNOWN_FIELDS = {"level", "location", "message", "timestamp", "service", "env"}

# Boilerplate fields shown once then suppressed (unless -v)
CONTEXT_FIELDS = {
    "function_arn",
    "function_name",
    "function_memory_size",
    "function_request_id",
    "cold_start",
    "xray_trace_id",
    "sampling_rate",
    "region",
}

# How many JSON lines to buffer for detecting constant fields
CONTEXT_BUFFER_SIZE = 5

# Runtime state
_verbose = False
_context_shown = False
_json_buffer: list[str] = []
_buffering_json = False
_context_values: dict[str, str] = {}  # fields shown in context block
_record_buffer: list[dict] = []  # buffer for detecting constant fields
_buffering_records = True  # start in buffering mode
_pre_buffer_lines: list[str] = []  # non-JSON lines received during buffering
_seen_first_log = False  # track if we've emitted a real log line yet


def colorize(text: str, color_key: str) -> str:
    """Wrap text in ANSI color from the COLORS config."""
    code = COLORS.get(color_key, "")
    if not code:
        return text
    return f"{code}{text}{RESET}"


def format_level(level: str) -> str:
    """Color-code and pad the log level."""
    level_upper = level.upper()
    color_key = level_upper.lower()
    if color_key not in COLORS:
        color_key = "info"
    display = "WARN" if level_upper == "WARNING" else level_upper
    return colorize(display.ljust(LEVEL_WIDTH), color_key)


def format_timestamp(ts: str) -> str:
    """Extract just HH:MM:SS from an ISO timestamp."""
    try:
        dt = datetime.fromisoformat(ts)
        return colorize(dt.strftime("%H:%M:%S"), "timestamp")
    except (ValueError, TypeError):
        return colorize(ts[:8] if len(ts) >= 8 else ts, "timestamp")


def format_location(loc: str) -> str:
    """Format location with fixed-width padding for alignment."""
    if len(loc) > LOCATION_WIDTH:
        display = loc[:LOCATION_WIDTH - 1] + "…"
    else:
        display = loc.ljust(LOCATION_WIDTH)
    return colorize(display, "location")


# Column where the message starts (after timestamp+level+location+│+space)
# timestamp(8) + sp(1) + level(5) + sp(1) + location(LOCATION_WIDTH) + sp(1) + │(1) + sp(1)
MSG_COL = 8 + 1 + 5 + 1 + LOCATION_WIDTH + 1 + 1 + 1


def wrap_message(msg_text: str) -> str:
    """Wrap long message text so continuation lines align with message column."""
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120

    available = term_width - MSG_COL
    if available < 20 or len(msg_text) <= available:
        return colorize(msg_text, "message")

    # Manual word wrap with character-level breaking for long tokens
    words = msg_text.split(" ")
    lines = []
    current = ""
    for word in words:
        # Break long words that exceed available width
        while len(word) > available:
            space_left = available - len(current) - (1 if current else 0)
            if space_left > 0 and current:
                current += " " + word[:space_left]
                word = word[space_left:]
            elif not current:
                lines.append(word[:available])
                word = word[available:]
            else:
                lines.append(current)
                current = ""

        test = f"{current} {word}".strip()
        if len(test) <= available:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    indent = " " * MSG_COL
    colored = [colorize(lines[0], "message")]
    for line in lines[1:]:
        colored.append(indent + colorize(line, "message"))
    return "\n".join(colored)


def format_message(msg) -> str:
    """Format the message field — string, dict, or list."""
    if isinstance(msg, str):
        return wrap_message(msg)
    formatted = json.dumps(msg, separators=(", ", ": "))
    return wrap_message(formatted)


def format_tag(k: str, v) -> str:
    """Format a single key=value tag."""
    return colorize(f"{k}={v}", "tag")


def format_tags(tag_dict: dict) -> str:
    """Format a dict of tags as a dim line."""
    return "  ".join(format_tag(k, v) for k, v in tag_dict.items())


def wrap_tags(prefix: str, tag_dict: dict, indent: str) -> list[str]:
    """Wrap tags at terminal width, aligning continuations under prefix."""
    try:
        term_width = os.get_terminal_size().columns
    except OSError:
        term_width = 120

    prefix_len = len(re.sub(r"\033\[[^m]*m", "", prefix))
    lines = []
    current_line = prefix
    current_len = prefix_len

    for i, (k, v) in enumerate(tag_dict.items()):
        tag = format_tag(k, v)
        tag_raw_len = len(f"{k}={v}")
        sep_len = 2 if i > 0 else 0  # "  " between tags

        if i > 0 and current_len + sep_len + tag_raw_len > term_width:
            # Wrap to next line
            lines.append(current_line)
            current_line = indent + "  " + tag
            current_len = len(indent) + 2 + tag_raw_len
        else:
            if i == 0:
                current_line = prefix + tag
                current_len = prefix_len + tag_raw_len
            else:
                current_line += "  " + tag
                current_len += sep_len + tag_raw_len

    if current_line:
        lines.append(current_line)
    return lines


def format_block(title: str, data: dict) -> str:
    """Format a titled key-value block (context, return, etc.)."""
    bar = colorize("─" * 3, "separator")
    trail = colorize("─" * (66 - len(title)), "separator")
    header = f"{bar} {colorize(title, 'block_header')} {trail}"
    lines = [header]
    for k, v in data.items():
        key = colorize(f"  {k}:", "block_key")
        val = colorize(f" {v}", "block_value")
        lines.append(f"{key}{val}")
    lines.append(colorize("─" * 70, "separator"))
    return "\n".join(lines)


def detect_constant_fields(records: list[dict]) -> dict[str, str]:
    """Find extra fields that have the same value across all buffered records."""
    if not records:
        return {}

    # Get all extra field keys from the first record
    first_extras = {
        k: str(v) for k, v in records[0].items()
        if k not in KNOWN_FIELDS
    }

    # Keep only fields that appear with the same value in ALL records
    constant = {}
    for k, v in first_extras.items():
        if all(str(r.get(k, "")) == v for r in records[1:]):
            constant[k] = v

    return constant


def build_context_block(records: list[dict]) -> str | None:
    """Build context block from buffered records, detecting constant fields."""
    global _context_shown, _context_values
    if _context_shown or not records:
        return None
    _context_shown = True

    ctx = {}

    # Identity fields from first record
    for key in ("service", "env", "region"):
        if key in records[0]:
            ctx[key] = records[0][key]

    # Powertools boilerplate from first record
    for key in sorted(CONTEXT_FIELDS):
        if key in records[0]:
            ctx[key] = records[0][key]

    # Detect constant extra fields across all buffered records
    constant = detect_constant_fields(records)
    for k, v in constant.items():
        if k not in ctx and k not in CONTEXT_FIELDS:
            ctx[k] = v

    if not ctx:
        return None

    _context_values = {k: str(v) for k, v in ctx.items()}

    note = colorize(
        f"  ↑ {len(ctx)} fields shown once above; repeats hidden until changed",
        "separator",
    )
    block = format_block("context", ctx)
    # Insert note before the closing separator
    block_lines = block.split("\n")
    block_lines.insert(-1, note)
    return "\n".join(block_lines)


def format_json_line(record: dict) -> str:
    """Format a parsed JSON log record into a colored one-liner."""
    lines = []
    parts = []

    # Timestamp
    if "timestamp" in record:
        parts.append(format_timestamp(record["timestamp"]))

    # Level
    level = record.get("level", "INFO")
    parts.append(format_level(level))

    # Location
    if "location" in record:
        parts.append(format_location(record["location"]))

    # Separator + Message
    parts.append(colorize("│", "separator"))
    msg = record.get("message", "")
    parts.append(format_message(msg))

    lines.append(" ".join(parts))

    # Tags — extras only (skip fields already in context block)
    tag_dict = {}
    for key in ("service", "env"):
        if key in record:
            if not _verbose and _context_values.get(key) == str(record[key]):
                continue
            tag_dict[key] = record[key]

    extras = {}
    for k, v in record.items():
        if k in KNOWN_FIELDS:
            continue
        if not _verbose and k in CONTEXT_FIELDS:
            continue
        sv = str(v)
        if not _verbose and _context_values.get(k) == sv:
            continue
        extras[k] = v
        # Update tracked value so this only shows once until it changes again
        if not _verbose:
            _context_values[k] = sv
    tag_dict.update(extras)

    if tag_dict:
        # Align under the message (after │)
        indent = " " * 40
        prefix = indent + colorize("↳ ", "separator")

        items = list(tag_dict.items())
        first_k, first_v = items[0]
        lines.append(prefix + format_tag(first_k, first_v))
        for k, v in items[1:]:
            lines.append(indent + "  " + format_tag(k, v))

    return "\n".join(lines)


def process_line(line: str) -> str:
    """Process a single line — JSON or passthrough."""
    stripped = line.strip()
    if not stripped:
        return ""

    # Try to parse as JSON
    if stripped.startswith("{"):
        try:
            record = json.loads(stripped)
            if isinstance(record, dict):
                # Suppress ddtrace span dumps
                if "traces" in record:
                    return ""
                if "message" in record:
                    return format_json_line(record)
        except json.JSONDecodeError:
            pass

    # Lambda runtime format: [INFO] 2026-03-14T13:35:29.236Z requestId [Thread - name] message
    lambda_match = re.match(
        r"^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s+"
        r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+"
        r"\S+\s+"  # request ID
        r"\[Thread\s*-\s*([^\]]+)\]\s+(.*)",
        stripped,
    )
    if lambda_match:
        level = lambda_match.group(1)
        ts = lambda_match.group(2)
        thread = lambda_match.group(3).strip()
        msg = lambda_match.group(4)
        parts = [
            format_timestamp(ts),
            format_level(level),
            format_location(thread),
            colorize("│", "separator"),
            wrap_message(msg),
        ]
        return " ".join(parts)

    # Python stdlib logging: LEVEL:logger:message
    match = re.match(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):(\S+):(.*)", stripped)
    if match:
        level, logger, msg = match.group(1), match.group(2), match.group(3).strip()
        parts = [
            "        ",  # empty timestamp column
            format_level(level),
            format_location(logger),
            colorize("│", "separator"),
            wrap_message(msg),
        ]
        return " ".join(parts)

    # Python warnings: collapse multi-line warnings to one-liner
    warn_match = re.match(r"^.*?(\w+Warning): (.+)", stripped)
    if warn_match:
        warn_type = warn_match.group(1)
        warn_msg = warn_match.group(2)
        return colorize(f"  ⚠ {warn_type}: {warn_msg}", "non_json")

    # Suppress warning continuation lines
    if (
        stripped.startswith("warnings.warn(")
        or stripped.startswith("* '")
        or stripped.startswith("  ")
    ):
        return ""

    # Serverless framework warnings
    if stripped.startswith("Warning:"):
        return colorize(f"  ⚠ {stripped}", "non_json")

    # Suppress bare null (lambda default return)
    if stripped == "null":
        return ""

    # Suppress ddtrace instrumentation noise
    if stripped.startswith("Configured ddtrace instrumentation"):
        return ""

    # Non-JSON line — generic stderr gets darker than warnings
    return colorize(stripped, "stderr")


def format_return_value(obj: dict) -> str:
    """Format the lambda return value as a clean summary block."""
    return "\n" + format_block("return", obj)


def flush_json_buffer() -> str | None:
    """Try to parse and format a buffered multi-line JSON block."""
    global _json_buffer, _buffering_json
    raw = "\n".join(_json_buffer)
    _json_buffer = []
    _buffering_json = False
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return format_return_value(obj)
        return colorize(json.dumps(obj, indent=2), "non_json")
    except json.JSONDecodeError:
        return colorize(raw, "non_json")


def main():
    """Read stdin line by line and format."""
    global _verbose, _buffering_json, _json_buffer, _buffering_records

    parser = argparse.ArgumentParser(
        description="Colorized structured log formatter for Lambda JSON logs",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="show all fields on every line (no suppression)",
    )
    args = parser.parse_args()
    _verbose = args.verbose
    _buffering_records = not _verbose

    def flush_record_buffer():
        """Emit context block and replay buffered records."""
        global _buffering_records

        if not _buffering_records:
            return
        _buffering_records = False

        if not _verbose and _record_buffer:
            ctx = build_context_block(_record_buffer)
            if ctx:
                # Print any non-JSON lines that arrived before context
                if _pre_buffer_lines:
                    bar = colorize("─── ", "separator")
                    title = colorize("startup", "block_header")
                    trail = colorize(" ───", "separator")
                    print(f"{bar}{title}{trail}", flush=True)
                    for pre_line in _pre_buffer_lines:
                        print(pre_line, flush=True)
                    _pre_buffer_lines.clear()
                    print("", flush=True)  # blank line before context
                print(ctx, flush=True)

        # Replay buffered non-JSON lines (if context wasn't shown)
        for pre_line in _pre_buffer_lines:
            print(pre_line, flush=True)
        _pre_buffer_lines.clear()

        # Replay buffered records
        for record in _record_buffer:
            print(format_json_line(record), flush=True)
        _record_buffer.clear()

    try:
        for line in sys.stdin:
            stripped = line.strip()

            # Buffer multi-line JSON (lambda return value)
            if _buffering_json:
                _json_buffer.append(stripped)
                if stripped == "}":
                    result = flush_json_buffer()
                    if result:
                        print(result, flush=True)
                continue

            # Detect start of multi-line JSON (bare { on its own line)
            if stripped == "{":
                _buffering_json = True
                _json_buffer = [stripped]
                continue

            # During record buffering phase, collect JSON records
            if _buffering_records:
                if stripped.startswith("{"):
                    try:
                        record = json.loads(stripped)
                        if isinstance(record, dict):
                            if "traces" in record:
                                continue
                            if "message" in record:
                                _record_buffer.append(record)
                                if len(_record_buffer) >= CONTEXT_BUFFER_SIZE:
                                    flush_record_buffer()
                                continue
                    except json.JSONDecodeError:
                        pass
                # Non-JSON during buffering — save for later
                formatted = process_line(line)
                if formatted:
                    _pre_buffer_lines.append(formatted)
                continue

            formatted = process_line(line)
            if formatted:
                print(formatted, flush=True)

        # Flush remaining buffers at EOF
        if _buffering_records:
            flush_record_buffer()
        if _json_buffer:
            result = flush_json_buffer()
            if result:
                print(result, flush=True)

    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
