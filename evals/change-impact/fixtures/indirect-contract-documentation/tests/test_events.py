from src.events import EVENT_VERSION, make_event


def test_event_contract() -> None:
    assert EVENT_VERSION == 2
    assert make_event("ready") == {"version": 2, "name": "ready"}
