from io import StringIO

from clogslib.cli import run


def test_multiline_json_return_buffering():
    input_data = StringIO("{\n\"status\": \"ok\",\n\"count\": 2\n}\n")
    output = StringIO()
    run(input_data, output, verbose=False)
    rendered = output.getvalue()
    assert "return" in rendered
    assert "status" in rendered


def test_stderr_passthrough_rendering():
    input_data = StringIO("non json stderr\n")
    output = StringIO()
    run(input_data, output, verbose=True)
    assert "non json stderr" in output.getvalue()
