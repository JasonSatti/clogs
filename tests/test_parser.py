"""Tests for line classification and parsing."""
import json

from clogs.parser import LineType, parse_line


class TestJsonLog:
    def test_powertools_json(self):
        line = json.dumps({
            "level": "INFO",
            "location": "handler",
            "message": "hello world",
            "timestamp": "2026-03-14T08:42:15.123Z",
        })
        parsed = parse_line(line)
        assert parsed.line_type == LineType.JSON_LOG
        assert parsed.record["message"] == "hello world"
        assert parsed.record["level"] == "INFO"

    def test_json_without_message_is_not_log(self):
        line = json.dumps({"status": 200, "body": "ok"})
        parsed = parse_line(line)
        # No "message" field — not classified as a log line
        assert parsed.line_type != LineType.JSON_LOG

    def test_ddtrace_spans_suppressed(self):
        line = json.dumps({"traces": [[{"span_id": 123}]]})
        parsed = parse_line(line)
        assert parsed.line_type == LineType.NOISE

    def test_ddtrace_large_batch_suppressed(self):
        # The tracer can flush hundreds of spans as one multi-MB line. The
        # prefix fast-path should classify it as noise without needing to
        # successfully json.loads() the whole thing.
        spans = [
            {"trace_id": f"T{i}", "span_id": f"S{i}", "duration": i}
            for i in range(1000)
        ]
        line = json.dumps({"traces": [spans]})
        parsed = parse_line(line)
        assert parsed.line_type == LineType.NOISE

    def test_ddtrace_prefix_with_truncated_json_suppressed(self):
        # Even if the JSON body is malformed/truncated, anything starting
        # with {"traces": is tracer output and should be dropped.
        parsed = parse_line('{"traces": [[{"trace_id": "ABC"')
        assert parsed.line_type == LineType.NOISE

    def test_oversized_json_line_truncated_to_passthrough(self):
        # Pathological huge JSON lines fall through without hitting json.loads.
        huge = '{"key": "' + ("x" * 200_000) + '"}'
        parsed = parse_line(huge)
        assert parsed.line_type == LineType.PASSTHROUGH
        assert "truncated" in parsed.message
        assert len(parsed.message) < 2000

    def test_json_with_message_and_traces_is_log(self):
        line = json.dumps({"message": "done", "traces": [{"span_id": 123}]})
        parsed = parse_line(line)
        assert parsed.line_type == LineType.JSON_LOG
        assert parsed.record["message"] == "done"

    def test_invalid_json_starting_with_brace(self):
        parsed = parse_line("{not valid json at all")
        assert parsed.line_type == LineType.PASSTHROUGH


class TestLambdaRuntime:
    def test_standard_format(self):
        line = "[INFO] 2026-03-14T13:35:29.236Z abc-123-def [Thread - main] Starting handler"
        parsed = parse_line(line)
        assert parsed.line_type == LineType.LAMBDA_RUNTIME
        assert parsed.level == "INFO"
        assert parsed.timestamp == "2026-03-14T13:35:29.236Z"
        assert parsed.location == "main"
        assert parsed.message == "Starting handler"

    def test_error_level(self):
        line = "[ERROR] 2026-03-14T13:35:29.236Z abc-123 [Thread - main] Something broke"
        parsed = parse_line(line)
        assert parsed.line_type == LineType.LAMBDA_RUNTIME
        assert parsed.level == "ERROR"


class TestPythonStdlib:
    def test_basic_format(self):
        parsed = parse_line("INFO:my_module:Starting up")
        assert parsed.line_type == LineType.PYTHON_STDLIB
        assert parsed.level == "INFO"
        assert parsed.location == "my_module"
        assert parsed.message == "Starting up"

    def test_warning_level(self):
        parsed = parse_line("WARNING:root:Low memory")
        assert parsed.line_type == LineType.PYTHON_STDLIB
        assert parsed.level == "WARNING"

    def test_debug_level(self):
        parsed = parse_line("DEBUG:app.db:Query executed")
        assert parsed.line_type == LineType.PYTHON_STDLIB
        assert parsed.level == "DEBUG"


class TestNoiseSuppression:
    def test_null_return(self):
        assert parse_line("null").line_type == LineType.NOISE

    def test_ddtrace_banner(self):
        assert parse_line("Configured ddtrace instrumentation for flask").line_type == LineType.NOISE

    def test_warnings_warn_continuation(self):
        assert parse_line("warnings.warn('deprecated')").line_type == LineType.NOISE

    def test_indented_lines_pass_through(self):
        """Indented lines (e.g., stack traces) should not be swallowed as noise."""
        parsed_file = parse_line("  File \"/app/handler.py\", line 42, in process")
        parsed_raise = parse_line("    raise ValueError('bad input')")
        assert parsed_file.line_type == LineType.PASSTHROUGH
        assert parsed_file.message == "  File \"/app/handler.py\", line 42, in process"
        assert parsed_raise.line_type == LineType.PASSTHROUGH
        assert parsed_raise.message == "    raise ValueError('bad input')"

    def test_bullet_lines_pass_through(self):
        parsed = parse_line("  * 'foo' support is deprecated")
        assert parsed.line_type == LineType.PASSTHROUGH
        assert parsed.message == "  * 'foo' support is deprecated"

    def test_stacktrace_indentation_preserved(self):
        lines = [
            "Traceback (most recent call last):",
            "  File \"/app/handler.py\", line 42, in process",
            "    raise ValueError('bad input')",
        ]
        parsed = [parse_line(line) for line in lines]
        assert parsed[0].message == "Traceback (most recent call last):"
        assert parsed[1].message == "  File \"/app/handler.py\", line 42, in process"
        assert parsed[2].message == "    raise ValueError('bad input')"

    def test_blank_line(self):
        assert parse_line("").line_type == LineType.BLANK
        assert parse_line("   ").line_type == LineType.BLANK


class TestWarnings:
    def test_python_warning(self):
        parsed = parse_line("/path/to/file.py:42: DeprecationWarning: use new_func instead")
        assert parsed.line_type == LineType.WARNING
        assert "DeprecationWarning" in parsed.message

    def test_python_warning_various_classes(self):
        for cls in ("UserWarning", "FutureWarning", "RuntimeWarning"):
            parsed = parse_line(f"/app/mod.py:10: {cls}: some message")
            assert parsed.line_type == LineType.WARNING, f"Failed for {cls}"

    def test_warning_in_plain_text_not_misclassified(self):
        """Lines that contain 'Warning' but aren't Python warnings should pass through."""
        parsed = parse_line("Error in SomeWarning: connection reset")
        assert parsed.line_type == LineType.PASSTHROUGH

    def test_log_mentioning_warning_not_misclassified(self):
        parsed = parse_line("Got FatalWarning: retrying in 5s")
        assert parsed.line_type == LineType.PASSTHROUGH

    def test_framework_warning(self):
        parsed = parse_line("Warning: This feature is deprecated")
        assert parsed.line_type == LineType.FRAMEWORK_WARNING


class TestPassthrough:
    def test_plain_text(self):
        parsed = parse_line("some random output")
        assert parsed.line_type == LineType.PASSTHROUGH
        assert parsed.message == "some random output"


class TestMultilineJsonStart:
    def test_bare_brace(self):
        parsed = parse_line("{")
        assert parsed.line_type == LineType.MULTILINE_JSON_START

    def test_bare_bracket(self):
        parsed = parse_line("[")
        assert parsed.line_type == LineType.MULTILINE_JSON_START
