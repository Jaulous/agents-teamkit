# Team Definition Guide

Use this reference when creating or updating `team.yaml` and expert profiles.

## Recommended Files

```text
team.yaml
experts/
  intake.md
  policy.md
references/
  sop.md
contexts/
runs/
```

## `team.yaml` Minimal Checklist

- `version`
- `team.id`
- `team.name`
- `team.purpose`
- `experts`
- `process`
- `process.graph`
- `output`

Add these only when needed:

- `contexts`
- `process.communication`
- `human_review.required_when`

Do not add `workspace` unless the user explicitly asks to override TeamKit's default run paths.

## Expert Profile Template

```md
# <Expert Name>

## Identity
You are ...

## Responsible For
- ...

## Not Responsible For
- ...

## Inputs
- Visible Context Items:
  - ...

## Outputs
- ...

## Collaboration Rules
- Ask <expert> when ...

## Human Input Triggers
- Request human input when ...

## Evidence Rules
- Cite managed Context Items, published artifacts, or human decisions.

## TeamKit Rules
- Send messages with `teamkit msg send`.
- Reply with `teamkit msg reply`.
- Inspect visible context with `teamkit context list`.
- Add context with `teamkit context add` only when authorized.
- Request human input with `teamkit human request`.
- Publish official outputs with `teamkit artifact publish`.
- Do not directly edit `messages.jsonl`, `events.jsonl`, `context-items.jsonl`, `human-review.jsonl`, `state.yaml`, `topic.yaml`, or final result publish records.
```

## Context Item Wording

Use business names for files and notes:

- operating SOP
- policy reference
- customer note
- contract template
- glossary
- case attachment

Do not expose API names, request schemas, MCP names, or tool registries to business users. If an agent needs a tool, describe the need in its profile and leave actual tool assignment to the runtime platform, Adapter, or user-managed agent configuration.

```yaml
contexts:
  - id: operating_sop
    name: 业务处理 SOP
    path: references/sop.md
    scope: team
  - id: specialist_terms
    name: 专业术语表
    path: contexts/terms.md
    scope: agents
    visible_to:
      - specialist
      - coordinator
  - id: case_materials
    name: 本次任务材料
    source: user_material
    scope: agents
    visible_to:
      - specialist
      - coordinator
```

Use `path` only for one concrete file. Do not set `path` to a directory such as `contexts/`. Runtime placeholders have no `path` and are filled during a run with `teamkit context add`.

For team definition changes, prefer deterministic commands:

```bash
teamkit team context list --team team.yaml
teamkit team context add --team team.yaml --id website_sop --name "网站审核 SOP" --file uploads/website-sop.md --scope agents --visible-to website-auditor --visible-to coordinator
teamkit team context assign --team team.yaml --context website_sop --visible-to qa
teamkit team context unassign --team team.yaml --context website_sop --visible-to qa
```

Do not edit expert prompts to grant or revoke context visibility. Profiles may describe expected inputs, but `team.yaml` remains the source of truth for default Context Item visibility.

## Communication Rule Template

```yaml
process:
  communication:
    allow_expert_requests: true
    default_response: required
    rules:
      - from: evidence
        to: policy
        when: 发现交易异常，需要判断适用规则
        response: required
```

Ask users in business language:

- When should this expert ask another expert for help?
- Who should receive that question?
- Does the recipient have to reply before the process can continue?

## Graph Template

Use `process.graph` for every v0.1 team. A simple fixed sequence is a straight graph.

TeamKit v0.1 has one current graph node per run. Do not draw parallel fan-out/fan-in or "all reviewers complete, then join" graphs. If several experts need to work during the same business phase, use one coordinator-owned graph node and have the coordinator request specialist outputs through messages, or make the review order explicit as sequential nodes.

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
    edges:
      - from: intake_step
        to: fact_check
        when: 需要补充事实核验
```

Ask:

- Which expert owns this step?
- Under what condition should work move to the next step?
- Should the result return to a previous expert?
- Is a loop allowed, and if so how many times?
- Is this really an alternative branch, not parallel work that needs a join?

At runtime, use `teamkit graph next` to inspect available transitions and `teamkit graph advance` to record the chosen transition. Only the coordinator or an explicitly assigned expert should advance the graph.

## Output Template

```yaml
output:
  name: 业务处理报告
  format: markdown
  sections:
    - 处理结论
    - 关键判断
    - 关键引用
    - 人工介入建议
```

Keep report section requirements, style rules, and citation requirements in the coordinator/reporting expert profile or a reusable reference file, not as nested objects inside `team.yaml`.
