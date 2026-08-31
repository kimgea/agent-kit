from parser.value import parse_value


def test_invalid_value_returns_none():
    assert parse_value("not-an-integer") is None
