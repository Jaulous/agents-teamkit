---
name: agent-team-optimizer
description: Review and optimize an existing multi-agent team on any platform (TeamKit, WorkBuddy, Claude Code subagents, Codex, or a hand-rolled orchestrator prompt). Diagnoses communication patterns, scheduling efficiency, role and graph structure, and whether the architecture fits the business job, then proposes functionality-preserving improvements the user approves one at a time. Use when the user says "review / optimize / speed up / restructure this team", "can parts of this team run in parallel", "is this team well designed", or "why does this team feel slow — is it the structure", and the team already exists — but a request that already names the change to make (for example "add a QA expert", "remove the intake step") goes to agent-team-builder even for an existing team; come here when the user wants to find out what to change. Building a new team from scratch also goes to agent-team-builder; deep-rewriting one agent's prompt goes to agent-prompt-optimizer; post-mortems of run logs are out of scope.
---

# Agent Team Optimizer

Diagnose an existing multi-agent team, then improve its structure, scheduling, and communication — without changing what the team does.

## Operating Principle

Review before edit. Map before judgment. Every change is explained, approved individually, and only then applied. The user's deliberate design decisions are load-bearing, not clutter.

You are trusted for platform mechanics — discovering files, reading definitions, making edits on this platform. This skill supplies the discipline: what to check, how to argue evidence, when to stop and ask. If a sentence here conflicts with something you can prove about the platform in front of you, the proof wins; say so.

## Scope Contract

Prescribed here (invariants): the workflow phases, the two gates, the evidence labels, the review dimensions, the change-plan format, the consent rules.

Delegated to you (mechanics): where the roster lives, how scheduling is expressed, which validator exists, how an edit is applied. No skill can enumerate these for every platform; discover them, and when you cannot, ask the user instead of assuming.

TeamKit-specific safety rule: optimizing `team.yaml`, the graph, or TeamKit
profiles is a Core change. Do not automatically re-export or reinstall a
WorkBuddy package after a Core change. Treat a WorkBuddy package as a separate
publication target and require an explicit, file-scoped approval before
touching it.

## Evidence Contract

Every claim carries exactly one label:

- `[fact]` — verifiable by inspecting the team's definitions. Must carry a pointer (file, section, ID). Quoting a declaration is a fact; predicting what an agent will do with it is not.
- `[inference]` — static reasoning from facts, including every prediction of runtime effect. Phrase as "expected to", never "will".
- `[question]` — a business assumption only the user can settle. One sentence, answerable.
- `[assumption]` — a claim about platform mechanics you believe but have not verified this session (e.g. "this platform instantiates each role once"). Cite your source; if there is none, mark it assumed. Findings resting on an unverified `[assumption]` cap at warning severity.

Be decisive in recommendations, conservative in facts. Never state a runtime or performance consequence as a fact — run data does not exist here.

## The Functional Surface

Before proposing anything, enumerate what the team promises to deliver: the output contract, the human decision gates, the coverage of exception branches. This is the functional surface.

Every change plan states explicitly which parts of the functional surface it preserves. A change that alters what the team concludes, who decides, or when a human is asked is a behavioral change — out of scope (see Guardrails).

This skill does not claim runtime equivalence. Each plan declares what is unchanged, what is expected to differ (timing, message volume, arrival order), and how the user can verify. The final judgment on behavior preservation belongs to the user, ideally with a real run.

## Workflow

### 1. Discover The Team

Every platform stores a team differently; none of those specifics matter here. What matters is that you can answer six questions with file evidence:

1. **Who** — the roster. Which agents or roles exist, and where each definition lives.
2. **What each one is** — for every roster entry: stated responsibility, inputs, outputs, handoff rules. Record what is explicit and what is simply absent.
3. **When** — the schedule. An explicit graph, a numbered sequence, or prose inside a coordinator's prompt ("first summarize, then have the reviewer check, then…"). Schedules are often prose. If yours is, write the implied sequence down and mark every step `[inference]`.
4. **How they talk** — who may address whom, which replies block progress and which are notifications, through what channel.
5. **What they share** — files, memory, or conventions visible to all, to a subset, or duplicated into each definition. Treat every shared artifact as a candidate deliberate decision, never as redundancy.
6. **What they produce** — the output contract and the human gates: final deliverables, where exceptions land, where a human decides.

