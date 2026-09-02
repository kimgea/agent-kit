# Local behavioral evaluations

Agent-kit separates deterministic repository validation from model-backed
behavioral evidence. The normal gate checks executable suite manifests,
fixtures, graders, fixed runner construction, and simulated outputs without
invoking an agent:

```bash
python scripts/agent_kit.py check
python scripts/behavioral_eval.py check --suite review-guidance-audit
python scripts/behavioral_eval.py check --suite project-review
python scripts/behavioral_eval.py check --suite review-and-fix
python scripts/behavioral_eval.py check --suite verification-harness-audit
```

GitHub Actions runs only that deterministic path. It does not invoke Codex,
Claude, a local model, or a hosted evaluation service.

## Run a real local evaluation

Real behavioral execution is explicit:

```bash
python scripts/behavioral_eval.py run \
  --suite project-review \
  --runner codex \
  --model gpt-5.6-sol
```

Use one or more `--case ID` arguments for a focused run. An explicit
`--model MODEL` is required so the evidence never hides a configured default.
Reasoning effort defaults to the recorded `medium` setting and can be selected
with `--reasoning-effort`. The default is 30 minutes per case because a complete
multi-role review-and-fix round can exceed 15 minutes; `--timeout SECONDS` is
bounded to one hour per case.
The runner prints only bounded per-case progress while it works; raw agent event
and error streams remain temporary and are not retained as evaluation evidence.
Windows direct runs require a native `codex.exe` on `PATH`; batch launchers are
rejected because `cmd.exe` cannot preserve arbitrary generated paths safely.

The Codex adapter starts a fresh ephemeral context for each synthetic
repository, ignores unrelated user configuration, applies a workspace sandbox,
and requests schema-constrained canonical JSON. The harness resolves the audit
target before invoking the agent and keeps that context as lead-owned authority
in a non-agent-writable host directory. Only the fixture and a dedicated
agent-work directory are writable: implicit temporary-directory access is
disabled, and host-side context, result, event, and error capture stay separate.
Afterward it verifies canonical validity, exact target and guidance provenance,
fixture content, hidden assertions, and prohibited command execution.
Malformed output, including excessive JSON nesting or invalid Unicode, becomes
bounded failed-case evidence instead of aborting the suite.

Before the first case, the harness freezes the parsed suite, every selected
fixture, the complete evaluated skill and any fixed skill dependencies, the
fixed output envelope, its own source digest, and one discovered Codex
launcher/version descriptor. Every case is materialized only from those
snapshots. Input traversal rejects symlinked ancestors and Windows reparse
points. A timeout terminates and reaps the complete POSIX process group or
Windows process tree before mutation checks continue.

`project-review` is analysis-only, so every fixture must remain unchanged.
`review-and-fix` may change only existing regular files declared by the host's
hidden `expected_mutations` policy. The harness compares exact before/after
digests and rejects additions, removals, type changes, links, file or directory
permission changes (POSIX mode bits or the Windows read-only attribute),
undeclared edits, and wrong contents. Its successful fix case also
requires a canonical applied `auto` plan, validation, and a later fresh
`project-review` acceptance round. Consequential and authorization cases must
remain mutation-free.

Codex inference normally uses an external model service and may consume the
user's allowance or API billing. The command is never run by the canonical gate,
commit hooks, packaging, GitHub Actions, or release automation.

## Evidence records

Local runs create a new ignored directory under `.eval-results/` by default:

```text
.eval-results/review-guidance-audit-<time>-<id>/
├── summary.json
└── cases/
    └── <case-id>/
        ├── context.json
        ├── result.json
        └── score.json
```

The summary binds the observation to the frozen suite, skill, fixed dependency
digests, harness, runner, Codex version, explicit model, reasoning effort, and
each fixture and canonical-result digest. Case records preserve canonical
context and output plus per-assertion and mutation grading. When the runner exposes bounded agent-tool
events, scores also retain only the deduplicated count of `spawn_agent` calls so
delegation-oriented cases can distinguish an observed local orchestration path
from a single-agent result. Tool arguments, subagent prompts, raw event streams,
stderr, prompts, and reasoning are not retained. A failed runner retains only a
generic failure category and a digest of the bounded transient error or event
stream.

