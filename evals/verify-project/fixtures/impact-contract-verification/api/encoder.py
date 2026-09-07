WIRE_FIELD = "event_type"


def encode(kind: str) -> dict[str, str]:
    return {WIRE_FIELD: kind}

