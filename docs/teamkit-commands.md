# TeamKit Commands

TeamKit commands are the deterministic action layer of the architecture.

Agents should not directly edit ledgers or canonical shared files. They call commands;
commands update the run workspace and append ledgers. On hosts with a native
member channel (WorkBuddy), messages travel through native tools and the adapter
syncs them into the ledgers before every state-reading command; nobody runs
`msg send` there.

## Design Goals

- Make stable actions reliable instead of prompt-dependent.
- Keep communication, artifacts, run state, and final results auditable.
- Provide a platform-independent command contract before host-platform integration.
- Keep platform-native delivery outside the core command implementation.

## Command Boundary

```text
Agent intent
  -> native host tool (Agent, SendMessage)        -> host records -> adapter sync -> ledgers
  -> teamkit command (run/graph/result/human)     -> ledgers
```

Commands that read run state (`run status`, `graph next`, `graph advance`,
`msg list`, `run audit`, `run close`) first sync native host activity when the
run is bound to a host session. Pass `--no-sync` to skip it where offered.

## Minimal Command Set

### `teamkit team validate`

Validate a team definition before compiling or running it.

```sh
teamkit team validate --team team.yaml
```

Responsibilities:

- validate required business-facing fields
- validate expert IDs and duplicate IDs
- validate expert profile and reference files exist
- validate Context Item IDs, paths, scopes, and visibility
- validate graph nodes and edges reference known experts
- validate communication rules reference known experts

### `teamkit team compile`

Compile `team.yaml` and expert profiles into a platform-independent execution plan.

```sh
teamkit team compile --team team.yaml --out build/execution-plan.json
```

Responsibilities:

- validate the team definition
- expand expert profile files into an execution plan
- preserve process, communication, contexts, human input, workspace, and output contracts
- mark the Adapter boundary without binding to host-platform APIs yet

### `teamkit team context list`

List Context Items declared in `team.yaml`.

```sh
teamkit team context list --team team.yaml --expert website-auditor
```

Responsibilities:

- show stable team Context Items and runtime placeholders
- filter by expert visibility when requested
- keep team-definition context separate from run-time `teamkit context list`

### `teamkit team context add`

Add one Context Item to the reusable team definition.

```sh
teamkit team context add \
  --team team.yaml \
  --id website_sop \
  --name "网站审核 SOP" \
  --file uploads/website-sop.md \
  --scope agents \
  --visible-to website-auditor \
  --visible-to coordinator
```

Responsibilities:

- copy external uploaded files into the team workspace under `references/`
- reject directory paths
- validate `scope` and `visible_to` expert IDs
- update `team.yaml`
- validate the updated team definition

Runtime material placeholders use `--source` without `--file`:

```sh
teamkit team context add \
  --team team.yaml \
  --id case_materials \
  --name "本次审核材料" \
  --source user_material \
  --scope agents \
  --visible-to coordinator \
  --visible-to website-auditor
```

### `teamkit team context assign`

Grant an existing Context Item to an expert.

```sh
teamkit team context assign \
  --team team.yaml \
  --context website_sop \
  --visible-to qa
```

### `teamkit team context unassign`

Remove an expert from an existing Context Item visibility list.

```sh
teamkit team context unassign \
  --team team.yaml \
  --context website_sop \
  --visible-to qa
```

### `teamkit team context remove`

Remove a Context Item from the team definition.

```sh
teamkit team context remove --team team.yaml --context website_sop
```

### `teamkit run init`

Create a run workspace from a team definition.

```sh
teamkit run init --team team.yaml --run run-001 --brief brief.md
```

Responsibilities:

- validate `team.yaml`
- create `runs/{run_id}/`
- copy or reference input brief
- snapshot declared Context Items into the managed run context directory
- create `state.yaml`
- create empty ledgers
- create per-expert folders
- record the host binding (`state.host`) when a host launcher declared one
  (`TEAMKIT_HOST`, `CODEBUDDY_SESSION_ID`, working directory, package)

Options: `--force` starts the run over; the previous run directory is moved to
`.archive/` beside it, never deleted. `--native-team <name>` binds a known host
team. `--json` returns the run root, archive path and `nextStep`.

Writes:

- `brief.md`
- `state.yaml`
- `topic.yaml`
- `context-items.jsonl`
- `contexts/<context-id>/manifest.json`
- `messages.jsonl`
- `events.jsonl`
- `human-review.jsonl`
- `decision-log.md`
- `experts/<expert-id>/`

