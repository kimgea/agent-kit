"""Shared paths, validation, private writes, and locking for todo-capture."""
from contextlib import contextmanager
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REFS = os.path.join(HERE, "..", "references")

# Only todo_safe.py exposes these commands to automatic permission rules.
SAFE_SUBCOMMANDS = ("list", "domain-add", "new", "show", "done", "check")
COMPONENT_RE = re.compile(r"[a-z0-9_]+(?:-[a-z0-9_]+)*\Z")


def active_agent(agent="auto"):
    """Resolve 'auto' to the current harness, or 'all' when run standalone."""
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


def data_root(explicit=None):
    """Return the shared todo data directory (agent-independent).

    Precedence: an explicit path (todo.py --dir) > $TODO_CAPTURE_DATA_DIR (base) >
    the OS-native private data dir:
      Windows  %LOCALAPPDATA%\\todo-capture
      macOS    ~/Library/Application Support/todo-capture
      Linux    ${XDG_STATE_HOME:-~/.local/state}/todo-capture
    """
    if explicit:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(explicit)))
    override = os.environ.get("TODO_CAPTURE_DATA_DIR")
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
    return os.path.join(base, "todo-capture")


def validate_component(value, label):
    """Return a safe single path component or raise ValueError."""
    if not isinstance(value, str) or not COMPONENT_RE.fullmatch(value):
        raise ValueError(
            f"{label} '{value}' must use lowercase letters, digits, underscores, "
            "and single hyphens only"
        )
    if value in (".", ".."):
        raise ValueError(f"unsafe {label}: {value}")
    return value


def contained_path(root, *components):
    """Join validated components and prove the result stays under root."""
    base = os.path.abspath(root)
    candidate = os.path.abspath(os.path.join(base, *components))
    try:
        inside = os.path.commonpath((base, candidate)) == base
    except ValueError:
        inside = False
    if not inside:
        raise ValueError(f"path escapes todo data store: {candidate}")
    return candidate


def ensure_private_dir(path):
    """Create a private directory and tighten its mode on POSIX."""
    if os.path.lexists(path) and os.path.islink(path):
        raise ValueError(f"refusing symlinked private directory: {path}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    if not os.path.isdir(path):
        raise ValueError(f"expected directory: {path}")
    if os.name != "nt":
        os.chmod(path, 0o700)


def atomic_write_text(path, text):
    """Durably replace one UTF-8 file without exposing partial contents."""
    parent = os.path.dirname(os.path.abspath(path))
    ensure_private_dir(parent)
    fd, tmp = tempfile.mkstemp(prefix=".todo-capture-", dir=parent)
    try:
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        last = None
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                break
            except PermissionError as exc:
                last = exc
                time.sleep(0.05 * (attempt + 1))
        else:
            raise last
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _try_lock(fh):
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def _unlock(fh):
    if os.name == "nt":
        import msvcrt
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def mutation_lock(root, timeout=15.0):
    """Serialize store mutations; OS locks are released automatically on exit."""
    ensure_private_dir(root)
    path = contained_path(root, ".todo-capture.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if os.name != "nt":
        os.chmod(path, 0o600)
    with os.fdopen(fd, "r+b", buffering=0) as fh:
        if os.path.getsize(path) == 0:
            fh.write(b"0")
            fh.flush()
        deadline = time.monotonic() + timeout
        while not _try_lock(fh):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"todo data store is busy: {root}")
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock(fh)


def load_domains(ddir):
    """{repo: {domain: note}} from the bundled baseline plus the machine-local
    override `<ddir>/domains.local.tsv`. Local rows extend/override the baseline,
    so a portable skill ships only generic domains and each machine adds its own.
    """
    out = {}
    paths = (os.path.join(REFS, "domains.tsv"),
             os.path.join(ddir, "domains.local.tsv"))
    for path in paths:
        if path == paths[1] and os.path.islink(path):
            raise ValueError(f"refusing symlinked local domain vocabulary: {path}")
        try:
            with open(path, encoding="utf-8") as fh:
                for line_no, line in enumerate(fh, 1):
                    line = line.rstrip("\n")
                    if not line.strip() or line.lstrip().startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 2:
                        raise ValueError(f"{path}:{line_no}: expected repo<TAB>domain")
                    repo, domain = parts[0].strip(), parts[1].strip()
                    validate_component(repo, "repo")
                    validate_component(domain, "domain")
                    note = parts[2].strip() if len(parts) > 2 else ""
                    out.setdefault(repo, {})[domain] = note
        except FileNotFoundError:
            continue
    return out
