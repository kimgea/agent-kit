import json
from pathlib import Path


def load_manifest(path: Path) -> dict[str, str]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    routes: dict[str, str] = {}
    for entry in entries:
        name = entry["name"]
        handler = entry["handler"]
        if not isinstance(name, str) or not name:
            raise ValueError("route name must be a nonempty string")
        if not isinstance(handler, str) or not handler:
            raise ValueError("route handler must be a nonempty string")
        if name in routes:
            raise ValueError(f"duplicate route name: {name}")
        routes[name] = handler
    return routes


def get_route(routes: dict[str, str], name: str) -> str:
    """Return the handler registered for name."""
    raise NotImplementedError
