"""Colors, field sets, and layout constants."""
from __future__ import annotations

# 256-color ANSI codes. Reference: https://256colors.com
# Set any value to "" to disable coloring for that element.
COLORS = {
    # Log levels
    "info": "\033[1;38;5;117m",
    "warning": "\033[1;38;5;214m",
    "error": "\033[1;38;5;9m",
    "debug": "\033[1;38;5;248m",
    "ok": "\033[1;38;5;78m",
    # Log content
    "message": "\033[0;37m",
    "location": "\033[38;5;245m",
    "timestamp": "\033[38;5;240m",
    "tag": "\033[38;5;134m",
    "non_json": "\033[38;5;250m",
    "passthrough": "\033[38;5;240m",
    # Structural
    "separator": "\033[38;5;240m",
    # Blocks (context header, return value)
    "block_header": "\033[1;38;5;250m",
    "block_key": "\033[38;5;245m",
    "block_value": "\033[38;5;252m",
}

RESET = "\033[0m"

TIMESTAMP_WIDTH = 8
LEVEL_WIDTH = 5
LOCATION_WIDTH = 22

# Column where the message starts.
MSG_COL = TIMESTAMP_WIDTH + 1 + LEVEL_WIDTH + 1 + LOCATION_WIDTH + 1 + 1 + 1

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
