#!/usr/bin/env python3
"""Use a custom snapshot history path; intentionally not auto-approved."""
import argparse
import json
import sys

sys.dont_write_bytecode = True

import config_audit as cfg
import snapshot


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="custom JSONL history path")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--changes", action="store_true")
    ap.add_argument("--agent", choices=("auto", "claude", "codex"), default="auto")
    ap.add_argument("--config", help="Claude settings.json or Codex rules file/directory override")
    args = ap.parse_args()
    if args.history:
        snapshot.show_history(args.file)
        return
    if args.changes:
        snapshot.show_changes(args.file)
        return
    agent = cfg.config_agent(args.agent)
    rec = snapshot.compute(agent, args.config)
    snapshot.append(args.file, rec)
    print(f"snapshot recorded -> {args.file}")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    sys.exit(main())
