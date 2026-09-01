# Architecture

## Goal

Build a lightweight, platform-independent TeamKit that lets non-technical business users assemble and run multi-agent teams for repeatable business work, such as risk review, compliance checking, contract review, or customer operations.

WorkBuddy is the first Adapter and packaging target. It must not define the user model or the TeamKit Core coordination model.

The system should be easy for business users while staying technically extensible underneath.

## Design References

TeamKit is informed by common agent-collaboration patterns:

- explicit agent profile and responsibility boundaries
- structured inter-agent communication
- shared run/topic workspace with a thin coordination Topic
- managed Context Item visibility
- artifact handoff and reference preservation
- human input or human decision as a first-class event
- message and event visibility for debugging and governance

TeamKit does not turn a chat thread into a durable agent. It defines reusable team files and per-run workspaces instead.

## Layered Architecture

```text
Business User
  -> Team Builder Skill / Team Studio / editable config files
  -> User Model
  -> TeamKit Core Model
  -> Team Compiler
  -> Adapter Boundary
  -> WorkBuddy Adapter, or another platform adapter
  -> target runtime agents, messages, skills, tasks, and artifacts

Side channel:
  Run Workspace
  Topic
  Context Item Ledger
  Event and Message Mirror
  Artifacts
  Decision Log
```

## Layers

### Command Layer

Provides deterministic actions for stable collaboration operations.

Agents should not directly edit communication ledgers, event ledgers, artifact indexes, or final result records. They should use commands such as:

- `teamkit msg send`
- `teamkit msg reply`
- `teamkit topic update`
- `teamkit context add`
- `teamkit context list`
- `teamkit graph next`
- `teamkit graph advance`
- `teamkit human request`
- `teamkit artifact publish`
- `teamkit result publish`

This follows the lesson that strong coordination semantics should be implemented by tools and commands rather than by asking agents to remember a text convention.

### Skill Layer

Provides guided creation and iteration:

- `agent-team-builder`: interviews the user and creates or updates a team.
- `agent-prompt-optimizer`: improves expert profiles after design or run feedback.
- future: `run-review`: reviews a completed run and suggests changes.

### Studio Layer

Provides a page-based experience when a host platform supports it. In the current adapter this can be surfaced inside WorkBuddy:

- create or open a team
- edit experts and process
- assign managed Context Items to the whole team or selected experts
- start a run
- inspect Topic state, messages, context, artifacts, and final output

The Studio should edit the same files that the Skills edit.

### Definition Layer

Stores the source of truth:

- `team.yaml`
- `experts/*.md`
- `references/*`
- optional reusable `contexts/*`
- run workspaces under `runs/*`

This keeps the system inspectable, copyable, and versionable.

### Team Compiler

Transforms the user model into a platform-independent TeamKit execution plan:

- expert definitions -> role contracts and profile text
- process graph -> graph nodes, edges, and message permissions
- context declarations -> managed Context Item visibility
- tool/data needs described in profiles -> capability expectations outside Core
- output definition -> final result contract

### Adapter Boundary

Maps the TeamKit execution plan to a target runtime. The Adapter should prefer official platform communication, task, artifact, and skill mechanisms when they exist.

The Adapter is deliberately after the platform-independent architecture. Team organization, logical message semantics, Topic behavior, Context Item visibility, and collaboration workspace rules must be defined before binding to platform-specific APIs.

The Adapter may be invoked by TeamKit commands, but it does not define the core command contract.

### Run Workspace

Records each task execution:

- run brief
- managed Context Items
- mirrored messages
- optional external tool/data snapshots
- artifacts
- human input requests
- final output

The workspace also defines file ownership rules so multiple experts can collaborate without overwriting canonical files. See `collaboration-workspace.md`.

### Governance and Visibility

Makes the work inspectable:

- who did what
- what context or tool output was consulted
- which expert produced which conclusion
- which stable references support the final decision
- where a human was asked to decide

## First Implementation Shape

Start with files, commands, and skills, then add a page:

1. Define `team.yaml`.
2. Add example expert profile files.
3. Implement focused `teamkit` command behavior.
4. Implement Team Builder Skill.
5. Implement Prompt Optimizer Skill.
6. Compile a platform-independent execution plan.
7. Export and install the Agents TeamKit 工作台 WorkBuddy entry package.
8. Export and install user-defined WorkBuddy Team expert packages through the package-level Adapter.
9. Build deeper adapter-native messaging/task sync only after target platform APIs are confirmed.
10. Add Team Studio once the file and command protocol stabilizes.
