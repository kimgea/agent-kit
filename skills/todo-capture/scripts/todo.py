#!/usr/bin/env python3
"""Manage deferred-work entries in a shared, private todo-capture data store.

This direct helper supports ``--dir`` and therefore is intentionally excluded
from automatic permission rules. Agents should normally use ``todo_safe.py``.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import (  # noqa: E402
    atomic_write_text,
    contained_path,
    data_root,
    ensure_private_dir,
    load_domains,
    mutation_lock,
    validate_component,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REQUIRED_FM = ("repo", "domain", "status", "created")
STATUSES = ("todo", "in-progress", "blocked")
PRIORITIES = ("high", "normal", "low")


def data_dir(args):
    root = data_root(getattr(args, "dir", None))
    if os.path.lexists(root) and os.path.islink(root):
        raise ValueError(f"refusing symlinked todo data store: {root}")
    return root


def clean_line(value, label, max_length=500):
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must not be empty")
    if "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError(f"{label} must be a single line")
    if len(value) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    return value


def bullet_lines(values, empty="None known."):
    cleaned = [clean_line(value, "section item", 1000) for value in values]
    return "\n".join(f"- {value}" for value in cleaned) if cleaned else f"- {empty}"


def yaml_string(value):
    """JSON strings are valid YAML scalars and avoid frontmatter injection."""
    return json.dumps(value, ensure_ascii=False)


def _unquote(value):
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, str) else value
        except json.JSONDecodeError:
            return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1]
    return value


def parse_frontmatter(text):
    """Return (dict, body) for the flat frontmatter schema used by entries."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    frontmatter = {}
    for line in lines[1:end]:
        match = re.match(r"\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$", line)
        if match:
            frontmatter[match.group(1)] = _unquote(match.group(2))
    return frontmatter, "".join(lines[end + 1:])


def title_of(body):
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _entry(repo, path, name, archived):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    frontmatter, body = parse_frontmatter(text)
    return name[:-3], path, repo, frontmatter, body, archived


def _entry_files(directory):
    if not os.path.isdir(directory) or os.path.islink(directory):
        return []
    entries = []
    with os.scandir(directory) as scan:
        for item in scan:
            if (item.is_file(follow_symlinks=False) and item.name.endswith(".md")
                    and re.fullmatch(r"[a-z0-9_]+(?:-[a-z0-9_]+)*\.md", item.name)):
                entries.append(item)
    return sorted(entries, key=lambda item: item.name)


def iter_entries(root, include_archive=False):
    """Yield (id, path, repo, frontmatter, body, archived) for safe files."""
    if not os.path.isdir(root):
        return
    with os.scandir(root) as scan:
        repos = sorted(
            (item for item in scan
             if item.is_dir(follow_symlinks=False)
             and re.fullmatch(r"[a-z0-9_]+(?:-[a-z0-9_]+)*", item.name)),
            key=lambda item: item.name,
        )
    for repo_item in repos:
        repo = repo_item.name
        for item in _entry_files(repo_item.path):
            yield _entry(repo, item.path, item.name, False)
        if include_archive:
            archive = contained_path(root, repo, "archive")
            for item in _entry_files(archive):
                yield _entry(repo, item.path, item.name, True)


def structure_issues(root):
    """Report ignored symlinks and malformed entry/repository names."""
    issues = []
    if not os.path.isdir(root):
        return issues
    with os.scandir(root) as scan:
        root_items = list(scan)
    for item in root_items:
        if item.name in ("INDEX.md", "domains.local.tsv", ".todo-capture.lock"):
            if item.is_symlink():
                issues.append(f"refusing symlinked store file: {item.path}")
            continue
        if item.is_symlink():
            issues.append(f"refusing symlink in store: {item.path}")
            continue
        if not item.is_dir(follow_symlinks=False):
            continue
        try:
            validate_component(item.name, "repo")
        except ValueError as exc:
            issues.append(str(exc))
            continue
        for directory, archived in ((item.path, False),
                                    (contained_path(root, item.name, "archive"), True)):
            if not os.path.isdir(directory) or os.path.islink(directory):
                if os.path.islink(directory):
                    issues.append(f"refusing symlinked archive directory: {directory}")
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    if not archived and entry.name == "archive":
                        continue
                    if entry.is_symlink():
                        issues.append(f"refusing symlinked entry: {entry.path}")
                    elif entry.is_file(follow_symlinks=False) and entry.name.endswith(".md"):
                        if not re.fullmatch(r"[a-z0-9_]+(?:-[a-z0-9_]+)*\.md", entry.name):
                            issues.append(f"invalid entry filename: {entry.path}")
    return issues


