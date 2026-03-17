"""Tests for context block detection and rolling baseline suppression."""
from clogs.context import ContextTracker, detect_constant_fields


class TestDetectConstantFields:
    def test_all_same_value(self):
        records = [
            {"level": "INFO", "message": "a", "request_id": "abc", "region": "us-east-1"},
            {"level": "INFO", "message": "b", "request_id": "abc", "region": "us-east-1"},
            {"level": "INFO", "message": "c", "request_id": "abc", "region": "us-east-1"},
        ]
        constant = detect_constant_fields(records)
        assert constant["request_id"] == "abc"
        assert constant["region"] == "us-east-1"

    def test_varying_field_excluded(self):
        records = [
            {"level": "INFO", "message": "a", "request_id": "abc", "counter": "1"},
            {"level": "INFO", "message": "b", "request_id": "abc", "counter": "2"},
        ]
        constant = detect_constant_fields(records)
        assert "request_id" in constant
        assert "counter" not in constant

    def test_layout_fields_excluded(self):
        records = [
            {"level": "INFO", "message": "same", "timestamp": "t1"},
            {"level": "INFO", "message": "same", "timestamp": "t1"},
        ]
        constant = detect_constant_fields(records)
        assert "level" not in constant
        assert "message" not in constant
        assert "timestamp" not in constant

    def test_strict_key_missing_from_one_record_excluded(self):
        """Strict rule: non-preferred key must appear in ALL records."""
        records = [
            {"level": "INFO", "message": "a", "custom": "val"},
            {"level": "INFO", "message": "b", "custom": "val", "other": "x"},
            {"level": "INFO", "message": "c", "custom": "val", "other": "x"},
        ]
        constant = detect_constant_fields(records)
        assert constant["custom"] == "val"
        assert "other" not in constant  # missing from record 0

    def test_strict_key_changing_within_window_excluded(self):
        records = [
            {"level": "INFO", "message": "a", "custom": "val", "counter": "1"},
            {"level": "INFO", "message": "b", "custom": "val", "counter": "2"},
        ]
        constant = detect_constant_fields(records)
        assert constant["custom"] == "val"
        assert "counter" not in constant  # value changed

    def test_preferred_field_in_some_records_included(self):
        """Preferred fields are included if stable across any records that have them."""
        records = [
            {"level": "INFO", "message": "a", "service": "billing"},
            {"level": "INFO", "message": "b", "service": "billing", "region": "us-east-1"},
            {"level": "INFO", "message": "c", "service": "billing", "region": "us-east-1"},
        ]
        constant = detect_constant_fields(records)
        assert constant["service"] == "billing"
        assert constant["region"] == "us-east-1"  # preferred, stable where present

    def test_preferred_field_changing_value_excluded(self):
        """Preferred fields are excluded if their value changes across records."""
        records = [
            {"level": "INFO", "message": "a", "request_id": "abc"},
            {"level": "INFO", "message": "b", "request_id": "def"},
        ]
        constant = detect_constant_fields(records)
        assert "request_id" not in constant

    def test_preferred_fields_listed_first(self):
        """Preferred fields should appear before strict fields in the result."""
        records = [
            {"level": "INFO", "message": "a", "service": "svc", "custom": "val"},
            {"level": "INFO", "message": "b", "service": "svc", "custom": "val"},
        ]
        constant = detect_constant_fields(records)
        keys = list(constant.keys())
        assert keys.index("service") < keys.index("custom")

    def test_empty_records(self):
        assert detect_constant_fields([]) == {}

    def test_single_record(self):
        records = [{"level": "INFO", "message": "a", "custom_field": "val"}]
        constant = detect_constant_fields(records)
        assert constant["custom_field"] == "val"


class TestContextTracker:
    def test_buffer_fills_and_signals_flush(self):
        ctx = ContextTracker(verbose=False)
        for i in range(4):
            assert not ctx.add_record({"level": "INFO", "message": f"msg{i}"})
        assert ctx.add_record({"level": "INFO", "message": "msg4"})

    def test_verbose_skips_buffering(self):
        ctx = ContextTracker(verbose=True)
        assert not ctx.buffering_records

    def test_context_block_built_once(self):
        ctx = ContextTracker(verbose=False)
        for i in range(3):
            ctx.add_record({
                "level": "INFO",
                "message": f"msg{i}",
                "timestamp": "2026-03-14T08:00:00Z",
                "service": "my-service",
                "function_name": "handler",
            })
        block = ctx.build_context_block()
        assert block is not None
        assert "my-service" in block
        assert "handler" in block

        # Second call returns None
        assert ctx.build_context_block() is None

    def test_context_values_populated(self):
        ctx = ContextTracker(verbose=False)
        ctx.add_record({
            "level": "INFO",
            "message": "hello",
            "service": "svc",
            "function_name": "fn",
        })
        ctx.build_context_block()
        assert ctx.context_values["service"] == "svc"
        assert ctx.context_values["function_name"] == "fn"


