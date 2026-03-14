# clogs

`clogs` is a terminal formatter for Lambda-oriented JSON logs (especially Powertools style logs).

It reads log lines from `stdin`, then renders a scan-friendly layout:

```text
timestamp LEVEL location               │ message
                                        ↳ key=value
```

## Why use it

When you run Lambda handlers locally, output can be noisy and hard to scan. `clogs` improves signal by:

- keeping `timestamp LEVEL location │ message` aligned
- moving repetitive metadata into a one-time **context** block
- suppressing repeated tag values until they change
- grouping startup noise under a startup heading
- rendering Lambda return objects as a **return** block

## Install

### Option 1: `uv tool`

```bash
uv tool install .
```

### Option 2: `pipx`

```bash
pipx install .
```

## Usage

```bash
some-command-that-emits-lambda-logs 2>&1 | clogs
```

Verbose mode disables suppression and shows all fields every time:

```bash
some-command-that-emits-lambda-logs 2>&1 | clogs -v
```

## Important shell caveat: `stderr` is separate

With this pipeline:

```bash
cmd | clogs
```

only `stdout` is piped into `clogs`. `stderr` still goes directly to your terminal.

To send both streams through `clogs`, redirect `stderr` to `stdout` first:

```bash
cmd 2>&1 | clogs
```

## Supported formats

`clogs` intentionally targets team Lambda workflows and supports:

- Powertools-style JSON logs (`{"level":...,"message":...}`)
- Lambda runtime lines (`[INFO] timestamp requestId [Thread - ...] message`)
- Python stdlib logs (`INFO:logger:message`)

It also suppresses common noise patterns (ddtrace span dumps, ddtrace instrumentation banners, warning continuation lines, and bare `null` return output).

## Customization

Tune behavior in `clogslib/config.py`:

- `COLORS`: ANSI palette
- `LOCATION_WIDTH`: location column width
- `CONTEXT_BUFFER_SIZE`: records used to infer constant context
- `CONTEXT_FIELDS`: fields shown once in context mode

## Development

Run tests:

```bash
pytest
```
