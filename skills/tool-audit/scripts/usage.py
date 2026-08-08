#!/usr/bin/env python3
"""Analyze how Claude Code and Codex agents use tools across sessions.

Mines Claude transcripts under CLAUDE_CONFIG_DIR and Codex rollouts under
CODEX_HOME, using each agent's standard user directory when unset. Use --agent
to select a source; auto selects the current harness and falls back to both
when run standalone.

Usage:
  python usage.py                      # volume + Bash program/subcommand + read/write split
  python usage.py --efficiency         # anti-pattern report (cd-prefix, grep-for-symbol, ...)
  python usage.py --trends             # weekly trajectory (Bash%, cd-rate, native share, advanced tools)
  python usage.py --mcp                # MCP usage grouped by server and tool
  python usage.py --errors             # explicit errors, shell failures, and patch failures
  python usage.py --friction           # aggregate session, approval, and workflow friction
  python usage.py --forgotten          # installed tools that are (almost) never invoked
  python usage.py --project bislab     # restrict to project dirs matching a substring
  python usage.py --since 2026-07-01   # only sessions on/after this date (--until also works)
  python usage.py --top 40             # rows in the Bash breakdown (default 30)
Flags combine freely.
"""
import argparse, json, os, re, shutil, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.dont_write_bytecode = True

from _common import (session_files, iter_session_records, iter_tool_uses,
                     iter_tool_result_details, first_real_prog, prog_key, classify,
                     load_classes)

# Windows consoles/pipes default to cp1252; transcript snippets and paths can hold
# chars outside it (emoji, CJK). Force UTF-8 so a report never aborts mid-print.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ADVANCED = ["rg", "sg", "ast-grep", "readtags", "difft", "tokei", "yq", "fd", "gitleaks", "lychee"]
CONFIG_RE = re.compile(r"\.(json|ya?ml|csproj|props|targets|toml)($|[\"'\s])", re.I)
NESTED_UID_RE = re.compile(r"^(.*):\d+$")


def day_of(ts):
    return ts[:10] if isinstance(ts, str) and len(ts) >= 10 else None


def week_of(dstr):
    try:
        d = datetime.strptime(dstr, "%Y-%m-%d")
    except Exception:
        return None
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def collect(args):
    files = session_files(args.project, args.agent)
    r = {
        "files": len(files),
        "tool_counts": Counter(), "bash_keys": Counter(), "bash_class": Counter(),
        "bash_total": 0, "cd_prefixed": 0,
        "grep_standalone": [], "grep_piped": 0,
        "cat_read": [], "cat_write": [], "cat_piped": 0,
        "locate": [], "config_bash": [], "config_read": [],
        "advanced": Counter(), "reads": defaultdict(list),
        "weekly": defaultdict(Counter),
        "mcp": Counter(), "errors": Counter(), "failure_kinds": Counter(),
        "expected_nonzero": Counter(), "result_records": 0, "used_progs": set(),
    }
    for f in files:
        meta = {}  # tool_use_id -> call metadata, for error correlation
        nested_meta = defaultdict(list)  # outer exec call ID -> nested call metadata
        for name, inp, ts, uid in iter_tool_uses(f):
            d = day_of(ts)
            if args.since and d and d < args.since:
                continue
            if args.until and d and d > args.until:
                continue
            r["tool_counts"][name] += 1
            label = name
            if name.startswith("mcp__"):
                r["mcp"][name] += 1
            wk = week_of(d) if d else None
            if wk:
                w = r["weekly"][wk]
                w["tool_calls"] += 1
                if name in ("Read", "Grep", "Glob"):
                    w["native_search_read"] += 1
                if name == "Bash":
                    w["bash"] += 1
            if name == "Read":
                fp = inp.get("file_path", "")
                if fp:
                    r["reads"][(f, fp)].append(1)
                    if CONFIG_RE.search(fp):
                        r["config_read"].append(fp)
            elif name == "Bash":
                cmd = str(inp.get("command", ""))
                if cmd.strip():
                    label = analyze_bash(cmd, r, wk)
            if uid:
                call_meta = {"label": label, "name": name,
                             "command": str(inp.get("command", ""))}
                meta[uid] = call_meta
                nested = NESTED_UID_RE.match(str(uid))
                if nested:
                    nested_meta[nested.group(1)].append(call_meta)
        if args.errors:
            for uid, detail in iter_tool_result_details(f):
                r["result_records"] += 1
                call_meta = result_call_meta(uid, meta, nested_meta, detail)
                record_failure(r, call_meta, detail)
    return r