def find_entries(root, entry_id, repo=None, archived=None):
    matches = [entry for entry in iter_entries(root, include_archive=True)
               if entry[0] == entry_id]
    if repo:
        matches = [entry for entry in matches if entry[2] == repo]
    if archived is not None:
        matches = [entry for entry in matches if entry[5] == archived]
    return matches


def resolve_one(root, entry_id, repo):
    matches = find_entries(root, entry_id, repo)
    if not matches:
        scope = f" in repo '{repo}'" if repo else ""
        print(f"no entry '{entry_id}'{scope} under {root}")
        return None
    if len(matches) > 1:
        repos = ", ".join(sorted(match[2] for match in matches))
        print(f"ambiguous id '{entry_id}' — exists in repos: {repos}. Use --repo.")
        return None
    return matches[0]


INDEX_HEADER = (
    "# TODO index\n\n"
    "Derived from active todo entry files by the `todo-capture` skill. "
    "Do not edit by hand; `new` and `done` rebuild it atomically.\n"
)


def index_path(root):
    return contained_path(root, "INDEX.md")


def read_index(root):
    path = index_path(root)
    if not os.path.exists(path):
        return INDEX_HEADER
    if os.path.islink(path):
        raise ValueError(f"refusing symlinked INDEX.md: {path}")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def index_hook(frontmatter, body, entry_id):
    value = frontmatter.get("hook") or title_of(body) or entry_id
    return re.sub(r"[\r\n]+", " ", value).strip()


def render_index(root):
    grouped = {}
    for entry_id, _path, repo, frontmatter, body, _archived in iter_entries(root):
        grouped.setdefault(repo, []).append(
            (entry_id, index_hook(frontmatter, body, entry_id))
        )
    parts = [INDEX_HEADER]
    for repo in sorted(grouped):
        parts.append(f"\n## {repo}\n")
        for entry_id, hook in sorted(grouped[repo]):
            parts.append(f"- [[{entry_id}]] — {hook}\n")
    return "".join(parts)


def rebuild_index(root):
    atomic_write_text(index_path(root), render_index(root))


def index_ids(root):
    return set(re.findall(r"\[\[([^\]]+)\]\]", read_index(root)))


def _validate_lookup(entry_id, repo=None):
    validate_component(entry_id, "id")
    if repo:
        validate_component(repo, "repo")


def cmd_list(args):
    root = data_dir(args)
    if args.repo:
        validate_component(args.repo, "repo")
    if args.domain:
        validate_component(args.domain, "domain")
    rows = []
    for entry_id, _path, repo, frontmatter, body, _archived in iter_entries(root):
        if args.repo and repo != args.repo:
            continue
        if args.domain and frontmatter.get("domain") != args.domain:
            continue
        if args.status and frontmatter.get("status") != args.status:
            continue
        if args.priority and frontmatter.get("priority") != args.priority:
            continue
        rows.append({
            "id": entry_id,
            "repo": repo,
            "domain": frontmatter.get("domain", "?"),
            "status": frontmatter.get("status", "?"),
            "priority": frontmatter.get("priority", ""),
            "created": frontmatter.get("created", ""),
            "title": title_of(body),
        })
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return 0
    if not rows:
        print(f"no matching entries in {root}")
        return 0
    count_word = "entry" if len(rows) == 1 else "entries"
    print(f"=== {len(rows)} active TODO {count_word} - {root} ===")
    last_repo = None
    for row in sorted(rows, key=lambda item: (item["repo"], item["id"])):
        if row["repo"] != last_repo:
            print(f"\n## {row['repo']}")
            last_repo = row["repo"]
        priority = row["priority"]
        suffix = f" ({priority})" if priority and priority != "normal" else ""
        print(f"  {row['id']}{suffix}\n      {row['title']}")
    return 0


