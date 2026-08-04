# Agents TeamKit

This repository contains Agents TeamKit, a lightweight, platform-independent kit that helps business users design and run multi-agent teams without learning agent engineering.

WorkBuddy is the first adapter and installation target. It must not define the TeamKit user model or core coordination model.

## Product Position

Agents TeamKit lets a business user define:

- a team of business experts
- each expert's responsibility boundary
- how experts collaborate
- which managed Context Items the whole team or selected experts can see
- what final output should be produced

The kit then compiles that user-facing definition into a TeamKit Core execution plan and deterministic run workspace. A platform Adapter maps that plan into a concrete runtime. The current WorkBuddy Adapter exports installable WorkBuddy packages, but that mapping is deliberately outside TeamKit Core.

## Core Principle

Keep three models separate:

- **User model**: team, experts, flow, context visibility, output.
- **TeamKit Core model**: Team, Agent, Flow Graph, Context Item, Topic, Message, Artifact, Run.
- **Adapter model**: WorkBuddy package/agent/skill/message mapping, or another platform's equivalent.

The lower layers can be flexible and technical, but the business user should only see the model they can reason about. Adapter constraints must not leak backward into the user model or force compromises in the core abstractions.

## Contents

- `docs/architecture.md`: overall architecture and boundaries.
- `docs/product-scope-v0.1.md`: first-phase product scope and non-goals.
- `docs/user-model.md`: user-facing concepts and their internal mappings.
- `docs/team-yaml-spec.md`: first version of the team definition protocol.
- `docs/coordination-model.md`: thin Graph + Topic + Message coordination model.
- `docs/context-items.md`: managed context file snapshots and visibility.
- `docs/workbuddy-bridge.md`: WorkBuddy integration responsibilities.
- `docs/workbuddy-adapter.md`: WorkBuddy export/install adapter usage.
- `docs/mvp-capability-map.md`: implemented vs deferred capabilities.
- `docs/communication-protocol.md`: platform-independent expert communication protocol.
- `docs/collaboration-workspace.md`: shared workspace ownership and anti-confusion rules.
- `docs/teamkit-commands.md`: deterministic command layer for stable actions.
- `docs/run-workspace.md`: run workspace and evidence layout.
- `schemas/team.schema.json`: draft schema for validating team definitions.
- `skills/agent-team-builder`: skill for creating and updating teams.
- `skills/agent-prompt-optimizer`: skill for improving expert profiles.
- `examples/risk-review-team`: example risk review team.
- `bin/teamkit` and `teamkit/`: local deterministic command layer.

## Local Smoke Run

From this directory:

```sh
bin/teamkit team validate --team examples/risk-review-team/team.yaml
bin/teamkit team compile --team examples/risk-review-team/team.yaml --out examples/risk-review-team/build/execution-plan.json
bin/teamkit run init --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit run status --team examples/risk-review-team/team.yaml --run demo-001
bin/teamkit graph next --team examples/risk-review-team/team.yaml --run demo-001
```

The first version is file-based and platform independent. WorkBuddy-native execution belongs behind the Adapter layer.

## WorkBuddy Trial

For a user who only wants to install Agents TeamKit 工作台 into WorkBuddy:

```sh
/bin/bash -c "$(curl -fsSL https://cdn.jsdelivr.net/gh/Jaulous/agents-teamkit@v0.1.3/scripts/install-workbuddy.sh)"
```

This uses a temporary build directory, installs the Agents TeamKit runtime inside the WorkBuddy plugin package, and registers Agents TeamKit 工作台 in the user's WorkBuddy expert marketplace.

Install the Agents TeamKit 工作台 entry package first:

```sh
bin/teamkit workbuddy detect --json
bin/teamkit workbuddy export-init --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/agents-teamkit-workbench --force
```

Then open WorkBuddy and look for `Agents TeamKit 工作台`. Use it to create teams, manage Context Item visibility, validate, export, and improve user-owned teams.

You can also export and install the example risk review team as a WorkBuddy Team expert package:

```sh
bin/teamkit workbuddy export --team examples/risk-review-team/team.yaml --out build/workbuddy --force
bin/teamkit workbuddy install --package build/workbuddy/risk-review --force
```

Then open WorkBuddy and look for the installed `风控审核团队` in the expert center.

## First MVP Scope

The first implementation should prove this loop:

1. Team Builder Skill creates `team.yaml` and expert profiles.
2. A user can edit the same files directly or through a page.
3. Agents use `teamkit` commands for messages, artifacts, and results instead of hand-editing ledgers.
4. Team Compiler creates a platform-independent execution plan.
5. WorkBuddy Adapter exports the Agents TeamKit 工作台 package as the WorkBuddy Skill carrier and entry point.
6. WorkBuddy Adapter exports user-defined teams into WorkBuddy Team packages and later maps command effects into WorkBuddy-native execution.
7. A run workspace records Topic state, managed context, messages, artifacts, human input, and final output.
8. Prompt Optimizer Skill improves expert profiles after real runs.

## Deliberate Non-Goals

- Do not build a replacement message bus if the target platform's official agent communication is sufficient.
- Do not expose API schemas, tool registries, or MCP concepts to business users.
- Do not manage tool/MCP/Skill assignment in TeamKit Core; the target runtime, Adapter, or user-managed agent definitions own "what tools an agent can use".
- Do not rely on prompt-only discipline for stable actions; provide deterministic commands.
- Do not implement CodexLoom's long-lived thread-to-agent model; it is only a design reference for communication, workspace, and governance patterns.