def result_call_meta(uid, meta, nested_meta, detail):
    """Resolve a result to one call without pretending wrapped calls are exact."""
    if uid in meta:
        return meta[uid]
    candidates = nested_meta.get(uid, [])
    if not candidates:
        return None
    if detail["patch_failure"]:
        patch_calls = [item for item in candidates if item["name"] == "apply_patch"]
        if len(patch_calls) == 1:
            return patch_calls[0]
        if patch_calls:
            return {"label": "exec (nested apply_patch)", "name": "apply_patch",
                    "command": ""}
    if detail["process_exit_codes"]:
        shell_calls = [item for item in candidates if item["name"] == "Bash"]
        if len(shell_calls) == 1:
            return shell_calls[0]
    if len(candidates) == 1:
        return candidates[0]
    return {"label": "exec (nested tools)", "name": "exec", "command": ""}


def expected_nonzero(command, label, code):
    """Recognize conservative command statuses that normally mean 'different/no match'."""
    if code != 1:
        return False
    prog, _toks, _seg = first_real_prog(command)
    if prog in ("rg", "grep", "cmp", "diff", "test", "[", "which"):
        return True
    if prog == "command" and re.search(r"\bcommand\s+-(?:v|V)\b", command):
        return True
    if label == "git grep":
        return True
    return label == "git diff" and bool(re.search(r"--(?:quiet|exit-code)\b", command))


def record_failure(r, call_meta, detail):
    """Classify one result record into actionable or expected signals."""
    label = call_meta["label"] if call_meta else "unattributed tool result"
    command = call_meta["command"] if call_meta else ""
    if detail["is_error"]:
        r["errors"][label] += 1
        r["failure_kinds"]["explicit is_error"] += 1
        return
    if detail["patch_failure"] and call_meta and call_meta["name"] == "apply_patch":
        r["errors"][label] += 1
        r["failure_kinds"]["patch application failure"] += 1
        return
    nonzero = [code for code in detail["process_exit_codes"] if code != 0]
    if not nonzero:
        return
    code = nonzero[-1]
    if call_meta and call_meta["name"] == "Bash" and expected_nonzero(
            command, label, code):
        r["expected_nonzero"][f"{label} (exit {code})"] += 1
        return
    r["errors"][label] += 1
    r["failure_kinds"][f"process exit {code}"] += 1


def analyze_bash(cmd, r, wk):
    r["bash_total"] += 1
    if re.match(r"^\s*cd\b", cmd):
        r["cd_prefixed"] += 1
        if wk:
            r["weekly"][wk]["cd_prefixed"] += 1
    prog, toks, seg = first_real_prog(cmd)
    if prog is None:
        return "Bash"
    r["used_progs"].add(prog)
    key, sub = prog_key(prog, toks)
    r["bash_keys"][key] += 1
    r["bash_class"][classify(prog, sub)] += 1
    if prog in ADVANCED:
        r["advanced"][prog] += 1
        if wk:
            r["weekly"][wk]["advanced"] += 1
    if re.search(r"\|\s*grep\b", cmd):
        r["grep_piped"] += 1
    elif prog == "grep":
        r["grep_standalone"].append(cmd.strip()[:90])
    if prog == "cat":
        if re.search(r">>?|<<", seg):
            r["cat_write"].append(cmd.strip()[:90])
        elif "|" in cmd:
            r["cat_piped"] += 1
        else:
            r["cat_read"].append(cmd.strip()[:90])
            if CONFIG_RE.search(seg):
                r["config_bash"].append(cmd.strip()[:90])
    if prog in ("find", "fd", "ls"):
        r["locate"].append(cmd.strip()[:90])
    return key


