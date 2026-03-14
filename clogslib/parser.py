"""Line classification and parsing for supported log formats."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ParsedLine:
    kind: str
    data: Any = None


def classify_line(line: str) -> ParsedLine:
    stripped = line.strip()
    if not stripped:
        return ParsedLine("empty")

    if stripped.startswith("{"):
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            record = None
        if isinstance(record, dict):
            if "traces" in record:
                return ParsedLine("suppressed")
            if "message" in record:
                return ParsedLine("json_log", record)
            return ParsedLine("json_other", record)

    lambda_match = re.match(
        r"^\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]\s+"
        r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+"
        r"\S+\s+"
        r"\[Thread\s*-\s*([^\]]+)\]\s+(.*)",
        stripped,
    )
    if lambda_match:
        return ParsedLine(
            "lambda_runtime",
            {
                "level": lambda_match.group(1),
                "timestamp": lambda_match.group(2),
                "location": lambda_match.group(3).strip(),
                "message": lambda_match.group(4),
            },
        )

    stdlib_match = re.match(r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL):(\S+):(.*)", stripped)
    if stdlib_match:
        return ParsedLine(
            "python_stdlib",
            {
                "level": stdlib_match.group(1),
                "logger": stdlib_match.group(2),
                "message": stdlib_match.group(3).strip(),
            },
        )

    warning_match = re.match(r"^.*?(\w+Warning): (.+)", stripped)
    if warning_match:
        return ParsedLine(
            "warning",
            {"warning": warning_match.group(1), "message": warning_match.group(2)},
        )

    if (
        stripped.startswith("warnings.warn(")
        or stripped.startswith("* '")
        or stripped.startswith("  ")
    ):
        return ParsedLine("suppressed")

    if stripped.startswith("Warning:"):
        return ParsedLine("serverless_warning", stripped)

    if stripped == "null":
        return ParsedLine("suppressed")

    if stripped.startswith("Configured ddtrace instrumentation"):
        return ParsedLine("suppressed")

    return ParsedLine("passthrough", stripped)