### `teamkit run status`

Read current run state.

```sh
teamkit run status --team team.yaml --run run-001
```

Responsibilities:

- sync native host activity first when the run is bound (`--no-sync` to skip); the
  report is included as `sync`
- summarize active nodes, open messages, open human input, managed context, artifacts, and final output status
- return `nextExpert`/`nextTask` for a single active node and a one-sentence
  `nextStep` that says what unblocks the run
- report damaged ledger lines as `ledgerWarnings` instead of failing

### `teamkit run audit`

Check whether a run followed the team protocol.

```sh
teamkit run audit --team team.yaml --run run-001 [--json] [--strict]
```

Checks ledger integrity, host binding, attribution of native records, protocol
violations, member results behind each member-owned node that advanced, results
that ran ahead of the graph, open required messages, forced advances, graph
progress, open blocking human input and the final result. Verdict: `PASS`,
`PASS_WITH_WARNINGS`, `FAIL`, or `UNVERIFIED` (collaboration not observable).
`--strict` exits 1 on `FAIL`.

### `teamkit run bind`

Bind a run to a host session or native team after the fact.

```sh
teamkit run bind --team team.yaml --run run-001 --native-team contract-order-audit-56af
```

### `teamkit run close`

Close a task run explicitly when the business process considers its work complete.
Closing does not require a final file, open-message check, human-review check, or
graph-completion check. `--status completed|failed|cancelled` records how the
business task ended (default `completed`).

```sh
teamkit run close \
  --team team.yaml \
  --run run-001 \
  --by decision \
  --summary "业务处理已完成"
```

Responsibilities:

- sync native host activity first, so nothing is lost if the host team is cleaned up afterwards
- set `state.yaml` status and `closedAt`
- close open required messages with resolution `run_closed`
- mark the Topic as `resolved`, clear its waiting condition and mark active nodes `done`
- record an optional summary only when supplied by the caller
- append a `run.closed` event

Repeated close attempts fail with the mechanical error `run already closed`.
The command does not inspect messages, human input, graph branches, or artifacts.
Other command writes remain mechanically available after close.

### `teamkit topic status`

Read the lightweight coordination Topic for a run.

```sh
teamkit topic status --team team.yaml --run run-001
```

Responsibilities:

- read `topic.yaml`
- show current node, responsible expert, context refs, waiting condition, summary, evidence links, and open messages for the current node

### `teamkit topic update`

Update the current shared coordination state.

```sh
teamkit topic update \
  --team team.yaml \
  --run run-001 \
  --current-node fact_check \
  --summary "正在核验事实信息。"
```

Responsibilities:

- validate graph node and responsible expert when provided
- update current node, summary, status, waiting condition, or evidence links
- append event to `events.jsonl`

### `teamkit topic link`

Link stable evidence to the current Topic.

```sh
teamkit topic link --team team.yaml --run run-001 --ref art_001 --label "事实核验结果"
```

### `teamkit graph next`

Show allowed next actions from the current Topic node or nodes. In a
parallel run, the JSON result includes an `activeNodes` array with one view per
active or waiting node. `currentNode` remains the first active node for
backward-compatible readers; use `activeNodes` to inspect the complete state.

```sh
teamkit graph next --team team.yaml --run run-001
```

Useful selectors:

```sh
teamkit graph next --team team.yaml --run run-001 --from-node fact_check
teamkit graph next --team team.yaml --run run-001 --ignore-waiting
```

`--from-node` asks for the transitions from one named node instead of every
active node. `--ignore-waiting` only bypasses unresolved required-message or
Topic-level waiting checks; a node that is waiting for parallel predecessors
remains blocked.

Responsibilities:

- read `process.graph`
- read `topic.yaml`
- return each active node's allowed outgoing graph edges and target experts
- report waiting nodes with reason `node is waiting for parallel predecessors`
- block next actions if a node has unresolved required messages or the Topic is waiting

### `teamkit graph advance`

Move one active graph node along an allowed edge. When a run has multiple
active nodes, `--node` is required to identify the source node.

```sh
teamkit graph advance \
  --team team.yaml \
  --run run-001 \
  --to evidence_check \
  --by decision
```

For explicit edge selection, use exactly one of `--edge` or `--to`:

