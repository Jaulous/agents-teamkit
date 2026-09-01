# Team YAML Spec

`team.yaml` is the editable source of truth for a business agent team.

It is intentionally business-facing. Internal compilers may expand it into a TeamKit Core execution plan and adapter-specific runtime configuration, but users should be able to read and modify this file without knowing any host platform's package format.

## Top-Level Shape

```yaml
version: 0.1

team:
  id: business-task
  name: 业务处理团队
  purpose: 处理可复用的业务任务并输出可复核结论

experts:
  - id: intake
    name: 任务接收专家
    profile: experts/intake.md

contexts:
  - id: operating_sop
    name: 业务处理 SOP
    path: references/operating-sop.md
    scope: team

  - id: business_rules
    name: 业务规则说明
    path: references/business-rules.md
    scope: agents
    visible_to:
      - policy
      - decision

process:
  mode: graph
  coordinator: decision
  communication:
    allow_expert_requests: true
    default_response: required
  graph:
    entry: intake_review
    nodes:
      - id: intake_review
        expert: intake
        task: 整理任务信息并指出缺失项
      - id: fact_check
        expert: verifier
        task: 核验事实信息
    edges:
      - from: intake_review
        to: fact_check
        when: 需要补充事实核验

output:
  name: 业务处理报告
  format: markdown
```

## Required Fields

- `version`: protocol version.
- `team.id`: stable lowercase ID.
- `team.name`: display name.
- `team.purpose`: business purpose.
- `experts`: at least one expert.
- `process.mode`: `graph`.
- `process.graph`: graph entry, nodes, and edges.
- `output.name`: final deliverable name.

## Expert

```yaml
- id: policy
  name: 业务规则专家
  profile: experts/policy.md
  references:
    - references/business-rules.md
```

Tool, MCP, and Skill assignment is not defined here. If an expert needs a tool, describe the need in the expert profile and configure the actual capability through the target runtime or platform adapter.

## Context Items

`contexts` declares standard files or notes that should be visible when the team runs.

```yaml
contexts:
  - id: operating_sop
    name: 业务处理 SOP
    path: references/operating-sop.md
    scope: team

  - id: specialist_terms
    name: 专业术语说明
    path: references/terms.md
    scope: agents
    visible_to:
      - specialist
      - coordinator
```

Rules:

- `scope: team` means every agent can see it.
- `scope: agents` means only `visible_to` agents can see it.
- The file is copied into the run's managed context directory during `teamkit run init`.
- Context Items do not grant tools or system permissions.
- `path` must point to one concrete file. Do not use a directory as a Context Item path.
- Runtime task material, user uploads, and Skill/API query results should be declared without `path` and filled during a run with `teamkit context add`.

## Process Model

`process.graph` is the only process orchestration model in TeamKit v0.1.

The graph is useful for both linear and branching work. A simple fixed sequence is
represented as a straight graph. A complex collaboration can branch as an
alternative route, loop, or return work to an earlier expert.

The graph remains lightweight. It defines allowed movement, not a workflow engine
or BPMN replacement.

TeamKit v0.3 retains the v0.1 single-node behavior unless parallelism is explicit.
Mark parallel edges with `relation: parallel` and the target node with `join: all`;
all parallel edges from a source are activated together. Unmarked multiple edges
remain mutually exclusive choice branches. A node that mixes parallel and choice
edges has no implicit fork path; model the choice inside the branches or remove
the mixed edges. The Topic ledger exposes `active_nodes` while keeping
`current_node` as the first active node for backward compatibility.

`main_steps` is not part of the v0.1 protocol. Older drafts may contain it, but
new teams should model every business step as a graph node.

## Graph

```yaml
process:
  mode: graph
  coordinator: decision
  graph:
    entry: intake_step
    nodes:
      - id: intake_step
        expert: intake
        task: 整理任务信息
      - id: fact_check
        expert: verifier
        task: 核验事实信息
      - id: rule_check
        expert: policy
        task: 判断规则
    edges:
      - from: intake_step
        to: fact_check
        when: 需要补充事实核验
      - from: fact_check
        to: rule_check
        when: 发现规则适用问题
      - from: rule_check
        to: fact_check
        when: 规则判断需要补充事实
        max_visits: 2
```

Graph edges allow communication between source and target experts in the default
and `hybrid` modes. In `manual` mode, graph edges do not themselves grant
communication; explicit rules and the lead/member channel apply.

## Topic

Each run creates one lightweight `topic.yaml`.

The Topic records the current shared coordination state:

- current node
- responsible coordinator
- short summary
- context refs
- waiting condition
- evidence links

It does not store each expert's private working context or a full process history.

## Communication

`process.communication` defines architecture-level communication behavior. It does not define any host-platform native message format.

```yaml
process:
  mode: graph
  communication:
    allow_expert_requests: true
    default_response: required
    allowed_message_types:
      - request
      - reply
      - notify
      - handoff
      - escalation
```

See `communication-protocol.md` for message types, status, reply rules, and adapter boundaries.

Graph edges also authorize communication between source and target experts, so do not duplicate every graph edge in `process.communication.rules`. Use explicit communication rules only for additional cross-checks or exceptions.

## Human Input

```yaml
human_review:
  required_when:
    - 关键引用不足
    - 规则冲突
    - 超出团队授权范围
```

The `human_review` section describes when a run needs human input, confirmation, approval, or decision. The compiler should inject these conditions into relevant expert profiles and the final quality step. During a run, human decisions are recorded through `teamkit human request` and `teamkit human resolve`.

## Tool And Data Access Boundary

TeamKit Core does not define MCP, Skill, API, or database access. The target runtime, platform adapter, or user-managed agent configuration owns "what tools this agent can use".

If a tool returns information that must become part of a run, add it as a managed Context Item or publish it as an artifact through TeamKit. That keeps the collaboration stable without exposing API schemas or tool registries to business users.

## Output

```yaml
output:
  name: 业务处理报告
  format: markdown
  sections:
    - 处理结论
    - 关键判断
    - 关键引用
    - 适用规则
    - 人工介入建议
```

Keep `output` flat in v0.1. Detailed report templates, section descriptions, and acceptance requirements belong in expert profiles or reusable reference files, not in nested `output.final_report` objects.

## Workspace Overrides

TeamKit has default run workspace paths. Do not include `workspace` in ordinary user-created teams.

Platform adapters may inject `TEAMKIT_RUNS_DIR` to place all default run data outside the team definition directory.

Only add `workspace` when an advanced user explicitly needs to override default run paths:

```yaml
workspace:
  run_root: runs/{run_id}
  final_report: runs/{run_id}/final-report.md
```
