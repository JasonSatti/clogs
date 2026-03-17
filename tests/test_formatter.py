"""Tests for formatting functions."""
import json

from clogs.formatter import (
    colorize,
    format_block,
    format_level,
    format_location,
    format_return_value,
    format_timestamp,
)


class TestColorize:
    def test_known_color(self):
        result = colorize("hello", "info")
        assert "hello" in result
        assert "\033[" in result

    def test_unknown_color_passes_through(self):
        assert colorize("hello", "nonexistent") == "hello"


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

    def test_unknown_level_uses_info_color(self):
        # Should not crash
        result = format_level("TRACE")
        assert "TRACE" in result


class TestFormatLocation:
    def test_short_location_padded(self):
        result = format_location("handler")
        # Should contain the text (padding is inside ANSI codes)
        assert "handler" in result

    def test_long_location_truncated(self):
        result = format_location("a" * 30)
        assert "…" in result


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
        assert "\033[1;32m 200" in result  # info/green

    def test_status_code_4xx_yellow(self):
        result = format_return_value({"statusCode": 404})
        assert "\033[1;33m 404" in result  # warning/yellow

    def test_status_code_5xx_red(self):
        result = format_return_value({"statusCode": 504})
        assert "\033[1;31m 504" in result  # error/red

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
