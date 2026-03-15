# clogs

Colorized, condensed log formatting for AWS Lambda, Powertools, and Python logs.

`clogs` makes noisy logs easier to read by colorizing output and hiding
repeated metadata until it changes. If you work with Lambda locally — via
Serverless Framework, SAM, or the AWS CLI — you've seen the wall of JSON that
Powertools and the Lambda runtime produce. `clogs` reformats that output so you
can actually scan it.

`clogs` is a local CLI tool: it formats logs on your machine, does not send them anywhere, and uses only the Python standard library at runtime.

**Before** — raw Powertools JSON:

```
{"level":"INFO","location":"handle_request","message":"Processing request","timestamp":"2026-03-14T08:42:15.123Z","service":"billing","request_id":"abc-123"}
{"level":"INFO","location":"handle_request","message":"Request completed","timestamp":"2026-03-14T08:42:15.456Z","service":"billing","request_id":"abc-123"}
```

**After** — piped through `clogs`:

```
─── context ──────────────────────────────────────────────────────
  service: billing
  request_id: abc-123
──────────────────────────────────────────────────────────────────
08:42:15 INFO  handle_request        │ Processing request
08:42:15 INFO  handle_request        │ Request completed
```

## Install

```bash
git clone https://github.com/JasonSatti/clogs.git
cd clogs
uv tool install .
```

## Usage

Pipe any command that emits supported logs:

```bash
sls invoke local -f my-function --data '{}' | clogs
sam local invoke MyFunction | clogs
aws logs tail /aws/lambda/my-function --follow | clogs
```

Or read from a file:

```bash
clogs < output.log
cat output.log | clogs
```

Use `-v` / `--verbose` to show every field on every line with no suppression:

```bash
sls invoke local -f my-function --data '{}' | clogs -v
```

Use `-c` / `--context` to control the startup context window:

```bash
# Use more records to detect stable fields
sls invoke local -f my-function --data '{}' | clogs -c 10

# Disable the context block entirely (start streaming immediately)
sls invoke local -f my-function --data '{}' | clogs --context 0
```

> **Note:** When piping, only stdout reaches `clogs`. If your tool writes logs
> to stderr, add `2>&1` before the pipe to merge both streams:
> `my-command 2>&1 | clogs`

## What it does

**Colorized, aligned output** — each log line becomes
`timestamp LEVEL location │ message`, with extra fields shown as
`↳ key=value` tags underneath. Color makes levels, timestamps, and metadata
easy to distinguish at a glance.

**Suppression of repeated metadata** — extra fields that repeat the same
value are shown once, then hidden until they change. This is the main way
`clogs` cuts noise. Use `-v` / `--verbose` to see everything.

**Context block** — at startup, the first few JSON records are inspected to
find fields that stay constant across the window (like `service` or
`request_id`). Those are shown once in a summary header. Use `-c N` /
`--context N` to control the window size, or `--context 0` to skip the
context block entirely. Suppression still works either way.

**Startup noise** — non-JSON lines that arrive before the first log record
(framework banners, config output) are grouped under a `─── startup ───`
header.

**Return values** — Lambda return values (multi-line JSON at the end of output)
are formatted as a `─── return ───` summary block. The `statusCode` field is
color-coded: green for 2xx, yellow for 4xx, red for 5xx.

## Supported log formats

| Format | Example |
|---|---|
| **Powertools JSON** | `{"level": "INFO", "location": "handler", "message": "hello", "timestamp": "..."}` |
| **Lambda runtime** | `[INFO] 2026-03-14T13:35:29.236Z reqId [Thread - main] message` |
| **Python stdlib** | `INFO:my_logger:message` |

Other lines (warnings, trace span dumps, framework noise) are either
suppressed or passed through dimmed.

## Modes

| Behavior | Default | `-v` / `--verbose` | `--context 0` |
|---|---|---|---|
| Colorized output | Yes | Yes | Yes |
| Repeated fields suppressed | Yes | No | Yes |
| Context block at startup | Yes | No | No |

## Customization

All config lives in [`clogs/config.py`](clogs/config.py) — edit it directly:

| Setting | What it controls | Default |
|---|---|---|
| `COLORS` | 256-color ANSI codes for every element | [defined in config](clogs/config.py) |
| `LOCATION_WIDTH` | Column width for location field | 22 |
| `CONTEXT_BUFFER_SIZE` | Records to buffer for context detection | 5 |
| `PREFERRED_CONTEXT_FIELDS` | Fields included in context block if stable in any buffered record | [see set in config](clogs/config.py) |

`COLORS` and `PREFERRED_CONTEXT_FIELDS` are plain dicts/sets you can edit to
match your stack. No models, no env vars — just change the file.

## Try it

```bash
cat examples/sample_lambda.log | clogs
```

## Development

```bash
uv run pytest
```

## Requirements

- Python 3.9+
- No external dependencies (stdlib only)
