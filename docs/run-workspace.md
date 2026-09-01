# Run Workspace

A run workspace records one execution of a user-created agent team.

Stable writes in the run workspace should be performed through TeamKit commands. Experts can write private scratch files, but communication, artifact publication, events, final-result archiving, and run closure should be command-mediated.

## Layout

```text
<run-base>/run-001/
  brief.md
  state.yaml
  topic.yaml
  contexts/
  shared/
  experts/
    intake/
      scratch.md
      result.md
  context-items.jsonl
  messages.jsonl
  events.jsonl
  human-review.jsonl
  decision-log.md
  artifacts/
    expert-results/
    final/
```

`<run-base>` resolves from `workspace.run_root`, then `TEAMKIT_RUNS_DIR`, then
the team directory's `runs/` default. In an installed WorkBuddy package the
adapter injects `~/.workbuddy/teamkit-runs/<team-id>`; the package's copied
`teamkit-workspace/` is a definition snapshot, not the runtime data location.

## Files

### `brief.md`

The run objective and output expectation.

### `state.yaml`

Runtime-owned run state. See `collaboration-workspace.md` for the canonical ownership model.

### `topic.yaml`

Thin shared coordination state for the run.

It records the current graph node, responsible coordinator, short summary, context refs, waiting condition, and evidence links. Update it through `teamkit topic`, `teamkit graph advance`, `teamkit context`, and human commands.

### `contexts/`

Runtime-managed Context Item snapshots. Agents should read managed paths listed in `context-items.jsonl`, not arbitrary user-machine paths.

### `context-items.jsonl`

Ledger of Context Items visible to the whole team or selected agents. Write through `teamkit context add`; declared `team.yaml` contexts are materialized during `teamkit run init`.

### `experts/<expert-id>/`

Per-expert working area. Experts own their own `scratch.md` and `result.md`; other experts cite the runtime-managed artifact copy.

### `messages.jsonl`

Mirrored host-platform messages when available.

In version 0.1 this file is primarily written by `teamkit msg` commands. A platform Adapter may add native message identifiers later.

Each line should include:

```json
{"id":"msg_001","runId":"run-001","topicId":"run-001","nodeId":"evidence_check","from":"intake","to":"policy","subject":"判断适用规则","status":"replied","createdAt":"..."}
```

### `events.jsonl`

Runtime and bridge events:

- run started
- graph advanced
- expert invoked
- message mirrored
- artifact produced
- human input requested
- run completed

Do not ask experts to append events manually.

### `human-review.jsonl`

Open and resolved human input, review, or decision requests.

Write this file through `teamkit human request` and `teamkit human resolve`.

### `decision-log.md`

Important human-readable decisions:

- missing required context
- reference conflict
- policy conflict
- human decision answer
- final decision rationale

Human resolution commands append stable decision entries here.

### `artifacts/`

All generated or synced files.

### `artifacts/final/`

Content-addressed archive for final outputs, when a run produces one. Files are
named `<hash>.<ext>` and are written through `teamkit result publish` (or the
equivalent final-kind artifact flow). Archiving a file does not change lifecycle
state; `teamkit run close` is the command that sets the run to completed.

## Evidence Rule

Final conclusions should cite stable references such as:

- Context Items
- expert result artifacts
- external data or tool snapshots recorded as Context Items
- human decisions

The system should avoid final claims with no stable reference.