def cmd_new(args):
    root = data_dir(args)
    repo = validate_component(args.repo, "repo")
    domain = validate_component(args.domain, "domain")
    slug = validate_component(args.slug.strip().lower(), "slug")
    if "_" in slug:
        raise ValueError("slug must be lowercase kebab-case without underscores")
    title = clean_line(args.title, "title", 300)
    hook = clean_line(args.hook, "hook", 500) if args.hook else None
    source = clean_line(args.source, "source", 500) if args.source else None
    why = clean_line(args.why, "why", 1500)
    where = [clean_line(value, "where", 1000) for value in args.where]
    what = clean_line(args.what, "what to do", 1500)
    constraints = [clean_line(value, "constraint", 1000) for value in args.constraint]
    out_of_scope = clean_line(args.out_of_scope, "out of scope", 1000)
    links = [clean_line(value, "link", 1000) for value in args.link]
    entry_id = f"{domain}-{slug}"

    with mutation_lock(root):
        domains = load_domains(root)
        if repo not in domains:
            known = ", ".join(sorted(domains))
            raise ValueError(
                f"unknown repo '{repo}'. Known: {known}. Add it to "
                f"{contained_path(root, 'domains.local.tsv')}"
            )
        if domain not in domains[repo]:
            allowed = ", ".join(sorted(domains[repo]))
            raise ValueError(
                f"unknown domain '{domain}' for repo '{repo}'. Allowed: {allowed}. "
                f"Add it to {contained_path(root, 'domains.local.tsv')}"
            )
        existing = find_entries(root, entry_id)
        if existing:
            where = "; ".join(
                f"{'archived' if entry[5] else 'active'} in {entry[2]}"
                for entry in existing
            )
            raise ValueError(f"id '{entry_id}' already exists ({where})")

        repo_dir = contained_path(root, repo)
        ensure_private_dir(repo_dir)
        path = contained_path(root, repo, entry_id + ".md")
        if os.path.lexists(path):
            raise ValueError(f"refusing to overwrite existing path: {path}")

        frontmatter = [
            f"repo: {repo}",
            f"domain: {domain}",
            "status: todo",
            f"created: {date.today().isoformat()}",
        ]
        if source:
            frontmatter.append(f"source: {yaml_string(source)}")
        if args.priority:
            frontmatter.append(f"priority: {args.priority}")
        if hook:
            frontmatter.append(f"hook: {yaml_string(hook)}")

        content = (
            "---\n" + "\n".join(frontmatter) + "\n---\n\n"
            f"# {title}\n\n"
            f"## Why\n\n{why}\n\n"
            f"## Where\n\n{bullet_lines(where)}\n\n"
            f"## What to do\n\n{what}\n\n"
            f"## Constraints\n\n{bullet_lines(constraints)}\n\n"
            f"## Out of scope\n\n{out_of_scope}\n\n"
            f"## Links\n\n{bullet_lines(links, empty='None.')}\n"
        )
        try:
            atomic_write_text(path, content)
            rebuild_index(root)
        except Exception:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise

    print(f"created {path}")
    print(f"indexed [[{entry_id}]] under ## {repo}")
    return 0


def cmd_domain_add(args):
    root = data_dir(args)
    repo = validate_component(args.repo, "repo")
    domain = validate_component(args.domain, "domain")
    note = clean_line(args.note, "domain note", 500) if args.note else ""
    if "\t" in note:
        raise ValueError("domain note must not contain tabs")
    local_path = contained_path(root, "domains.local.tsv")
    with mutation_lock(root):
        domains = load_domains(root)
        if domain in domains.get(repo, {}):
            print(f"domain already available: {repo}/{domain}")
            return 0
        existing = ""
        if os.path.exists(local_path):
            with open(local_path, encoding="utf-8") as handle:
                existing = handle.read()
        if existing and not existing.endswith("\n"):
            existing += "\n"
        line = f"{repo}\t{domain}"
        if note:
            line += f"\t{note}"
        atomic_write_text(local_path, existing + line + "\n")
    print(f"added domain: {repo}/{domain} -> {local_path}")
    return 0


