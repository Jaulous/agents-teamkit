# Coordination Model

This is the thin coordination model for complex business agent teams.

It borrows CodexLoom's useful Topic idea without copying CodexLoom's full long-lived agent organization model.

## Core Objects

Only five core objects are needed in version 0.1:

```text
Team          reusable expert team definition
Graph         allowed process structure
Context Item  managed visible context for the team or selected agents
Topic         current shared state for one run
Message       expert-to-expert request/reply
```

Artifacts, human input, and final results already exist in the run workspace. They are runtime records, not separate coordination layers.

## Responsibilities

### Team

Defines agents, responsibilities, flow, context visibility, and output.

### Graph

Defines how work may move:

- which nodes exist
- which expert owns each node
- which edges are allowed
- what condition makes an edge relevant
- optional `max_visits` for loops

The graph does not execute work by itself.

### Context Item

A Context Item is a managed snapshot of information agents may read.

It records:

- stable ID and display name
- managed path and checksum
- source type
- visibility: whole team or selected agents

It does not define tool access, MCP access, database permissions, or API behavior. The target runtime, platform adapter, or user-managed agent definitions own those.

### Topic

`topic.yaml` is the current shared coordination state for one run.

It records:

- current node
- responsible coordinator or owner
- participants
- short summary
- context references
- optional waiting condition
- stable evidence links

It does not contain each expert's full working context, complete history, or a second copy of every Context Item or artifact.

Human input requests can set the Topic to `waiting`; resolving the request clears that waiting condition.

### Message

Messages record concrete coordination actions:

- who asked whom
- which Topic this belongs to
- which graph node this belongs to
- whether a reply is required
- which message a reply answers

Messages are written through `teamkit msg` commands, not by hand.

## How Complex Flow Works

For A -> B -> C -> A:

```text
process.graph says A can call B, B can call C, and C/B can return work to A.
topic.yaml says the run is currently at A, B, or C.
context-items.jsonl says which managed context each participant may read.
messages.jsonl says who is waiting for whom.
teamkit graph next shows allowed next actions.
teamkit graph advance records the chosen transition.
```

Each expert only needs local responsibility rules. No expert needs to memorize or maintain the whole global process.

## Coordinator

A coordinator expert is allowed but not required.

When there is a coordinator:

- the graph constrains what can happen
- `teamkit graph next` proposes allowed actions
- the coordinator chooses among ambiguous actions and records the choice with `teamkit graph advance`

When there is no coordinator:

- a system runner or platform Adapter may call `teamkit graph advance` when there is exactly one allowed action
- ambiguous branches should ask a coordinator or human

## Deliberate Limits

Version 0.1 does not implement:

- BPMN-style workflow execution
- a complex queue or retry engine
- Topic history/version conflict control
- automatic quality judgment
- automatic summary of every expert's working files
- interruption rules beyond what the target runtime gives the Adapter

Those can be added later only if real runs prove they are needed.
