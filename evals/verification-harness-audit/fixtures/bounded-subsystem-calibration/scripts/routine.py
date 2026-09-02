import subprocess
import sys


COMMANDS = [
    [sys.executable, "-m", "unittest", "tests/unit/test_core.py"],
    [sys.executable, "scripts/static_check.py"],
]


def main():
    for command in COMMANDS:
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
