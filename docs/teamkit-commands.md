# TeamKit Commands

TeamKit commands are the deterministic action layer of the architecture.

Agents should not directly edit ledgers or canonical shared files. They call commands;
commands update the run workspace and append ledgers. Physical message delivery is
performed by the sender agent with the host platform's native member-messaging tool.

## Design Goals

- Make stable actions reliable instead of prompt-dependent.
- Keep communication, artifacts, run state, and final results auditable.
- Provide a platform-independent command contract before host-platform integration.
- Keep platform-native delivery outside the core command implementation.

## Command Boundary

```text
Agent intent
  -> teamkit command
  -> run workspace ledger/artifact update
  -> sender agent uses host-native communication tool when a message must be delivered
```

The first version records logical messages locally. The host platform owns the actual
delivery mechanism; WorkBuddy generated agents use `SendMessage`.

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

- read `state.yaml`
- summarize active graph node, open messages, open human input, managed context, artifacts, and final output status

### `teamkit run close`

Close a task run explicitly when the business process considers its work complete.
Closing does not require a final file, open-message check, human-review check, or
graph-completion check.

```sh
teamkit run close \
  --team team.yaml \
  --run run-001 \
  --by decision \
  --summary "业务处理已完成"
```

Responsibilities:

- set `state.yaml` status to `completed`
- mark the Topic as `resolved` when one exists and clear its waiting condition
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
- refuse to advance while the source node has unresolved required messages or is waiting
- update `topic.yaml` and `state.yaml`
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
- return message ID
- delivery: the sender member uses its host platform's native member-messaging tool
  (WorkBuddy: `SendMessage`); see the Communication Guidance in generated team templates

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

The following commands belong to the current WorkBuddy Adapter. They are not part of the platform-independent core model.

### `teamkit workbuddy detect`

Detect local WorkBuddy desktop installation and user expert marketplace paths.

```sh
teamkit workbuddy detect --json
```

### `teamkit workbuddy export-init`

Export the Agents TeamKit 工作台 WorkBuddy entry package.

```sh
teamkit workbuddy export-init \
  --out build/workbuddy \
  --force
```

Responsibilities:

- generate an installable `Agents TeamKit 工作台` WorkBuddy package
- bundle every repository Skill (including `agent-team-builder`,
  `agent-prompt-optimizer`, and `agent-team-reviewer`) plus a generic TeamKit
  command wrapper
- include TeamKit docs, schema, and vendored CLI for self-contained team creation and validation

### `teamkit workbuddy export`

Export a TeamKit team definition as a WorkBuddy Team expert package.

```sh
teamkit workbuddy export \
  --team team.yaml \
  --out build/workbuddy \
  --force
```

Responsibilities:

- validate `team.yaml`
- generate `.codebuddy-plugin/plugin.json`
- generate WorkBuddy lead and member agent files
- bundle a `teamkit-runtime` skill and command wrapper
- copy the TeamKit workspace and vendored TeamKit CLI into the package

### `teamkit workbuddy install`

Install and register a generated WorkBuddy Team package.

```sh
teamkit workbuddy install \
  --package build/workbuddy/risk-review \
  --force
```

Responsibilities:

- copy the package into WorkBuddy's user expert marketplace
- update `marketplace.json`
- keep package registration deterministic and repeatable

### `teamkit workbuddy uninstall`

Remove an installed WorkBuddy package from the user expert marketplace.

```sh
teamkit workbuddy uninstall \
  --package agents-teamkit-workbench \
  --force
```

Responsibilities:

- remove the installed package directory
- remove the package registration from `marketplace.json`
- leave TeamKit Core definitions and generated build outputs untouched

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

A platform Adapter does not map core message commands to a native messaging API in the
current design. The sender agent performs physical delivery:

```text
teamkit msg send
  -> append messages.jsonl
  -> sender member calls WorkBuddy SendMessage
```

The command contract should remain stable even if host-platform APIs change.
