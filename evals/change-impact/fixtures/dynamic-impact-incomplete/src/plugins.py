import importlib
import json
from pathlib import Path


def load_plugin(config_path: Path) -> object:
    module_name = json.loads(config_path.read_text(encoding="utf-8"))["module"]
    return importlib.import_module(module_name)
