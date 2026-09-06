EVENT_VERSION = 2


def make_event(name: str) -> dict[str, object]:
    return {"version": EVENT_VERSION, "name": name}
