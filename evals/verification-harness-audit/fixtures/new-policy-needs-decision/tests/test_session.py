def token_lifetime_hours():
    return 24


def test_supported_token_lifetime():
    assert token_lifetime_hours() == 24
