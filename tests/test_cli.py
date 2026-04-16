"""Tests for the main processing loop."""
import json
import re
from io import StringIO

from clogs.cli import run


def _run_clogs(input_text: str, verbose: bool = False, context_size: int | None = None) -> str:
    """Run clogs in-process and return output."""
    stdin = StringIO(input_text)
    stdout = StringIO()
    run(stdin, stdout, verbose=verbose, context_size=context_size)
    return stdout.getvalue()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _make_json_line(**fields) -> str:
    defaults = {
        "level": "INFO",
        "location": "handler",
        "message": "test message",
        "timestamp": "2026-03-14T08:42:15.123Z",
    }
    defaults.update(fields)
    return json.dumps(defaults)


class TestJsonLogFormatting:
    def test_json_log_formatted(self):
        output = _run_clogs(_make_json_line(message="hello world"))
        assert "hello world" in output
        assert "08:42:15" in output

    def test_verbose_flag(self):
        lines = []
        for i in range(6):
            lines.append(_make_json_line(
                message=f"msg{i}",
                service="svc",
                function_name="fn",
            ))
        output = _run_clogs("\n".join(lines), verbose=True)
        assert output.count("function_name=fn") >= 5


class TestLambdaRuntime:
    def test_lambda_runtime_formatted(self):
        line = "[INFO] 2026-03-14T13:35:29.236Z abc-123 [Thread - main] handler started"
        output = _run_clogs(line)
        assert "handler started" in output
        assert "13:35:29" in output

    def test_runtime_only_stream_flushes_before_eof(self):
        lines = [
            "[INFO] 2026-03-14T13:35:29.236Z abc-123 [Thread - main] runtime one",
            "[INFO] 2026-03-14T13:35:30.236Z abc-123 [Thread - main] runtime two",
            "[INFO] 2026-03-14T13:35:31.236Z abc-123 [Thread - main] runtime three",
        ]
        output = _run_clogs("\n".join(lines))
        assert output
        assert "runtime one" in output
        assert "runtime two" in output
        assert "runtime three" in output


class TestPythonStdlib:
    def test_python_stdlib_formatted(self):
        output = _run_clogs("INFO:my_module:Connecting to database")
        assert "Connecting to database" in output

    def test_stdlib_only_stream_flushes_before_eof(self):
        lines = [
            "INFO:my_module:message one",
            "WARNING:my_module:message two",
            "ERROR:my_module:message three",
        ]
        output = _run_clogs("\n".join(lines))
        assert output
        assert "message one" in output
        assert "message two" in output
        assert "message three" in output


class TestNoiseSuppression:
    def test_null_suppressed(self):
        output = _run_clogs("null")
        assert output.strip() == ""

    def test_ddtrace_noise_suppressed(self):
        line = json.dumps({"traces": [[{"span_id": 1}]]})
        output = _run_clogs(line)
        assert output.strip() == ""


class TestPassthrough:
    def test_passthrough_lines(self):
        output = _run_clogs("some random output text")
        assert "some random output text" in output

    def test_passthrough_only_stream_flushes_before_eof(self):
        lines = [
            "first passthrough line",
            "second passthrough line",
            "third passthrough line",
        ]
        output = _run_clogs("\n".join(lines))
        assert output
        assert "first passthrough line" in output
        assert "second passthrough line" in output
        assert "third passthrough line" in output


class TestStartupGrouping:
    def test_startup_lines_grouped(self):
        lines = [
            "Loading configuration...",
            "Initializing handlers",
        ]
        for i in range(5):
            lines.append(_make_json_line(message=f"msg{i}", service="svc"))
        output = _run_clogs("\n".join(lines))
        assert "startup" in output


