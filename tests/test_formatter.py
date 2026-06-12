"""Tests for formatting functions."""
import json
import re

import pytest

from clogs.config import BADGE_COLORS, COLORS
from clogs.formatter import (
    colorize,
    format_block,
    format_json_line,
    format_level,
    format_location,
    format_return_value,
    format_runtime_line,
    format_stdlib_line,
    format_timestamp,
    reset_layout,
    set_badges,
    set_color_enabled,
)


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    # Ambient NO_COLOR in the shell would suppress ANSI and break tests that
    # assert specific color codes. Tests for NO_COLOR behavior re-set it explicitly.
    monkeypatch.delenv("NO_COLOR", raising=False)
    set_color_enabled(None)
    set_badges(False)
    reset_layout()
    yield
    set_color_enabled(None)
    set_badges(False)
    reset_layout()


class TestColorize:
    def test_known_color(self):
        result = colorize("hello", "info")
        assert "hello" in result
        assert "\033[" in result

    def test_unknown_color_passes_through(self):
        assert colorize("hello", "nonexistent") == "hello"

    def test_no_color_env_suppresses_ansi(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert colorize("hello", "info") == "hello"

    def test_no_color_empty_value_keeps_color(self, monkeypatch):
        # no-color.org spec: only a *non-empty* NO_COLOR disables color.
        monkeypatch.setenv("NO_COLOR", "")
        assert "\033[" in colorize("hello", "info")

    def test_no_color_unset_keeps_color(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        result = colorize("hello", "info")
        assert "\033[" in result

    def test_explicit_disable_overrides(self):
        set_color_enabled(False)
        assert colorize("hello", "info") == "hello"

    def test_explicit_enable_overrides_no_color(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        set_color_enabled(True)
        assert "\033[" in colorize("hello", "info")


class TestFormatTimestamp:
    def test_iso_timestamp(self):
        result = format_timestamp("2026-03-14T08:42:15.123Z")
        assert "08:42:15" in result

    def test_short_timestamp(self):
        result = format_timestamp("08:42")
        assert "08:42" in result


class TestFormatLevel:
    def test_info(self):
        result = format_level("INFO")
        assert "INFO" in result

    def test_warning_abbreviated(self):
        result = format_level("WARNING")
        assert "WARN" in result
        assert "WARNING" not in result

    def test_lowercase_warning_uses_warning_color(self):
        result = format_level("warning")
        assert "WARN" in result
        assert COLORS["warning"] in result

    def test_critical_abbreviated_with_critical_color(self):
        result = format_level("CRITICAL")
        assert "CRIT" in result
        assert "CRITICAL" not in result
        assert COLORS["critical"] in result

    def test_unknown_level_uses_info_color(self):
        # Should not crash
        result = format_level("TRACE")
        assert "TRACE" in result

    def test_long_unknown_level_truncated_to_column_width(self):
        result = _strip_ansi(format_level("EXCEPTION"))
        assert len(result) == 5


class TestBadges:
    @pytest.fixture(autouse=True)
    def _badges_on(self):
        set_badges(True)
        yield
        set_badges(False)

    def test_chips_uniform_width_and_perfectly_centered(self):
        # 3-letter labels: every chip identical, text dead-center
        assert _strip_ansi(format_level("INFO")) == " INF "
        assert _strip_ansi(format_level("ERROR")) == " ERR "
        assert _strip_ansi(format_level("WARNING")) == " WRN "
        assert _strip_ansi(format_level("DEBUG")) == " DBG "
        assert _strip_ansi(format_level("CRITICAL")) == " CRT "

    def test_unknown_level_truncated_to_three_letters(self):
        assert _strip_ansi(format_level("NOTICE")) == " NOT "

    def test_chip_uses_badge_color(self):
        result = format_level("WARNING")
        assert BADGE_COLORS["warning"] in result
        assert " WRN " in result

    def test_all_cells_same_width(self):
        widths = {
            len(_strip_ansi(format_level(lvl)))
            for lvl in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        }
        assert len(widths) == 1

    def test_separator_stays_aligned_across_levels(self):
        out_info = _strip_ansi(
            format_json_line(
                {"level": "INFO", "message": "a", "timestamp": "2026-03-14T08:00:00Z"},
                {},
                verbose=False,
            )
        )
        out_error = _strip_ansi(
            format_json_line(
                {"level": "ERROR", "message": "b", "timestamp": "2026-03-14T08:00:01Z"},
                {},
                verbose=False,
            )
        )
        assert out_info.index("│") == out_error.index("│")

    def test_no_color_renders_plain_chip(self):
        set_color_enabled(False)
        result = format_level("INFO")
        assert result == " INF "
        assert "\033[" not in result


class TestFormatLocation:
    def test_short_location_padded(self):
        result = format_location("handler")
        # Should contain the text (padding is inside ANSI codes)
        assert "handler" in result

    def test_long_location_truncated(self):
        result = format_location("a" * 30)
        assert "…" in result


class TestAdaptiveLayout:
    def test_location_column_sized_to_longest_seen(self):
        out = _strip_ansi(format_location("db:4"))
        assert out == "db:4"
        out = _strip_ansi(format_location("permissions:18"))
        assert out == "permissions:18"
        # Width stays at the high-water mark for shorter locations
        out = _strip_ansi(format_location("db:4"))
        assert out == "db:4".ljust(14)

    def test_location_width_capped(self):
        out = _strip_ansi(format_location("x" * 40))
        assert len(out) == 22
        assert out.endswith("…")

    def test_timestamp_column_absent_until_seen(self):
        line = _strip_ansi(format_stdlib_line("INFO", "mod", "msg"))
        assert line.startswith("▎ INFO")

    def test_timestamp_column_padded_after_seen(self):
        format_json_line(
            {"level": "INFO", "message": "a", "timestamp": "2026-03-14T08:00:00Z"},
            {},
            verbose=False,
        )
        line = _strip_ansi(format_stdlib_line("INFO", "mod", "msg"))
        # Timestamp column now exists — stdlib lines pad it to stay aligned
        assert line.startswith("▎ " + " " * 8 + " INFO")


class TestFormatBlock:
    def test_block_structure(self):
        result = format_block("test", {"key1": "val1", "key2": "val2"})
        assert "test" in result
        assert "key1:" in result
        assert "val1" in result
        assert "─" in result


class TestReturnValue:
    def test_formats_dict_as_block(self):
        result = format_return_value({"statusCode": 200, "body": "ok"})
        assert "return" in result
        assert "statusCode:" in result
        assert "200" in result

    def test_status_code_2xx_green(self):
        result = format_return_value({"statusCode": 200})
        assert COLORS["ok"] + " 200" in result

    def test_status_code_4xx_yellow(self):
        result = format_return_value({"statusCode": 404})
        assert COLORS["warning"] + " 404" in result

    def test_status_code_5xx_red(self):
        result = format_return_value({"statusCode": 504})
        assert COLORS["error"] + " 504" in result

    def test_status_code_string_no_color(self):
        result = format_return_value({"statusCode": "200"})
        # String status codes use default block_value color, not the green status color
        assert "\033[1;32m 200" not in result

    def test_body_json_object_rendered_structured(self):
        payload = {"statusCode": 200, "body": '{"id":"usr_1","name":"Bruce"}'}
        result = format_return_value(payload)
        assert "body:" in result
        assert "id:" in result
        assert "usr_1" in result
        assert "name:" in result
        assert "Bruce" in result
        # Should NOT contain escaped quotes
        assert '\\"' not in result

    def test_body_json_list_rendered_indexed(self):
        payload = {"statusCode": 200, "body": '["alpha", "bravo", "charlie"]'}
        result = format_return_value(payload)
        assert "body:" in result
        assert "[0]:" in result
        assert "alpha" in result
        assert "[1]:" in result
        assert "bravo" in result
        assert "[2]:" in result
        assert "charlie" in result

    def test_body_invalid_json_stays_raw(self):
        payload = {"statusCode": 200, "body": "not json {{{"}
        result = format_return_value(payload)
        assert "body:" in result
        assert "not json {{{" in result

    def test_body_json_scalar_rendered_inline(self):
        payload = {"statusCode": 200, "body": '"just a string"'}
        result = format_return_value(payload)
        assert "body:" in result
        assert "just a string" in result

    def test_body_nested_dict_falls_back_to_json(self):
        payload = {"statusCode": 200, "body": '{"user":{"name":"Bruce","city":"Gotham"}}'}
        result = format_return_value(payload)
        assert "user:" in result
        # Nested dict rendered as compact JSON
        assert "Gotham" in result

    def test_non_body_fields_unaffected(self):
        payload = {"statusCode": 200, "headers": '{"Content-Type":"application/json"}'}
        result = format_return_value(payload)
        # headers should be rendered as-is, not parsed
        assert "headers:" in result

    def test_dict_value_rendered_as_json_not_python_repr(self):
        payload = {"statusCode": 200, "headers": {"Content-Type": "application/json"}}
        result = format_return_value(payload)
        assert '"Content-Type": "application/json"' in result
        assert "'Content-Type'" not in result

    def test_header_and_footer_same_width(self):
        result = _strip_ansi(format_return_value({"statusCode": 200}))
        lines = [l for l in result.split("\n") if l]
        assert len(lines[0]) == len(lines[-1])


class TestFormatRuntimeLine:
    def test_contains_all_fields(self):
        result = format_runtime_line("INFO", "2026-03-14T13:35:29.236Z", "worker-1", "handler started")
        assert "13:35:29" in result
        assert "INFO" in result
        assert "worker-1" in result
        assert "handler started" in result

    def test_default_main_location_hidden(self):
        result = format_runtime_line("INFO", "2026-03-14T00:00:00Z", "main", "msg")
        # `main` is the default thread name on every Lambda runtime line —
        # suppress it as noise alongside MainThread.
        assert "main" not in result.replace("msg", "")  # avoid false match in unrelated text
        assert "msg" in result

    def test_warning_abbreviated(self):
        result = format_runtime_line("WARNING", "2026-03-14T00:00:00Z", "loc", "msg")
        assert "WARN" in result
        assert "WARNING" not in result

    def test_separator_present(self):
        result = format_runtime_line("INFO", "2026-03-14T00:00:00Z", "loc", "msg")
        assert "│" in result

    def test_main_thread_location_hidden(self):
        result = format_runtime_line("INFO", "2026-03-14T00:00:00Z", "MainThread", "msg")
        assert "MainThread" not in result
        assert "msg" in result

    def test_non_main_thread_preserved(self):
        result = format_runtime_line("INFO", "2026-03-14T00:00:00Z", "worker-1", "msg")
        assert "worker-1" in result


class TestFormatStdlibLine:
    def test_contains_fields(self):
        result = format_stdlib_line("ERROR", "my_module", "something broke")
        assert "ERROR" in result
        assert "my_module" in result
        assert "something broke" in result

    def test_timestamp_column_collapsed_when_stream_has_none(self):
        """Stdlib lines have no timestamp — the column shouldn't exist
        unless a timestamped line has been seen (adaptive layout)."""
        result = format_stdlib_line("INFO", "mod", "msg")
        clean = _strip_ansi(result)
        assert clean.startswith("▎ INFO")

    def test_separator_present(self):
        result = format_stdlib_line("INFO", "loc", "msg")
        assert "│" in result
