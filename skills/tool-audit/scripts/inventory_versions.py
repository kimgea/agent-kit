#!/usr/bin/env python3
"""Probe labeled CLI versions; executes installed programs and is not auto-approved."""
import argparse
import json
import sys

sys.dont_write_bytecode = True

from _common import classify, load_classes
import inventory


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    installed = inventory.path_executables()
    catalog = {t for t, _sub in load_classes()}
    catalog.update(inventory.category_of())
    rows = []
    for name in sorted(catalog & set(installed)):
        rows.append({"tool": name, "path": installed[name],
                     "class": classify(name, None),
                     "version": inventory.version_of(name)})
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['tool']:<18} {row['version']:<62} {row['path']}")


if __name__ == "__main__":
    sys.exit(main())