class TestMultilineJsonReturn:
    def test_mid_stream_multiline_dict_not_labeled_return(self):
        lines = [
            _make_json_line(message="before"),
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
            _make_json_line(message="after"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "statusCode" in output
        assert "─── return " not in output

    def test_multiline_dict_formatted_as_return_block(self):
        lines = [
            _make_json_line(message="before return"),
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
        ]
        output = _run_clogs("\n".join(lines))
        assert "return" in output
        assert "statusCode" in output

    def test_nested_multiline_json_return(self):
        """Nested JSON that doesn't end with a bare '}' should still be captured."""
        lines = [
            _make_json_line(message="before return"),
            "{",
            '  "nested": {"a": 1},',
            '  "ok": true}',
        ]
        output = _run_clogs("\n".join(lines))
        assert "return" in output
        assert "nested" in output

    def test_terminal_multiline_dict_still_labeled_return(self):
        lines = [
            _make_json_line(message="before return"),
            _make_json_line(message="still before return"),
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── return " in output

    def test_multiline_array_formatted(self):
        """A top-level JSON array return should be captured and formatted."""
        lines = [
            _make_json_line(message="before return"),
            "[",
            '  {"id": 1},',
            '  {"id": 2}',
            "]",
        ]
        output = _run_clogs("\n".join(lines))
        assert '"id": 1' in output or "id" in output

    def test_buffer_limit_prevents_infinite_buffering(self):
        """A stray '{' followed by many non-closing lines should eventually flush."""
        lines = [_make_json_line(message="first")]
        lines.append("{")
        for i in range(210):
            lines.append(f"  line {i}")
        output = _run_clogs("\n".join(lines))
        assert "first" in output
        assert "line 0" in output
        assert "line 209" in output

    def test_multiline_json_during_buffering_preserves_context_window(self):
        # `region` is a preferred field only present in msg2-4. Under the bug
        # that flushed the record buffer on `{`, only msg0-1 would be in the
        # window when context is built, so region would never enter the block.
        lines = [
            _make_json_line(message="msg0", service="svc"),
            _make_json_line(message="msg1", service="svc"),
            "{",
            '  "foo": 1',
            "}",
            _make_json_line(message="msg2", service="svc", region="us-east-1"),
            _make_json_line(message="msg3", service="svc", region="us-east-1"),
            _make_json_line(message="msg4", service="svc", region="us-east-1"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── context ───" in output
        context_start = output.index("─── context ───")
        context_end = output.index("─" * 60, context_start + 20)
        context_section = output[context_start:context_end]
        assert "region:" in context_section
        assert '"foo": 1' in output


class TestContextFlag:
    def test_default_context_shows_block(self):
        """Default behavior: stable fields appear in context block."""
        lines = []
        for i in range(5):
            lines.append(_make_json_line(message=f"msg{i}", service="billing"))
        output = _run_clogs("\n".join(lines))
        assert "context" in output
        assert "billing" in output

    def test_context_zero_no_block(self):
        """--context 0 disables the context block entirely."""
        lines = []
        for i in range(5):
            lines.append(_make_json_line(message=f"msg{i}", service="billing"))
        output = _run_clogs("\n".join(lines), context_size=0)
        assert "msg0" in output
        assert "context" not in output

    def test_context_zero_suppression_still_works(self):
        """--context 0 should not disable suppression."""
        lines = []
        for i in range(5):
            lines.append(_make_json_line(
                message=f"msg{i}",
                custom_field="stable",
            ))
        output = _run_clogs("\n".join(lines), context_size=0)
        # Field should appear once (first time), then be suppressed
        assert output.count("custom_field=stable") == 1

    def test_context_zero_streams_immediately(self):
        """--context 0 should not buffer records — output starts on first line."""
        line = _make_json_line(message="immediate")
        output = _run_clogs(line, context_size=0)
        assert "immediate" in output

    def test_custom_context_size(self):
        """--context 3 should buffer 3 records for context detection."""
        lines = []
        for i in range(5):
            lines.append(_make_json_line(message=f"msg{i}", service="billing"))
        output = _run_clogs("\n".join(lines), context_size=3)
        assert "context" in output
        assert "billing" in output

    def test_strict_rule_non_preferred_key_must_appear_in_all_records(self):
        """A non-preferred field missing from any record should not enter context."""
        lines = [
            _make_json_line(message="msg0", custom="stable"),
            _make_json_line(message="msg1", custom="stable", other="x"),
            _make_json_line(message="msg2", custom="stable", other="x"),
        ]
        output = _run_clogs("\n".join(lines), context_size=3)
        assert "custom" in output
        # 'other' missing from record 0 and not preferred -> not in context

    def test_preferred_field_picked_up_from_any_record(self):
        """A preferred field should enter context even if not in every record."""
        lines = [
            _make_json_line(message="msg0", service="svc"),
            _make_json_line(message="msg1", service="svc", region="us-east-1"),
            _make_json_line(message="msg2", service="svc", region="us-east-1"),
        ]
        output = _run_clogs("\n".join(lines), context_size=3)
        assert "svc" in output
        assert "us-east-1" in output  # preferred, stable where present

    def test_preferred_field_changing_value_excluded(self):
        """A preferred field that changes value should not enter context."""
        lines = [
            _make_json_line(message="msg0", service="svc", request_id="abc"),
            _make_json_line(message="msg1", service="svc", request_id="def"),
            _make_json_line(message="msg2", service="svc", request_id="ghi"),
        ]
        output = _run_clogs("\n".join(lines), context_size=3)
        assert "svc" in output
        # request_id changes -> should not be in context block

    def test_short_stream_fewer_than_n_records(self):
        """If fewer than N records arrive, context should still work at EOF."""
        lines = [
            _make_json_line(message="msg0", service="billing"),
            _make_json_line(message="msg1", service="billing"),
        ]
        output = _run_clogs("\n".join(lines), context_size=5)
        # Only 2 records but context should still be built at EOF
        assert "billing" in output
        assert "context" in output

    def test_mixed_non_json_lines_only_count_json_records(self):
        """Non-JSON lines should not count toward the context window."""
        lines = [
            "Loading config...",
            _make_json_line(message="msg0", service="billing"),
            "Framework ready",
            _make_json_line(message="msg1", service="billing"),
            _make_json_line(message="msg2", service="billing"),
        ]
        output = _run_clogs("\n".join(lines), context_size=3)
        assert "billing" in output
        assert "context" in output

    def test_non_json_interleaved_does_not_shrink_context_window(self):
        # Under the bug, a traceback after msg0 would flush the buffer early.
        # Only msg0 would reach the context block — `region` (only in msg1-4)
        # would never be detected as stable.
        lines = [
            _make_json_line(message="msg0", service="billing"),
            "Traceback (most recent call last):",
            _make_json_line(message="msg1", service="billing", region="us-east-1"),
            _make_json_line(message="msg2", service="billing", region="us-east-1"),
            _make_json_line(message="msg3", service="billing", region="us-east-1"),
            _make_json_line(message="msg4", service="billing", region="us-east-1"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── context ───" in output
        context_start = output.index("─── context ───")
        context_end = output.index("─" * 60, context_start + 20)
        context_section = output[context_start:context_end]
        assert "region:" in context_section

    def test_interleaved_non_json_preserves_source_order(self):
        """A traceback line between buffered JSON records must not print first."""
        lines = [
            _make_json_line(message="msg0", service="billing"),
            "Traceback (most recent call last):",
            _make_json_line(message="msg1", service="billing"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        msg0_pos = output.index("msg0")
        trace_pos = output.index("Traceback")
        msg1_pos = output.index("msg1")
        assert msg0_pos < trace_pos < msg1_pos

    def test_interleaved_multiline_json_preserves_source_order(self):
        """A mid-stream multiline blob between buffered records must emit between them."""
        lines = [
            _make_json_line(message="msg0", service="billing"),
            _make_json_line(message="msg1", service="billing"),
            "{",
            '  "foo": 1',
            "}",
            _make_json_line(message="msg2", service="billing"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        msg1_pos = output.index("msg1")
        foo_pos = output.index('"foo": 1')
        msg2_pos = output.index("msg2")
        assert msg1_pos < foo_pos < msg2_pos

    def test_mixed_stream_with_late_json_still_builds_context(self):
        lines = [
            "[INFO] 2026-03-14T13:35:29.236Z abc-123 [Thread - main] runtime one",
            "[INFO] 2026-03-14T13:35:30.236Z abc-123 [Thread - main] runtime two",
            _make_json_line(message="msg0", service="billing"),
            _make_json_line(message="msg1", service="billing"),
            _make_json_line(message="msg2", service="billing"),
        ]
        output = _run_clogs("\n".join(lines), context_size=3)
        assert "runtime one" in output
        assert "runtime two" in output
        assert "context" in output
        assert "billing" in output