def cmd_show(args):
    root = data_dir(args)
    _validate_lookup(args.id, args.repo)
    hit = resolve_one(root, args.id, args.repo)
    if not hit:
        return 2
    _entry_id, path, _repo, _frontmatter, _body, archived = hit
    tag = "  [ARCHIVED]" if archived else ""
    print(f"# {path}{tag}\n")
    with open(path, encoding="utf-8") as handle:
        print(handle.read())
    return 0


def _replace_with_retry(source, destination):
    last = None
    for attempt in range(8):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.05 * (attempt + 1))
    raise last


def cmd_done(args):
    root = data_dir(args)
    _validate_lookup(args.id, args.repo)
    note = clean_line(args.note, "resolution note", 1000)
    with mutation_lock(root):
        active = find_entries(root, args.id, args.repo, archived=False)
        if len(active) > 1:
            repos = ", ".join(sorted(entry[2] for entry in active))
            raise ValueError(f"ambiguous id '{args.id}' — active in repos: {repos}")
        if not active:
            if find_entries(root, args.id, args.repo, archived=True):
                raise ValueError(f"'{args.id}' is already archived")
            scope = f" in repo '{args.repo}'" if args.repo else ""
            raise ValueError(f"no active entry '{args.id}'{scope} under {root}")

        entry_id, path, repo, _frontmatter, _body, _archived = active[0]
        archive_dir = contained_path(root, repo, "archive")
        ensure_private_dir(archive_dir)
        destination = contained_path(root, repo, "archive", os.path.basename(path))
        if os.path.lexists(destination):
            raise ValueError(f"refusing to overwrite archived entry: {destination}")
        with open(path, encoding="utf-8") as handle:
            original = handle.read()
        resolved = original.rstrip("\n") + f"\n\n**Resolved:** {note}\n"
        modified = moved = False
        try:
            atomic_write_text(path, resolved)
            modified = True
            _replace_with_retry(path, destination)
            moved = True
            rebuild_index(root)
        except Exception:
            if moved and os.path.exists(destination):
                _replace_with_retry(destination, path)
            if modified and os.path.exists(path):
                atomic_write_text(path, original)
            raise

    print(f"archived -> {destination}")
    print(f"removed [[{entry_id}]] from INDEX.md")
    return 0


def cmd_check(args):
    root = data_dir(args)
    issues = structure_issues(root)
    try:
        domains = load_domains(root)
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
        domains = {}
    active_ids, archived_ids, seen = set(), set(), {}
    for entry_id, path, repo, frontmatter, body, archived in iter_entries(
            root, include_archive=True):
        (archived_ids if archived else active_ids).add(entry_id)
        seen.setdefault(entry_id, []).append((repo, archived))
        missing = [key for key in REQUIRED_FM if not frontmatter.get(key)]
        if missing:
            issues.append(f"{entry_id}: missing frontmatter {missing} ({path})")
        if frontmatter.get("repo") != repo:
            issues.append(
                f"{entry_id}: frontmatter repo '{frontmatter.get('repo', '')}' != folder '{repo}'"
            )
        domain = frontmatter.get("domain", "")
        if domain and not entry_id.startswith(domain + "-"):
            issues.append(f"{entry_id}: filename does not start with domain '{domain}'")
        try:
            validate_component(repo, "repo")
            if domain:
                validate_component(domain, "domain")
        except ValueError as exc:
            issues.append(f"{entry_id}: {exc}")
        if domains:
            if repo not in domains:
                issues.append(f"{entry_id}: repo '{repo}' not in domain vocabulary")
            elif domain and domain not in domains[repo]:
                issues.append(f"{entry_id}: domain '{domain}' not listed for repo '{repo}'")
        status = frontmatter.get("status")
        if status and status not in STATUSES:
            issues.append(f"{entry_id}: invalid status '{status}'")
        priority = frontmatter.get("priority")
        if priority and priority not in PRIORITIES:
            issues.append(f"{entry_id}: invalid priority '{priority}'")
        created = frontmatter.get("created")
        if created:
            try:
                date.fromisoformat(created)
            except ValueError:
                issues.append(f"{entry_id}: invalid created date '{created}'")
        if not title_of(body):
            issues.append(f"{entry_id}: missing '# ' title")
        hook = frontmatter.get("hook")
        if hook and ("\r" in hook or "\n" in hook):
            issues.append(f"{entry_id}: hook must be a single line")
    for entry_id, locations in seen.items():
        if len(locations) > 1:
            issues.append(f"{entry_id}: duplicate id at {locations} — ids must be unique")
    try:
        actual_index = read_index(root)
        expected_index = render_index(root)
        if actual_index != expected_index:
            issues.append("INDEX.md differs from the active entry files")
        indexed = index_ids(root)
        for entry_id in sorted(active_ids - indexed):
            issues.append(f"{entry_id}: active entry missing from INDEX.md")
        for entry_id in sorted(indexed - active_ids):
            where = "archived" if entry_id in archived_ids else "no file"
            issues.append(f"{entry_id}: in INDEX.md but {where}")
    except (OSError, ValueError) as exc:
        issues.append(str(exc))
    if issues:
        print(f"=== {len(issues)} issue(s) - {root} ===")
        for issue in issues:
            print("  " + issue)
        return 1
    print(
        f"OK — {len(active_ids)} active, {len(archived_ids)} archived, "
        f"INDEX.md consistent ({root})"
    )
    return 0