Results are local evidence, not universal proof. A useful claim names the exact
configuration, for example: "16 of 16 cases passed with this skill and suite
digest using Codex version X and model Y." A later model, runner, skill revision,
or repository shape requires a new observation.

## Grade recorded output

Another agent integration can produce canonical output and use the same
provider-neutral grader:

```bash
python scripts/behavioral_eval.py grade \
  --suite review-guidance-audit \
  --case json-consumer-output \
  --context /path/to/context.json \
  --result /path/to/result.json
```

Both files are required. The context preserves the lead-owned target and
provenance; accepting a result alone would let an evaluated agent redefine its
own scope. The grader rematerializes the committed synthetic fixture, resolves
the selected target again, normalizes only the temporary repository location,
and rejects any other context drift.

For a case that declares a mutation, also supply the resulting disposable
fixture. Without independently observed post-run files, a claimed change fails:

```bash
python scripts/behavioral_eval.py grade \
  --suite review-and-fix \
  --case routine-heading-fix \
  --context /path/to/context.json \
  --result /path/to/result.json \
  --fixture-after /path/to/disposable-fixture-after
```

## Suite contract

Executable suites are cataloged with `behavioral_evals` and use a versioned
JSON manifest under `evals/<skill>/`. Each case provides:

- a small synthetic repository under `fixtures/<case-id>/`;
- one exact path or file-part target;
- the user-like prompt shown to the agent;
- hidden deterministic assertions over canonical JSON; and
- bounded forbidden-command markers when execution authority is under test; and
- optional host-owned exact after-content digests for permitted file mutations.

Assertions use JSON-pointer paths with optional `*` array traversal. Supported
operators are `equals`, `not_equals`, `any`, `none`, `count_equals`,
`count_at_least`, and ordered `sequence`. Object values are partial structural
matches so tests can require stable decisions, paths, provenance, and harness
relationships without coupling to generated prose.

Suite data cannot provide a command, validator executable, agent binary, schema
path, or arbitrary adapter. The repository helper contains a fixed mapping from
the versioned result contract to its resolver, validator, and schema. The v1
direct runner is the locally discovered Codex CLI; other agents use recorded
output until a separately reviewed fixed adapter exists.

The executable suites currently cover:

| Suite | Canonical result | Mutation policy |
| --- | --- | --- |
| `review-guidance-audit` | Guidance-audit result | No mutations |
| `project-review` | Project-review result | No mutations |
| `review-and-fix` | Review-and-fix workflow result | Exact declared existing files only |
| `verification-harness-audit` | Verification-harness audit result | No mutations |

`review-and-fix` selects one reviewer per case from a code-owned allowlist:
`project-review` v1, `review-guidance-audit` v1, or
`verification-harness-audit` v1. The host freezes only the selected reviewer
beside the evaluated skill and embeds its lead-owned canonical context in the
review-and-fix context. Suite data cannot name another skill, helper, schema, or
adapter. These cases can use multiple fresh agent contexts and are therefore
slower and more allowance-intensive than single-pass review cases.

The verification-harness suite uses a fixed 4 KiB semantic-inspection ceiling
for compact fixtures. Its adapter performs metadata resolution first, then
deterministically inspects every eligible file in a broad selected inventory.
This makes oversized and unread content explicit material evidence rather than
letting a model silently sample a directory or project. Suite data cannot add a
command plan, user-global authority, external evidence source, or context path.

## Add another skill

Adopt executable evaluation one skill at a time:

1. Keep or update the existing descriptive `cases.json` forward-test catalog.
2. Add a versioned `suite.json` and compact synthetic fixtures.
3. Add a fixed result-contract mapping only when the skill has canonical JSON,
   a deterministic validator, and lead-owned target provenance.
4. Add `behavioral_evals` to the skill's `toolkit.toml` entry.
5. Test success, malformed output, target drift, fixture mutation, timeouts, and
   command authority without invoking a model.
6. Run selected real cases locally and inspect the bounded evidence.

Do not migrate every skill merely for format consistency. A descriptive suite
remains valid until the skill has a stable machine-readable result contract and
real behavior worth grading.