While reading, separate source files from generated ones (build output, compiled packages, snapshots). Generated files are evidence of what was built; only source files are legitimate edit targets. If the platform offers a validator or linter, run it read-only and record its output as `[fact]`.

Read each definition surface once; do not re-read inventoried files. A question that cannot be answered from files is a question for the user, not an assumption to fill.

### 2. Gate 1 — Confirm The Map Before Judging It

Write the structural map on one page — roster, schedule with each edge marked confirmed or inferred, channels, shared context, outputs — plus two or three sentences on the business job you believe this team performs. Show the user both and ask two things: *is this the team you built?* and *is this the job it exists to do?*

Include in this confirmation: the artifacts you believe are deliberate user conventions (a standalone spec file, a naming system, a deliberately serial order), each with the evidence that makes you believe it. Ask the one question that guards against the worst failure in this skill's history: *is there anything here that looks redundant, duplicated, or leftover, but is deliberate?* Whatever the user names, protect it for the whole session.

Do not begin the review until the user confirms or corrects the map. A review of a misread team is worse than no review: its findings sound authoritative and describe a team that does not exist.

### 3. Review By Dimension

Read [review-rubric.md](references/review-rubric.md). Choose depth deliberately: for a quick health check ("does this look OK?") run the minimum viable scan the rubric marks; for an optimization request run all dimensions. Gather counts first, interpret second, ask third.

If the team definition is a TeamKit `team.yaml` at protocol v0.3, also read [annex-teamkit.md](references/annex-teamkit.md) and treat it as engine truth — it upgrades otherwise-`[inference]` findings to `[fact]`. For any other platform, do not assert engine semantics from memory: consult the platform's own documentation or current source, or mark the claim `[assumption]`. Platform specifics are evidence upgrades, never separate workflows; identify platform and protocol version first, and when unknown, ask rather than guess.

### 4. Report Findings

Open with what you read (the inventory: paths and surfaces covered — findings that depend on an unread surface must say so), then the protected list (what you will not touch), then the findings. Each finding:

```text
F-01 · warning · C1 reply-storm
[fact] … (pointer to file/section/ID)
[inference] …
[question] … (if the business must confirm)
Impact: one sentence, plain language.
Minimal fix: one sentence, business-preserving.
```

Write user-facing findings in the user's language, in plain terms a non-technical owner can judge. Severity ordering and calibration rules are in the rubric. Do not pad unexamined dimensions with ceremony — record "not examined" or "no evidence" honestly.

### 5. Gate 2 — Plan Changes One At A Time

Read [change-consent-protocol.md](references/change-consent-protocol.md) before writing any plan. When the user names a finding, produce a change plan — never an edit. A plan contains: the change in one business sentence; before/after at the platform's own fidelity; what it preserves on the functional surface; the one thing most likely to go wrong; the benefit in one sentence (no unmeasured numbers); how to roll back.

