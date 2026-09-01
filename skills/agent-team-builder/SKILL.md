---
name: agent-team-builder
description: Guide business users and builders through designing, creating, or updating a TeamKit multi-agent team. Use when the user wants to define agents, responsibilities, collaboration flow, Topic-based coordination, managed context visibility, or output structure for a repeatable business task.
---

# Agent Team Builder

Use this skill to convert business intent into a compact, editable agent team definition.

## Operating Principle

Keep the business user in control. Do not auto-invent a final team without giving the user chances to choose, rename, remove, or adjust experts and flow.

Expose business concepts:

- Team
- Agent role
- Flow Graph
- Topic
- Context Item
- Output
- Human input

Hide technical concepts unless the user asks:

- API schema
- tool registry
- MCP configuration
- metadata envelope
- host-platform message internals
- prompt compilation

Important boundary: this skill helps users define who participates, how they collaborate, and what context each role can see. It does not configure which tools, MCPs, or Skills an agent can use. Tool assignment remains a runtime platform, Adapter, or user-managed agent configuration concern.

`team.yaml` is a concise team contract, not a full prompt, run log, report template, or generated execution plan. Keep detailed role behavior in `experts/*.md`, reusable policy/checklist content in `references/*`, and runtime case material in Context Items added during a run.

## Workflow

### 1. Establish The Business Job

Capture:

- business process name
- task trigger/input
- desired final output
- failure cost or risk
- typical business exceptions

Ask concise questions. If the user already supplied enough context, proceed with assumptions and mark them.

### 2. Draft Agents

Ask which agents or expert roles the user already wants. Preserve their names and intent.

If the user is unsure, suggest roles by responsibility boundary, not by technical capability.

For example, a team may include:

- coordinator / task owner
- intake or classification role
- specialist judgment role
- verification role
- drafting or synthesis role
- quality review role
- human interface role

### 3. Define Each Agent

For each agent, define:

- identity
- responsible scope
- not responsible scope
- visible context needs
- outputs
- when to ask another agent
- when to ask the user for input

Write each profile as `experts/<expert-id>.md`.

Include the runtime rules from `docs/expert-runtime-rules.md` or summarize them in a `TeamKit Rules` section. Experts must use commands for messages, artifacts, and final results. When a phase is genuinely parallel, generate member-targeted nodes connected with explicit `relation: parallel` edges and a `join: all` node; keep choice edges unmarked. Communication defaults for fan-out may be `optional`, while required responses remain explicit at handoff or gate points.
Also include commands for graph/topic inspection, managed context inspection, and human input when the expert may perform those actions.
Only the coordinator or an explicitly assigned expert should advance the graph or update shared Topic state.

### 4. Define Context Items

Ask what standard files or notes the team should be able to see.

For each item, ask:

- display name
- source file or note
- visible to the whole team or selected agents
- short purpose/summary

Do not split the user's context into fixed business categories. In `team.yaml`, write them as neutral `contexts` with `scope: team` or `scope: agents`.

Only put a `path` on a Context Item when it points to one concrete file managed in the team definition workspace. Do not use a directory path as a catch-all for case attachments. For per-run files, uploaded material, or Skill/API query results, declare a runtime placeholder with no `path`, for example `source: user_material` or `source: query_result`, and fill it during a run with `teamkit context add`.

If the user says a role needs to query a system or use a platform Skill, record that need in the agent profile as a work expectation. Do not model the Skill/API/MCP binding in TeamKit Core.

When the user uploads files or asks which experts should see which files, manage visibility through TeamKit commands instead of editing expert prompts:

- `teamkit team context list`
- `teamkit team context add --id <context-id> --name "<display-name>" --file <uploaded-file> --scope agents --visible-to <expert-id>`
- `teamkit team context assign --context <context-id> --visible-to <expert-id>`
- `teamkit team context unassign --context <context-id> --visible-to <expert-id>`

Recommend visibility from business responsibility: give a document to every expert who must use it, and to the coordinator when they need to verify coverage or synthesize the result. Do not grant team-wide visibility merely because it is convenient.

### 5. Define Flow

Use `process.graph` as the TeamKit flow model.

A simple fixed sequence is a straight graph. A more complex collaboration can
branch as an alternative route, loop, or return work to an earlier expert. Do not create `main_steps`;
each business step should be represented as a graph node.

TeamKit retains single-node behavior by default. For genuinely parallel work, use member-targeted nodes, explicit `relation: parallel` edges, and a `join: all` target. Leave choice edges unmarked; do not mix parallel and choice edges from one source unless the definition intentionally accepts that the parallel path has no implicit activation command.

Define communication rules only when they add permissions or business conditions that are not already obvious from graph edges:

- which agents may ask which other agents for help
- what business condition allows the message
- whether a reply is required
- what stable reference or artifact should be attached

Define a lightweight `process.graph`:

- nodes are business steps owned by one expert
- edges are allowed movements between steps
- `when` explains the business condition for the edge
- `max_visits` limits simple loops

Do not model BPMN, queueing, retry logic, or tool schemas for the user.

Use the platform-independent logical protocol. Do not define host-platform-native message fields here.

### 6. Define Output Rules

Capture:

- final report name
- required sections as a short list of section names
- decision fields and citation expectations in the relevant expert profiles or references
- human input requirements

Outputs should cite managed Context Items, published artifacts, agent result artifacts, or human decisions when those are used.

### 7. Generate Or Update Files

Create or update:

- `team.yaml`
- `experts/*.md`
- optional `references/*` or `contexts/*`

Use the structure in `references/team-definition-guide.md` when details are needed.

When creating `team.yaml`, include only:

- `version`
- `team`
- `experts`
- `contexts` only when the team has stable files or runtime context placeholders
- `process.mode`, `process.coordinator`, and `process.graph`
- `process.communication` only when explicit non-graph communication rules are needed
- `human_review.required_when` only when human input rules are needed
- `output.name`, `output.format`, and `output.sections`

Do not generate `workspace` unless the user explicitly asks to override TeamKit's default run paths. Do not generate nested output objects such as `output.final_report`, output requirement lists, host-platform package fields, queue settings, retry settings, or adapter-specific fields.

## Output Style

When presenting a draft to the user:

- summarize the proposed team first
- list agents and responsibilities
- show flow graph
- show Context Items and visibility
- call out assumptions
- ask which part they want to adjust

Do not bury the user in raw YAML unless they ask for it or are reviewing a file.
