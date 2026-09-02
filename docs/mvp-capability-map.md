# MVP Capability Map

This file keeps the first implementation honest: what is already implemented, what is intentionally deferred, and what belongs behind the WorkBuddy Adapter.

## Implemented In Version 0.1

### Team Definition

- `team.yaml` source of truth
- expert profile files under `experts/`
- references under `references/`
- example risk review team
- JSON schema draft for the business-facing definition
- `process.graph` as the only process orchestration model

### Skills

- `agent-team-builder`: guides team, expert, process, Topic-based coordination, Context Item visibility, human input, and output definition
- `agent-prompt-optimizer`: tightens expert prompts after design or run feedback
- `agent-team-reviewer`: reviews existing team definitions for parallelism and communication issues

### Deterministic Command Layer

- `teamkit team validate`
- `teamkit team compile`
- `teamkit run init`
- `teamkit run status`
- `teamkit run close`
- `teamkit topic status/update/link`
- `teamkit graph next/advance`
- `teamkit msg send/reply/close/list`
- `teamkit context add/list`
- `teamkit human request/resolve/list`
- `teamkit artifact publish/list`
- `teamkit result publish`
- `teamkit workbuddy detect/export/export-init/install/uninstall`

### WorkBuddy Adapter

- detects local WorkBuddy desktop app and bundled `codebuddy` CLI
- exports an `Agents TeamKit 工作台` WorkBuddy entry package with all repository
  Skills, including builder, reviewer, context management, and optimizer skills
- exports `team.yaml` into a WorkBuddy Team expert package
- vendors TeamKit runtime into the generated package
- installs and registers packages in WorkBuddy's user expert marketplace

### Run Workspace

- run state
- `topic.yaml` shared coordination state
- managed Context Item snapshots
- Context Item visibility ledger
- per-expert scratch/result folders
- message ledger
- event ledger
- optional external tool/data snapshots
- human input ledger
- decision log
- artifact index and content-addressed snapshots
- final-output archiving and explicit run closure

### Verification

- standard-library `unittest` coverage for the end-to-end local run loop
- validation for communication route rejection
- source-tree `bin/teamkit` entrypoint smoke test
- WorkBuddy package export tests for both Agents TeamKit 工作台 and generated team packages

## Host-Native WorkBuddy Boundary

These are deterministic implementation facts, not open product design questions.
The first item is implemented as generated-agent guidance; the remaining native
integration items are intentionally not implemented:

- create/configure WorkBuddy-native agent teams through official APIs beyond package installation
- map execution plans to WorkBuddy native task objects
- send TeamKit logical messages through a WorkBuddy agent's native `SendMessage`
  tool (generated-agent guidance; TeamKit itself remains ledger-only)
- mirror WorkBuddy native messages/events back into the run workspace (not planned)
- mirror or attach managed Context Items through WorkBuddy-native file/artifact mechanisms
- record outputs from existing WorkBuddy Skills or internal API wrappers as Context Items or artifacts when a team wants them in the run record
- attach published artifacts to WorkBuddy-native artifacts if supported
- create native human input/approval tasks if supported

## Deferred Product Surface

These can be built after the file and command protocol stabilizes:

- Team Studio page for non-technical editing
- guided run launcher
- visual message/artifact timeline
- run review skill for improving teams after real cases
- context import and visibility picker
- richer WorkBuddy extension bundle or page-based Studio

## Deliberate Non-Goals For Version 0.1

- no `main_steps` or separate step-based process model
- no replacement message bus
- no long-lived thread-to-agent runtime
- no custom queue/retry engine unless WorkBuddy APIs require it
- no business-user exposure of API schemas, MCP concepts, or tool registries
