#!/usr/bin/env python3
"""Reconcile Claude Code or Codex permission config against catalog + usage.

Two jobs, both closing the loop the rest of the skill only describes:

  --suggest : read-class commands run often but NOT on the allowlist -> candidate
              `allow` rules (so you extend the allowlist from data, not by hand).
  --lint    : safety/consistency check across command-classes.tsv and the
              selected agent's permission rules (plus Claude guard hooks):
              destructive/write commands that are allowlisted, allowlisted
              commands with no class entry, and guarded tools missing an allow rule.

Usage:
  python config_audit.py                 # both, current agent's global config
  python config_audit.py --suggest --min 5
  python config_audit.py --lint
  python config_audit.py --agent claude --config /path/to/settings.json
  python config_audit.py --agent codex --config /path/to/rules-or-directory
  python config_audit.py --project bislab --since 2026-07-01   # scope the usage side
"""
import argparse, ast, glob, itertools, json, os, re, shlex, sys
from collections import Counter

sys.dont_write_bytecode = True

from _common import (active_agent, agent_home, session_files, iter_tool_uses, first_real_prog,
                     prog_key, classify, redact_sensitive)
from audit import PROFILES

# Force UTF-8 stdout so a non-cp1252 char in a command snippet/path can't abort output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_SETTINGS = os.path.join(agent_home("claude"), "settings.json")
DEFAULT_RULES = os.path.join(agent_home("codex"), "rules")
# Tools the guard hooks (read-guard.sh) treat as read-with-a-write-form; each
# needs an allow rule or the "silent read / prompt on write" contract half-breaks.
GUARDED = {"cat": ["cat"], "find": ["find"], "fd": ["fd"],
           "yq": ["yq"], "sg": ["sg run", "sg scan"]}


def load_settings(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(f"cannot read settings ({path}): {e}", file=sys.stderr)
        return {}


def load_codex_rules(path):
    """Parse one rules file or every *.rules file in a directory, without execution."""
    paths = sorted(glob.glob(os.path.join(path, "*.rules"))) if os.path.isdir(path) else [path]
    out = []
    for rules_path in paths:
        try:
            with open(rules_path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=rules_path)
        except Exception as e:
            print(f"cannot read rules ({rules_path}): {e}", file=sys.stderr)
            continue
        for node in tree.body:
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Name) or call.func.id != "prefix_rule":
                continue
            values = {}
            for kw in call.keywords:
                if kw.arg in ("pattern", "decision"):
                    try:
                        values[kw.arg] = ast.literal_eval(kw.value)
                    except Exception:
                        pass
            pattern = values.get("pattern")
            decision = values.get("decision")
            if not isinstance(pattern, list) or not isinstance(decision, str):
                continue
            choices = []
            valid = True
            for part in pattern:
                if isinstance(part, str):
                    choices.append([part])
                elif isinstance(part, list) and part and all(isinstance(x, str) for x in part):
                    choices.append(part)
                else:
                    valid = False
                    break
            if valid:
                for expanded in itertools.product(*choices):
                    out.append({"decision": decision, "tokens": list(expanded),
                                "rule_id": f"{rules_path}:{getattr(node, 'lineno', 0)}"})
    return out


def config_agent(agent):
    selected = active_agent(agent)
    if selected != "all":
        return selected
    if os.path.exists(DEFAULT_RULES):
        return "codex"
    return "claude"


def default_config(agent):
    return DEFAULT_RULES if agent == "codex" else DEFAULT_SETTINGS


def load_config(path, agent):
    return load_codex_rules(path) if agent == "codex" else load_settings(path)


def allow_prefixes(settings):
    """Inner command prefixes of every Bash(...) allow rule, ':*' stripped."""
    out = []
    for r in settings.get("permissions", {}).get("allow", []):
        m = re.match(r"^Bash\((.*)\)$", r)
        if not m:
            continue
        out.append(re.sub(r":\*$", "", m.group(1)).strip())
    return out


def is_token_prefix(prefix, command):
    return command[:len(prefix)] == prefix


def codex_effective_allow_rules(rules):
    """Return allow expansions not fully shadowed by prompt/forbidden rules."""
    restrictive = [r["tokens"] for r in rules
                   if r.get("decision") in ("prompt", "forbidden")]
    return [r for r in rules if r.get("decision") == "allow"
            and not any(is_token_prefix(prefix, r["tokens"])
                        for prefix in restrictive)]


def codex_allow_prefixes(rules):
    return [shlex.join(r["tokens"]) for r in codex_effective_allow_rules(rules)]


def configured_prefixes(config, agent):
    return codex_allow_prefixes(config) if agent == "codex" else allow_prefixes(config)


def configured_rule_count(config, agent):
    if agent == "codex":
        return len({r.get("rule_id", str(i))
                    for i, r in enumerate(codex_effective_allow_rules(config))})
    return len(allow_prefixes(config))


def tokens(s):
    try:
        return shlex.split(s)
    except ValueError:
        return s.split()


def covered(cmd, prefixes):
    ct = tokens(cmd)
    for p in prefixes:
        pt = tokens(p)
        if pt and ct[:len(pt)] == pt:
            return True
    return False


def rule_class(prefix):
    pt = tokens(prefix)
    if not pt:
        return "unknown", prefix
    prog = re.sub(r"\.exe$", "", re.split(r"[/\\]", pt[0])[-1])
    pt = [prog, *pt[1:]]
    _key, sub = prog_key(prog, pt)
    return classify(prog, sub), prog


