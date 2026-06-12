"""Tests for runtime configuration loading and application."""
import pytest

from clogs import config, settings


@pytest.fixture(autouse=True)
def _restore_config():
    """settings.apply mutates global config — snapshot and restore."""
    colors = dict(config.COLORS)
    badges = dict(config.BADGE_COLORS)
    loc_width = config.LOCATION_WIDTH
    preferred = set(config.PREFERRED_CONTEXT_FIELDS)
    yield
    config.COLORS.clear()
    config.COLORS.update(colors)
    config.BADGE_COLORS.clear()
    config.BADGE_COLORS.update(badges)
    config.LOCATION_WIDTH = loc_width
    config.PREFERRED_CONTEXT_FIELDS.clear()
    config.PREFERRED_CONTEXT_FIELDS.update(preferred)


class TestMiniToml:
    def test_sections_and_scalars(self):
        data = settings._mini_toml(
            '# comment\n[colors]\ninfo = "#00afff"\ntag = 213\n'
            "[defaults]\nbadges = true\ndelta = false\ncontext = 3\n"
        )
        assert data["colors"]["info"] == "#00afff"
        assert data["colors"]["tag"] == 213
        assert data["defaults"]["badges"] is True
        assert data["defaults"]["delta"] is False
        assert data["defaults"]["context"] == 3

    def test_arrays_of_strings(self):
        data = settings._mini_toml('[context]\nextra_preferred_fields = ["a", "b"]\n')
        assert data["context"]["extra_preferred_fields"] == ["a", "b"]

    def test_inline_comments_stripped(self):
        data = settings._mini_toml("[layout]\nlocation_width = 10  # cap\n")
        assert data["layout"]["location_width"] == 10

    def test_hash_inside_string_preserved(self):
        data = settings._mini_toml('[colors]\ninfo = "#3D7FE0"\n')
        assert data["colors"]["info"] == "#3D7FE0"


class TestConfigPath:
    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("CLOGS_CONFIG", "/tmp/custom.toml")
        assert settings.config_path() == "/tmp/custom.toml"

    def test_xdg_default(self, monkeypatch):
        monkeypatch.delenv("CLOGS_CONFIG", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
        assert settings.config_path() == "/tmp/xdg/clogs.toml"


class TestLoad:
    def test_missing_file_returns_empty(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLOGS_CONFIG", str(tmp_path / "nope.toml"))
        assert settings.load() == {}

    def test_valid_file_parsed(self, monkeypatch, tmp_path):
        path = tmp_path / "clogs.toml"
        path.write_text("[defaults]\nbadges = true\n")
        monkeypatch.setenv("CLOGS_CONFIG", str(path))
        assert settings.load()["defaults"]["badges"] is True


class TestApply:
    def test_color_override_hex(self):
        settings.apply({"colors": {"info": "#00afff"}})
        assert config.COLORS["info"] != ""
        assert "38;5;39" in config.COLORS["info"] or "38;2;0;175;255" in config.COLORS["info"]
        # level colors also rebuild the badge variant
        assert "48;5;39" in config.BADGE_COLORS["info"] or "48;2;0;175;255" in config.BADGE_COLORS["info"]

    def test_color_override_256_index(self):
        settings.apply({"colors": {"tag": 213}})
        assert config.COLORS["tag"] == "\033[38;5;213m"

    def test_unknown_color_key_ignored(self, capsys):
        before = dict(config.COLORS)
        settings.apply({"colors": {"bogus": "#000000"}})
        assert config.COLORS == before
        assert "bogus" in capsys.readouterr().err

    def test_location_width(self):
        settings.apply({"layout": {"location_width": 10}})
        assert config.LOCATION_WIDTH == 10

    def test_location_width_bool_rejected(self):
        before = config.LOCATION_WIDTH
        settings.apply({"layout": {"location_width": True}})
        assert config.LOCATION_WIDTH == before

    def test_extra_preferred_fields(self):
        settings.apply({"context": {"extra_preferred_fields": ["tenant_id"]}})
        assert "tenant_id" in config.PREFERRED_CONTEXT_FIELDS

    def test_defaults_returned(self):
        out = settings.apply({"defaults": {"badges": True, "level": "warning", "context": 3}})
        assert out == {"badges": True, "level": "warning", "context": 3}

    def test_invalid_defaults_ignored(self, capsys):
        out = settings.apply({"defaults": {"badges": "yes", "bogus": 1, "context": True}})
        assert out == {}
        assert "ignoring" in capsys.readouterr().err


class TestColorConversion:
    def test_rgb_roundtrip_cube(self):
        # #00afff is exactly cube color 39
        assert config._rgb_to_idx(0, 175, 255) == 39

    def test_grey_maps_to_grey_ramp(self):
        idx = config._rgb_to_idx(128, 128, 128)
        assert 232 <= idx <= 255 or idx == 102  # grey ramp (or grey cube cell)

    def test_idx_to_rgb_inverse(self):
        assert config._idx_to_rgb(39) == (0, 175, 255)
        assert config._idx_to_rgb(244) == (128, 128, 128)
