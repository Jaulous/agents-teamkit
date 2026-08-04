# TeamKit v0.1 Product Scope

TeamKit v0.1 is a lightweight engineering kit for creating and running business
multi-agent teams with minimal setup.

The product surface is intentionally small: a user defines expert profiles, a
flow graph, shared coordination state, expert messages, managed context, and the
final output contract. TeamKit validates those files, initializes a run
workspace, records coordination state, and lets adapters package the team for a
target runtime.

## Core Product Model

Version 0.1 is built around these concepts:

- `Profile`: each expert's role, responsibility boundary, inputs, outputs, and
  collaboration rules.
- `Graph`: the only process orchestration model. Nodes describe business steps
  owned by experts. Edges describe allowed movement between experts.
- `Topic`: the current shared state for one run, including current graph node,
  responsible expert, waiting condition, context references, and summary.
- `Message`: structured expert-to-expert requests, replies, notifications,
  handoffs, and escalations.
- `Context Item`: a managed file, note, or snapshot visible to the whole team or
  selected experts.
- `Output`: the final business deliverable contract.

The `Team` definition ties these concepts together in `team.yaml`.

## First Usable Loop

The v0.1 implementation should let a user:

1. Create or edit a team definition and expert profile files.
2. Validate the team definition.
3. Compile the team into a platform-independent execution plan.
4. Initialize a run workspace.
5. Inspect Topic, Graph, Context Items, Messages, artifacts, human input, and
   final result state.
6. Export the team through the current WorkBuddy Adapter for trial use.
7. Improve expert profiles after real runs.

## Explicit Non-Goals

Version 0.1 does not include:

- `main_steps` or a second step-based process model.
- A workflow/BPMN engine.
- A queue, retry, or background scheduling engine.
- Tool, MCP, API, database, or Skill assignment in TeamKit Core.
- Host-platform package fields in the user model or TeamKit Core schema.
- WorkBuddy-native execution APIs beyond the current package-level Adapter.

If a future runtime needs platform-native tasks or message delivery, the Adapter
maps TeamKit Graph, Topic, Message, Context Item, artifact, and output records to
that platform. The Core model remains unchanged.
