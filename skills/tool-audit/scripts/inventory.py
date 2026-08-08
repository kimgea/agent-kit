#!/usr/bin/env python3
"""Inventory CLI tools installed on this machine.

Detection is DYNAMIC: every run walks $PATH for executables (no hardcoded
"what's installed" list). The CATEGORIES map and command-classes.tsv are only
an overlay that *labels* what discovery finds with a category and a read/write
class. Anything discovered but unlabeled is surfaced under "uncategorized" so
the catalog can be extended -- categorization is semantic and has no reliable
automatic source, so it stays curated.

Usage:
  python inventory.py                 # installed tools grouped by category (+ uncategorized count)
  python inventory.py --uncategorized # also list the discovered-but-unlabeled executables
  python inventory_versions.py        # probe versions (executes installed tools; approval-gated)
  python inventory_learn.py           # persist uncategorized names (writes; approval-gated)
  python inventory.py --json          # machine-readable
"""
import argparse, json, os, subprocess, sys
from collections import defaultdict

sys.dont_write_bytecode = True

from _common import active_agent, classify, data_root, load_classes

# Force UTF-8 stdout so a non-cp1252 char in a tool path can't abort output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# category -> tools. Pure labeling overlay; NOT the source of what's installed.
CATEGORIES = {
    "search/nav": ["rg", "sg", "ast-grep", "fd", "grep", "find", "readtags", "ctags"],
    "data/format": ["jq", "yq", "difft", "tokei"],
    "git/pr": ["git", "gh", "rail", "lazygit"],
    "secrets/links": ["gitleaks", "lychee"],
    "languages/build": ["dotnet", "node", "npm", "npx", "yarn", "pnpm", "python",
                        "python3", "py", "pip", "pipx", "uv", "cargo", "rustc", "go"],
    "cloud/infra": ["docker", "docker-compose", "kubectl", "aws", "az", "terraform"],
    "editors/agents": ["code", "cursor", "aider", "codex", "gemini", "kiro", "claude", "neovim"],
    "shell/util": ["bash", "pwsh", "curl", "wget", "tar", "zip", "unzip", "make",
                   "cmake", "sed", "awk", "fzf", "btop", "taskkill", "pwd", "which", "command"],
}
NO_VERSION_PROBE = {"fzf", "lazygit", "btop", "vim", "nano", "less", "more"}


def is_system(path):
    """OS plumbing lives here; dev tools essentially never do. Filters the
    ~1000+ System32 / coreutil binaries so 'uncategorized' stays a curatable
    dev-tool list. Covers Windows and Unix system dirs. Deliberately does NOT
    include /usr/local or /opt/homebrew — that's where user-installed dev tools
    live on macOS/Linux. Trade-off: on Linux, apt-installed dev tools in /usr/bin
    that aren't in the catalog get filtered too; the curated catalog is the signal
    there, and filtering the coreutil flood is the lesser evil."""
    p = path.replace("\\", "/").lower()
    # Distinctive segments — safe as substrings. NOTE: bare "/bin/" is NOT here:
    # it is a substring of /opt/homebrew/bin, /usr/local/bin, ~/.cargo/bin, Git's
    # mingw64/bin, etc., so it would wrongly filter dev tools. "/usr/bin/" &c. are
    # specific enough. (Git's MSYS coreutils under .../git/usr/bin match "/usr/bin/".)
    segments = (
        "/windows/system32/", "/windows/syswow64/", "/windows/winsxs/",
        "/windowsapps/", "/windows/microsoft.net/",          # Windows
        "/usr/bin/", "/usr/sbin/", "/sbin/", "/usr/libexec/", "/system/library/")  # Unix
    if any(s in p for s in segments):
        return True
    # bare /bin: match the executable's directory exactly, so /opt/.../bin etc. are kept
    return (p.rsplit("/", 1)[0] if "/" in p else "") == "/bin"


def category_of():
    rev = {}
    for cat, tools in CATEGORIES.items():
        for t in tools:
            rev[t] = cat
    return rev


