from parser import parse_value


def test_invalid_value():
    result = parse_value("invalid")
    assert result is not None
