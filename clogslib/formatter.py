"""Rendering helpers for clogs output."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from .config import COLORS, LEVEL_WIDTH, LOCATION_WIDTH, RESET

MSG_COL = 8 + 1 + 5 + 1 + LOCATION_WIDTH + 1 + 1 + 1


def colorize(text: str, color_key: str) -> str:
    code = COLORS.get(color_key, "")
    if not code:
        return text
    return f"{code}{text}{RESET}"


def format_level(level: str) -> str:
    level_upper = level.upper()
    color_key = level_upper.lower()
    if color_key not in COLORS:
        color_key = "info"
    display = "WARN" if level_upper == "WARNING" else level_upper
    return colorize(display.ljust(LEVEL_WIDTH), color_key)


def format_timestamp(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        return colorize(dt.strftime("%H:%M:%S"), "timestamp")
    except (ValueError, TypeError):
        return colorize(ts[:8] if len(ts) >= 8 else ts, "timestamp")


def format_location(loc: str) -> str:
    if len(loc) > LOCATION_WIDTH:
        display = loc[: LOCATION_WIDTH - 1] + "…"
    else:
        display = loc.ljust(LOCATION_WIDTH)
    return colorize(display, "location")


def _term_width(default: int = 120) -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return default


def wrap_message(msg_text: str) -> str:
    available = _term_width() - MSG_COL
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


def format_message(msg: Any) -> str:
    if isinstance(msg, str):
        return wrap_message(msg)
    return wrap_message(json.dumps(msg, separators=(", ", ": ")))


def format_tag(k: str, v: Any) -> str:
    return colorize(f"{k}={v}", "tag")


def format_block(title: str, data: dict[str, Any]) -> str:
    bar = colorize("─" * 3, "separator")
    trail = colorize("─" * (66 - len(title)), "separator")
    header = f"{bar} {colorize(title, 'block_header')} {trail}"
    lines = [header]
    for k, v in data.items():
        lines.append(f"{colorize(f'  {k}:', 'block_key')}{colorize(f' {v}', 'block_value')}")
    lines.append(colorize("─" * 70, "separator"))
    return "\n".join(lines)


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[^m]*m", "", text)
