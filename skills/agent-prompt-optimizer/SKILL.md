---
name: agent-prompt-optimizer
description: Improve a business expert Agent profile or prompt for a TeamKit multi-agent team. Use when the user wants to tighten an expert's responsibility boundary, input/output contract, collaboration rules, human input triggers, citation requirements, or behavior after a failed or unsatisfactory run.
---

# Agent Prompt Optimizer

Use this skill to improve one or more expert profiles while preserving the user's intended business role.

## Optimization Goals

Make the expert:

- easier for business users to understand
- narrower in responsibility
- explicit about what it can and cannot decide
- clear about inputs and outputs
- aware of collaboration boundaries
- explicit about message triggers and required replies
- strict about citing stable Context Items, artifacts, or decisions
- safe around human input and sensitive context/tool output
- compliant with TeamKit command-mediated action rules

## Workflow

### 1. Identify The Expert And Context

Read the current expert profile and relevant `team.yaml` if available.

Capture:

- team purpose
- expert role
- current issue or desired improvement
- run feedback if provided

### 2. Diagnose Profile Quality

Use `references/expert-profile-rubric.md`.

Look for:

- scope too broad
- missing non-responsibilities
- unclear output
- hidden authority to make final decisions
- no collaboration triggers
- vague message rules such as "communicate as needed"
- no human input or human decision triggers
- weak evidence discipline
- tool, API, or data-source leakage into user-facing language
- direct edits to ledgers or canonical shared files

### 3. Rewrite The Profile

Keep the markdown structure stable:

- Identity
- Responsible For
- Not Responsible For
- Inputs
- Outputs
- Collaboration Rules
- Human Input Triggers
- Evidence Rules
- Style Constraints
- TeamKit Rules

For Collaboration Rules, prefer concrete message triggers:

- Ask the rule expert when a fact pattern needs rule interpretation.
- Ask the fact-checking expert when a conclusion lacks a stable reference.
- Notify the coordinator when a required human input condition is detected.

Use concrete business language. Avoid generic agent boilerplate.

Ensure TeamKit Rules say:

- inspect shared coordination state through `teamkit topic status` and `teamkit graph next`
- inspect visible managed context through `teamkit context list`
- add managed context through `teamkit context add` only when authorized
- advance the graph or update shared Topic state only when the expert is the coordinator or explicitly assigned
- send messages through `teamkit msg send`
- reply through `teamkit msg reply`
- record external Skill/API output through `teamkit context add` only when it should become managed context for the run
- request human input through `teamkit human request`
- publish artifacts through `teamkit artifact publish`
- do not directly edit ledgers or canonical final result records
- do not embed the whole global process into every expert profile

### 4. Explain The Changes

After editing, summarize:

- what responsibility was narrowed
- what output contract was clarified
- what collaboration or human input rule was added
- any remaining assumption

## Guardrails

- Do not silently expand an expert's authority.
- Do not let a support expert become the final decision maker unless the team definition says so.
- Do not expose internal API/tool configuration to a business user.
- Do not remove human input triggers for high-risk, authority-conflict, or reference-insufficient cases.
