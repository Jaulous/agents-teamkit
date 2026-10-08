---
name: agent-team-builder
description: Design and generate a new TeamKit multi-agent team — or apply a user-named change to an existing one — from a business job description through a draft-and-adjust interview, ending in a validated team.yaml, expert profiles, scoped context visibility, and a business-language flow the user ratifies before files are written. Use when the user says "build / set up / create a team for X", "I want a team that handles Y", "add an expert / a step to my team", or wants to turn a repeatable business process into agents. For an existing team, use this skill when the user can already name the change (add/remove/rename an expert, change a flow step, attach or re-scope context, adjust output sections); if the user wants an assessment, diagnosis, or proposals for what to change, use agent-team-optimizer instead. Deep-rewriting one agent's profile is agent-prompt-optimizer; run post-mortems and tool/MCP assignment are out of scope.
---

# Agent Team Builder

Use this skill to convert business intent into a compact, editable agent team definition.

## Operating Principle

Keep the business user in control. Do not auto-invent a final team without giving the user chances to choose, rename, remove, or adjust experts and flow. The user ratifies everything: every expert, step, and Context Item traces to something they said or to an assumption you marked and they saw.

Write `version: 0.4` — the current protocol (0.3 definitions remain valid). Parallel edges require 0.3 or later.

Consent in this skill follows one line: consent to existence is a single review of the whole draft; consent to loss (changing an existing team) is the exact change shown. Creation needs the former; updates additionally need the latter.

Expose business concepts: Team, Expert, Flow, shared context, Output, human input. Hide technical concepts unless asked: API schemas, tool registries, MCP configuration, prompt compilation, host-platform message internals.

Important boundary: this skill defines who participates, how they collaborate, and what context each expert sees. It does not assign tools, MCPs, or Skills — that is the runtime platform's, Adapter's, or user's concern.

When a user asks for a WorkBuddy export, keep host capability declarations at
the adapter boundary. If a `workbuddy.yaml` file is used, it may name external
Skills and the TeamKit adapter will verify and package them; do not put those
paths, tools, or MCP settings into `team.yaml`.

## Workflow

### 1. Establish The Business Job

Capture: business process name, task trigger/input, desired final output, failure cost or risk, typical business exceptions. Ask concise questions; do not run a third round where a marked assumption can carry the detail. If the user supplied enough context, proceed and mark assumptions.

The exceptions you capture here are design inputs, not background: every one must land somewhere in the final team (a report section, a human input trigger, or an explicit route). See step 7.

### 2. Draft Experts

Ask which experts the user already wants; preserve their names and intent. If unsure, suggest roles by responsibility boundary — coordinator, intake, specialist judgment, verification, drafting/synthesis, quality review, human interface. The list is a vocabulary, not a checklist: suggest the smallest set of roles the responsibilities require, and add a role only when a responsibility has no owner.

### 3. Define Each Expert

Read [team-definition-guide.md](references/team-definition-guide.md) and follow its Expert Profile Template. For each expert define: identity, responsible scope, not-responsible scope, visible context needs, outputs, when to ask another expert, when to ask the user.

