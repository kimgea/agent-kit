from .transforms import normalize_text


def normalize(value: str) -> str:
    return normalize_text(value)
