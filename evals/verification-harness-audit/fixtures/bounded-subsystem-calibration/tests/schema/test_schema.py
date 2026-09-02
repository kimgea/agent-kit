import json
from pathlib import Path
import unittest


class SchemaCompatibilityTests(unittest.TestCase):
    def test_public_manifest_version(self):
        manifest = json.loads(Path("schema/manifest.json").read_text())
        self.assertEqual(1, manifest["version"])
