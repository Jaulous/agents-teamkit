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
- `agent-team-optimizer`: reviews and optimizes existing multi-agent teams on any platform — communication, scheduling, structure, and architecture fit, with per-change user approval

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
- native-sync, audit, launcher and installer tests with synthetic WorkBuddy data; local replay of recorded production runs
- the full suite runs on Python 3.9 and 3.13

## WorkBuddy Integration (v0.4)

Implemented:

- generated lead/member agents that follow WorkBuddy's official expert-team rules
  and an SOP compiled from the graph
- native sync of team config, member inboxes, the lead transcript and the task
  list into the run ledgers, with reply correlation and protocol violations
- run audit, environment doctor, dependency-free runtime packages

Not implemented, by design:

- writing WorkBuddy inboxes, tasks or sessions (TeamKit observes, never impersonates)
- WorkBuddy hooks (expert packages may not ship them)
- mapping execution plans to native task objects
- attaching Context Items or artifacts to WorkBuddy-native file mechanisms

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
