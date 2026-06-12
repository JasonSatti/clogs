"""Runtime configuration from ~/.config/clogs.toml.

Sections:

    [colors]      element = "#RRGGBB" or 256-palette index
    [layout]      location_width = 22
    [context]     extra_preferred_fields = ["tenant_id"]
    [defaults]    badges = true, color = "auto", level = "warning",
                  delta = true, verbose = false, context = 5

CLI flags always override [defaults]. The path can be overridden with the
CLOGS_CONFIG environment variable.
"""
from __future__ import annotations

import os
import sys

from clogs import config

_LEVEL_COLOR_KEYS = set(config.LEVEL_PALETTE)
_VALID_DEFAULTS = {
    "badges": bool,
    "color": str,
    "level": str,
    "delta": bool,
    "verbose": bool,
    "context": int,
}


def config_path() -> str:
    override = os.environ.get("CLOGS_CONFIG")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "clogs.toml")


def _parse_toml(text: str) -> dict:
    try:
        import tomllib

        return tomllib.loads(text)
    except ModuleNotFoundError:
        pass
    try:
        import tomli

        return tomli.loads(text)
    except ModuleNotFoundError:
        pass
    return _mini_toml(text)


def _parse_value(raw: str) -> object:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(item) for item in inner.split(",")]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return raw[1:-1]
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _mini_toml(text: str) -> dict:
    """Tiny TOML-subset parser for Python 3.9/3.10 (no tomllib): sections,
    strings, ints, floats, booleans, and single-line arrays."""
    data: dict = {}
    current = data
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = data.setdefault(line[1:-1].strip(), {})
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        # Strip inline comments (not inside a quoted string)
        if not value.startswith(("'", '"', "[")) and "#" in value:
            value = value.split("#", 1)[0].strip()
        current[key.strip()] = _parse_value(value)
    return data


def load() -> dict:
    path = config_path()
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return {}
    try:
        return _parse_toml(text)
    except Exception as exc:  # malformed config must never break log output
        print(f"clogs: ignoring invalid config {path}: {exc}", file=sys.stderr)
        return {}


def apply(data: dict) -> dict:
    """Apply settings to the runtime config. Returns CLI argument defaults."""
    colors = data.get("colors", {})
    if isinstance(colors, dict):
        for key, spec in colors.items():
            if key not in config.COLORS or not isinstance(spec, (str, int)):
                print(f"clogs: ignoring unknown color setting {key!r}", file=sys.stderr)
                continue
            bold = key in _LEVEL_COLOR_KEYS
            config.COLORS[key] = config.color_code(spec, bold=bold)
            if key in _LEVEL_COLOR_KEYS and key in config.BADGE_COLORS:
                config.BADGE_COLORS[key] = config.badge_code(spec)

    layout = data.get("layout", {})
    if isinstance(layout, dict):
        width = layout.get("location_width")
        # bool is an int subclass — `location_width = true` must not become 1
        if isinstance(width, int) and not isinstance(width, bool) and width > 0:
            config.LOCATION_WIDTH = width

    context = data.get("context", {})
    if isinstance(context, dict):
        extra = context.get("extra_preferred_fields", [])
        if isinstance(extra, list):
            config.PREFERRED_CONTEXT_FIELDS.update(str(f) for f in extra)

    defaults: dict = {}
    section = data.get("defaults", {})
    if isinstance(section, dict):
        for key, value in section.items():
            expected = _VALID_DEFAULTS.get(key)
            valid = (
                expected is not None
                and isinstance(value, expected)
                # bool is an int subclass — `context = true` must not pass
                and not (expected is int and isinstance(value, bool))
            )
            if not valid:
                print(f"clogs: ignoring invalid default {key!r}", file=sys.stderr)
                continue
            defaults[key] = value
    return defaults
