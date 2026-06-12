"""Colors, field sets, and layout constants."""
from __future__ import annotations

import os


def _supports_truecolor() -> bool:
    colorterm = os.environ.get("COLORTERM", "").lower()
    return "truecolor" in colorterm or "24bit" in colorterm


_TRUECOLOR = _supports_truecolor()


def _fg(hex_color: str, fallback: int, *, bold: bool = False) -> str:
    """Build an ANSI foreground code: 24-bit when the terminal supports it,
    256-color otherwise. ``fallback`` is the 256-palette index."""
    prefix = "1;" if bold else ""
    if _TRUECOLOR:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
        return f"\033[{prefix}38;2;{r};{g};{b}m"
    return f"\033[{prefix}38;5;{fallback}m"


def _badge(hex_color: str, fallback: int) -> str:
    """Filled-badge code: dark text on a level-colored background."""
    if _TRUECOLOR:
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
        return f"\033[1;38;2;22;24;29;48;2;{r};{g};{b}m"
    return f"\033[1;38;5;235;48;5;{fallback}m"


# Datadog-inspired palette. Truecolor hex values approximate the Log Explorer
# status colors and brand purple; the second value is the 256-color fallback
# used when COLORTERM doesn't advertise truecolor.
LEVEL_PALETTE = {
    "info": ("#3D7FE0", 33),
    "warning": ("#FFAC2E", 214),
    "error": ("#EB4D58", 9),
    "critical": ("#FF3B4E", 196),
    "debug": ("#8C939E", 248),
    "ok": ("#53B06A", 78),
}

# Filled level chips for --badges mode (Datadog status-chip style)
BADGE_COLORS = {k: _badge(h, f) for k, (h, f) in LEVEL_PALETTE.items()}

# Set any value to "" to disable coloring for that element.
COLORS = {
    # Log levels (also used for the left status bar)
    **{k: _fg(h, f, bold=True) for k, (h, f) in LEVEL_PALETTE.items()},
    # Log content
    "message": _fg("#D6D9DE", 252),
    "message_warning": _fg("#F2CE8B", 222),
    "message_error": _fg("#F2A8B0", 217),
    "location": _fg("#8A919C", 245),
    "timestamp": _fg("#646B76", 240),
    "tag": _fg("#B48EE8", 140),
    "non_json": _fg("#B6BBC2", 250),
    "passthrough": _fg("#646B76", 240),
    # Structural
    "separator": _fg("#646B76", 240),
    # Blocks (context header, return value)
    "block_header": _fg("#C8CCD2", 250, bold=True),
    "block_key": _fg("#8A919C", 245),
    "block_value": _fg("#D6D9DE", 252),
}

RESET = "\033[0m"

TIMESTAMP_WIDTH = 8
LEVEL_WIDTH = 5

# Maximum width of the location column. The column sizes itself to the
# longest location actually seen (see formatter.observe_location) and this
# is the cap beyond which locations are truncated.
LOCATION_WIDTH = 22

# Status bar drawn at the left edge of every log row, colored by level —
# mirrors the row border in Datadog's Log Explorer.
BAR_GLYPH = "▎"
BAR_WIDTH = 2  # glyph + trailing space

# Total width of block rules (context, return, startup headers)
BLOCK_WIDTH = 70

# Fields rendered in the fixed-column layout (not shown as tags)
KNOWN_FIELDS = {"level", "location", "message", "timestamp"}

# Preferred context fields — included in the context block with relaxed rules.
# See detect_constant_fields() in context.py for the two-tier logic.
PREFERRED_CONTEXT_FIELDS = {
    "account_id",
    "cold_start",
    "correlation_id",
    "env",
    "environment",
    "function_arn",
    "function_memory_size",
    "function_name",
    "function_request_id",
    "region",
    "request_id",
    "sampling_rate",
    "service",
    "stage",
    "trace_id",
    "version",
    "xray_trace_id",
}

CONTEXT_BUFFER_SIZE = 5

# Prevents a stray '{' from swallowing all subsequent output.
JSON_BUFFER_MAX_LINES = 200

# Skip json.loads on lines above this size — catches pathological emitters
# that dump multi-MB blobs as a single line.
MAX_JSON_PARSE_BYTES = 65_536