class TestContextSize:
    def test_custom_context_size(self):
        ctx = ContextTracker(verbose=False, context_size=3)
        assert ctx.buffering_records
        for i in range(2):
            assert not ctx.add_record({"level": "INFO", "message": f"msg{i}"})
        assert ctx.add_record({"level": "INFO", "message": "msg2"})

    def test_context_zero_disables_buffering(self):
        ctx = ContextTracker(verbose=False, context_size=0)
        assert not ctx.buffering_records

    def test_context_zero_not_verbose(self):
        """--context 0 should not imply verbose mode."""
        ctx = ContextTracker(verbose=False, context_size=0)
        assert not ctx.verbose
        assert not ctx.buffering_records


class TestJsonBuffer:
    def test_start_and_append(self):
        ctx = ContextTracker()
        ctx.start_json_buffer("{")
        assert ctx.buffering_json
        assert not ctx.append_json_line('  "key": "val",')
        assert ctx.append_json_line("}")

    def test_take_clears_buffer(self):
        ctx = ContextTracker()
        ctx.start_json_buffer("{")
        ctx.append_json_line("}")
        buf = ctx.take_json_buffer()
        assert buf == ["{", "}"]
        assert not ctx.buffering_json
        assert ctx.json_buffer == []

    def test_buffer_limit_triggers_flush(self):
        ctx = ContextTracker()
        ctx.start_json_buffer("{")
        for i in range(201):
            result = ctx.append_json_line(f"line {i}")
            if result:
                break
        assert result is True

    def test_nested_json_flushes_on_valid_parse(self):
        """Nested JSON without a bare '}' line should flush when it parses as valid."""
        ctx = ContextTracker()
        ctx.start_json_buffer("{")
        assert not ctx.append_json_line('  "nested": {"a": 1},')
        # Final line completes the JSON but doesn't end with bare "}"
        assert ctx.append_json_line('  "ok": true}')
        buf = ctx.take_json_buffer()
        assert buf == ["{", '  "nested": {"a": 1},', '  "ok": true}']

    def test_nested_json_array_return(self):
        """A multiline JSON array should flush once it parses successfully."""
        ctx = ContextTracker()
        ctx.start_json_buffer("[")
        assert not ctx.append_json_line('  {"id": 1},')
        assert ctx.append_json_line('  {"id": 2}]')
        buf = ctx.take_json_buffer()
        assert len(buf) == 3

    def test_bare_bracket_closes_array(self):
        """A bare ']' line should close an array buffer immediately."""
        ctx = ContextTracker()
        ctx.start_json_buffer("[")
        assert not ctx.append_json_line('  "a",')
        assert ctx.append_json_line("]")


class TestRollingBaseline:
    """Test that format_json_line suppresses repeated values via context_values."""

    def test_show_first_then_suppress_then_show_on_change(self):
        from clogs.formatter import format_json_line

        context_values: dict[str, str] = {}

        record1 = {"level": "INFO", "message": "a", "timestamp": "t", "location": "l", "custom": "val1"}
        out1 = format_json_line(record1, context_values, verbose=False)
        assert "custom=val1" in out1
        assert context_values["custom"] == "val1"

        record2 = {"level": "INFO", "message": "b", "timestamp": "t", "location": "l", "custom": "val1"}
        out2 = format_json_line(record2, context_values, verbose=False)
        assert "custom" not in out2

        record3 = {"level": "INFO", "message": "c", "timestamp": "t", "location": "l", "custom": "val2"}
        out3 = format_json_line(record3, context_values, verbose=False)
        assert "custom=val2" in out3

    def test_verbose_shows_all(self):
        from clogs.formatter import format_json_line

        context_values: dict[str, str] = {"custom": "val1"}

        record = {"level": "INFO", "message": "a", "timestamp": "t", "location": "l", "custom": "val1"}
        out = format_json_line(record, context_values, verbose=True)
        assert "custom=val1" in out
