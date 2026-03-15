"""Line classification and parsing — pure functions, no state."""
from __future__ import annotations

import json
import re
from enum import Enum, auto


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
    """Result of classifying and parsing a single log line.

    Attributes
    ----------
    line_type : LineType
        Classification of the line.
    record : dict or None
        Parsed JSON dict for JSON_LOG lines, None otherwise.
    level, timestamp, location, message : str
        Extracted fields, empty string when not applicable.
    """

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
_WARNING_RE = re.compile(r"^\S+:\d+: (\w+Warning): (.+)")


def parse_line(line: str) -> ParsedLine:
    """Classify a raw log line and extract its fields."""
    stripped = line.strip()

    if not stripped:
        return ParsedLine(LineType.BLANK)

    if stripped.startswith("{"):
        try:
            record = json.loads(stripped)
            if isinstance(record, dict):
                if "traces" in record:
                    return ParsedLine(LineType.NOISE)
                if "message" in record:
                    return ParsedLine(LineType.JSON_LOG, record=record)
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
    if stripped.startswith("warnings.warn(") or stripped.startswith("* '"):
        return ParsedLine(LineType.NOISE)

    if stripped.startswith("Warning:"):
        return ParsedLine(LineType.FRAMEWORK_WARNING, message=stripped)

    # Suppress bare null (Lambda default return)
    if stripped == "null":
        return ParsedLine(LineType.NOISE)

    if stripped.startswith("Configured ddtrace instrumentation"):
        return ParsedLine(LineType.NOISE)

    return ParsedLine(LineType.PASSTHROUGH, message=stripped)
