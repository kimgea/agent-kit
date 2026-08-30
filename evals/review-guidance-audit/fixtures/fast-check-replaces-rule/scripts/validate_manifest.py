import json
import sys


value = json.load(open(sys.argv[1], encoding="utf-8"))
if list(value) != sorted(value):
    raise SystemExit("manifest keys are not sorted at document root")
