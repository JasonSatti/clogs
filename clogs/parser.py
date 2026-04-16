"""Line parsing helpers."""
from __future__ import annotations

import json
import re
from enum import Enum, auto

from clogs.config import MAX_JSON_PARSE_BYTES


class LineType(Enum):
    JSON_LOG = auto()
    LAMBDA_RUNTIME = auto()
    PYTHON_STDLIB = auto()
    WARNING = auto()
    FRAMEWORK_WARNING = auto()
    NOISE = auto()
    MULTILINE_JSON_START = auto()
    PASSTHROUGH = auto()
    BLANK = auto()


class ParsedLine:
    """Parsed representation of one input line."""

    __slots__ = ("line_type", "record", "level", "timestamp", "location", "message")

    def __init__(
        self,
        line_type: LineType,
        *,
        record: dict | None = None,
        level: str = "",
        timestamp: str = "",
        location: str = "",
        message: str = "",
    ):
        self.line_type = line_type
        self.record = record
        self.level = level
        self.timestamp = timestamp
        self.location = location
        self.message = message


_LAMBDA_RE = re.compile(
    r"^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s+"
    r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+"
    r"\S+\s+"  # request ID
    r"\[Thread\s*-\s*([^\]]+)\]\s+(.*)"
)

_STDLIB_RE = re.compile(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):(\S+):(.*)")

# Python warnings format: /path/to/file.py:42: DeprecationWarning: message
_WARNING_RE = re.compile(r"^.+:\d+: (\w+Warning): (.+)")

# ddtrace writer output prefix. The tracer can flush hundreds of spans as a
# single multi-MB line; match on the prefix so we skip the expensive json.loads.
_DDTRACE_PREFIX_RE = re.compile(r'^\{\s*"traces"\s*:')


def parse_line(line: str) -> ParsedLine:
    """Classify a raw log line and extract its fields."""
    raw = line.rstrip("\r\n")
    stripped = raw.strip()

    if not stripped:
        return ParsedLine(LineType.BLANK)

    if stripped.startswith("{"):
        if len(stripped) > MAX_JSON_PARSE_BYTES:
            # Too large to parse safely. ddtrace batches dump multi-MB blobs —
            # drop them. Anything else oversized, truncate and pass through.
            if _DDTRACE_PREFIX_RE.match(stripped):
                return ParsedLine(LineType.NOISE)
            return ParsedLine(
                LineType.PASSTHROUGH,
                message=stripped[:1024] + "… (truncated)",
            )

        try:
            record = json.loads(stripped)
            if isinstance(record, dict):
                if "message" in record:
                    return ParsedLine(LineType.JSON_LOG, record=record)
                if "traces" in record:
                    return ParsedLine(LineType.NOISE)
        except json.JSONDecodeError:
            pass

        if stripped == "{":
            return ParsedLine(LineType.MULTILINE_JSON_START)

    if stripped == "[":
        return ParsedLine(LineType.MULTILINE_JSON_START)

    # Lambda runtime: [INFO] 2026-03-14T... requestId [Thread - name] message
    m = _LAMBDA_RE.match(stripped)
    if m:
        return ParsedLine(
            LineType.LAMBDA_RUNTIME,
            level=m.group(1),
            timestamp=m.group(2),
            location=m.group(3).strip(),
            message=m.group(4),
        )

    # Python stdlib: LEVEL:logger:message
    m = _STDLIB_RE.match(stripped)
    if m:
        return ParsedLine(
            LineType.PYTHON_STDLIB,
            level=m.group(1),
            location=m.group(2),
            message=m.group(3).strip(),
        )

    # Python warnings (e.g., DeprecationWarning: ...)
    m = _WARNING_RE.match(stripped)
    if m:
        return ParsedLine(
            LineType.WARNING,
            message=f"{m.group(1)}: {m.group(2)}",
        )

    # Warning continuation lines (indented source context from warnings module)
    if stripped.startswith("warnings.warn("):
        return ParsedLine(LineType.NOISE)

    if stripped.startswith("Warning:"):
        return ParsedLine(LineType.FRAMEWORK_WARNING, message=stripped)

    # Suppress bare null (Lambda default return)
    if stripped == "null":
        return ParsedLine(LineType.NOISE)

    if stripped.startswith("Configured ddtrace instrumentation"):
        return ParsedLine(LineType.NOISE)

    return ParsedLine(LineType.PASSTHROUGH, message=raw)
