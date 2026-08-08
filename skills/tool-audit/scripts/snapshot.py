#!/usr/bin/env python3
"""Snapshot tool-audit metrics over time, to track state that transcripts can't.

`usage.py --trends` already gives live trends for transcript-derived metrics, but
(a) it's blind to inventory and config/allowlist state, and (b) it silently loses
history when old transcripts age out (cleanupPeriodDays). This appends a compact,
dated metrics record so those numbers survive and non-transcript state is tracked.

Writes one JSON object per line under the private tool-audit data directory.
Set TOOL_AUDIT_DATA_DIR to override the OS-specific data root.

Usage:
  python snapshot.py                # compute + append one snapshot
  python snapshot.py --history      # print the logged snapshots as a trend table
  python snapshot_custom.py PATH    # custom paths remain approval-gated
"""
import argparse, json, os, sys
from collections import Counter
from datetime import datetime

sys.dont_write_bytecode = True

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import (data_root, session_files, iter_tool_uses, first_real_prog,
                     prog_key, classify)
import inventory as inv
import config_audit as cfg

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TRACK_ADV = ["rg", "sg", "readtags", "fd", "difft", "tokei", "yq", "gitleaks", "lychee"]


def default_file(agent):
    return os.path.join(data_root(agent), "history.jsonl")


def compute(agent="auto", config_path=None):
    agent = cfg.config_agent(agent)
    # --- transcript side ---
    tool_calls = 0
    bash_total = cd_prefixed = native = 0
    cls = Counter()
    adv = Counter()
    files = session_files(agent=agent)
    for f in files:
        for name, inp, ts, uid in iter_tool_uses(f):
            tool_calls += 1
            if name in ("Read", "Grep", "Glob"):
                native += 1
            if name != "Bash":
                continue
            cmd = str(inp.get("command", ""))
            if not cmd.strip():
                continue
            bash_total += 1
            if cmd.lstrip().startswith("cd "):
                cd_prefixed += 1
            prog, toks, seg = first_real_prog(cmd)
            if not prog:
                continue
            key, sub = prog_key(prog, toks)
            cls[classify(prog, sub)] += 1
            if prog in TRACK_ADV:
                adv[prog] += 1

    # --- inventory side ---
    installed = inv.path_executables()
    cat_of = inv.category_of()
    from _common import load_classes
    known = {t for (t, _s) in load_classes().keys()}
    labeled = uncategorized = systemc = 0
    for name, path in installed.items():
        if cat_of.get(name) is None and name not in known:
            if inv.is_system(path):
                systemc += 1
            else:
                uncategorized += 1
        else:
            labeled += 1

    # --- config side ---
    config = cfg.load_config(config_path or cfg.default_config(agent), agent)
    prefixes = cfg.configured_prefixes(config, agent)
    lint_err = lint_warn = 0
    for p in prefixes:
        c, _ = cfg.rule_class(p)
        if c == "destructive":
            lint_err += 1
        elif c in ("write", "mixed"):
            lint_warn += 1
    if agent == "claude":
        for tool, needed in cfg.GUARDED.items():
            if not any(cfg.covered(n, prefixes) for n in needed):
                lint_warn += 1

    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "agent": agent,
        "sessions": len(files),
        "tool_calls": tool_calls,
        "bash_total": bash_total,
        "cd_pct": round(100 * cd_prefixed / bash_total, 1) if bash_total else 0,
        "native_pct": round(100 * native / tool_calls, 1) if tool_calls else 0,
        "class": dict(cls),
        "unknown_class": cls.get("unknown", 0),
        "adv": {t: adv.get(t, 0) for t in TRACK_ADV},
        "inv": {"on_path": len(installed), "labeled": labeled,
                "uncategorized": uncategorized, "system": systemc},
        "cfg": {"allow_rules": cfg.configured_rule_count(config, agent),
                "allow_bash_rules": cfg.configured_rule_count(config, agent),
                "lint_errors": lint_err, "lint_warns": lint_warn},
    }


