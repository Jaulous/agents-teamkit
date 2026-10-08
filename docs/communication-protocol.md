# Communication Protocol

This protocol defines how team members coordinate at the architecture level.

It is platform independent. Host-platform-specific mapping belongs in the Adapter layer.

## Goals

- Let user-defined experts communicate without confusing the run state.
- Preserve who asked what, why, and with which evidence.
- Support fixed flow, hybrid collaboration, and lead-driven delegation.
- Keep messages readable to business users and machine-processable for the runtime.
- Avoid coupling the team definition to any host platform's native message format.
- Make message creation and reply linkage command-mediated, not prompt-mediated.

## Implementation Principle

Messages enter the run ledger through one of two transports. Both produce the
same logical envelope.

| Transport | Used when | How a message is recorded |
|---|---|---|
| **Native, observed** (default on WorkBuddy) | the host has a member-messaging tool | agents call the host tool (`Agent`, `SendMessage`); the adapter's sync reads the host's own records and appends them with `source: workbuddy.native` |
| **Command-mediated** | the host has no native channel, or a script drives the run | `teamkit msg send/reply/close` appends the ledger directly (`source: teamkit`) |

Agents never write ledger files, and on hosts with a native channel they never
record the same message twice.

## Core Concepts

### Run

A Run is one execution of a business task.

Every message belongs to a `runId`.

### Topic

For the first version, `topicId` can equal `runId`. The term exists so later versions can support subtopics inside a long or highly concurrent run.

### Expert

An Expert is a team member defined by `team.yaml` and an expert profile file.

### Message

A Message is a structured request, reply, notification, escalation, or handoff between experts or between an expert and a human.

## Message Envelope

```yaml
id: msg_001
runId: run_001
topicId: run_001
nodeId: evidence_check
from: intake
to: policy
type: request
intent: rule_check
subject: 判断适用业务规则
body: 请根据任务摘要和已发布的事实结果判断适用规则。
response: required
replyTo: null
artifactRefs:
  - artifacts/expert-results/fact-summary.md
evidenceRefs:
  - contexts/operating_sop/content.md
priority: normal
status: sent
createdAt: "2026-08-02T00:00:00Z"
updatedAt: "2026-08-02T00:00:00Z"
```

## Required Fields

- `id`
- `runId`
- `from`
- `to`
- `type`
- `subject`
- `body`
- `response`
- `status`
- `createdAt`

`topicId` and `nodeId` are added by TeamKit when a run Topic exists. `nodeId` is optional but recommended when `process.graph` is configured.

## Message Types

| Type | Purpose |
|---|---|
| `request` | Ask another expert to do work and usually reply. |
| `reply` | Answer a prior request. Must include `replyTo`. |
| `notify` | Share information without requiring action. |
| `handoff` | Transfer responsibility for the next step. |
| `question` | Ask a narrow clarification question. |
| `escalation` | Ask a human or lead expert to decide. |
| `result` | Publish an expert result artifact to the run. |

## Response Modes

| Mode | Meaning |
|---|---|
| `required` | The recipient must reply, no-reply, or escalate. |
| `optional` | The recipient may reply if useful. |
| `none` | No reply expected. |

## Status

```text
sent -> replied        (a correlated reply arrived)
sent -> closed         (closed with a resolution, or the run was closed)
```

- `sent`: recorded in the ledger. For native messages this also means the host
  delivered it (TeamKit read it from the recipient's inbox or the lead transcript).
- `replied`: a reply was correlated (`resolution: reply` or `reply_correlated`).
- `closed`: closed by `msg close` with a resolution and reason, or by `run close`
  (`resolution: run_closed`).

`created` and `failed` remain reserved and are not produced.

## Reply Rules

- A `reply` carries `replyTo`.
- A `required` message stays open until a reply is correlated or someone closes
  it with a reason; open required messages block only the graph node they name.
- Correlation, in order of precedence:
  1. `msg reply --reply-to <id>`;
  2. an explicit `re=<msg-id>` in the `[TeamKit ...]` header of a native message;
  3. the recipient sending anything back to the requester (same node when both
     name one) closes the requester's oldest open required message to it.
- Messages typed `question` or `escalation` (or a native header with
  `type=question`) never close a request, so a clarifying question cannot
  unblock the graph early.
- A coordinator who knows a result arrived outside the ledger can run
  `graph advance --force --reason "<why>"`; the override is audited.

### Correlation header

Native messages carry their run and node in the first line:

```text
[TeamKit run=<run-id> node=<node-id>]
[TeamKit run=<run-id> node=<node-id> type=question]
[TeamKit run=<run-id> node=<node-id> re=<msg-id>]
```

The header is how sync attributes a message to a run when several runs share
one native team (one run per case). Messages without a header are attributed
by time window only when exactly one run of that native team was open at the
time; otherwise they are counted as `unattributed` and reported by the audit.

A native dispatch is `required` only when its header names a node, because only
then is it precise enough to gate that node.

## Artifact And Evidence References

Messages should pass references, not copy large file contents.

Use:

- `artifactRefs` for files or generated outputs.
- `evidenceRefs` for managed Context Items, external tool/data snapshots, source documents, human decisions, or prior expert outputs.

## Collaboration Modes

The coordinator channel (coordinator <-> any member) is always open: hub
platforms require dispatch and report-back. Beyond that:

| `communication.mode` | Additional allowed routes |
|---|---|
| `lead` | only explicit `communication.rules` (strict hub-and-spoke) |
| `manual` | only explicit `communication.rules` |
| `hybrid` (default) | explicit rules plus graph-adjacent experts; a team that declares no rules and keeps `allow_expert_requests: true` is fully open (v0.3 behavior) |

Hub platforms such as WorkBuddy evaluate routes **without** the open default,
because the platform's own expert-team rules require all cross-member traffic
to go through the lead unless a route is declared. Generated prompts list the
allowed peer routes, and native sync records a `protocol.violation`
(`unauthorized_route`) for every member-to-member message outside them.

## Business User Visibility

Show messages in business language:

- who asked
- who answered
- what was asked
- why it mattered
- what evidence was attached
- whether the request is still open

Hide native platform IDs unless debugging.

## Adapter Boundary

Adapters map the logical protocol onto host tools and observe the host's own
records; they never write host inboxes or impersonate agents. For WorkBuddy see
[workbuddy-adapter.md](workbuddy-adapter.md); for writing a new adapter see
[adapter-development.md](adapter-development.md).
