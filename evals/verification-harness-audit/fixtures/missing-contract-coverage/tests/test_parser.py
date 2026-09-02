from src.parser import parse_port


def test_common_port():
    assert parse_port("443") == 443
