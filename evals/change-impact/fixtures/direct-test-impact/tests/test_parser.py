from src.parser import normalize


def test_normalize_lowercases_and_trims() -> None:
    assert normalize("  VALUE ") == "value"