def append(path, rec, private_dir=False):
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, mode=0o700 if private_dir else 0o755, exist_ok=True)
    if private_dir and os.name != "nt":
        os.chmod(parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def load(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def show_history(path):
    rows = load(path)
    if not rows:
        print(f"no snapshots yet at {path}\n(run without --history to record one)")
        return
    print(f"=== tool-audit history ({len(rows)} snapshots) - {path} ===")
    hdr = f"  {'date':<16} {'sess':>4} {'cd%':>5} {'nat%':>5} {'unk':>5} {'sg':>3} {'rtag':>4} {'fd':>3} {'lbl':>4} {'rules':>5} {'lintE/W':>8}"
    print(hdr)
    for r in rows:
        adv = r.get("adv", {})
        c = r.get("cfg", {})
        iv = r.get("inv", {})
        print(f"  {r.get('date',''):<16} {r.get('sessions',0):>4} {r.get('cd_pct',0):>5} "
              f"{r.get('native_pct',0):>5} {r.get('unknown_class',0):>5} "
              f"{adv.get('sg',0):>3} {adv.get('readtags',0):>4} {adv.get('fd',0):>3} "
              f"{iv.get('labeled',0):>4} {c.get('allow_rules',c.get('allow_bash_rules',0)):>5} "
              f"{str(c.get('lint_errors',0))+'/'+str(c.get('lint_warns',0)):>8}")
    print("  (cd%=redundant-cd rate, nat%=native-tool share, unk=unknown-class bash cmds, "
          "sg/rtag/fd=advanced-tool uses, lbl=labeled tools, rules=allowlisted Bash rules, "
          "lintE/W=config lint errors/warnings)")


# metric -> "down"=lower is better, "up"=higher is better, "flat"=neutral/track-only
DIRECTION = {
    "cd_pct": "down", "unknown_class": "down", "uncategorized": "down",
    "lint_errors": "down", "lint_warns": "down",
    "native_pct": "up", "labeled": "up",
    "sessions": "flat", "allow_rules": "flat",
}


def flatten(rec):
    d = {
        "sessions": rec.get("sessions"),
        "cd_pct": rec.get("cd_pct"),
        "native_pct": rec.get("native_pct"),
        "unknown_class": rec.get("unknown_class"),
        "labeled": rec.get("inv", {}).get("labeled"),
        "uncategorized": rec.get("inv", {}).get("uncategorized"),
        "allow_rules": rec.get("cfg", {}).get(
            "allow_rules", rec.get("cfg", {}).get("allow_bash_rules")),
        "lint_errors": rec.get("cfg", {}).get("lint_errors"),
        "lint_warns": rec.get("cfg", {}).get("lint_warns"),
    }
    for t, v in rec.get("adv", {}).items():
        d["adv." + t] = v
    return d


def direction(metric):
    if metric.startswith("adv."):
        return "up"          # more advanced-tool use = adoption win
    return DIRECTION.get(metric, "flat")


def diff(old, new):
    """Return [(metric, oldval, newval, delta, verdict)] for metrics that moved."""
    out = []
    for k in sorted(set(old) | set(new)):
        o, n = old.get(k), new.get(k)
        if o is None or n is None or o == n:
            continue
        delta = round(n - o, 2)
        d = direction(k)
        arrow = "up" if delta > 0 else "down"
        if d == "flat":
            verdict = "·"
        elif d == arrow:
            verdict = "WIN"
        else:
            verdict = "REGRESSION"
        out.append((k, o, n, delta, verdict))
    return out


def render_diff(title, old, new):
    print(f"\n{title}  ({old.get('date','?')}  ->  {new.get('date','?')})")
    rows = diff(flatten(old), flatten(new))
    if not rows:
        print("   (no tracked metric changed)")
        return
    for k, o, n, dl, verdict in rows:
        sign = f"+{dl}" if dl > 0 else f"{dl}"
        tag = "" if verdict == "·" else f"   [{verdict}]"
        print(f"   {k:<16} {o!s:>7} -> {n!s:<7} ({sign}){tag}")


def show_changes(path):
    rows = load(path)
    if len(rows) < 2:
        print(f"need >=2 snapshots to compare (have {len(rows)}). Record more with "
              "`snapshot.py` over time.")
        return
    # dates carry the record's stamp; rows are append-order = chronological
    render_diff("SINCE PREVIOUS", rows[-2], rows[-1])
    if len(rows) > 2:
        render_diff(f"OVERALL (first -> latest, {len(rows)} snapshots)", rows[0], rows[-1])
    # headline flags
    latest = flatten(rows[-1])
    flags = []
    if latest.get("lint_errors"):
        flags.append(f"config lint has {latest['lint_errors']} ERROR(s) — a destructive rule is allowlisted")
    overall = diff(flatten(rows[0]), flatten(rows[-1]))
    regs = [k for k, *_r, v in overall if v == "REGRESSION"]
    wins = [k for k, *_r, v in overall if v == "WIN"]
    if regs:
        flags.append("regressions since first snapshot: " + ", ".join(regs))
    if wins:
        flags.append("improvements since first snapshot: " + ", ".join(wins))
    print("\nFLAGS:")
    print("   " + ("\n   ".join(flags) if flags else "(nothing notable)"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history", action="store_true", help="print logged snapshots as a table")
    ap.add_argument("--changes", action="store_true", help="analyse deltas + flag regressions/wins")
    ap.add_argument("--agent", choices=("auto", "claude", "codex"), default="auto")
    ap.add_argument("--config", help="Claude settings.json or Codex rules file/directory override")
    args = ap.parse_args()
    agent = cfg.config_agent(args.agent)
    path = default_file(agent)
    if args.history:
        show_history(path)
        return
    if args.changes:
        show_changes(path)
        return
    rec = compute(agent, args.config)
    append(path, rec, private_dir=True)
    print(f"snapshot recorded -> {path}")
    print(json.dumps(rec, indent=2))


if __name__ == "__main__":
    sys.exit(main())
