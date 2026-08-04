# Collaboration Workspace

The collaboration workspace defines how experts work together without overwriting or confusing each other's work.

It is platform independent. Host-platform-specific file and artifact handling belongs in the Adapter.

## Goals

- Give every run a shared source of truth.
- Separate managed context, expert scratch work, expert outputs, artifacts, and final deliverables.
- Prevent multiple experts from editing the same canonical output at the same time.
- Keep the process auditable and easy to debug.
- Route stable writes through commands instead of free-form agent edits.

## Implementation Principle

The workspace is command-mediated.

Experts may read shared files and write private scratch files. They should publish communication, artifacts, and final results through TeamKit commands.

```sh
teamkit msg send ...
teamkit context add ...
teamkit artifact publish ...
teamkit human request ...
teamkit result publish ...
```

## Workspace Layout

```text
runs/run-001/
  brief.md
  state.yaml
  topic.yaml
  contexts/
  shared/
  experts/
    intake/
      scratch.md
      result.md
    policy/
      scratch.md
      result.md
  artifacts/
    expert-results/
    final/
  messages.jsonl
  events.jsonl
  context-items.jsonl
  human-review.jsonl
  decision-log.md
  final-report.md
```

## File Ownership

### `brief.md`

Owned by the run creator/runtime. Experts read it but should not edit it directly.

### `state.yaml`

Owned by the runtime. Records run status, active graph node, open messages, and final output status.

### `topic.yaml`

Owned by the runtime. Records the current shared coordination state for this run: current graph node, responsible expert, summary, context refs, waiting condition, and evidence links.

Only `teamkit topic` commands should write this file.

### `contexts/`

Owned by the runtime. Stores managed Context Item snapshots. Experts read only the context paths visible to their role.

### `context-items.jsonl`

Runtime-managed Context Item ledger.

Only `teamkit context` commands and `teamkit run init` should write this file.

### `shared/`

Shared notes that are safe for all experts to append to. Avoid putting final conclusions here.

### `experts/<expert-id>/scratch.md`

Owned by that expert. Other experts may read but should not edit.

### `experts/<expert-id>/result.md`

Owned by that expert. Contains the expert's current official output for the run.

### `artifacts/expert-results/`

Runtime-managed copies of expert results. Use these when citing another expert's output.

### `human-review.jsonl`

Runtime-managed human input, review, or decision requests and resolutions.

Only `teamkit human` commands should write this file.

### `messages.jsonl`

Runtime-managed communication ledger.

Only `teamkit msg` commands should write this file.

### `events.jsonl`

Runtime-managed event ledger.

Only TeamKit commands and runtime/adapter processes should write this file.

### `decision-log.md`

Append-only human-readable decision log. Experts may propose entries; runtime or lead commits them.

### `final-report.md`

Owned by the final decision/drafting expert during drafting, then locked for QA, then finalized by the runtime or human.

## Collaboration Rules

1. Experts write scratch work only in their own expert folder.
2. Experts publish official outputs as `result.md`.
3. Experts publish official result artifacts through `teamkit artifact publish`.
4. Experts cite other outputs through artifact references, not by copying mutable scratch notes.
5. Shared files are append-only unless the runtime explicitly assigns edit ownership.
6. The final report has one active owner at a time.
7. Human decisions go into `decision-log.md` and should be cited by the final report.
8. Experts do not directly edit ledgers or artifact indexes.

## Suggested Run States

```text
created
prepared
running
waiting_for_message
waiting_for_human
quality_check
completed
failed
cancelled
```

## `state.yaml` Example

```yaml
run_id: run-001
status: running
process_mode: graph
active_node: policy_review
final_report_owner: decision
open_messages:
  - msg_003
locked_files:
  final-report.md:
    owner: decision
    reason: drafting final report
```

## Evidence Discipline

Any final claim should cite at least one stable reference:

- managed Context Item
- expert result artifact
- external data or tool snapshot
- human decision log entry

Scratch files are not stable evidence.
