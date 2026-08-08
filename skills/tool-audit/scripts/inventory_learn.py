#!/usr/bin/env python3
"""Persist uncategorized CLI names for curation; intentionally not auto-approved."""
import argparse
import sys

sys.dont_write_bytecode = True

from _common import load_classes
import inventory


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--agent", choices=("auto", "claude", "codex"), default="auto")
    args = ap.parse_args()
    installed = inventory.path_executables()
    categorized = inventory.category_of()
    known = {t for t, _sub in load_classes()}
    names = [name for name, path in sorted(installed.items())
             if name not in categorized and name not in known and not inventory.is_system(path)]
    if not names:
        print("nothing new to add")
        return
    inventory.learn(names, args.agent)


if __name__ == "__main__":
    sys.exit(main())
