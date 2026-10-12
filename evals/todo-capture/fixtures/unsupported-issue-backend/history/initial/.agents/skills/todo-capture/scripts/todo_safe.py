#!/usr/bin/env python3
"""Permission-safe todo-capture dispatcher for the fixed OS-native store.

Unlike todo.py, this entry point has no custom path option. Automatic Codex and
Claude rules pin this script plus one enumerated subcommand; argparse validates
all remaining arguments as todo data.
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from todo import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main(allow_custom_dir=False, description=__doc__))
