"""Static configuration for clogs formatting behavior."""

from __future__ import annotations

COLORS = {
    "info": "\033[1;32m",
    "warning": "\033[1;33m",
    "error": "\033[1;31m",
    "debug": "\033[38;5;245m",
    "message": "\033[0;37m",
    "location": "\033[38;5;245m",
    "timestamp": "\033[38;5;240m",
    "tag": "\033[38;5;139m",
    "non_json": "\033[38;5;250m",
    "stderr": "\033[38;5;240m",
    "separator": "\033[38;5;240m",
    "block_header": "\033[38;5;173m",
    "block_key": "\033[38;5;245m",
    "block_value": "\033[38;5;252m",
}

RESET = "\033[0m"

LEVEL_WIDTH = 5
LOCATION_WIDTH = 22

KNOWN_FIELDS = {"level", "location", "message", "timestamp", "service", "env"}

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

CONTEXT_BUFFER_SIZE = 5
