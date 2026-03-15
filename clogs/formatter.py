"""Rendering, colors, wrapping, and block formatting."""
from __future__ import annotations

import json
import os

from clogs.config import COLORS, KNOWN_FIELDS, LEVEL_WIDTH, LOCATION_WIDTH, MSG_COL, RESET


def colorize(text: str, color_key: str) -> str:
    code = COLORS.get(color_key, "")
    if not code:
        return text
    return f"{code}{text}{RESET}"


def _terminal_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 120


def format_level(level: str) -> str:
    level_upper = level.upper()
    color_key = level_upper.lower()
    if color_key not in COLORS:
        color_key = "info"
    display = "WARN" if level_upper == "WARNING" else level_upper
    return colorize(display.ljust(LEVEL_WIDTH), color_key)


def format_timestamp(ts: str) -> str:
    """Extract HH:MM:SS from an ISO timestamp (handles both T and space separators)."""
    if len(ts) >= 19 and ts[10] in ("T", " "):
        return colorize(ts[11:19], "timestamp")
    return colorize(ts[:8] if len(ts) >= 8 else ts, "timestamp")


def format_location(loc: str) -> str:
    if len(loc) > LOCATION_WIDTH:
        display = loc[: LOCATION_WIDTH - 1] + "…"
    else:
        display = loc.ljust(LOCATION_WIDTH)
    return colorize(display, "location")


def format_message(msg: object) -> str:
    if isinstance(msg, str):
        return _wrap_message(msg)
    return _wrap_message(json.dumps(msg, separators=(", ", ": ")))


def _wrap_message(msg_text: str) -> str:
    term_width = _terminal_width()
    available = term_width - MSG_COL
    if available < 20 or len(msg_text) <= available:
        return colorize(msg_text, "message")

    words = msg_text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
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


def format_tag(k: str, v: object) -> str:
    return colorize(f"{k}={v}", "tag")


def format_block(title: str, data: dict) -> str:
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


def _status_color(code: int) -> str:
    if 200 <= code < 300:
        return "info"
    if 400 <= code < 500:
        return "warning"
    if code >= 500:
        return "error"
    return "block_value"


def _format_body_value(v: object) -> str:
    """Format a single value from a parsed body, falling back to JSON for complex types."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(", ", ": "))
    return str(v)


def _render_body(body: object, key_prefix: str, lines: list[str]) -> None:
    """Render a parsed body value as structured lines."""
    if isinstance(body, dict):
        lines.append(key_prefix)
        for bk, bv in body.items():
            bkey = colorize(f"    {bk}:", "block_key")
            bval = colorize(f" {_format_body_value(bv)}", "block_value")
            lines.append(f"{bkey}{bval}")
    elif isinstance(body, list):
        lines.append(key_prefix)
        for i, item in enumerate(body):
            idx = colorize(f"    [{i}]:", "block_key")
            val = colorize(f" {_format_body_value(item)}", "block_value")
            lines.append(f"{idx}{val}")
    else:
        lines.append(f"{key_prefix}{colorize(f' {body}', 'block_value')}")


def format_return_value(obj: dict) -> str:
    bar = colorize("─" * 3, "separator")
    trail = colorize("─" * (66 - len("return")), "separator")
    header = f"{bar} {colorize('return', 'block_header')} {trail}"
    lines = ["\n" + header]
    for k, v in obj.items():
        key = colorize(f"  {k}:", "block_key")
        if k == "statusCode" and isinstance(v, int):
            val = colorize(f" {v}", _status_color(v))
            lines.append(f"{key}{val}")
        elif k == "body" and isinstance(v, str):
            try:
                body = json.loads(v)
                _render_body(body, key, lines)
            except (json.JSONDecodeError, ValueError):
                lines.append(f"{key}{colorize(f' {v}', 'block_value')}")
        else:
            val = colorize(f" {v}", "block_value")
            lines.append(f"{key}{val}")
    lines.append(colorize("─" * 70, "separator"))
    return "\n".join(lines)


def format_json_line(record: dict, context_values: dict[str, str], verbose: bool) -> str:
    """Format a JSON log record as a colored line with suppressed-repeat tags.

    Parameters
    ----------
    record : dict
        Parsed JSON log record.
    context_values : dict
        Rolling baseline of previously seen field values. Mutated in-place
        to track suppressions across calls.
    verbose : bool
        If True, show all fields and skip suppression.
    """
    lines: list[str] = []
    parts: list[str] = []

    if "timestamp" in record:
        parts.append(format_timestamp(record["timestamp"]))

    level = record.get("level", "INFO")
    parts.append(format_level(level))

    if "location" in record:
        parts.append(format_location(record["location"]))

    parts.append(colorize("│", "separator"))
    parts.append(format_message(record.get("message", "")))
    lines.append(" ".join(parts))

    # Show each extra field once, then suppress until its value changes
    tag_dict: dict = {}
    for k, v in record.items():
        if k in KNOWN_FIELDS:
            continue
        sv = str(v)
        if not verbose and context_values.get(k) == sv:
            continue
        tag_dict[k] = v
        if not verbose:
            context_values[k] = sv

    if tag_dict:
        indent = " " * MSG_COL
        prefix = indent + colorize("↳ ", "separator")

        items = list(tag_dict.items())
        first_k, first_v = items[0]
        lines.append(prefix + format_tag(first_k, first_v))
        for k, v in items[1:]:
            lines.append(indent + "  " + format_tag(k, v))

    return "\n".join(lines)


def format_passthrough(text: str) -> str:
    return colorize(text, "stderr")


def format_warning(msg: str) -> str:
    return colorize(f"  ⚠ {msg}", "non_json")


def format_runtime_line(level: str, timestamp: str, location: str, message: str) -> str:
    parts = [
        format_timestamp(timestamp),
        format_level(level),
        format_location(location),
        colorize("│", "separator"),
        _wrap_message(message),
    ]
    return " ".join(parts)


def format_stdlib_line(level: str, location: str, message: str) -> str:
    parts = [
        "        ",  # empty timestamp column
        format_level(level),
        format_location(location),
        colorize("│", "separator"),
        _wrap_message(message),
    ]
    return " ".join(parts)