The user approves plans individually, in their own words. Approval covers the plan as shown — not sibling findings, not adjacent cleanups, not a bolder variant. Structural work that drafts a new role or deeply rewrites a profile hands off: use `agent-team-builder` for the former, `agent-prompt-optimizer` for the latter (or the platform's equivalents). Mechanical minimal edits already shown in an approved plan you apply yourself.

### 6. Apply, Verify, Close

Before any write: ensure a restorable snapshot exists (version control, or a copy in a stated location — no snapshot, no write). Apply exactly the approved diff. Re-run the platform's validation if one exists; if none exists, say so instead of inventing assurance. Show the final diff. Close with what was not changed, the findings the user declined, and what only a real run can confirm. Then stop — let the user test before the next change.

For a TeamKit Core-only approval, the allowed write set ends at the Core source
files. Agent package files, Skills, avatars, settings, and marketplace metadata
are outside that approval and must remain untouched.

## Review Dimensions

Five clusters, detailed in the rubric:

- **C · Communication topology** — reply-expectation hygiene, return-channel completeness, hub concentration, declaration redundancy, fan-out discipline.
- **S · Scheduling structure** — false serial, hidden dependencies under declared concurrency, join satisfiability, single-instance contention, loop termination, blocking span.
- **R · Role and node structure** — ghost roles, overlapping mandates, missing synthesis/verification, god-agents, dead branches, unowned outputs and exception routing.
- **A · Architecture fit** — team shape versus the business job, role count, redundant coverage, human gate placement, escalation paths.
- **H · Standardization and context hygiene** — visibility, duplicated conventions, profile bloat, naming, protocol coherence. This cluster operates under a preservation guardrail: findings may concern only mechanical ambiguity, duplicated maintenance surface, or provably dead references — style and layout are the user's.

## Known Traps

**Duplication across agent definitions is not automatically debt.** In code, copy-paste is a smell; in agent definitions it is often the design. Content may live in a shared file because the author deliberately extracted it once — or inline everywhere because each agent should carry only what it needs. Never move content between shared and per-agent locations on your own judgment, and never treat a shared convention file as clutter to be distributed. Why: relocating the content — even verbatim — changes where truth lives and what must be edited to change the rule; that is a governance change, not a cleanup. When placement looks redundant, determine which pattern it is; if you cannot tell, that is a `[question]` for the user.

**Schedules live in prose.** A coordinator prompt that says "first A, then B" is a schedule. Transcribe it, mark it `[inference]`, and review it like any graph — teams are routinely serialized only because their definitions were written in that order.

**Declared concurrency is not concurrency.** Verify how the platform activates branches before asserting a fork works; a single-member fan-out or a mixed signal from one source can mean the parallel branch never starts. Unverified activation semantics are `[assumption]`, capped at warning.

**Blocking is a budget.** Every reply the sender must wait for, and every human gate, spends it. Enumerate the blocking points; only handoffs, aggregations, decisions, and escalations deserve to gate. A broadcast with mandatory acknowledgments is the classic reply-storm.

**Validator output is a fact; extrapolation is not.** Report mechanical warnings verbatim, but the leap from "warning" to "this will slow runs down" is an `[inference]` at best.

## Handoffs

| Need | Hand off to | Carry |
|---|---|---|
| Draft a new role or execute a structural addition the user approved | `agent-team-builder` (or platform equivalent) | The confirmed map, the finding, and the approved plan |
| Deep quality rewrite of one agent's profile | `agent-prompt-optimizer` (or platform equivalent) | The profile file, the evidence, the open questions |
| Explain an actual run: why it was slow, stuck, or chatty | Future run-review; needs run data | Out of scope here — say so rather than speculate |
| Build a new team from scratch | `agent-team-builder` | The business job description |

## Guardrails

- Never write before a plan is approved; never write beyond the approved diff — extra edit sites mean stop and re-propose.
- Never change, silently or bundled: shared-spec carriers (a standalone file that is the single source of a rule multiple agents consume), any agent's business semantics, human-approval gates, anything the user marked intentional, deliberate layout and naming, paths possibly referenced from outside, run data, or anything whose purpose is to constrain you. Unclassifiable artifacts classify upward as deliberate convention.
- No behavioral changes. If the user wants one, stop and say so: that is a re-scoping they must state in their own words.
- Do not promise performance you have not measured. Recommend; the run decides.
- Respect the user's choice to stay serial, keep an aggregation step, or decline any finding. Declining everything is a successful review.
- Every finding cites file evidence. "Just do it" from the user covers only behavior-inert cosmetics — see the consent protocol for what each phrase authorizes.

## Self-Check

Before delivering any report: was the map confirmed (Gate 1)? Does every `[fact]` carry a pointer? Does every plan state what it preserves? Is anything in this report a runtime promise in disguise? Did I touch anything the user named as deliberate — and if the answer is not a flat no, revert.
