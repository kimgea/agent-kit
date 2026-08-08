#!/usr/bin/env python3
"""Run a fixed, side-effect-bounded tool-audit profile.

This is the only dispatcher intended for automatic permission rules. It accepts
one enumerated profile and no free-form paths, commands, or passthrough flags.
"""
import argparse
import sys

sys.dont_write_bytecode = True


PROFILES = {
    "inventory": ("inventory", []),
    "inventory-json": ("inventory", ["--json"]),
    "inventory-uncategorized": ("inventory", ["--uncategorized"]),
    "inventory-uncategorized-json": ("inventory", ["--uncategorized", "--json"]),
    "usage": ("usage", []),
    "usage-efficiency": ("usage", ["--efficiency"]),
    "usage-trends": ("usage", ["--trends"]),
    "usage-mcp": ("usage", ["--mcp"]),
    "usage-errors": ("usage", ["--errors"]),
    "usage-friction": ("usage", ["--friction"]),
    "usage-forgotten": ("usage", ["--forgotten"]),
    "config": ("config_audit", []),
    "config-lint": ("config_audit", ["--lint"]),
    "config-suggest": ("config_audit", ["--suggest"]),
    "snapshot": ("snapshot", []),
    "snapshot-history": ("snapshot", ["--history"]),
    "snapshot-changes": ("snapshot", ["--changes"]),
}


def run_profile(profile):
    module_name, args = PROFILES[profile]
    module = __import__(module_name)
    old_argv = sys.argv
    try:
        sys.argv = [f"{module_name}.py", *args]
        return module.main()
    finally:
        sys.argv = old_argv


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", choices=sorted(PROFILES))
    args = ap.parse_args()
    return run_profile(args.profile)


if __name__ == "__main__":
    sys.exit(main())
