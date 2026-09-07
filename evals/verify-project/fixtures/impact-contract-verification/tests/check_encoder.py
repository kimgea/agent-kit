import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("encoder", Path("api/encoder.py"))
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.encode("created") == {"event_type": "created"}
print("wire contract passed")

