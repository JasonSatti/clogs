"""Line parsing helpers."""
from __future__ import annotations

import json
import re
from enum import Enum, auto

from clogs.config import MAX_JSON_PARSE_BYTES


class LineType(Enum):
    JSON_LOG = auto()
    JSON_OBJECT = auto()
    LAMBDA_RUNTIME = auto()
    LAMBDA_START = auto()
    LAMBDA_REPORT = auto()
    PYTHON_STDLIB = auto()
    WARNING = auto()
    FRAMEWORK_WARNING = auto()
    TRACEBACK_START = auto()
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


# Lambda runtime format. Real CloudWatch / runtime output is tab-separated
# without a thread segment; `sls invoke local` adds `[Thread - name]`.
_LAMBDA_RE = re.compile(
    r"^\[(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\]\s+"
    r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+"
    r"\S+\s+"  # request ID
    r"(?:\[Thread\s*-\s*([^\]]+)\]\s+)?(.*)"
)

_STDLIB_RE = re.compile(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL):(\S+):(.*)")

# Python warnings format: /path/to/file.py:42: DeprecationWarning: message
_WARNING_RE = re.compile(r"^.+:\d+: (\w+Warning): (.+)")

# ddtrace writer output prefix. The tracer can flush hundreds of spans as a
# single multi-MB line; match on the prefix so we skip the expensive json.loads.
_DDTRACE_PREFIX_RE = re.compile(r'^\{\s*"traces"\s*:')

# `aws logs tail` prefixes every event with its own ISO timestamp. Strip it
# so the wrapped payload (Powertools JSON, runtime lines) still classifies;
# the captured timestamp backfills inner formats that carry none (stdlib).
_LOG_TAIL_PREFIX_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+(.+)$"
)

_DDTRACE_BANNER = "Configured ddtrace instrumentation"

# Lambda lifecycle lines (CloudWatch / sam local / runtime emulators)
_START_RE = re.compile(r"^START RequestId:\s+(\S+)")
_END_RE = re.compile(r"^END RequestId:\s+\S+")
_REPORT_RE = re.compile(r"^REPORT RequestId:\s+(\S+)\s+(.+)$")

_TRACEBACK_RE = re.compile(r"^Traceback \(most recent call last\):")


def _parse_report(request_id: str, rest: str) -> dict:
    """Parse REPORT key-value pairs (tab- or multi-space-separated)."""
    fields: dict = {"request_id": request_id}
    chunks = rest.split("\t") if "\t" in rest else re.split(r"\s{2,}", rest)
    for chunk in chunks:
        key, sep, value = chunk.partition(":")
        if sep and value.strip():
            fields[key.strip()] = value.strip()
    return fields


def parse_line(line: str) -> ParsedLine:
    """Classify a raw log line and extract its fields."""
    raw = line.rstrip("\r\n")
    parsed = _classify(raw)

    # Unrecognized line starting with an ISO timestamp: try again without the
    # prefix (`aws logs tail` wraps every event this way).
    if parsed.line_type is LineType.PASSTHROUGH:
        m = _LOG_TAIL_PREFIX_RE.match(raw.strip())
        if m:
            inner = _classify(m.group(2))
            if inner.line_type is not LineType.PASSTHROUGH:
                # Formats without their own timestamp (stdlib) inherit the
                # event timestamp so the column isn't lost.
                if not inner.timestamp and inner.line_type is LineType.PYTHON_STDLIB:
                    inner.timestamp = m.group(1)
                return inner

    return parsed


def _classify(raw: str) -> ParsedLine:
    stripped = raw.strip()

    if not stripped:
        return ParsedLine(LineType.BLANK)

    if stripped.startswith("{"):
        oversized = len(stripped) > MAX_JSON_PARSE_BYTES

        # Fast-path for pathological ddtrace span batches: a multi-MB blob
        # whose prefix matches and which carries no "message" field is pure
        # noise — skip the cost of json.loads entirely.
        if (
            oversized
            and _DDTRACE_PREFIX_RE.match(stripped)
            and '"message"' not in stripped
        ):
            return ParsedLine(LineType.NOISE)

        try:
            record = json.loads(stripped)
            if isinstance(record, dict):
                if "message" in record:
                    return ParsedLine(LineType.JSON_LOG, record=record)
                if "traces" in record:
                    return ParsedLine(LineType.NOISE)
                if not oversized:
                    # A bare JSON object with no message — possibly a single-
                    # line invoke return value. Held by the CLI so a terminal
                    # one can render as a return block.
                    return ParsedLine(
                        LineType.JSON_OBJECT, record=record, message=stripped
                    )
        except json.JSONDecodeError:
            pass

        # Oversized JSON that isn't a recognized log shape — truncate instead
        # of letting a multi-MB blob fall through as a giant passthrough.
        if oversized:
            return ParsedLine(
                LineType.PASSTHROUGH,
                message=stripped[:1024] + "… (truncated)",
            )

        if stripped == "{":
            return ParsedLine(LineType.MULTILINE_JSON_START)

    if stripped == "[":
        return ParsedLine(LineType.MULTILINE_JSON_START)

    # Lambda lifecycle: START / END / REPORT
    m = _START_RE.match(stripped)
    if m:
        return ParsedLine(LineType.LAMBDA_START, message=m.group(1))
    if _END_RE.match(stripped):
        return ParsedLine(LineType.NOISE)  # REPORT carries the useful info
    m = _REPORT_RE.match(stripped)
    if m:
        return ParsedLine(
            LineType.LAMBDA_REPORT, record=_parse_report(m.group(1), m.group(2))
        )

    if _TRACEBACK_RE.match(stripped):
        return ParsedLine(LineType.TRACEBACK_START, message=raw)

    # Lambda runtime: [INFO] 2026-03-14T... requestId [Thread - name] message
    m = _LAMBDA_RE.match(stripped)
    if m:
        return ParsedLine(
            LineType.LAMBDA_RUNTIME,
            level=m.group(1),
            timestamp=m.group(2),
            location=(m.group(3) or "").strip(),
            message=m.group(4),
        )

    # Python stdlib: LEVEL:logger:message
    m = _STDLIB_RE.match(stripped)
    if m:
        message = m.group(3).strip()
        if message.startswith(_DDTRACE_BANNER):
            return ParsedLine(LineType.NOISE)
        return ParsedLine(
            LineType.PYTHON_STDLIB,
            level=m.group(1),
            location=m.group(2),
            message=message,
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

    if stripped.startswith(_DDTRACE_BANNER):
        return ParsedLine(LineType.NOISE)

    return ParsedLine(LineType.PASSTHROUGH, message=raw)
