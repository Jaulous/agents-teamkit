# Team Definition Guide

Use this reference when creating or updating `team.yaml` and expert profiles. Field-level authority is `docs/team-yaml-spec.md`; when this guide and the spec disagree, the spec wins — say so.

## Recommended Files

```text
team.yaml
experts/
  intake.md
  policy.md
references/
  sop.md
contexts/
```

Run data is not part of the definition layout: it resolves through the directory model (`TEAMKIT_RUNS_DIR`, or `<team-root>/runs/` as the bare-CLI fallback), and platform adapters may place it elsewhere entirely. When a user asks where run output went, `teamkit home --team team.yaml --run <run-id>` shows the resolved tool, team, and run directories.

## `team.yaml` Minimal Checklist

- `version: 0.3` — write the literal value; parallel edges require it
- `team.id`
- `team.name`
- `team.purpose`
- `experts`
- `process`
- `process.graph`
- `output` (`name`, `format`, and `sections`)

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
```

### Protocol Rules Are Injected, Not Written

Profiles hold business content only. Do not add a `TeamKit Rules` section or
any `teamkit ...` command lists: each platform adapter injects the protocol
that fits its host when it exports the team (for WorkBuddy: TeamCreate ->
Agent spawn -> SendMessage report-back, Agent ID naming, the `[TeamKit run=...
node=...]` header, and the four ledger commands the lead runs). Legacy
`TeamKit Rules` sections are stripped automatically on export, so old profiles
keep working, but new ones should not carry them.

Describe collaboration in business terms instead: who to ask, when, and what
to hand over. The adapter turns those routes into platform instructions.

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
teamkit team context remove --team team.yaml --context website_sop
```

Do not edit expert prompts to grant or revoke context visibility. Profiles may describe expected inputs, but `team.yaml` remains the source of truth for default Context Item visibility.

## Communication Rule Template

```yaml
process:
  communication:
    allow_expert_requests: true
    default_response: optional
    rules:
      - from: evidence
        to: policy
        when: 发现交易异常，需要判断适用规则
        response: required
```

Communication defaults to `optional` so ordinary requests do not block the
process. Mark a response `required` only for a handoff, aggregation, report,
or decision gate that must be completed before the process can continue.
(Graph edges already authorize communication between the experts they connect
in the default and `hybrid` modes; only add rules for extra permissions or
conditions. `communication.mode` — `manual`, `hybrid`, `lead` — is an advanced
axis; leave it unset unless the user has a reason.)

Ask users in business language:

- When should this expert ask another expert for help?
- Who should receive that question?
- Does the recipient have to reply before the process can continue?

## Graph Template

Use `process.graph` for every team. A simple fixed sequence is a straight graph;
single-node behavior remains the default.

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
- 这条边是互斥分支，还是需要 join 收束的并行？

### Parallel: good and bad shapes

GOOD — two member nodes fork from the source, **both fork edges and both return edges** are marked, one join node collects:

```yaml
edges:
  - from: intake
    to: evidence_check
    relation: parallel
  - from: intake
    to: policy_check
    relation: parallel
  - from: evidence_check
    to: decision
    relation: parallel
  - from: policy_check
    to: decision
    relation: parallel

nodes:
  # ... intake, evidence_check, policy_check as above ...
  - id: decision
    expert: coordinator
    join: all
    task: 汇总两条核验结果并形成结论
```

BAD — mixed parallel + choice from one source; the parallel branch has **no command path at all** that can ever activate it:

```yaml
edges:
  - from: intake
    to: evidence_check
    relation: parallel
  - from: intake
    to: manual_review
    when: 发现高风险
```

Also bad: a single `relation: parallel` edge with no sibling (no fork happens — it is a plain edge in disguise), and a join fed by an unreachable branch (the join waits forever).

Ask the user one question before marking anything parallel: "do these two checks need each other's results?" If no, fork; if yes, keep them serial.

### Loop caps

Write `max_visits` on the returning **edge**, never on a node — the engine consumes edge-level caps only, and node-level ones trigger a validator warning while protecting nothing:

```yaml
edges:
  - from: rule_check
    to: fact_check
    when: 规则判断需要补充事实
    max_visits: 2
```

### Runtime operation

At runtime, `teamkit graph next` shows available transitions and `teamkit graph advance` records the chosen one. In a parallel run there are multiple active nodes: `next` returns `activeNodes`, and `advance` requires `--node` to name the source. Activating a fork is an argument-free advance (omit `--edge`/`--to`); a join node reports `waiting` until all its parallel predecessors complete. Only the coordinator or an explicitly assigned expert should advance the graph.

## Good Shape Defaults

Generation defaults that mirror the review expectations in the `agent-team-optimizer` skill's rubric — emit these without asking; update both files together:

1. Default reply expectation `optional`; block (`required`) only at handoff, aggregation, report, and decision points.
2. Every declared output section has a named producing expert.
3. Every captured business exception lands somewhere: a report section, a human input trigger, or an explicit route.
4. Parallel segments: member nodes, paired parallel edges both ways, one join; independence confirmed by the user.
5. Loop caps on edges with a stated business condition for the return.
6. Context visibility scoped to the experts who use the material (plus the coordinator when they verify coverage) — never team-wide for convenience.

## Output Template

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

Keep report section requirements, style rules, and citation requirements in the coordinator/reporting expert profile or a reusable reference file, not as nested objects inside `team.yaml`.
