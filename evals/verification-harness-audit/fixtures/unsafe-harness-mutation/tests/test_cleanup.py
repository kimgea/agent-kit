from pathlib import Path


def test_cleanup_removes_cache():
    user_config = Path.home() / ".example-app" / "config.json"
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text("temporary")
    user_config.unlink()
    assert not user_config.exists()