def path_executables():
    """name(lowercased stem) -> full path, first-on-PATH wins (shell resolution order)."""
    seen = {}
    if sys.platform == "win32":
        exts = [e.lower() for e in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT;.COM").split(os.pathsep) if e]
    else:
        exts = None
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if not d or not os.path.isdir(d):
            continue
        try:
            entries = os.listdir(d)
        except OSError:
            continue
        for e in entries:
            full = os.path.join(d, e)
            if exts is not None:
                stem, ext = os.path.splitext(e)
                if ext.lower() not in exts:
                    continue
                key = stem.lower()
            else:
                if os.path.isdir(full) or not os.access(full, os.X_OK):
                    continue
                key = e
            seen.setdefault(key, full)
    return seen


def version_of(name):
    if name in NO_VERSION_PROBE:
        return ""
    for flag in ("--version", "-V", "version"):
        try:
            r = subprocess.run([name, flag], capture_output=True, text=True, timeout=4)
            out = (r.stdout or r.stderr).strip().splitlines()
            if out:
                return out[0][:60]
        except Exception:
            continue
    return "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uncategorized", action="store_true", help="list discovered-but-unlabeled executables")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    installed = path_executables()
    cat_of = category_of()
    known_tools = {t for (t, _s) in load_classes().keys()}

    grouped = defaultdict(list)
    uncategorized = []      # discovered dev tools not in the catalog (curatable)
    system = 0              # OS plumbing, filtered out
    for name in sorted(installed):
        cat = cat_of.get(name)
        cls = classify(name, None)
        if cat is None and name not in known_tools:
            if is_system(installed[name]):
                system += 1
            else:
                uncategorized.append(name)
            continue
        ver = ""
        grouped[cat or "other (classified, uncategorized)"].append(
            {"tool": name, "path": installed[name], "class": cls, "version": ver})

    if args.json:
        print(json.dumps({"grouped": grouped, "uncategorized": uncategorized,
                          "system_filtered": system, "total_on_path": len(installed)}, indent=2))
        return

    order = list(CATEGORIES) + ["other (classified, uncategorized)"]
    for cat in order:
        rows = grouped.get(cat)
        if not rows:
            continue
        print(f"\n=== {cat} ===")
        for r in rows:
            v = f"  ({r['version']})" if r["version"] else ""
            print(f"  {r['tool']:<16} {r['class']:<11} {r['path']}{v}")

    print(f"\n{len(installed)} executables on PATH | "
          f"{sum(len(v) for v in grouped.values())} labeled | {len(uncategorized)} uncategorized "
          f"| {system} system (filtered)")
    if args.uncategorized and uncategorized:
        print("\n=== uncategorized (installed, not OS plumbing, not yet in the catalog) ===")
        for i in range(0, len(uncategorized), 8):
            print("  " + "  ".join(uncategorized[i:i+8]))
    elif uncategorized:
        print("  (run --uncategorized to list them; inventory_learn.py stages them with approval)")

def discovered_file(agent="auto"):
    selected = active_agent(agent)
    if selected == "all":
        raise ValueError("cannot infer agent; pass --agent codex or --agent claude")
    return os.path.join(data_root(selected), "discovered-tools.tsv")


def learn(names, agent="auto"):
    path = discovered_file(agent)
    existing = set()
    if os.path.exists(path):
        try:
            for line in open(path, encoding="utf-8"):
                if line.strip() and not line.startswith("#"):
                    existing.add(line.split("\t")[0].strip())
        except OSError:
            pass
    new = [n for n in names if n not in existing]
    if not new:
        print("\n(--learn: nothing new to add)")
        return
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        header = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as fh:
            if header:
                fh.write("# tool<TAB>category<TAB>class  -- discovered on PATH, fill in and "
                         "promote worthwhile rows into command-classes.tsv\n")
            for n in new:
                fh.write(f"{n}\t?\t?\n")
        if os.name != "nt":
            os.chmod(path, 0o600)
        print(f"\n(--learn: staged {len(new)} tools in {path} "
              "for classification)")
    except OSError as e:
        print(f"\n(--learn: data dir not writable ({e}); no persistence needed -- "
              "discovery runs fresh each invocation)")


if __name__ == "__main__":
    sys.exit(main())
