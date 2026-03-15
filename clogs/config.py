"""Colors, field sets, and layout constants."""
from __future__ import annotations

# 256-color ANSI codes. Reference: https://256colors.com
# Set any value to "" to disable coloring for that element.
COLORS = {
    # Log levels
    "info": "\033[1;32m",
    "warning": "\033[1;33m",
    "error": "\033[1;31m",
    "debug": "\033[38;5;245m",
    # Log content
    "message": "\033[0;37m",
    "location": "\033[38;5;245m",
    "timestamp": "\033[38;5;240m",
    "tag": "\033[38;5;139m",
    "non_json": "\033[38;5;250m",
    "stderr": "\033[38;5;240m",
    # Structural
    "separator": "\033[38;5;240m",
    # Blocks (context header, return value)
    "block_header": "\033[38;5;173m",
    "block_key": "\033[38;5;245m",
    "block_value": "\033[38;5;252m",
}

RESET = "\033[0m"

LEVEL_WIDTH = 5
LOCATION_WIDTH = 22

# Column where the message starts: timestamp(8) + sp + level(5) + sp + location(LOCATION_WIDTH) + sp + │ + sp
MSG_COL = 8 + 1 + LEVEL_WIDTH + 1 + LOCATION_WIDTH + 1 + 1 + 1

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
