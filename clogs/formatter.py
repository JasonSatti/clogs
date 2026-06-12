"""Formatting helpers for rendered output."""
from __future__ import annotations

import json
import os
import shutil

from clogs.config import (
    BADGE_COLORS,
    BAR_GLYPH,
    BAR_WIDTH,
    BLOCK_WIDTH,
    COLORS,
    KNOWN_FIELDS,
    LEVEL_WIDTH,
    LOCATION_WIDTH,
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


def set_badges(enabled: bool) -> None:
    global _badges
    _badges = enabled


def set_color_enabled(enabled: bool | None) -> None:
    global _color_override
    _color_override = enabled


def _color_enabled() -> bool:
    if _color_override is not None:
        return _color_override
    # no-color.org: presence of a non-empty NO_COLOR disables color.
    return not os.environ.get("NO_COLOR")


def reset_layout() -> None:
    global _loc_width, _ts_seen
    _loc_width = 0
    _ts_seen = False


def observe_location(loc: str) -> None:
    global _loc_width
    if len(loc) > _loc_width:
        _loc_width = min(len(loc), LOCATION_WIDTH)


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
    # Badge chips are uniform width: sized so 4-letter levels (INFO, WARN,
    # CRIT — the common ones) center perfectly; 5-letter levels carry the
    # unavoidable half-character offset.
    return LEVEL_WIDTH + 3 if _badges else LEVEL_WIDTH


def _sep_col() -> int:
    """Column of the `│` separator under the current adaptive layout."""
    col = BAR_WIDTH + _level_cell_width() + 1
    if _ts_seen:
        col += TIMESTAMP_WIDTH + 1
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


def _level_color_key(level: str) -> str:
    key = level.lower()
    return key if key in COLORS else "info"


def _message_color_key(level_key: str) -> str:
    if level_key in ("error", "critical"):
        return "message_error"
    if level_key == "warning":
        return "message_warning"
    return "message"


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


def format_message(msg: object, level_key: str = "info") -> str:
    if not isinstance(msg, str):
        msg = json.dumps(msg, separators=(", ", ": "))
    return _wrap_message(msg, level_key)


def _wrap_message(msg_text: str, level_key: str = "info") -> str:
    msg_color = _message_color_key(level_key)
    term_width = _terminal_width()
    available = term_width - _msg_col()
    if available < 20 or len(msg_text) <= available:
        return colorize(msg_text, msg_color)

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
    colored = [colorize(lines[0], msg_color)]
    for line in lines[1:]:
        colored.append(cont + colorize(line, msg_color))
    return "\n".join(colored)


def format_tag(k: str, v: object) -> str:
    return colorize(f"{k}={v}", "tag")


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
        joined = "  ".join(colorize(seg, "tag") for seg in row)
        marker = colorize("↳ ", "separator") if i == 0 else "  "
        out.append(cont + marker + joined)
    return out


def _block_header(title: str) -> str:
    bar = colorize("─" * 3, "separator")
    trail = colorize("─" * (BLOCK_WIDTH - len(title) - 5), "separator")
    return f"{bar} {colorize(title, 'block_header')} {trail}"


def format_section_header(title: str) -> str:
    return _block_header(title)


def format_block(title: str, data: dict) -> str:
    lines = [_block_header(title)]
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
    lines = ["\n" + _block_header("return")]
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
    observe_record(record)

    level = record.get("level", "INFO")
    level_key = _level_color_key(level)

    parts: list[str] = [
        _bar(level_key),
        _timestamp_column(record.get("timestamp", "")),
        format_level(level),
        format_location(str(record.get("location", ""))) if _loc_width else "",
        colorize("│", "separator"),
        format_message(record.get("message", ""), level_key),
    ]
    lines = [" ".join(p for p in parts if p)]

    # Show each extra field once, then suppress until its value changes
    tag_dict: dict[str, object] = {}
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
        lines.extend(_format_tags(tag_dict, level_key))

    return "\n".join(lines)


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


def format_runtime_line(level: str, timestamp: str, location: str, message: str) -> str:
    # Default Lambda runtime logs carry `[Thread - main]`; some emitters use
    # `MainThread`. Both are noise — hide them, keep other thread names.
    level_key = _level_color_key(level)
    display_loc = "" if location in ("main", "MainThread") else location
    observe_location(display_loc)
    parts = [
        _bar(level_key),
        _timestamp_column(timestamp),
        format_level(level),
        format_location(display_loc) if _loc_width else "",
        colorize("│", "separator"),
        _wrap_message(message, level_key),
    ]
    return " ".join(p for p in parts if p)


def format_stdlib_line(level: str, location: str, message: str) -> str:
    level_key = _level_color_key(level)
    observe_location(location)
    parts = [
        _bar(level_key),
        _timestamp_column(""),
        format_level(level),
        format_location(location) if _loc_width else "",
        colorize("│", "separator"),
        _wrap_message(message, level_key),
    ]
    return " ".join(p for p in parts if p)
