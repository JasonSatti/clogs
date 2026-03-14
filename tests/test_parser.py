from clogslib.parser import classify_line


def test_line_classification_variants():
    assert classify_line('{"message":"ok","level":"INFO"}').kind == "json_log"
    assert classify_line('[INFO] 2026-03-14T13:35:29.236Z req [Thread - worker] hi').kind == "lambda_runtime"
    assert classify_line('INFO:root:hello').kind == "python_stdlib"
    assert classify_line('Warning: deprecated thing').kind == "serverless_warning"
    assert classify_line('Configured ddtrace instrumentation foo').kind == "suppressed"
    assert classify_line('random stderr line').kind == "passthrough"