```sh
teamkit graph advance --team team.yaml --run run-001 --node fact_check --edge edge_2
teamkit graph advance --team team.yaml --run run-001 --node fact_check --to rule_check
```

`--to` must identify one outgoing edge; if several edges target the same node,
use `--edge`. A `relation: parallel` edge cannot be selected by itself. When a
source has a parallel fork, omit `--edge`/`--to` and TeamKit activates all
allowed parallel branches together. Choice edges remain selectable one at a
time; a source that mixes parallel and choice edges must select a non-parallel
choice explicitly.

When a branch enters a parallel join target, the target is recorded as
`waiting` until all of its parallel predecessors have completed. `graph next`
then reports the waiting reason above; after the final predecessor completes,
the join becomes active and can be advanced normally.

With `--json`, the successful response includes the updated `activeNodes`
views, so callers can see which branches remain active and whether the join is
still waiting.

Responsibilities:

- read the current Topic node
- require `--node` when more than one graph node is active
- validate the selected edge is available and has not exceeded `max_visits`
- reject using `--edge` and `--to` together, and reject selecting one parallel edge from a fork
- activate all allowed parallel branches for an implicit fork
- refuse to advance while the source node has unresolved required messages or is
  waiting, unless `--force --reason "<why>"` is given (recorded as `forced` in the event)
- refuse to advance from an end node (no outgoing edges): close the run instead
- update `topic.yaml` and `state.yaml` (a `prepared` run becomes `running`)
- append event to `events.jsonl`

### `teamkit msg send`

Create a root message from one expert to another.

```sh
teamkit msg send \
  --team team.yaml \
  --run run-001 \
  --from evidence \
  --to policy \
  --node evidence_check \
  --subject "判断适用规则" \
  --body "发现交易异常，请判断适用规则。" \
  --response required
```

Responsibilities:

- validate run exists
- validate `from` and `to` are experts in `team.yaml`
- validate communication is allowed by team rules when configured
- associate the message with the current Topic and graph node when available
- generate message ID
- append logical message to `messages.jsonl`
- append event to `events.jsonl`
- if the message answers an open required message from the recipient (same node
  when both name one), mark that message `replied` and set `replyTo` — unless the
  new message is typed `question` or `escalation`
- return message ID

`msg send` is the transport for hosts without a native member channel. On
WorkBuddy, agents use `SendMessage` and TeamKit records it through sync.

### `teamkit msg reply`

Reply to a previous required message.

```sh
teamkit msg reply \
  --team team.yaml \
  --run run-001 \
  --from policy \
  --reply-to msg_001 \
  --body "适用规则 C，原因是近 30 天交易增长超过阈值。"
```

Responsibilities:

- validate original message exists
- validate sender is the original recipient
- create reply message with `replyTo`
- mark original message replied/closed
- append message and event ledgers

### `teamkit msg close`

Close a message without a substantive reply.

```sh
teamkit msg close \
  --team team.yaml \
  --run run-001 \
  --from policy \
  --message msg_001 \
  --resolution no_reply \
  --reason "该请求被后续 msg_003 替代。"
```

Responsibilities:

- validate close authority
- record resolution and reason
- append event

### `teamkit msg list`

List run messages.

```sh
teamkit msg list --team team.yaml --run run-001 --status open
```

Responsibilities:

- read `messages.jsonl`
- filter by expert, status, or reply chain

### `teamkit artifact publish`

Publish a stable artifact from a file.

```sh
teamkit artifact publish \
  --team team.yaml \
  --run run-001 \
  --from evidence \
  --file experts/evidence/result.md \
  --kind expert_result
```

Responsibilities:

- validate file exists
- copy or snapshot file into `artifacts/`
- compute content hash
- create artifact record
- append event
- return artifact reference

### `teamkit artifact list`

List published artifacts for the run.

```sh
teamkit artifact list --team team.yaml --run run-001
```

### `teamkit context add`

Add a managed Context Item to the current run.

```sh
teamkit context add \
  --team team.yaml \
  --run run-001 \
  --file /absolute/path/to/file.pdf \
  --name "补充说明" \
  --scope agents \
  --visible-to coordinator \
  --visible-to qa
```

External Skill/API output uses the same command and should enter the run as a Context Item:

```sh
teamkit context add \
  --team team.yaml \
  --run run-001 \
  --id blacklist_hit \
  --text '{"merchant":"merchant-123","blacklistHit":false}' \
  --source-type query_result \
  --by evidence \
  --summary "未命中黑名单。"
```

