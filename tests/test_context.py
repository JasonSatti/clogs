from clogslib.cli import CliState, format_json_line
from clogslib.context import ContextState, build_context_block


def test_rolling_baseline_suppression():
    state = CliState(verbose=False)
    state.context.values = {"request": "abc"}

    first = format_json_line({"message": "x", "request": "abc", "user": "u1"}, state)
    assert "user=u1" in first

    repeat = format_json_line({"message": "x", "request": "abc", "user": "u1"}, state)
    assert "user=u1" not in repeat

    changed = format_json_line({"message": "x", "request": "abc", "user": "u2"}, state)
    assert "user=u2" in changed


def test_context_constant_field_detection():
    records = [
        {"message": "a", "service": "svc", "env": "dev", "tenant": "t1", "req": "1"},
        {"message": "b", "service": "svc", "env": "dev", "tenant": "t1", "req": "2"},
    ]
    state = ContextState()
    block = build_context_block(records, state)
    assert block is not None
    assert "tenant" in block
    assert "req" not in block
