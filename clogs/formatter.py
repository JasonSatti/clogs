"""Formatting helpers for rendered output."""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime

from clogs import config
from clogs.config import (
    BADGE_COLORS,
    BAR_GLYPH,
    BAR_WIDTH,
    BLOCK_WIDTH,
    COLORS,
    KNOWN_FIELDS,
    LEVEL_ALIASES,
    LEVEL_WIDTH,
    RESET,
    TIMESTAMP_WIDTH,
)

# None = decide from NO_COLOR alone (library / test usage). The CLI sets an
# explicit value from --color and isatty().
_color_override: bool | None = None

# Adaptive layout state. The location column sizes itself to the longest
# location seen so far (capped at LOCATION_WIDTH) and the timestamp column
# only exists once a timestamped line has been seen — so streams without
# timestamps or with short locations don't pay for fixed-width dead space.
_loc_width = 0
_ts_seen = False

# --badges: render levels as filled chips (Datadog status-chip style)
_badges = False

# --delta: show elapsed time since the previous timestamped record
_delta_on = False
_prev_dt: datetime | None = None
DELTA_WIDTH = 7

# --grep: highlight matches in messages and tags
_grep: re.Pattern | None = None


def set_badges(enabled: bool) -> None:
    global _badges
    _badges = enabled


def set_delta(enabled: bool) -> None:
    global _delta_on, _prev_dt
    _delta_on = enabled
    _prev_dt = None


def set_grep(pattern: re.Pattern | None) -> None:
    global _grep
    _grep = pattern


def set_color_enabled(enabled: bool | None) -> None:
    global _color_override
    _color_override = enabled


def _color_enabled() -> bool:
    if _color_override is not None:
        return _color_override
    # no-color.org: presence of a non-empty NO_COLOR disables color.
    return not os.environ.get("NO_COLOR")


def reset_layout() -> None:
    global _loc_width, _ts_seen, _prev_dt
    _loc_width = 0
    _ts_seen = False
    _prev_dt = None


def observe_location(loc: str) -> None:
    global _loc_width
    if len(loc) > _loc_width:
        _loc_width = min(len(loc), config.LOCATION_WIDTH)


def observe_timestamp() -> None:
    global _ts_seen
    _ts_seen = True


def observe_record(record: dict) -> None:
    """Register a JSON record's layout-relevant fields before rendering."""
    if "timestamp" in record:
        observe_timestamp()
    if "location" in record:
        observe_location(str(record["location"]))


def _level_cell_width() -> int:
    # Badge chips are uniform width, keeping full level names. Sized so the
    # 4-letter levels (INFO, WARN, CRIT — the common ones) center perfectly;
    # 5-letter levels carry an imperceptible half-character offset, which is
    # unavoidable for mixed-length words on a character grid.
    return LEVEL_WIDTH + 3 if _badges else LEVEL_WIDTH


def _sep_col() -> int:
    """Column of the `│` separator under the current adaptive layout."""
    col = BAR_WIDTH + _level_cell_width() + 1
    if _ts_seen:
        col += TIMESTAMP_WIDTH + 1
        if _delta_on:
            col += DELTA_WIDTH + 1
    if _loc_width:
        col += _loc_width + 1
    return col


def _msg_col() -> int:
    return _sep_col() + 2


def colorize(text: str, color_key: str) -> str:
    if not _color_enabled():
        return text
    code = COLORS.get(color_key, "")
    if not code:
        return text
    return f"{code}{text}{RESET}"


def _terminal_width() -> int:
    # shutil honors the COLUMNS env var and never raises when piped.
    return shutil.get_terminal_size(fallback=(120, 24)).columns


_LEVEL_DISPLAY = {"WARNING": "WARN", "CRITICAL": "CRIT"}

_MESSAGE_COLORS = {
    "error": "message_error",
    "critical": "message_error",
    "warning": "message_warning",
}


def _level_color_key(level: str) -> str:
    key = level.lower()
    key = LEVEL_ALIASES.get(key, key)
    return key if key in COLORS else "info"


def _bar(level_key: str) -> str:
    """Status bar at the left edge of a log row, colored by level."""
    return colorize(BAR_GLYPH, level_key)


def _cont_prefix(level_key: str) -> str:
    """Prefix for continuation lines (wrapped messages, tags): the status
    bar plus the gutter rule, so a multi-line record reads as one row."""
    return (
        colorize(BAR_GLYPH, level_key)
        + " " * (_sep_col() - 1)
        + colorize("│", "separator")
        + " "
    )


def format_level(level: str) -> str:
    color_key = _level_color_key(level)
    level_upper = level.upper()
    display = _LEVEL_DISPLAY.get(level_upper, level_upper)[:LEVEL_WIDTH]
    if _badges:
        chip = display.center(_level_cell_width())
        code = BADGE_COLORS.get(color_key, "") if _color_enabled() else ""
        if code:
            return f"{code}{chip}{RESET}"
        return chip
    return colorize(display.ljust(LEVEL_WIDTH), color_key)


