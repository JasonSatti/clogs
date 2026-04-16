"""Context tracking and buffering."""
from __future__ import annotations

import json

from clogs.config import CONTEXT_BUFFER_SIZE, JSON_BUFFER_MAX_LINES, KNOWN_FIELDS, PREFERRED_CONTEXT_FIELDS


def detect_constant_fields(records: list[dict]) -> dict[str, str]:
    """Identify fields eligible for the context block using two-tier logic.

    Preferred fields only need a stable value across whichever records contain
    them. All other fields must appear in every record with the same value.
    Preferred fields are listed first in the result.

    Parameters
    ----------
    records : list of dict
        Buffered JSON log records.
    """
    if not records:
        return {}

    preferred: dict[str, str] = {}
    for k in sorted(PREFERRED_CONTEXT_FIELDS - KNOWN_FIELDS):
        values = [str(r[k]) for r in records if k in r]
        if values and len(set(values)) == 1:
            preferred[k] = values[0]

    # Keys present in every record (strict rule for non-preferred fields)
    common_keys = set(records[0].keys())
    for r in records[1:]:
        common_keys &= set(r.keys())

    common_keys -= KNOWN_FIELDS
    common_keys -= PREFERRED_CONTEXT_FIELDS

    strict: dict[str, str] = {}
    for k in sorted(common_keys):
        val = str(records[0][k])
        if all(str(r[k]) == val for r in records[1:]):
            strict[k] = val

    return {**preferred, **strict}


class ContextTracker:
    """Mutable state for one clogs run."""

    def __init__(self, verbose: bool = False, context_size: int = CONTEXT_BUFFER_SIZE):
        self.verbose = verbose
        self.context_size = context_size
        self.context_shown = False
        self.context_values: dict[str, str] = {}

        # Interleaved buffer used during the context-detection window. Each
        # item is one of:
        #   - dict: a JSON log record (drives context detection)
        #   - str:  a pre-rendered non-JSON line (passthrough/runtime/etc.)
        #   - list[str]: a completed multi-line JSON blob, deferred so the
        #     flush path can decide generic-vs-return rendering based on
        #     whether EOF actually arrived while it was still pending.
        self.pending_output: list[dict | str | list[str]] = []
        self.buffering_records = not verbose and context_size > 0

        self.json_buffer: list[str] = []
        self.buffering_json = False

    def add_record(self, record: dict) -> bool:
        """Buffer a record. Returns True when the buffer should flush."""
        self.pending_output.append(record)
        return self._buffer_full()

    def add_formatted(self, line: str) -> bool:
        """Buffer a formatted non-JSON line so it emits in source order.

        Returns True when the buffer should flush — this is how
        passthrough-only or non-JSON streams bail out of the initial
        context-detection window without waiting for a record that will
        never arrive.
        """
        self.pending_output.append(line)
        return self._buffer_full()

    def add_multiline(self, buf: list[str]) -> bool:
        """Buffer a completed multi-line JSON blob for ordered flushing."""
        self.pending_output.append(buf)
        return self._buffer_full()

    def _buffer_full(self) -> bool:
        records = sum(1 for item in self.pending_output if isinstance(item, dict))
        if records >= self.context_size:
            return True
        # Cap total buffered lines so non-record streams don't stall waiting
        # for a record that never comes. 2x the context size keeps the initial
        # delay short (default: 10 lines) while still allowing meaningful
        # context detection in mixed streams.
        return len(self.pending_output) >= self.context_size * 2

    def has_records(self) -> bool:
        return any(isinstance(item, dict) for item in self.pending_output)

    def start_json_buffer(self, first_line: str) -> None:
        self.buffering_json = True
        self.json_buffer = [first_line]

    def append_json_line(self, line: str) -> bool:
        """Append a line. Returns True when the buffer is complete or hits the safety limit."""
        self.json_buffer.append(line)
        if line in ("}", "]") or len(self.json_buffer) > JSON_BUFFER_MAX_LINES:
            return True
        try:
            json.loads("\n".join(self.json_buffer))
            return True
        except json.JSONDecodeError:
            return False

    def take_json_buffer(self) -> list[str]:
        buf = self.json_buffer
        self.json_buffer = []
        self.buffering_json = False
        return buf

    def take_context(self) -> dict[str, str] | None:
        """Return detected context fields and mark them as shown. Returns None if already taken or no fields."""
        records = [item for item in self.pending_output if isinstance(item, dict)]
        if self.context_shown or not records:
            return None
        self.context_shown = True

        ctx = detect_constant_fields(records)
        if not ctx:
            return None

        self.context_values = ctx.copy()
        return ctx