Keep profiles to business content. Do not write a `TeamKit Rules` section or command lists: platform adapters inject the collaboration protocol at export time (see the guide's "Protocol Rules Are Injected" note). Name the coordinator in `process.coordinator`; on WorkBuddy that expert becomes the team lead, and the lead's generated prompt embeds the coordinator profile, so put the coordinator's real orchestration duties there. Give every expert a one-line `role` in `team.yaml`; it becomes the responsibility column of the lead's roster.

### 4. Define Context Items

Ask what standard files or notes the team should see. For each: display name, source, team-wide or selected-expert visibility, short purpose.

Write them as neutral `contexts` with `scope: team` or `scope: agents`. Put a `path` only on Context Items pointing at one concrete file in the team workspace; runtime material uses a placeholder with no `path`, filled during a run. Manage visibility through commands, not prompt edits:

- `teamkit team context list`
- `teamkit team context add --id <context-id> --name "<display-name>" --file <uploaded-file> --scope agents --visible-to <expert-id>`
- `teamkit team context assign --context <context-id> --visible-to <expert-id>`
- `teamkit team context unassign --context <context-id> --visible-to <expert-id>`
- `teamkit team context remove --context <context-id>`

Recommend visibility from business responsibility: give a document to every expert who must use it, and to the coordinator when they verify coverage or synthesize. Do not grant team-wide visibility merely because it is convenient.

### 5. Define Flow

Use `process.graph`: nodes are business steps owned by one expert; edges are allowed movements; `when` states the business condition; edge-level `max_visits` limits loops. Do not create `main_steps`; do not model BPMN, queueing, retry logic, or tool schemas.

Single-node progression is the default. For genuinely parallel work — confirmed independent steps — use member-targeted nodes and mark **both** the fork edges and the branch-return edges `relation: parallel`, collected by one join node. Parallel edges come in pairs: a lone `relation: parallel` edge does nothing. The join fires on its parallel in-edges, not on the `join: all` annotation (that is a readability marker). Never mix parallel and choice edges from one source: the engine provides no command that can ever activate the parallel branch in that shape. The guide's Graph Template carries the good and bad shapes in YAML.

Before marking any two steps parallel, ask: does either step need the other's result? Only a "no" from the user licenses `relation: parallel`. Parallelism is a statement about data independence, not a speed setting.

Define communication rules only when they add permissions or conditions beyond the graph edges: who may ask whom, the business condition, whether a reply is required, what reference to attach. Default `default_response: optional`; mark `required` only at handoff, aggregation, report, or decision gates.

### 6. Define Output Rules

Capture: final report name, required sections as a short list, decision fields and citation expectations (in profiles or references), human input requirements. Outputs should cite managed Context Items, published artifacts, or human decisions when used.

When human input requirements are written to `team.yaml`,
`human_review.required_when` must be a YAML list of strings, even when there is
only one condition. Never write it as a scalar or folded text block.

### 7. Verify The Shape

Check the draft against these before presenting it. If a check fails, fix the draft and tell the user what you changed.

- Every section in `output.sections` has a named producing expert whose profile declares it.
- Every business exception from step 1 has a landing spot: a report section, a human input trigger, or an explicit route. A team that only describes the happy path strands its first real failure.
- Every parallel fork has ≥2 parallel out-edges, every branch returns to its join on a `relation: parallel` edge, and no source mixes parallel and choice edges.
- `max_visits` sits on edges, never on nodes — node-level caps are ignored and the validator warns.
- Every declared Context Item is visible to at least one named expert whose profile uses it.
- The coordinator coordinates: if it also owns more than one or two substantive steps, ask which genuinely require its judgment before generating.

### 8. Present The Draft (Gate)

Present in the conversation — write nothing yet:

- the expert roster and each responsibility in one line
- the flow as arrow prose a business reader can follow (`intake → fact-check → decision`; branches indented, loops marked with their cap)
- Context Items and who sees each, in business terms
- the numbered assumptions list (A-1, A-2, …): everything you inferred that the user did not say
- one question: which part do you want to adjust?

If the user adjusts anything, return to the owning step (roster → 2, profile → 3, visibility → 4, flow → 5, output → 6), regenerate only the affected parts, and re-present.

Never show raw YAML to a business user unless they ask for it or are reviewing the file itself.

### 9. Write Files

Write only after the user confirms the draft in their own words. Create or update `team.yaml`, `experts/*.md`, and optional `references/*` or `contexts/*`, following the guide's checklists. Include only the fields the guide's minimal checklist names; do not generate `workspace` unless the user explicitly overrides default run paths.

When updating an existing team:

- Show the before/after of every file you touch, get one plain approval, apply exactly that. No bundled cleanups discovered along the way.
- Touch nothing the user did not name: shared reference files other experts read, human input conditions, another expert's business semantics, and deliberate naming and layout stay put unless the user asked for that change in their own words.
- Prefer archiving over deleting; make a restorable copy before overwriting if the workspace is not under version control.

### 10. Validate And Close

Run `teamkit team validate --team team.yaml`; fix mechanical errors; show the result. The team is done when all three hold: the user confirmed the draft; validation passes; the assumptions list was shown once more so the user can still overturn any default. Offer one next step — a test run, or a structural review by `agent-team-optimizer`.

If a WorkBuddy package was requested, export is a separate, explicit step after
Core validation. A Core-only edit must not trigger an automatic package export
or installation.

## Known Traps

**Template sprawl.** The role list in step 2 is a vocabulary, not a checklist. A team assembled to fill every slot pays per-expert context and handoff overhead the work never needed, and the unused roles become ghost agents a later review must remove. Why: role count must match the granularity of the work. Instead: suggest the smallest set the responsibilities require; add a role only when a responsibility has no owner.

**Premature parallelism.** "Parallel" is a data statement, not a speed knob. Encoding a fork before the user confirms the branches do not read each other's results creates a hidden dependency the join cannot see. Instead: ask "does either step need the other's result?" first; only a "no" licenses `relation: parallel`.

**Exception amnesia.** The interview captures typical business exceptions in step 1 and nothing downstream consumes them. A generated team that models only the happy path strands its first real failure — no report section, no human gate, no route back. Instead: every captured exception appears in the draft as a landing spot before files are written.

**Interview exhaustion.** A business user who answers twenty questions before seeing anything cannot steer — they are approving memory, not a design. Instead: ask few questions per step, show the draft early, let adjustments drive the next round; carry the rest as marked assumptions.

## Handoffs

| Need | Hand off to | Carry |
|---|---|---|
| Assess an existing team, or propose what to change | `agent-team-optimizer` | The team's location; what feels wrong |
| Deep quality rewrite of one expert's profile | `agent-prompt-optimizer` | The profile file, the design intent, open questions |
| Explain a completed run | Future run-review | Out of scope here — say so |

## Self-Check

Before declaring the team done:

1. **Ratification** — can every expert, Context Item, and output section be traced to something the user said or an assumption on the shown list? An expert the user cannot explain in their own words is an unratified invention — remove it or get it named.
2. **Producers and landings** — does every output section have a producing expert, and does every failure path ("cannot complete", "evidence missing", "experts disagree") land somewhere?
3. **Parallel honesty** — is every declared fork member nodes + paired parallel edges + a join, with no mixed sources and no lone parallel edge? If the user never confirmed independence, it is serial.
4. **Respect for the audience** — did the user see a business-language summary before any file was written? Was raw YAML shown unasked?
5. **Validation** — `version: 0.3` written, `max_visits` on edges only, and `teamkit team validate` passed?