def rule_text(prefix, agent):
    prefix = redact_sensitive(prefix)
    if agent == "codex":
        return f"prefix_rule(pattern={json.dumps(tokens(prefix))}, decision=\"allow\")"
    return f'"Bash({prefix}:*)"'


def scoped_audit_profile(prefix):
    """Recognize a fixed profile from any installed copy of this skill."""
    pt = tokens(prefix)
    for i, token in enumerate(pt):
        normalized = os.path.normcase(os.path.normpath(os.path.expanduser(token)))
        parts = normalized.replace("\\", "/").split("/")
        if (parts[-3:] == ["tool-audit", "scripts", "audit.py"]
                and i + 2 == len(pt) and pt[i + 1] in PROFILES):
            return pt[i + 1]
    return None


def suggest(args, config):
    prefixes = configured_prefixes(config, args.agent)
    counts = Counter()   # candidate key -> uses
    for f in session_files(args.project, args.agent):
        for name, inp, ts, uid in iter_tool_uses(f):
            if name != "Bash":
                continue
            d = ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None
            if args.since and d and d < args.since:
                continue
            if args.until and d and d > args.until:
                continue
            cmd = str(inp.get("command", ""))
            if not cmd.strip():
                continue
            prog, toks, seg = first_real_prog(cmd)
            if not prog:
                continue
            key, sub = prog_key(prog, toks)
            if classify(prog, sub) != "read":
                continue
            if covered(seg, prefixes):
                continue
            counts[key] += 1
    print("=== ALLOWLIST SUGGESTIONS ===")
    print(f"read-class commands run >= {args.min}x that still prompt (heuristic: first "
          "segment of each Bash call):\n")
    hits = [(k, n) for k, n in counts.most_common() if n >= args.min]
    if not hits:
        print("  (none — read-class usage is already covered)")
        return
    for k, n in hits:
        print(f"  {n:5d}x   candidate rule:  {rule_text(k, args.agent)}")
    print("\n  Review before adding - a 'read' class is the tool's default; confirm the "
          "specific invocations are genuinely read-only, then add it to the permission config.")
    print("  Note: prefix rules can cover longer or compound commands. Only allow a prefix whose "
          "mutation-capable forms remain excluded by the chosen token boundary.")


def lint(config, agent="claude"):
    prefixes = configured_prefixes(config, agent)
    print("\n=== CONFIG LINT ===")
    errors, warns, infos, summary = [], [], [], Counter()
    scoped_profiles = set()
    for p in prefixes:
        profile = scoped_audit_profile(p)
        if profile:
            scoped_profiles.add(profile)
            continue
        cls, prog = rule_class(p)
        summary[cls] += 1
        if cls == "destructive":
            errors.append(f"allowlisted DESTRUCTIVE command: {rule_text(p, agent)}  (should this auto-run?)")
        elif cls == "write":
            warns.append(f"allowlisted write command: {rule_text(p, agent)}  (intended? e.g. build artifacts)")
        elif cls == "mixed":
            warns.append(f"allowlisted mixed read/write command: {rule_text(p, agent)}  "
                         "(narrow it to a read-only form or guard its flags)")
        elif cls == "network":
            infos.append(f"allowlisted network command: {rule_text(p, agent)}  "
                         "(verify its method cannot mutate remote state)")
        elif cls == "exec":
            infos.append(f"allowlisted code/build command: {rule_text(p, agent)}  "
                         "(may execute code or write build artifacts)")
        elif cls == "unknown":
            infos.append(f"allowlisted but no class in catalog: {rule_text(p, agent)}  (classify it in command-classes.tsv)")
    # guarded tools must have an allow rule, else read forms still prompt.
    # Use covered() (token-prefix) not exact membership, so a broad Bash(sg:*)
    # rule correctly counts as covering "sg run"/"sg scan".
    if agent == "claude":
        for tool, needed in GUARDED.items():
            if not any(covered(n, prefixes) for n in needed):
                warns.append(f"guarded tool '{tool}' has no allow rule ({'/'.join(needed)}) - "
                             "its read forms will still prompt")

    def block(title, items):
        print(f"\n{title}: {len(items)}")
        for x in items:
            print("   " + x)

    block("ERRORS", errors)
    block("WARNINGS", warns)
    block("INFO", infos)
    kept = " ".join(f"{k}={v}" for k, v in summary.most_common())
    if scoped_profiles:
        kept = (kept + " " if kept else "") + f"scoped-audit={len(scoped_profiles)}"
    print(f"\nallowlisted command rules by class: {kept}")
    print("  (read rules are quiet; destructive is an error; write/mixed are warnings; "
          "network/exec/unknown are review information.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suggest", action="store_true")
    ap.add_argument("--lint", action="store_true")
    ap.add_argument("--agent", choices=("auto", "claude", "codex"), default="auto")
    ap.add_argument("--config", "--settings", dest="config",
                    help="Claude settings.json or Codex rules file/directory "
                         "(default: selected agent's global config)")
    ap.add_argument("--min", type=int, default=3, help="min uses for a suggestion (default 3)")
    ap.add_argument("--project")
    ap.add_argument("--since")
    ap.add_argument("--until")
    args = ap.parse_args()

    args.agent = config_agent(args.agent)
    path = args.config or default_config(args.agent)
    config = load_config(path, args.agent)
    if not config:
        return 1
    both = not args.suggest and not args.lint
    if args.suggest or both:
        suggest(args, config)
    if args.lint or both:
        lint(config, args.agent)


if __name__ == "__main__":
    sys.exit(main())