def format_timestamp(ts: str) -> str:
    """Extract HH:MM:SS from an ISO timestamp (handles both T and space separators)."""
    if len(ts) >= 19 and ts[10] in ("T", " "):
        display = ts[11:19]
    else:
        display = ts[:8]
    return colorize(display.ljust(TIMESTAMP_WIDTH), "timestamp")


def format_location(loc: str) -> str:
    observe_location(loc)
    if len(loc) > _loc_width:
        display = loc[: _loc_width - 1] + "…"
    else:
        display = loc.ljust(_loc_width)
    return colorize(display, "location")


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00").replace(",", "."))
    except ValueError:
        return None


def _format_delta_text(seconds: float) -> str:
    sign = "-" if seconds < 0 else "+"
    s = abs(seconds)
    if s < 10:
        return f"{sign}{s:.2f}s"
    if s < 60:
        return f"{sign}{s:.1f}s"
    if s < 3600:
        return f"{sign}{int(s // 60)}m{int(s % 60):02d}s"
    return f"{sign}{s / 3600:.1f}h"


def _delta_color(seconds: float) -> str:
    if seconds >= 5:
        return "error"
    if seconds >= 1:
        return "warning"
    return "timestamp"


def _delta_column(ts: str) -> str:
    """Elapsed-time cell for --delta mode: time since the previous
    timestamped record, color-stepped when gaps grow."""
    if not _delta_on:
        return ""
    global _prev_dt
    dt = _parse_ts(ts) if ts else None
    if dt is None:
        return " " * DELTA_WIDTH if _ts_seen else ""
    prev, _prev_dt = _prev_dt, dt
    if prev is None:
        return " " * DELTA_WIDTH
    try:
        seconds = (dt - prev).total_seconds()
    except TypeError:  # mixed naive/aware timestamps
        return " " * DELTA_WIDTH
    text = _format_delta_text(seconds).rjust(DELTA_WIDTH)
    return colorize(text, _delta_color(seconds))


def format_message(msg: object, level_key: str = "info") -> str:
    if not isinstance(msg, str):
        msg = json.dumps(msg, separators=(", ", ": "))
    return _wrap_message(msg, level_key)


def _wrap_message(msg_text: str, level_key: str = "info") -> str:
    msg_color = _MESSAGE_COLORS.get(level_key, "message")
    term_width = _terminal_width()
    available = term_width - _msg_col()
    if available < 20 or len(msg_text) <= available:
        return colorize(_highlight(msg_text), msg_color)

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

    cont = _cont_prefix(level_key)
    colored = [colorize(_highlight(lines[0]), msg_color)]
    for line in lines[1:]:
        colored.append(cont + colorize(_highlight(line), msg_color))
    return "\n".join(colored)


def _highlight(text: str) -> str:
    """Mark --grep matches with reverse video (preserves surrounding color)."""
    if _grep is None or not _color_enabled():
        return text
    return _grep.sub(lambda m: f"\033[7m{m.group(0)}\033[27m", text)


def _format_tags(tag_dict: dict[str, object], level_key: str) -> list[str]:
    """Render tags inline under the message, wrapping at tag boundaries.

    The first line carries the `↳` marker; every line repeats the status bar
    and gutter rule so the record reads as one visual row.
    """
    cont = _cont_prefix(level_key)
    available = max(_terminal_width() - _msg_col() - 2, 20)  # 2 = "↳ "

    rows: list[list[str]] = [[]]
    width = 0
    for k, v in tag_dict.items():
        seg = f"{k}={v}"
        added = len(seg) + (2 if rows[-1] else 0)
        if rows[-1] and width + added > available:
            rows.append([seg])
            width = len(seg)
        else:
            rows[-1].append(seg)
            width += added

    out: list[str] = []
    for i, row in enumerate(rows):
        joined = "  ".join(colorize(_highlight(seg), "tag") for seg in row)
        marker = colorize("↳ ", "separator") if i == 0 else "  "
        out.append(cont + marker + joined)
    return out


def format_section_header(title: str) -> str:
    bar = colorize("─" * 3, "separator")
    trail = colorize("─" * (BLOCK_WIDTH - len(title) - 5), "separator")
    return f"{bar} {colorize(title, 'block_header')} {trail}"


def format_block(title: str, data: dict) -> str:
    lines = [format_section_header(title)]
    max_key = max(len(k) for k in data) if data else 0
    for k, v in data.items():
        padded = f"  {k}:".ljust(max_key + 4)  # 2 indent + key + colon + padding
        key = colorize(padded, "block_key")
        val = colorize(f" {v}", "block_value")
        lines.append(f"{key}{val}")
    lines.append(colorize("─" * BLOCK_WIDTH, "separator"))
    return "\n".join(lines)


def _status_color(code: int) -> str:
    if 200 <= code < 300:
        return "ok"
    if 400 <= code < 500:
        return "warning"
    if code >= 500:
        return "error"
    return "block_value"


