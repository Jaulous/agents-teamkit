# User Model

The user model is platform independent.

Business users should not have to understand prompts, tools, schemas, APIs, host-platform package fields, or agent runtime concepts. They should design a team in business terms. TeamKit Core then turns that business model into its own stable coordination model. Platform adapters map the core model into a concrete runtime later.

## Concepts Shown To Users

### Team

The team is the reusable business capability, such as "Risk Review Team".

### Expert

An expert is a team member with a clear business role, such as "Material Intake Expert" or "Policy Interpretation Expert".

### Process

The process describes the expected collaboration pattern. It can be fixed, lead-driven, hybrid, or graph-based.

### Context Item

Context Items are files, notes, or snapshots the team can see. A user decides whether each item is visible to the whole team or only selected experts.

### Output

The output is the final business deliverable, such as a risk review report.

## Hidden Concepts

These exist either in TeamKit Core or in platform adapters, but should not be the user's primary mental model:

- platform-native agent/package format
- platform-native message format
- API request schema
- tool registry
- MCP configuration
- metadata envelope
- prompt compilation
- artifact synchronization
- event mirror

## User To Core Mapping

This table maps user-facing concepts only to TeamKit Core concepts. It must not map directly to any host platform.

| User concept | TeamKit Core model |
|---|---|
| Team | `TeamDefinition` |
| Expert | `ExpertProfile` / role contract |
| Process | `ProcessFlow` and optional `FlowGraph` |
| Context Item | `ContextItem` + visibility policy |
| Output | `OutputContract` + final artifact contract |

## Adapter Boundary

Core-to-platform mapping is a separate adapter concern. Adapter-specific objects must not appear in the user model.

An Adapter may map:

- `TeamDefinition` to a host-platform team or package
- `ExpertProfile` to a host-platform role, prompt, or agent definition
- `ProcessFlow` or `FlowGraph` to host-platform tasks, prompts, or messages
- `ContextItem` records to packaged files, attachments, or run-visible paths
- `LogicalMessage`, `Artifact`, `Topic`, and `Run` state to host-platform mechanisms when they exist

Those mappings must not change the user model or the TeamKit Core model. If a platform cannot express a Core concept directly, its Adapter should bridge or emulate it at the package/runtime layer.

Tool, MCP, and Skill assignment is outside TeamKit Core. The builder may record that a role needs a capability in business language, but actual tool binding belongs to the runtime platform or user-managed agent configuration.

## Product Rule

Whenever the system needs a technical configuration, wrap it in a business-facing choice first.

Ask:

> Which files or notes should this team or role be able to see?

Do not ask:

> Which API tool and input schema should this Agent bind?
