"""Shared helpers for the tool-audit scripts."""
import ast, glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES_TSV = os.path.join(HERE, "..", "references", "command-classes.tsv")

# Programs that are shell scaffolding, not the "real" command of a line.
SCAFFOLD = {"cd", "pushd", "popd", "export", "set", "source", ".", ":", "true", "env"}

# Commands where the second token (subcommand) is the meaningful unit.
TWO_TOKEN = {"git", "gh", "dotnet", "cargo", "docker", "docker-compose", "kubectl",
             "aws", "az", "terraform", "npm", "npx", "yarn", "pnpm", "go", "rail"}
GH_GROUPS = {"auth", "issue", "label", "pr", "release", "repo", "run", "search", "workflow"}

_SENSITIVE_OUTPUT_PATTERNS = (
    re.compile(r"(?i)(\bauthorization\s*:\s*bearer\s+)([^\s'\"]+)"),
    re.compile(r"(?i)(\bbearer\s+)([A-Za-z0-9._~+/=-]{8,})"),
    re.compile(
        r"(?i)((?:--?)(?:token|password|secret|api[-_]?key|access[-_]?token)"
        r"(?:=|\s+))([^\s'\"]+)"
    ),
    re.compile(
        r"(?i)(\b[A-Za-z0-9_]*(?:TOKEN|PASSWORD|SECRET|API_?KEY|AUTH)"
        r"[A-Za-z0-9_]*=)([^\s'\"]+)"
    ),
    re.compile(r"\b((?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{12,})\b"),
)


def redact_sensitive(value):
    """Redact common credential forms before printing transcript/config text."""
    text = str(value)
    for pattern in _SENSITIVE_OUTPUT_PATTERNS:
        if pattern.groups == 1:
            text = pattern.sub("[REDACTED]", text)
        else:
            text = pattern.sub(lambda match: match.group(1) + "[REDACTED]", text)
    return text


def active_agent(agent="auto"):
    """Resolve auto to the current harness, or all when run standalone."""
    if agent != "auto":
        return agent
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_CI"):
        return "codex"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        return "claude"
    return "all"


def agent_home(agent):
    """Return the selected harness root, honoring its documented override."""
    if agent == "codex":
        root = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    elif agent == "claude":
        root = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
            os.path.expanduser("~"), ".claude")
    else:
        raise ValueError(f"unsupported agent: {agent}")
    return os.path.abspath(os.path.expandvars(os.path.expanduser(root)))


def skill_data_root():
    """Return the private, agent-independent runtime-data directory.

    Keep generated data outside the installed skill and agent configuration
    trees. This lets skill updates stay immutable and gives installers one
    narrow location to expose to a sandbox when a write-capable helper runs.
    """
    override = os.environ.get("TOOL_AUDIT_DATA_DIR")
    if override:
        base = override
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_STATE_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "state")
    base = os.path.abspath(os.path.expandvars(os.path.expanduser(base)))
    return os.path.join(base, "tool-audit")


def data_root(agent):
    """Return the private runtime-data directory for one agent."""
    return os.path.join(skill_data_root(), agent)


def projects_root(agent="claude"):
    leaf = "sessions" if agent == "codex" else "projects"
    return os.path.join(agent_home(agent), leaf)


def _codex_project_matches(path, project_substr):
    if not project_substr:
        return True
    needle = project_substr.lower()
    for obj in _iter_lines(path):
        if obj.get("type") == "session_meta":
            cwd = str(obj.get("payload", {}).get("cwd", ""))
            return needle in cwd.lower()
    return False


def session_files(project_substr=None, agent="auto"):
    """Return Claude and/or Codex JSONL sessions for the requested project."""
    out = []
    selected = active_agent(agent)
    agents = ("claude", "codex") if selected == "all" else (selected,)
    for source in agents:
        root = projects_root(source)
        if not os.path.isdir(root):
            continue
        if source == "claude":
            for proj in sorted(os.listdir(root)):
                if project_substr and project_substr.lower() not in proj.lower():
                    continue
                pdir = os.path.join(root, proj)
                if os.path.isdir(pdir):
                    out.extend(sorted(glob.glob(os.path.join(pdir, "*.jsonl"))))
        else:
            files = sorted(glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True))
            out.extend(f for f in files if _codex_project_matches(f, project_substr))
    return out


def _iter_lines(path):
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def iter_session_records(path):
    """Yield decoded transcript records without exposing the private parser."""
    yield from _iter_lines(path)


def _json_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}
    return {}


def _normalise_tool(name, inp):
    """Map harness-specific shell tools onto the report's historical Bash label."""
    if name in ("exec_command", "shell", "shell_command"):
        cmd = inp.get("cmd", inp.get("command", ""))
        return "Bash", {**inp, "command": cmd}
    return name or "?", inp


_NESTED_TOOL_RE = re.compile(r"\btools\.([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_CMD_RE = re.compile(
    r"\bcmd\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)",
    re.S,
)


def _literal_string(token):
    if not token:
        return ""
    if token.startswith("`"):
        return token[1:-1]
    try:
        return ast.literal_eval(token)
    except Exception:
        return token[1:-1]


def _codex_exec_calls(source, call_id):
    """Extract statically visible nested tool call sites from Codex exec JavaScript.

    Programmatic loops may execute a call site more than once; transcripts do not
    retain each nested invocation separately, so this intentionally reports call
    sites rather than inventing an exact runtime count.
    """
    matches = list(_NESTED_TOOL_RE.finditer(source))
    for i, match in enumerate(matches):
        name = match.group(1)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        inp = {}
        if name == "exec_command":
            found = _CMD_RE.search(source, match.end(), end)
            if found:
                inp["cmd"] = _literal_string(found.group(1))
        name, inp = _normalise_tool(name, inp)
        yield name, inp, f"{call_id}:{i}"