def build_parser(allow_custom_dir=True):
    common = argparse.ArgumentParser(add_help=False)
    if allow_custom_dir:
        common.add_argument(
            "--dir",
            default=None,
            help="custom full data-store path; direct helper only and approval-gated",
        )
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    command = subparsers.add_parser("list", parents=[common], help="list active entries")
    command.add_argument("--repo")
    command.add_argument("--domain")
    command.add_argument("--status", choices=STATUSES)
    command.add_argument("--priority", choices=PRIORITIES)
    command.add_argument("--json", action="store_true")
    command.set_defaults(fn=cmd_list)

    command = subparsers.add_parser("new", parents=[common], help="create an entry and rebuild INDEX")
    command.add_argument("--repo", required=True)
    command.add_argument("--domain", required=True)
    command.add_argument("--slug", required=True)
    command.add_argument("--title", required=True)
    command.add_argument("--hook", help="INDEX one-liner; defaults to title")
    command.add_argument("--source")
    command.add_argument("--priority", choices=PRIORITIES)
    command.add_argument("--why", required=True, help="concrete reason this work matters")
    command.add_argument("--where", action="append", required=True,
                         help="file/symbol location; repeat for multiple locations")
    command.add_argument("--what", required=True, help="next implementation outcome")
    command.add_argument("--constraint", action="append", default=[],
                         help="load-bearing constraint; repeat as needed")
    command.add_argument("--out-of-scope", required=True,
                         help="what must not be silently expanded")
    command.add_argument("--link", action="append", default=[],
                         help="related entry, issue, PR, or document; repeat as needed")
    command.set_defaults(fn=cmd_new)

    command = subparsers.add_parser(
        "domain-add", parents=[common], help="add a validated local repo/domain row"
    )
    command.add_argument("--repo", required=True)
    command.add_argument("--domain", required=True)
    command.add_argument("--note")
    command.set_defaults(fn=cmd_domain_add)

    command = subparsers.add_parser("show", parents=[common], help="print an entry")
    command.add_argument("id")
    command.add_argument("--repo", help="disambiguate a duplicated id")
    command.set_defaults(fn=cmd_show)

    command = subparsers.add_parser("done", parents=[common], help="archive an entry")
    command.add_argument("id")
    command.add_argument("--repo", help="disambiguate a duplicated id")
    command.add_argument("--note", required=True)
    command.set_defaults(fn=cmd_done)

    command = subparsers.add_parser("check", parents=[common], help="audit store consistency")
    command.set_defaults(fn=cmd_check)
    return parser


def main(argv=None, allow_custom_dir=True):
    parser = build_parser(allow_custom_dir=allow_custom_dir)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (OSError, TimeoutError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