def pct(a, b):
    return f"{(100*a//b) if b else 0}%"


def report_default(r, top):
    tc = r["tool_counts"]
    print(f"=== VOLUME ({r['files']} sessions) ===")
    print(f"Total tool calls: {sum(tc.values())}")
    for k, v in tc.most_common(15):
        print(f"  {v:6d}  {k}")
    print(f"\n=== BASH: program / subcommand (top {top}) ===")
    for k, v in r["bash_keys"].most_common(top):
        print(f"  {v:6d}  {k}")
    print("\n=== BASH read/write class (from command-classes.tsv) ===")
    for k, v in r["bash_class"].most_common():
        print(f"  {v:6d}  {k}")


def report_efficiency(r):
    bt = r["bash_total"]
    print("\n=== EFFICIENCY / ANTI-PATTERNS ===")
    print(f"Bash calls: {bt} | cd-prefixed: {r['cd_prefixed']} ({pct(r['cd_prefixed'], bt)})"
          "   <- Bash starts in the working dir; most cd <root> && are redundant")
    tc = r["tool_counts"]
    print(f"Native search/read: Read={tc['Read']} Grep={tc['Grep']} Glob={tc['Glob']}  "
          f"vs Bash grep-standalone={len(r['grep_standalone'])} cat-read={len(r['cat_read'])} "
          f"locate(find/fd/ls)={len(r['locate'])}")
    print("\nAdvanced tools actually invoked:")
    print("  " + "  ".join(f"{t}={r['advanced'].get(t,0)}" for t in ADVANCED))

    def show(title, lst, n=5):
        print(f"\n{title}  (n={len(lst)})")
        for x in lst[:n]:
            print("   ", x)
        if len(lst) > n:
            print(f"    ... +{len(lst)-n} more")

    show("grep on files (Grep tool / readtags / sg are leaner)", r["grep_standalone"])
    print(f"   (piped `| grep` filters, legitimate: {r['grep_piped']})")
    show("`cat >`/heredoc file writes (use the Write tool)", r["cat_write"])
    show("whole-config reads via cat (jq/yq targets a value)", r["config_bash"])
    show("find/fd/ls to locate files (Glob tool)", r["locate"])
    rereads = sorted(((len(v), p) for (f, p), v in r["reads"].items() if len(v) >= 3), reverse=True)
    print(f"\nRe-reads (same file Read >=3x in a session): {len(rereads)}")
    for c, p in rereads[:6]:
        print(f"   {c}x  {os.path.basename(p)}")


def report_trends(r):
    print("\n=== TRENDS (by ISO week starting Monday) ===")
    weeks = sorted(r["weekly"])
    if not weeks:
        print("  (no dated sessions in range)")
        return
    print(f"  {'week':<12} {'calls':>6} {'bash%':>6} {'cd%':>5} {'native%':>8} {'adv':>4}")
    for wk in weeks:
        w = r["weekly"][wk]
        c = w["tool_calls"]
        print(f"  {wk:<12} {c:>6} {pct(w['bash'], c):>6} {pct(w['cd_prefixed'], w['bash']):>5} "
              f"{pct(w['native_search_read'], c):>8} {w['advanced']:>4}")
    print("  (bash%=Bash share; cd%=Bash that cd-prefix; native%=Read+Grep+Glob; adv=advanced-tool calls)")


def report_mcp(r):
    print("\n=== MCP USAGE (by server / tool) ===")
    if not r["mcp"]:
        print("  (no MCP tool calls in range)")
        return
    by_server = defaultdict(Counter)
    for name, n in r["mcp"].items():
        parts = name.split("__", 2)  # mcp__<server>__<tool>
        server = parts[1] if len(parts) > 1 else "?"
        tool = parts[2] if len(parts) > 2 else name
        by_server[server][tool] += n
    for server in sorted(by_server, key=lambda s: -sum(by_server[s].values())):
        print(f"  {server}  ({sum(by_server[server].values())})")
        for tool, n in by_server[server].most_common(8):
            print(f"      {n:5d}  {tool}")


