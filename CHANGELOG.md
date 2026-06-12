# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-06-12

### Added
- Invocation boundaries: `START RequestId` lines render as
  `─── invocation <id> ───` dividers, and a `request_id` change in JSON
  records emits the same divider; `END` lines are suppressed.
- Lambda `REPORT` lines parse into a duration/memory summary block.
- Traceback rendering: Powertools `exception` fields render as a block
  under the record (frames dim, exception line red); raw multi-line
  tracebacks in the stream get the same styling.
- `--level LEVEL` minimum-severity filter (aliases: `warn`, `crit`, `fatal`).
- `--grep PATTERN` record filter (case-insensitive regex) with reverse-video
  match highlighting; context/return/report blocks stay visible.
- `--delta` elapsed-time column (orange ≥ 1s, red ≥ 5s).
- Configuration file `~/.config/clogs.toml` (override with `CLOGS_CONFIG`):
  colors as hex or 256-index, `location_width`, extra preferred context
  fields, and default flags. Uses `tomllib` on Python 3.11+, a built-in
  subset parser on 3.9/3.10.
- Wrapper mode: `clogs -- cmd args` runs the command with merged
  stdout/stderr and propagates its exit code.
- GitHub Actions CI (ruff + pytest on Python 3.9–3.13) and a PyPI
  trusted-publishing release workflow.

## [0.2.0] - 2026-06-12

### Added
- Status-colored left-edge bar on every log row, continuous through
  wrapped messages and tag lines (Datadog Log Explorer-style row border).
- Adaptive layout: the location column sizes itself to the longest
  location seen (capped at 22); the timestamp column collapses for
  streams without timestamps.
- Truecolor Datadog-inspired palette when `COLORTERM` advertises
  truecolor, with a 256-color fallback.
- Error/warn messages tinted to match their level; inline tag rendering.
- `--badges`: uniform filled level chips (opt-in).
- `--color auto/always/never`; colors auto-disable when piped.
- `python -m clogs` entry point.

### Fixed
- Return values with a nested object as the last key no longer break the
  return block (brace-depth tracking replaces the bare-`}` terminator);
  raw fallbacks keep original indentation.
- `CRITICAL` renders as an aligned red `CRIT` instead of a misaligned
  info-blue token; `WARN`/`CRIT`/`FATAL` shorthands map to the right colors.
- Real CloudWatch runtime lines (tab-separated, no `[Thread - x]`) parse.
- `aws logs tail` event-timestamp prefixes are stripped before
  classification; stdlib lines inherit the event timestamp.
- Single-line return values (`sam local invoke`) render as a return block.
- ddtrace banner suppressed consistently (including the stdlib-logger form).
- Return-block dict values render as JSON instead of Python repr.

### Changed
- `NO_COLOR` is spec-compliant: only a non-empty value disables color.
- Output layout changed (edge bar prefix, adaptive column widths).

## [0.1.0] - 2026-04-17

### Added
- Initial release: colorized formatting for Powertools JSON, Lambda
  runtime, and Python stdlib logs; startup context block with stable-field
  detection; rolling suppression of repeated metadata; return-value
  blocks with color-coded `statusCode`; noise suppression (ddtrace spans,
  `null` returns); reliable streaming with preserved log order;
  `-v/--verbose` and `-c/--context` flags.

[0.3.0]: https://github.com/JasonSatti/clogs/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/JasonSatti/clogs/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/JasonSatti/clogs/releases/tag/v0.1.0
