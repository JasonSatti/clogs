# clogs

Colorized structured log formatter for Lambda JSON logs.

## Install

```bash
pipx install -e /path/to/clogs
```

## Usage

```bash
# Pipe lambda output
com sls invoke local -f clarity --stage prod --data '{}' | clogs

# Verbose — show all fields on every line, no suppression
com sls invoke local -f clarity --stage prod --data '{}' | clogs -v
```

## What it does

- Parses JSON log lines and reformats as `timestamp LEVEL location │ message`
- Color-codes log levels: `INFO` (green), `WARNING` (yellow), `ERROR` (red)
- Detects constant fields across the first few log lines and promotes them to a **context block** at the top — suppressed from subsequent lines
- Shows changed values once when they differ from context, then auto-suppresses
- Extra metadata tags shown as `key=value` in muted purple under the message
- Formats the **lambda return value** as a clean summary block
- Parses Python stdlib logging (`INFO:root:message`) and Lambda runtime format (`[INFO] timestamp requestId [Thread] message`)
- Collapses Python warnings into one-liners, suppresses ddtrace span dumps
- Non-JSON lines pass through dimmed

## Customizing

Edit the top of `clogs.py`:
- `COLORS` dict — 256-color ANSI codes ([reference](https://256colors.com))
- `LOCATION_WIDTH` — column width for location (default 22)
- `CONTEXT_BUFFER_SIZE` — how many JSON lines to buffer for constant detection (default 5)
- `CONTEXT_FIELDS` — Powertools boilerplate fields to show once in context
- `SUPPRESSED_FIELDS` — fields to always suppress (unless `-v`)
