def test_malformed_legacy_input_falls_back():
    assert parse("malformed") == {}