Responsibilities:

- validate the run and visibility target agents
- copy the source file or text snapshot into `runs/{run_id}/contexts/{context_id}/`
- compute content hash and write `manifest.json`
- append `context-items.jsonl`
- link the item to the run Topic as `context_refs`

### `teamkit context list`

List managed Context Items for a run.

```sh
teamkit context list --team team.yaml --run run-001 --visible-to qa
```

`scope: team` items are visible to every agent. `scope: agents` items are visible only to listed agents.

### `teamkit human request`

Record a human input, review, or decision request.

```sh
teamkit human request \
  --team team.yaml \
  --run run-001 \
  --from policy \
  --reason "规则冲突" \
  --question "历史口径和当前规则冲突，请确认以哪个为准。"
```

Responsibilities:

- validate run and expert
- append open request to `human-review.jsonl`
- update `state.yaml` to `waiting_for_human`
- set `topic.yaml` to `waiting` with a `human_review` waiting reference
- append event to `events.jsonl`

Add `--non-blocking` for a follow-up that should be recorded without pausing
the run: the run and Topic are not put into a waiting state.

### `teamkit human resolve`

Record a human decision and close the human request.

```sh
teamkit human resolve \
  --team team.yaml \
  --run run-001 \
  --review hr_001 \
  --by reviewer \
  --resolution approved \
  --answer "以当前规则为准。"
```

Responsibilities:

- update `human-review.jsonl`
- append a readable entry to `decision-log.md`
- update `state.yaml`
- clear the matching Topic waiting condition when all human input requests are resolved
- append event to `events.jsonl`

### `teamkit result publish`

Archive a final run result when one exists. This command does not close the run.

```sh
teamkit result publish \
  --team team.yaml \
  --run run-001 \
  --from decision \
  --file experts/decision/result.md
```

Responsibilities:

- validate the publishing expert exists in `team.yaml`
- validate that the input file exists
- store the file by content hash under `artifacts/final/<hash>.<ext>`
- record the archived artifact in `state.yaml.final_result`
- append a `result.published` event
- return the final artifact reference

`result publish` is equivalent to publishing an artifact with kind `final`.
It does not check open messages, human input, waiting Topics, or unfinished
graph branches, and it no longer accepts `--force`. Use `teamkit run close`
separately when the business process is complete.

## WorkBuddy Adapter Commands

These belong to the WorkBuddy adapter, not to the platform-independent core.
See [workbuddy-adapter.md](workbuddy-adapter.md) for the full flow.

| Command | Purpose |
|---|---|
| `teamkit workbuddy detect [--json]` | WorkBuddy app, CLI, validator and directory locations |
| `teamkit workbuddy doctor [--json]` | read-only health check: app, validator, Python, installed TeamKit packages (version, legacy launcher, registration) |
| `teamkit workbuddy export-init --out <dir> [--force]` | build the Agents TeamKit 工作台 package (all repository skills + runtime) |
| `teamkit --team team.yaml workbuddy export --out <dir> [--force] [--name <pkg>]` | build a team package: lead/member agents, compiled SOP, roster, launcher, vendored runtime |
| `teamkit workbuddy install --package <dir> [--force] [--strict]` | transactional install with closure + official validation; previous version moved to `teamkit-backups/` |
| `teamkit workbuddy uninstall --package <name> [--force]` | move the package to `teamkit-backups/` and unregister it |
| `teamkit --team team.yaml workbuddy sync --run <id> [--native-team <name>]` | ingest native team activity now |
| `teamkit workbuddy teams [--native-team <name>]` | list native Agent Teams, or describe one |

## Files Agents Must Not Edit Directly

- `messages.jsonl`
- `events.jsonl`
- `human-review.jsonl`
- `state.yaml`
- `topic.yaml`
- artifact index files
- final-output archive records

## Files Agents May Edit

- their own `experts/<expert-id>/scratch.md`
- their own draft files under `experts/<expert-id>/`

Agents should publish official results through `teamkit artifact publish`.

## Adapter Boundary

Adapters never map message commands to host messaging APIs and never write host
inboxes. On hosts with a native member channel the adapter observes the host's
own records:

```text
lead/member -> WorkBuddy Agent / SendMessage -> teams/<team>/inboxes, lead transcript
TeamKit command -> adapter sync -> messages.jsonl, events.jsonl
```

The command contract stays stable even if host-platform APIs change.
