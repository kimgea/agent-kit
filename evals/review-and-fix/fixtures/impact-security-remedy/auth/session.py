import json
from pathlib import Path


def token_lifetime_hours() -> int:
    config = json.loads(Path("config/auth.json").read_text(encoding="utf-8"))
    return int(config["token_lifetime_hours"])