def iter_tool_uses(path):
    """Yield normalized tool calls from Claude Code or Codex JSONL."""
    for obj in _iter_lines(path):
        ts = obj.get("timestamp")
        if obj.get("type") == "response_item":
            item = obj.get("payload")
            if not isinstance(item, dict):
                continue
            typ = item.get("type")
            if typ == "function_call":
                inp = _json_dict(item.get("arguments"))
                name, inp = _normalise_tool(item.get("name"), inp)
                yield name, inp, ts, item.get("call_id")
            elif typ == "custom_tool_call":
                call_id = item.get("call_id")
                name = item.get("name")
                source = item.get("input", "")
                if name == "exec" and isinstance(source, str):
                    nested = list(_codex_exec_calls(source, call_id))
                    if nested:
                        for nested_name, inp, uid in nested:
                            yield nested_name, inp, ts, uid
                    else:
                        yield "exec", {"code": source}, ts, call_id
                else:
                    inp = source if isinstance(source, dict) else {"input": source}
                    yield name or "?", inp, ts, call_id
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                inp = item.get("input")
                yield item.get("name", "?"), (inp if isinstance(inp, dict) else {}), ts, item.get("id")


def _is_error(value):
    if isinstance(value, dict):
        if value.get("is_error") is True or value.get("isError") is True:
            return True
        return any(_is_error(v) for v in value.values())
    if isinstance(value, list):
        return any(_is_error(v) for v in value)
    if isinstance(value, str):
        try:
            return _is_error(json.loads(value))
        except Exception:
            return False
    return False


_PROCESS_EXIT_RE = re.compile(r"(?:^|\n)Process exited with code (-?\d+)(?:\n|$)")
_PATCH_FAILURE_RE = re.compile(
    r"^apply_patch verification failed(?::|$)",
    re.I | re.M,
)


def _output_strings(value):
    """Yield string leaves from structured tool output."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _output_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _output_strings(item)


def tool_result_detail(value):
    """Return conservative failure signals present in one tool result.

    Codex shell results commonly encode the process status in text rather than
    setting ``is_error``. Newer wrapped ``exec`` calls may expose only rendered
    text, so detect only stable result markers and leave ambiguous nested
    ``exit=...`` snippets unclassified.
    """
    codes = []
    patch_failure = False
    for text in _output_strings(value):
        # A command may print a previous Codex result as ordinary output. The
        # first envelope status belongs to the current result; later matches
        # are untrusted command output and must not be counted again.
        match = _PROCESS_EXIT_RE.search(text)
        if match:
            codes.append(int(match.group(1)))
        patch_failure = patch_failure or bool(_PATCH_FAILURE_RE.search(text))
    return {
        "is_error": _is_error(value),
        "process_exit_codes": tuple(codes),
        "patch_failure": patch_failure,
    }


def iter_tool_result_details(path):
    """Yield tool call IDs with explicit and text-encoded failure signals."""
    for obj in _iter_lines(path):
        if obj.get("type") == "response_item":
            item = obj.get("payload")
            if isinstance(item, dict) and item.get("type") in (
                    "function_call_output", "custom_tool_call_output"):
                yield item.get("call_id"), tool_result_detail(item.get("output"))
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_result":
                yield item.get("tool_use_id"), tool_result_detail(item)


def iter_tool_results(path):
    """Yield normalized result error state from Claude Code or Codex JSONL."""
    for uid, detail in iter_tool_result_details(path):
        failed = (detail["is_error"] or detail["patch_failure"] or
                  any(code != 0 for code in detail["process_exit_codes"]))
        yield uid, failed


def split_segments(cmd):
    return [s.strip() for s in re.split(r"&&|\|\||\||;|\n", cmd) if s.strip()]


def first_real_prog(cmd):
    """Return (prog, tokens, segment) of the first non-scaffold command in a shell line."""
    for seg in split_segments(cmd):
        toks = seg.split()
        while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
            toks = toks[1:]
        if not toks:
            continue
        p = re.sub(r"\.exe$", "", os.path.basename(toks[0]))
        if p in SCAFFOLD:
            continue
        return p, toks, seg
    return None, [], ""


def prog_key(prog, toks):
    """Collapse to 'prog' or 'prog sub' for the two-token families."""
    if (prog == "gh" and len(toks) > 2 and toks[1] in GH_GROUPS
            and not toks[2].startswith("-")):
        sub = f"{toks[1]} {toks[2]}"
        return f"gh {sub}", sub
    if prog in TWO_TOKEN and len(toks) > 1 and not toks[1].startswith("-"):
        return f"{prog} {toks[1]}", toks[1]
    return prog, None


_CLASSES = None


def load_classes():
    global _CLASSES
    if _CLASSES is not None:
        return _CLASSES
    d = {}
    local_tsv = os.path.join(skill_data_root(), "command-classes.local.tsv")
    for path in (CLASSES_TSV, local_tsv):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 3:
                        continue
                    tool, sub, cls = parts[0].strip(), parts[1].strip(), parts[2].strip()
                    d[(tool, sub)] = cls
        except OSError:
            pass
    _CLASSES = d
    return d


def classify(prog, sub):
    """Look up read/write/... class for a program + optional subcommand."""
    d = load_classes()
    if sub and (prog, sub) in d:
        return d[(prog, sub)]
    if (prog, "*") in d:
        return d[(prog, "*")]
    return "unknown"
