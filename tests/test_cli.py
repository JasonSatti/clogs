"""Tests for the main processing loop."""
import json
import re
from io import StringIO

from clogs.cli import run


def _run_clogs(
    input_text: str,
    verbose: bool = False,
    context_size: int | None = None,
    min_level: str | None = None,
    grep: str | None = None,
    delta: bool = False,
) -> str:
    """Run clogs in-process and return output."""
    stdin = StringIO(input_text)
    stdout = StringIO()
    run(
        stdin,
        stdout,
        verbose=verbose,
        context_size=context_size,
        min_level=min_level,
        grep=grep,
        delta=delta,
    )
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

    def test_passthrough_only_stream_has_no_startup_header(self):
        """Startup header should not appear when no structured record follows."""
        output = _strip_ansi(_run_clogs("my-command output\nanother line"))
        assert "startup" not in output
        assert "my-command output" in output


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

    def test_return_block_preserved_in_verbose_mode(self):
        """`-v` (verbose) still renders a terminal multiline dict as a return block."""
        lines = [
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines), verbose=True))
        assert "─── return " in output
        assert "statusCode" in output

    def test_return_block_preserved_with_context_zero(self):
        """`--context 0` still renders a terminal multiline dict as a return block."""
        lines = [
            _make_json_line(message="before return"),
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines), context_size=0))
        assert "─── return " in output
        assert "before return" in output

    def test_return_block_survives_trailing_blank_lines(self):
        """Blank lines after a terminal dict must not demote it to generic."""
        lines = [
            _make_json_line(message="before return"),
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
            "",
            "",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── return " in output

    def test_return_block_survives_trailing_suppressed_noise(self):
        """Suppressed noise (null, ddtrace) after a terminal dict must not demote it."""
        lines = [
            _make_json_line(message="before return"),
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
            "null",
            '{"traces": [[{"span_id": 1}]]}',
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── return " in output

    def test_pure_multiline_dict_at_eof_renders_as_return_block(self):
        """A lone multiline dict (e.g. local Lambda invoke return) keeps return formatting."""
        lines = [
            "{",
            '  "statusCode": 200,',
            '  "body": "ok"',
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── return " in output
        assert "statusCode" in output

    def test_pure_multiline_stream_does_not_stall(self):
        """Pure multiline JSON with no records must not wait for records/EOF-cap."""
        # Two back-to-back multiline dicts and nothing else. Under the old
        # bug these would sit in pending_output until 10 blobs accumulated.
        lines = [
            "{",
            '  "a": 1',
            "}",
            "{",
            '  "b": 2',
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert '"a": 1' in output
        # Second blob is still pending at EOF → renders as return-block.
        assert '"b": 2' in output or "b:" in output

    def test_multiline_after_buffering_flush_still_labeled_return_at_eof(self):
        """Terminal multiline after the buffering flush still reaches return block at EOF."""
        lines = []
        # Exceed context_size=5 to close the buffering window.
        for i in range(5):
            lines.append(_make_json_line(message=f"msg{i}"))
        lines.extend(["{", '  "statusCode": 200,', '  "body": "ok"', "}"])
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "statusCode" in output
        # Single-slot hold now applies in every mode, so the terminal dict
        # still renders as a return block.
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


class TestReturnValueShapes:
    def test_nested_dict_as_last_key_still_return_block(self):
        """A bare nested '}' line must not terminate the buffer early."""
        lines = [
            _make_json_line(message="before"),
            "{",
            '  "statusCode": 200,',
            '  "headers": {',
            '    "Content-Type": "application/json"',
            "  }",
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── return " in output
        assert "Content-Type" in output

    def test_single_line_dict_at_eof_renders_as_return_block(self):
        """`sam local invoke` emits the return value as one-line JSON."""
        lines = [
            _make_json_line(message="before"),
            '{"statusCode": 200, "body": "ok"}',
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "─── return " in output
        assert "statusCode" in output

    def test_single_line_dict_mid_stream_not_labeled_return(self):
        lines = [
            _make_json_line(message="before"),
            '{"statusCode": 200, "body": "ok"}',
            _make_json_line(message="after"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "statusCode" in output
        assert "─── return " not in output

    def test_unparseable_buffer_preserves_indentation(self):
        """The raw fallback for an incomplete blob must keep original indentation."""
        lines = [
            _make_json_line(message="first"),
            "{",
            "    indented line one",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "    indented line one" in output


class TestLevelRendering:
    def test_critical_abbreviated_and_aligned(self):
        lines = [
            json.dumps({"level": "CRITICAL", "location": "h:9", "message": "meltdown",
                        "timestamp": "2026-03-14T08:42:15.123Z"}),
            json.dumps({"level": "ERROR", "location": "h:9", "message": "bad",
                        "timestamp": "2026-03-14T08:42:16.123Z"}),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines), context_size=0))
        assert "CRIT " in output
        assert "CRITICAL" not in output
        crit_line, error_line = [ln for ln in output.split("\n") if "│" in ln]
        assert crit_line.index("│") == error_line.index("│")


class TestRealRuntimeFormats:
    def test_runtime_without_thread_segment(self):
        """Real CloudWatch runtime lines have no [Thread - x] part."""
        line = "[INFO]\t2026-03-14T13:35:29.236Z\t6f1b1c8e-1234\thandler started"
        output = _strip_ansi(_run_clogs(line))
        assert "handler started" in output
        assert "13:35:29" in output
        assert "[INFO]" not in output

    def test_aws_logs_tail_prefix_stripped(self):
        """`aws logs tail` wraps every event in its own ISO timestamp."""
        line = (
            "2026-03-14T13:35:29.236000+00:00 "
            + _make_json_line(message="from cloudwatch")
        )
        output = _strip_ansi(_run_clogs(line))
        assert "from cloudwatch" in output
        assert "08:42:15" in output  # record's own timestamp used

    def test_plain_text_with_timestamp_prefix_passes_through(self):
        line = "2026-03-14T13:35:29.236Z something unstructured"
        output = _strip_ansi(_run_clogs(line))
        assert "2026-03-14T13:35:29.236Z something unstructured" in output


class TestDdtraceBanner:
    def test_stdlib_ddtrace_banner_suppressed(self):
        line = (
            "INFO:ddtrace._monkey:Configured ddtrace instrumentation for "
            "62 integration(s). The following modules have been patched: flask"
        )
        output = _run_clogs(line)
        assert output.strip() == ""


class TestLifecycleLines:
    def test_report_rendered_as_block(self):
        line = (
            "REPORT RequestId: 6f1b1c8e\tDuration: 142.33 ms\t"
            "Billed Duration: 200 ms\tMemory Size: 512 MB\tMax Memory Used: 87 MB"
        )
        output = _strip_ansi(_run_clogs(line))
        assert "─── report " in output
        assert "Duration:" in output
        assert "142.33 ms" in output
        assert "Max Memory Used:" in output

    def test_start_renders_invocation_divider(self):
        output = _strip_ansi(_run_clogs("START RequestId: 6f1b1c8e Version: $LATEST"))
        assert "─── invocation 6f1b1c8e " in output

    def test_end_suppressed(self):
        output = _run_clogs("END RequestId: 6f1b1c8e")
        assert output.strip() == ""

    def test_request_id_change_emits_divider(self):
        lines = [
            _make_json_line(message="first", request_id="req-aaa"),
            _make_json_line(message="second", request_id="req-aaa"),
            _make_json_line(message="third", request_id="req-bbb"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines), context_size=0))
        assert "─── invocation req-bbb " in output
        # no divider for the first invocation (context covers it)
        assert "─── invocation req-aaa " not in output
        assert output.index("second") < output.index("invocation req-bbb") < output.index("third")


class TestTracebacks:
    def test_exception_field_rendered_as_block(self):
        record = json.dumps({
            "level": "ERROR", "location": "h:9", "message": "boom",
            "timestamp": "2026-03-14T08:42:15.123Z",
            "exception": 'Traceback (most recent call last):\n  File "/app/h.py", line 4\nValueError: 1',
            "exception_name": "ValueError",
        })
        output = _strip_ansi(_run_clogs(record, context_size=0))
        assert 'File "/app/h.py", line 4' in output
        # rendered as block lines, not a one-line exception= tag
        assert "exception=Traceback" not in output
        assert "exception_name=ValueError" in output

    def test_raw_traceback_lines_grouped(self):
        lines = [
            _make_json_line(message="before"),
            "Traceback (most recent call last):",
            '  File "/app/handler.py", line 42, in process',
            "    raise ValueError(1)",
            "ValueError: 1",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "Traceback (most recent call last):" in output
        assert "ValueError: 1" in output


class TestLevelFilter:
    def test_min_level_hides_lower(self):
        lines = [
            _make_json_line(message="info msg"),
            _make_json_line(message="warn msg", level="WARNING"),
            _make_json_line(message="error msg", level="ERROR"),
        ]
        output = _run_clogs("\n".join(lines), min_level="warning")
        assert "info msg" not in output
        assert "warn msg" in output
        assert "error msg" in output

    def test_runtime_and_stdlib_filtered(self):
        lines = [
            "[INFO] 2026-03-14T13:35:29.236Z abc-123 [Thread - main] runtime info",
            "INFO:mod:stdlib info",
            "ERROR:mod:stdlib error",
        ]
        output = _run_clogs("\n".join(lines), min_level="error")
        assert "runtime info" not in output
        assert "stdlib info" not in output
        assert "stdlib error" in output

    def test_aliases(self):
        lines = [_make_json_line(message="error msg", level="ERROR")]
        output = _run_clogs("\n".join(lines), min_level="warn")
        assert "error msg" in output


class TestGrepFilter:
    def test_only_matching_records_shown(self):
        lines = [
            _make_json_line(message="Querying DynamoDB"),
            _make_json_line(message="Cache miss"),
        ]
        output = _run_clogs("\n".join(lines), grep="dynamodb")
        assert "DynamoDB" in output
        assert "Cache miss" not in output

    def test_matches_tags_too(self):
        lines = [
            _make_json_line(message="first", table="users-dev"),
            _make_json_line(message="second"),
        ]
        output = _run_clogs("\n".join(lines), grep="users-dev")
        assert "first" in output
        assert "second" not in output

    def test_return_block_kept(self):
        lines = [
            _make_json_line(message="nothing matches"),
            "{",
            '  "statusCode": 200',
            "}",
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines), grep="zzz"))
        assert "nothing matches" not in output
        assert "─── return " in output

    def test_passthrough_filtered(self):
        output = _run_clogs("random chatter line", grep="zzz")
        assert "random chatter" not in output


class TestDelta:
    def test_delta_column_shows_elapsed(self):
        lines = [
            _make_json_line(message="first", timestamp="2026-03-14T08:42:15.000Z"),
            _make_json_line(message="second", timestamp="2026-03-14T08:42:18.010Z"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines), delta=True))
        assert "+3.01s" in output

    def test_no_delta_without_flag(self):
        lines = [
            _make_json_line(message="first", timestamp="2026-03-14T08:42:15.000Z"),
            _make_json_line(message="second", timestamp="2026-03-14T08:42:18.010Z"),
        ]
        output = _strip_ansi(_run_clogs("\n".join(lines)))
        assert "+3.01s" not in output


class TestWrapperMode:
    def test_command_output_formatted(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "clogs", "--color", "never", "--", "echo", "hello wrapper"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "hello wrapper" in result.stdout

    def test_exit_code_propagated(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "clogs", "--color", "never", "--",
             sys.executable, "-c", "import sys; sys.exit(3)"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 3


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

    def test_long_startup_preamble_does_not_disable_context(self):
        """15 passthrough lines before records must not prevent context detection."""
        lines = [f"startup log line {i}" for i in range(15)]
        for i in range(3):
            lines.append(_make_json_line(message=f"msg{i}", service="billing"))
        output = _strip_ansi(_run_clogs("\n".join(lines), context_size=3))
        assert "─── context ───" in output
        assert "billing" in output

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