def source_key(value):
    if value == "cli":
        return "interactive_cli"
    if value == "exec":
        return "autonomous_exec"
    if isinstance(value, dict):
        subagent = value.get("subagent")
        if isinstance(subagent, dict) and str(subagent.get("other", "")).lower() == "guardian":
            return "approval_guardian"
        if str(subagent).lower() == "review":
            return "review_subagent"
        return "subagent"
    return "unknown"


def message_text(content):
    """Extract human text while ignoring Claude tool-result blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in ("text", "input_text") and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(parts)


def role_of(text):
    match = re.search(r"\bRole:\s*(planner|implementer|reviewer)\b", text, re.I)
    return match.group(1).lower() if match else "unknown"


def collect_friction(args):
    """Collect aggregate workflow signals without retaining transcript samples."""
    result = {
        "files": 0,
        "sources": Counter(),
        "messages": defaultdict(Counter),
        "interactive": Counter(),
        "roles": defaultdict(Counter),
        "outcomes": Counter(),
        "issues": Counter(),
        "guardian": Counter(),
    }
    for path in session_files(args.project, args.agent):
        source = None
        session_role = None
        role_recorded = False
        saw_record = False
        for obj in iter_session_records(path):
            saw_record = True
            ts = obj.get("timestamp")
            day = day_of(ts)
            if args.since and day and day < args.since:
                continue
            if args.until and day and day > args.until:
                continue
            if obj.get("type") == "session_meta":
                source = source_key(obj.get("payload", {}).get("source"))
                continue

            text = ""
            if obj.get("type") == "event_msg" and obj.get("payload", {}).get("type") == "user_message":
                text = str(obj.get("payload", {}).get("message", ""))
            elif obj.get("type") == "user":
                msg = obj.get("message", {})
                if isinstance(msg, dict) and msg.get("role", "user") == "user":
                    text = message_text(msg.get("content"))
                    if text and source is None:
                        source = "claude_transcript"

            if text:
                current = source or "unknown"
                stats = result["messages"][current]
                stats["count"] += 1
                stats["bytes"] += len(text)
                stats["oversized_12k"] += int(len(text) > 12000)
                stats["short_under_80"] += int(len(text) < 80)
                if current in ("interactive_cli", "claude_transcript"):
                    signals = result["interactive"]
                    signals["messages"] += 1
                    signals["one_token"] += int(bool(re.fullmatch(
                        r"\s*[A-Za-z0-9][.!?]?\s*", text)))
                    signals["continue_finish"] += int(bool(re.fullmatch(
                        r"\s*(continue|do it|fix it|commit(?: it)?|finish(?: it)?|try again|"
                        r"sounds good[.]? do it)[.!?\s]*", text, re.I)))
                    signals["next_step"] += int(bool(re.search(
                        r"what.{0,20}next|what should we do|what do you "
                        r"(?:recommend|reccomend|recomend|suggest)|next[?]?\s*$", text, re.I)))
                    signals["review_quality"] += int(bool(re.search(
                        r"\breview\b|world.?class|\bperfect\b|quality|\baudit\b", text, re.I)))
                    signals["explicit_correction"] += int(bool(re.search(
                        r"(?:^|[\s\W])(?:no|wrong|incorrect|that.s not|do not|don.t)"
                        r"(?:$|[\s\W])", text, re.I)))
                if current == "autonomous_exec" and not role_recorded:
                    session_role = role_of(text)
                    role_stats = result["roles"][session_role]
                    role_stats["sessions"] += 1
                    role_stats["prompt_bytes"] += len(text)
                    role_recorded = True
                if current == "approval_guardian" and text.startswith(
                        "The following is the Codex agent history"):
                    result["guardian"]["review_prompts"] += 1
                    result["guardian"]["prompt_bytes"] += len(text)

            if obj.get("type") != "event_msg" or obj.get("payload", {}).get("type") != "task_complete":
                continue
            payload = obj.get("payload", {})
            final = str(payload.get("last_agent_message", ""))
            current = source or "unknown"
            if current == "autonomous_exec":
                result["outcomes"]["task_completes"] += 1
                result["outcomes"]["complete_or_review"] += int(bool(re.search(
                    r"complete|returned to .*review|ready for review|implemented", final, re.I)))
                result["outcomes"]["blocked_or_stopped"] += int(bool(re.search(
                    r"blocked|could not complete|unable to complete|stopped", final, re.I)))
                result["outcomes"]["no_work"] += int(bool(re.search(
                    r"no (?:ready |approved )?(?:work|issue|task)|nothing to "
                    r"(?:do|implement)|queue.*empty", final, re.I)))
                result["outcomes"]["concurrency"] += int(bool(re.search(
                    r"concurren|another (?:implementer|agent|process|run)|"
                    r"already.*(?:claimed|working|completed)|duplicate", final, re.I)))
                result["outcomes"]["permission"] += int(bool(re.search(
                    r"approval|permission|sandbox|read.only file system", final, re.I)))
                issue = re.search(r"\b[Ii]ssue #(\d+)\b", final)
                if issue:
                    result["issues"][issue.group(1)] += 1
                if session_role:
                    role_stats = result["roles"][session_role]
                    role_stats["completed"] += 1
                    try:
                        role_stats["duration_ms"] += int(payload.get("duration_ms") or 0)
                    except (TypeError, ValueError):
                        pass
            elif current == "approval_guardian":
                try:
                    decision = json.loads(final)
                except (TypeError, json.JSONDecodeError):
                    result["guardian"]["unparsed_decisions"] += 1
                else:
                    outcome = decision.get("outcome") if isinstance(decision, dict) else None
                    if outcome:
                        result["guardian"][f"decision_{outcome}"] += 1
                    else:
                        result["guardian"]["unparsed_decisions"] += 1
        if saw_record:
            result["files"] += 1
            result["sources"][source or "unknown"] += 1
    return result


def report_friction(r):
    print("\n=== SESSION / WORKFLOW FRICTION (aggregate; no message samples) ===")
    print(f"Sessions: {r['files']}")
    for source, sessions in r["sources"].most_common():
        stats = r["messages"][source]
        print(f"  {source:<22} sessions={sessions:<5} messages={stats['count']:<6} "
              f"bytes={stats['bytes']:<9} oversized>12k={stats['oversized_12k']}")

    interactive = r["interactive"]
    total = interactive["messages"]
    print("\nInteractive conversation signals:")
    if not total:
        print("  (no interactive user messages in range)")
    else:
        for key, label in (
                ("one_token", "one-token choices"),
                ("continue_finish", "continue/finish replies"),
                ("next_step", "next-step questions"),
                ("review_quality", "review/quality requests"),
                ("explicit_correction", "explicit correction language")):
            print(f"  {interactive[key]:6d}  {label:<29} ({pct(interactive[key], total)})")

    print("\nAutonomous role prompts:")
    if not r["roles"]:
        print("  (none in range)")
    for role, stats in sorted(r["roles"].items()):
        sessions = stats["sessions"]
        avg_bytes = stats["prompt_bytes"] // sessions if sessions else 0
        avg_minutes = (stats["duration_ms"] / stats["completed"] / 60000
                       if stats["completed"] else 0)
        print(f"  {role:<12} sessions={sessions:<5} avg_prompt_bytes={avg_bytes:<6} "
              f"avg_duration_min={avg_minutes:.1f}")

    outcomes = r["outcomes"]
    print("\nAutonomous completion signals (heuristic; categories may overlap):")
    if not outcomes:
        print("  (none in range)")
    else:
        for key in ("task_completes", "complete_or_review", "blocked_or_stopped",
                    "no_work", "concurrency", "permission"):
            print(f"  {outcomes[key]:6d}  {key.replace('_', ' ')}")
        repeated = [(issue, count) for issue, count in r["issues"].most_common(10)
                    if count > 1]
        if repeated:
            print("  repeated issue mentions: " + ", ".join(
                f"#{issue}={count}" for issue, count in repeated))

    guardian = r["guardian"]
    print("\nApproval guardian:")
    if not guardian:
        print("  (no guardian prompts or decisions in range)")
    else:
        print(f"  review prompts={guardian['review_prompts']}  "
              f"prompt_bytes={guardian['prompt_bytes']}")
        decisions = sorted((key.removeprefix("decision_"), value)
                           for key, value in guardian.items()
                           if key.startswith("decision_"))
        print("  decisions: " + (", ".join(f"{key}={value}" for key, value in decisions)
                                  if decisions else "(none parsed)"))
        if guardian["unparsed_decisions"]:
            print(f"  unparsed decisions={guardian['unparsed_decisions']}")
    print("  Privacy: reports counts and byte sizes only; no transcript samples are retained.")


def report_errors(r):
    print("\n=== TOOL / COMMAND FAILURE SIGNALS ===")
    print(f"Result records inspected: {r['result_records']}")
    if not r["errors"]:
        print("Actionable failures: 0")
    else:
        total = sum(r["errors"].values())
        print(f"Actionable failures: {total}")
        for kind, n in r["failure_kinds"].most_common():
            print(f"  {n:5d}  signal: {kind}")
        print("Top attributed tools/commands:")
        for label, n in r["errors"].most_common(20):
            print(f"  {n:5d}  {label}")
    expected = sum(r["expected_nonzero"].values())
    print(f"Expected non-error statuses: {expected}")
    for label, n in r["expected_nonzero"].most_common(10):
        print(f"  {n:5d}  {label}")
    print("  Detects explicit is_error, direct shell process exits, and patch failures. "
          "Wrapped exec calls remain conservative when nested result metadata is absent.")


def report_forgotten(r):
    print("\n=== FORGOTTEN TOOLS (installed but (almost) never invoked) ===")
    universe = {t for (t, _sub) in load_classes().keys()}
    for cat in ("rg sg ast-grep fd readtags ctags difft tokei jq yq gitleaks lychee "
                "dotnet cargo go docker kubectl terraform aws az").split():
        universe.add(cat)
    used = r["used_progs"]
    rows = []
    for t in sorted(universe):
        path = shutil.which(t)
        if path:
            rows.append((t, t in used, path))
    forgotten = [t for t, u, _ in rows if not u]
    rare = []  # installed + used but < 3 times
    key_counts = Counter()
    for k, n in r["bash_keys"].items():
        parts = k.split()
        if parts:
            key_counts[parts[0]] += n
    for t, u, _ in rows:
        if u and key_counts.get(t, 0) < 3:
            rare.append(f"{t}({key_counts.get(t,0)})")
    print(f"  installed & probed: {len(rows)}")
    print(f"  NEVER invoked in range: {', '.join(forgotten) if forgotten else '(none)'}")
    print(f"  invoked <3x (barely used): {', '.join(rare) if rare else '(none)'}")
    print("  (cross-references shutil.which against programs actually seen in transcripts.)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project")
    ap.add_argument("--agent", choices=("auto", "claude", "codex", "all"), default="auto",
                    help="transcript source (default: current harness, otherwise all)")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--efficiency", action="store_true")
    ap.add_argument("--trends", action="store_true")
    ap.add_argument("--mcp", action="store_true")
    ap.add_argument("--errors", action="store_true")
    ap.add_argument("--friction", action="store_true")
    ap.add_argument("--forgotten", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    standard_extra = args.efficiency or args.trends or args.mcp or args.errors or args.forgotten
    r = collect(args) if (not args.friction or standard_extra) else None
    if not standard_extra and not args.friction:
        report_default(r, args.top)
    if args.efficiency:
        report_efficiency(r)
    if args.trends:
        report_trends(r)
    if args.mcp:
        report_mcp(r)
    if args.errors:
        report_errors(r)
    if args.friction:
        report_friction(collect_friction(args))
    if args.forgotten:
        report_forgotten(r)


if __name__ == "__main__":
    sys.exit(main())