def _format_body_value(v: object) -> str:
    """Format one parsed body value."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(", ", ": "))
    return str(v)


def _render_body(body: object, key_prefix: str, lines: list[str]) -> None:
    """Render a parsed return body."""
    if isinstance(body, dict):
        lines.append(key_prefix)
        max_key = max(len(str(bk)) for bk in body) if body else 0
        for bk, bv in body.items():
            padded = f"    {bk}:".ljust(max_key + 6)  # 4 indent + key + colon + padding
            bkey = colorize(padded, "block_key")
            bval = colorize(f" {_format_body_value(bv)}", "block_value")
            lines.append(f"{bkey}{bval}")
    elif isinstance(body, list):
        lines.append(key_prefix)
        max_idx = len(str(len(body) - 1)) if body else 1
        for i, item in enumerate(body):
            padded = f"    [{i}]:".ljust(max_idx + 7)  # 4 indent + [ + idx + ]: + padding
            idx = colorize(padded, "block_key")
            val = colorize(f" {_format_body_value(item)}", "block_value")
            lines.append(f"{idx}{val}")
    else:
        lines.append(f"{key_prefix}{colorize(f' {body}', 'block_value')}")


def format_return_value(obj: dict) -> str:
    lines = ["\n" + format_section_header("return")]
    max_key = max(len(k) for k in obj) if obj else 0
    for k, v in obj.items():
        padded = f"  {k}:".ljust(max_key + 4)
        key = colorize(padded, "block_key")
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
            val = colorize(f" {_format_body_value(v)}", "block_value")
            lines.append(f"{key}{val}")
    lines.append(colorize("─" * BLOCK_WIDTH, "separator"))
    return "\n".join(lines)


def format_json_line(record: dict, context_values: dict[str, str], verbose: bool) -> str:
    """Format a JSON log record as a colored line with its tags. Mutates
    context_values to suppress repeated tag values across calls (unless
    verbose)."""
    observe_record(record)

    level = record.get("level", "INFO")
    level_key = _level_color_key(level)

    ts = record.get("timestamp", "")
    parts: list[str] = [
        _bar(level_key),
        _timestamp_column(ts),
        _delta_column(ts),
        format_level(level),
        format_location(str(record.get("location", ""))) if _loc_width else "",
        colorize("│", "separator"),
        format_message(record.get("message", ""), level_key),
    ]
    lines = [" ".join(p for p in parts if p)]

    # Powertools logger.exception() puts the traceback in `exception` —
    # render it as a block instead of a one-line tag.
    exception = record.get("exception")
    has_exception_block = isinstance(exception, str) and "\n" in exception

    # Show each extra field once, then suppress until its value changes
    tag_dict: dict[str, object] = {}
    for k, v in record.items():
        if k in KNOWN_FIELDS or (k == "exception" and has_exception_block):
            continue
        sv = str(v)
        if not verbose and context_values.get(k) == sv:
            continue
        tag_dict[k] = v
        if not verbose:
            context_values[k] = sv

    if tag_dict:
        lines.extend(_format_tags(tag_dict, level_key))

    if has_exception_block:
        lines.extend(_format_exception(exception, level_key))

    return "\n".join(lines)


def _format_exception(text: str, level_key: str) -> list[str]:
    """Render a traceback string: frames dim, header and final line red."""
    cont = _cont_prefix(level_key)
    raw_lines = [ln for ln in text.split("\n") if ln.strip()]
    out = []
    for i, ln in enumerate(raw_lines):
        is_frame = ln.startswith((" ", "\t")) and 0 < i < len(raw_lines) - 1
        style = "non_json" if is_frame else "message_error"
        out.append(cont + colorize(ln, style))
    return out


def _timestamp_column(ts: str) -> str:
    """Timestamp cell for the adaptive layout: real value, pad, or nothing."""
    if ts:
        observe_timestamp()
        return format_timestamp(ts)
    if _ts_seen:
        return " " * TIMESTAMP_WIDTH
    return ""


def format_passthrough(text: str) -> str:
    return colorize(text, "passthrough")


def format_warning(msg: str) -> str:
    return colorize(f"  ⚠ {msg}", "non_json")


def _format_plain_line(level: str, timestamp: str, location: str, message: str) -> str:
    level_key = _level_color_key(level)
    observe_location(location)
    parts = [
        _bar(level_key),
        _timestamp_column(timestamp),
        _delta_column(timestamp),
        format_level(level),
        format_location(location) if _loc_width else "",
        colorize("│", "separator"),
        _wrap_message(message, level_key),
    ]
    return " ".join(p for p in parts if p)


def format_runtime_line(level: str, timestamp: str, location: str, message: str) -> str:
    # Default Lambda runtime logs carry `[Thread - main]`; some emitters use
    # `MainThread`. Both are noise — hide them, keep other thread names.
    display_loc = "" if location in ("main", "MainThread") else location
    return _format_plain_line(level, timestamp, display_loc, message)


def format_stdlib_line(level: str, location: str, message: str, timestamp: str = "") -> str:
    return _format_plain_line(level, timestamp, location, message)
