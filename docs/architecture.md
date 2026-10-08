# Architecture

## Goal

Let business users assemble and run repeatable multi-agent teams (risk review,
compliance checks, contract review, customer operations) on the agent platform
they already use, with a team definition they can read and a run record they
can audit.

TeamKit Core is platform-independent. WorkBuddy is the first adapter; it must
not define the user model or the Core coordination model.

## The Central Design Decision (v0.4)

Hosts such as WorkBuddy already have a native collaboration channel: the lead
creates a team, spawns members, and members exchange messages with
`SendMessage`. Up to v0.3 TeamKit asked every agent to *also* record each
message through `teamkit msg send`. In production that second channel drifted
from reality: agents skipped it, replied with new root messages, or bypassed
the team entirely, and required messages that were never correlated blocked
the graph forever.

v0.4 inverts the relationship:

```text
                 transport (what agents do)          observation (what TeamKit records)
Host platform    TeamCreate / Agent / SendMessage  ->  native team files + lead transcript
                                                      |
TeamKit          run init, graph advance,             v
                 result publish, run close  <----  sync -> ledgers -> audit
```

* **Native tools are the only transport.** Generated prompts never ask an agent
  to double-book a message.
* **TeamKit observes.** Host adapters read the platform's own records and write
  them into the run ledgers idempotently, correlating replies and flagging
  protocol violations.
* **Agents run four ledger commands**: `run init`, `graph advance`,
  `result publish`, `run close` (plus `run status` when unsure). Everything else
  is captured automatically.
* **The audit answers "did the protocol hold?"** with PASS / PASS_WITH_WARNINGS
  / FAIL / UNVERIFIED. Unobservable runs are never reported as PASS.

Platforms without a native channel keep using `teamkit msg send/reply`, which
remains a complete, command-mediated transport.

## Layers

```text
Business user
  -> agent-team-builder skill / editable files (team.yaml, experts/*.md, references/*)
  -> User model (team, experts, flow graph, contexts, output)
  -> TeamKit Core: validation, graph engine, run ledgers, audit
  -> Adapter boundary
  -> WorkBuddy adapter (roster, prompts, package, installer, native sync)
  -> host runtime agents, native messages, tasks
```

### Definition layer

`team.yaml`, `experts/*.md`, `references/*`. Profiles contain business content
only; the collaboration protocol is injected per platform at export time.
Optional adapter manifests (for example `workbuddy.yaml`) sit beside
`team.yaml` and never inside it.

### Core

| Module | Responsibility |
|---|---|
| `teamkit/team.py` | `TeamContext`: experts, graph, contexts, communication policy, run locations |
| `teamkit/validation.py` | definition errors and shape warnings (unreachable nodes, broken forks/joins) |
| `teamkit/graph.py` | graph execution over the Topic: next actions, advance, fork/join, terminal nodes |
| `teamkit/runs.py` | `RunStore` and run ledgers: state, topic, messages, events, artifacts, human input, closure, reply correlation |
| `teamkit/contexts.py` | Context Items: team-level declarations and per-run managed copies |
| `teamkit/batch.py` | case queue for one-run-per-case batches |
| `teamkit/audit.py` | protocol-compliance audit of one run |
| `teamkit/plan.py` | platform-neutral execution plan |
| `teamkit/fsutil.py` | atomic writes, crash-tolerant JSONL, locks, YAML (installed or vendored) |
| `teamkit/cli.py` | argument parsing and output only |

### Adapter layer

`teamkit/adapters/__init__.py` resolves an adapter by the platform name stored in
a run's host binding and exposes `sync_bound_run(store)`, which every
state-reading command calls under the run lock. Sync is observation, never a
gate: an adapter failure becomes a warning.

The WorkBuddy adapter (`teamkit/adapters/workbuddy/`):

| Module | Responsibility |
|---|---|
| `paths.py` | host locations, bundled Python discovery, and the **roster**: expert id <-> Agent ID <-> native member name |
| `prompts.py` | lead/member/skill markdown that follows WorkBuddy's official expert-team rules and compiles the graph into an SOP |
| `package.py` | team and Workbench package export, launcher, vendored runtime, closure validation |
| `installer.py` | transactional install, uninstall to backups, official validator, `doctor` |
| `native.py` | native sync: team config, member inboxes, lead transcript, task list -> ledgers and violations |

See [adapter development](adapter-development.md) for the adapter contract.

### Run workspace

One directory per run (`runs/<run-id>/` or the adapter-provided
`TEAMKIT_RUNS_DIR`): `state.yaml`, `topic.yaml`, `messages.jsonl`,
`events.jsonl`, `context-items.jsonl`, `human-review.jsonl`, `artifacts/`,
`contexts/`, `experts/`, `decision-log.md`, and `native-sync.json` (sync cursor).
See [run workspace](run-workspace.md).

## Invariants

1. Ledger writes happen under the run lock and are atomic (temp file + rename)
   or fsync'd appends; a truncated JSONL line is skipped and reported, never fatal.
2. Native sync is idempotent: every native record has a stable key.
3. A required message blocks only the graph node it names. Replies are
   correlated automatically (explicit `replyTo`, `[TeamKit ... re=...]`, or the
   recipient answering the sender); questions and escalations never close a request.
4. `graph advance --force` needs `--reason` and is recorded for the audit.
5. `run init --force` archives the previous run; installs and uninstalls move the
   previous package to `teamkit-backups/`. TeamKit never deletes run data.
6. Closing a run closes its open required messages and its active nodes.

## Governance

Every run can answer: who was dispatched for which node, who answered, which
routes were used and whether they were allowed, which nodes advanced with or
without the owner's own result, where a human was asked to decide, and which
overrides were forced. `teamkit run audit --run <id>` prints that answer.
