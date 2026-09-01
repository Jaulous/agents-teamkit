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

Experts do not directly write message ledger files or handcraft native platform messages.

They use TeamKit commands:

```sh
teamkit msg send ...
teamkit msg reply ...
teamkit msg close ...
teamkit msg list ...
```

The command layer creates logical messages, appends ledgers, and later delegates native delivery to a platform Adapter when available.

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

First-version logical state machine:

```text
created -> sent -> replied
    |        |        |
    v        v        v
 closed   failed   closed
```

### Status Meanings

- `created`: message was created in the logical ledger.
- `sent`: message was handed to the current communication substrate or staged for handoff.
- `replied`: message has a linked reply.
- `closed`: message was explicitly closed without requiring further action.
- `failed`: delivery or handling failed.

Host platforms may use different native states. The Adapter maps native states into this low-cut logical set for version 0.1.

Do not model complex delivery queues, handling attempts, or active-turn reply injection in the first version unless a target runtime makes them essentially free.

## Reply Rules

- A `reply` must include `replyTo`.
- A `required` message is unresolved until one of these happens:
  - a reply is attached
  - recipient or authorized owner closes it with a reason
- A reply should summarize the answer and reference artifacts or evidence.

Agents must use `teamkit msg reply`; they should not start a new root message for an answer that belongs to an existing request.

## Artifact And Evidence References

Messages should pass references, not copy large file contents.

Use:

- `artifactRefs` for files or generated outputs.
- `evidenceRefs` for managed Context Items, external tool/data snapshots, source documents, human decisions, or prior expert outputs.

## Collaboration Modes

### manual

通信许可来自显式 `communication.rules` 与 lead↔member 内建通道；图边本身不自动授予成员间通信。`allow_expert_requests` 仍可显式开启成员请求。

### hybrid

沿用 v0.1 兼容逻辑：图边、显式 rules 和 `allow_expert_requests` 共同决定通信许可。

### lead

成员间通信沿用图边/rules 判定；成员可向 lead 发起请求。该字段描述协议能力，不规定调度时序。

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

Each platform Adapter must map:

```text
TeamKit-created LogicalMessage -> host-platform native message
host-platform native message/event -> LogicalMessage mirror
```

The logical protocol remains stable even if a host platform's native protocol changes.
