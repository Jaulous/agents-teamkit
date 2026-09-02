# Review Rubric

Review an existing multi-agent team against this rubric. Record evidence from the team's definitions first, then draw conclusions. Mechanical dimensions may assert; business-dependent dimensions must degrade to `[inference]` or `[question]`. The optimization goal throughout: improve standardization, performance, and effectiveness without changing business functionality.

## How To Read This

**Definition surface.** "Definitions" means whatever artifacts on the invoking platform encode the team. This rubric never names concrete paths; the invoking agent discovers them.

**Canonical vocabulary** (aliases are examples, not limits):

| Neutral term | Meaning | Familiar aliases |
|---|---|---|
| Role | A defined worker with a responsibility contract | expert, subagent, agent, 专家 |
| Step | A unit of work the team may perform | node, task, stage |
| Route | A declared allowed movement of work between steps/roles | edge, transition, handoff |
| Message | A directed communication between roles, or role↔human | request/reply/notify, member message |
| Reply expectation | Whether the sender waits: blocking / optional / none | `response: required`, ack-before-proceeding |
| Channel | The concrete path a result travels: a route, a shared artifact, or a message permission | permission rule, allow-list, file convention |
| Shared context | Information declared visible to some set of roles | context item, memory, referenced doc |
| Entry | Where one execution starts | entry node, first stage |
| Join | A step consuming results from more than one branch | fan-in, aggregation point |
| Gate | A point requiring human decision | human review, approval step |
| Output contract | The declared shape of the final deliverable | output sections, report schema |
| Team shape | The macro control structure | pipeline, parallel-reduce, debate, relay/star |

**Detection modes.** Each dimension is tagged: *mechanical* (countable from definitions), *mixed* (mechanical signal + judgment), *judgment* (semantic reading — always co-tag `[inference]`/`[question]`).

**Depth.** The **minimum viable scan** is **C1, C2, S1, S3, R1, R3, A1, H1** — these eight catch the majority of business-visible failures. Run them for quick health checks; run all dimensions for optimization requests.

## Severity And Ordering

Severity answers two questions, both decidable without runtime data: (1) *contradiction* — as written, can the team still deliver what it declares? (2) *degradation* — does the issue strand work, lose results, or add coordination cost, or is it cosmetic?

| Level | Definition |
|---|---|
| **blocker** | A provable self-contradiction: the definition defeats its own declared intent. Requires proof from definitions alone. |
| **warning** | A structural gap or high-probability degradation needing one user confirmation. Also the cap for findings resting on an unverified `[assumption]`. |
| **info** | Consistency, readability, maintenance surface. No correctness impact. |

Rules:

- A warning whose underlying business fact the user confirms, and which implies loss of a declared output, escalates to blocker. Record the escalation.
- Never assign blocker on runtime-performance grounds; performance predictions are always `[inference]`.
- Severity (how bad), evidence tag (how sure), and dimension code (where) are orthogonal; one of each per finding.
- Report order: blockers, then warnings (declared-output impact > stranded work > coordination cost), then infos. Tiebreak: cluster order C, S, R, A, H, then code number.

---

## Cluster C — Communication Topology

*Who talks to whom, with what reply expectation, over which channel.*

### C1 · Reply-expectation hygiene

Whether each message's reply expectation matches whether the sender truly must wait.

- **Detection:** mixed
- **Signals:** the team's default reply expectation (is it blocking?); count of blocking declarations per role; profiles instructing "broadcast to everyone and require confirmation before proceeding"; blocking expectations attached to notification-shaped bodies (one-way informational, no question in them).
- **Ask the user:** Which replies gate progress — the work cannot correctly continue without them — and which are awareness only?
- **Anti-patterns:** **reply-storm** (every dispatch demands a reply; starting work costs N blocking round-trips); **mandatory-ack cascade** (each acknowledgment triggers the next broadcast); **courtesy-required** (blocking used as politeness).
- **Minimal fix:** make non-blocking the default; attach blocking only to true gates — handoffs, aggregations, decisions, escalations.

### C2 · Return-channel completeness

Every branch producing a needed result has at least one declared, consumed channel to its consumer.

- **Detection:** mixed
- **Signals:** for each producing step, no route, permission, or shared-artifact convention carries its result onward; a role's declared outputs with no matching downstream input rule; output phrasing like "post findings in your final message" with nothing downstream instructed to read that medium.
- **Ask the user:** How is this result meant to travel — shared file, direct message, relay through a lead? Is it required for the final deliverable?
- **Anti-patterns:** **orphan result** (work completes, nobody receives it); **silent branch** (outbound route exists, consumer never reads that medium); **dead-letter handoff** (result written where no downstream step reads).
- **Minimal fix:** declare exactly one channel — a route plus permission, or a named shared artifact with an explicit reader. Escalates to blocker if the user confirms the result is required for the final deliverable.

### C3 · Hub concentration

Whether one role sits on the critical path of more exchanges than its business function justifies.

- **Detection:** mixed
- **Signals:** degree centrality of one role across routes/permissions (star shape); profiles forbidding peer contact ("all communication goes through the lead"); a lead owning dispatch, arbitration, synthesis, *and* substantive domain steps; every peer question costing two hops.
- **Ask the user:** Which peer exchanges are routine (deserve a direct channel) and which exceptional (deserve arbitration)? Which of the lead's substantive steps require judgment only the lead has?
- **Anti-patterns:** **god-router** (all traffic relays through one role); **star-trap** (structurally parallel team, behaviorally serial because everything transits the hub).
- **Minimal fix:** open direct peer channels for named routine pairs; keep the hub for arbitration and final aggregation.

### C4 · Declaration redundancy

The same permission/route declared in more than one place without differentiated meaning.

- **Detection:** mechanical
- **Signals:** normalize route declarations across declaration surfaces (structure file vs communication rules vs profile prose); flag pairs identical in endpoints with no additional condition or different expectation; instruction blocks restated in both a team-level convention and a profile.
- **Ask the user:** Is one copy meant to add a condition, or is it verbatim?
- **Anti-patterns:** **double-licensed edge**; **mirror config** (every structural edge copied one-for-one into communication rules).
- **Minimal fix:** keep the more specific declaration, delete the verbatim copy. Severity info — maintenance risk (change one, miss the other), not a correctness bug; escalates only when copies already contradict.

### C5 · Fan-out discipline

Multi-recipient dispatch targeted to roles who must act, not to everyone.

- **Detection:** mixed
- **Signals:** identical message body/intent addressed to many; broadcast instructions in profiles; fan-out where the collator is also the sender; fan-out combined with blocking expectations (the expensive combination — see C1).
- **Ask the user:** Who must *act* on this information versus be *aware* of it?
- **Anti-patterns:** **broadcast blast**; **reply-all culture** (broadcast + blocking as standing habit).
- **Minimal fix:** narrow recipients to actors; route awareness through a shared-context note instead of messages.

---

## Cluster S — Scheduling Structure

*Serial vs parallel, dependencies, convergence, waiting, loops.*

### S1 · Parallelizable-segment detection

Whether serially arranged steps are coupled by data, or only by the order someone wrote them down.

- **Detection:** mixed
- **Signals:** adjacent steps where the later step's declared inputs do not reference the earlier step's outputs; multiple steps declaring the same trigger or source artifact; orchestration phrasing implying mere sequence ("then", "after that") with no data reason; serial depth large relative to the width of independent step sets.
- **Ask the user:** Does any later step use the earlier step's result in substance — not just "comes after" it? Is wall-time latency or per-run cost the priority?
- **Anti-patterns:** **false serial** (independent steps chained because they were authored in that order); **polite queue** (steps wait out of sequencing courtesy, not data need); **conga line** (long single-file chain whose only true coupling is the final consumer — see A1).
- **Minimal fix:** dispatch independent steps concurrently, converge where a consumer needs all results. Arrival order becomes the join's concern, not the business's.

### S2 · Hidden dependency vs declared concurrency

Steps declared concurrent that secretly read or write each other's territory.

- **Detection:** mixed
- **Signals:** concurrent branches referencing the same artifact paths; a step's declared input naming a path only a *concurrent sibling* writes; concurrent roles with write access to the same file; instructions saying "wait until X is done" inside a branch declared concurrent with X.
- **Ask the user:** For each shared reference — read-only-both, producer-consumer, or a genuine race?
- **Anti-patterns:** **phantom dependency** (undeclared producer-consumer between concurrent branches); **shadow ordering** (correctness silently depends on one branch finishing first); **shared scratchpad race** (two concurrent writers, last wins).
- **Minimal fix:** real dependency → serialize or insert the producing step; race → distinct output paths, merge at the join.

### S3 · Join satisfiability

Whether every input a convergence point waits for can actually occur.

- **Detection:** mechanical
- **Signals:** from the entry, compute reachability; for each join, list incoming branch inputs and check each is reachable and activatable; a source mixing concurrent-type and conditional-type outgoing steps is structurally ambiguous (the concurrent branch may have no activation command); degenerate forks (a "concurrent" out-degree of exactly one — an identity transform); declared join input count mismatching actual in-edges.
- **Ask the user:** For a conditional feeder — always run, sometimes run, or retired? When it does not run, should the join still complete?
- **Anti-patterns:** **eternal wait** (join waits for an input that can never occur); **unreachable feeder** (one join input has no path from entry — e.g. a renamed or deleted source); **mixed-signal fork**; **premature join** (consumer fires on first arrival when it needs all — usually platform mechanics, tag `[assumption]`).
- **Minimal fix:** make every join input reachable; if an input is sometimes-absent, route the not-taken case to the join too (an explicit skip or exception step) so it can complete. Remove degenerate single-branch concurrency markers.

### S4 · Single-instance role contention

Concurrent steps resolving to the same role instance that cannot host concurrent work.

- **Detection:** mixed — rests on platform instance semantics; **verify mechanics first, cap at warning until verified**
- **Signals:** two or more concurrent steps owned by the same role; a join owned by the same role as one of its feeders; a profile implying single working state ("I hold the working draft") while sitting on two branches.
- **Ask the user:** Can this role host concurrent work on your platform? If one instance, are the two tasks genuinely separable?
- **Anti-patterns:** **one body, two heads** (two concurrent steps, one instance — they serialize or interleave unpredictably); **self-join deadlock**.
- **Minimal fix:** split into two role variants with distinct focus, or sequence the steps explicitly.

### S5 · Loop bounds and rework termination

Every cycle has a stated, enforceable termination.

- **Detection:** mixed
- **Signals:** cycles in the step graph; return/rework edges with no visit cap, count, or termination condition anywhere; profile language like "iterate until good" with no arbiter named; caps written where the runtime does not consume them (cross-check what the platform actually reads — false protection).
- **Ask the user:** What is the business maximum rework count, and who breaks the tie when reached?
- **Anti-patterns:** **unbounded rework loop**; **ping-pong pair** (conflicting standards bounce work forever); **false guardrail** (cap written where the runtime ignores it — the definer believes protection exists).
- **Minimal fix:** put the cap at the platform's actual enforcement point with a stated condition; route cap-exhaustion to an escalation gate.

### S6 · Blocking span

How much independent work is frozen while a blocking expectation or gate is pending.

- **Detection:** judgment
- **Signals:** a blocking reply or human gate positioned *before* steps that do not depend on it; a slow role's acknowledgment gating unrelated branches; gate placement halting the whole run where only one branch needs approval.
- **Ask the user:** Which pending answers actually block which downstream work?
- **Anti-patterns:** **frozen run** (team idles on one answer while independent work exists); **gate-everything** (see A4).
- **Minimal fix:** let independent branches proceed; narrow the wait to the dependent branch, or defer the gate to the latest point where it is still decisive.

---

## Cluster R — Role And Node Structure

### R1 · Ghost roles

Roles defined but never reachable or invoked.

- **Detection:** mechanical
- **Signals:** zero in/out routes referencing the role; no profile instruction or trigger activating it; declared in a roster but absent from the executable structure.
- **Ask the user:** Reserved for future work, or leftover from an earlier design?
- **Anti-patterns:** **ghost agent**; **benchwarmer**; **trophy role** (kept for org-chart completeness).
- **Minimal fix:** remove it, or move it to a clearly marked optional library outside the executable definition.

### R2 · Overlapping responsibilities

Two roles whose contracts claim the same territory.

- **Detection:** mixed
- **Signals:** near-identical responsibility statements in two profiles; both holding write access to the same artifact; both routed in the same phase with the same inputs.
- **Ask the user:** Deliberate overlap (check versus counter-check, redundancy for robustness) or accidental?
- **Anti-patterns:** **twin agents**; **boundary bleed**; **dueling reviewers**.
- **Minimal fix:** accidental → split along a decision boundary or demote one to consult-only; deliberate → make the adversarial intent explicit (different mandates, different evidence sources).

### R3 · Missing synthesis and verification

Convergent work has an owner that merges it; outputs have an owner that checks them.

- **Detection:** mixed
- **Signals:** multiple producing branches but no step declared to consume all; output contract contains acceptance criteria but no role owns checking them; the producer of a high-stakes output is also its sign-off; final report assembled by "whatever arrived last".
- **Ask the user:** Who is accountable for the merged conclusion? Which outputs carry enough risk to warrant a separate verifier?
- **Anti-patterns:** **no synthesizer** (the report is an accident of arrival order); **missing verifier**; **self-grading solver** (producer and grader are the same role).
- **Minimal fix:** assign one aggregation owner (an existing role may take it); where risk warrants, add a distinct verification role with read access to all branch outputs. Adding a role is a structural change — propose, never invent silently.

### R4 · God-agent

One role accumulating coordination plus substantive work across all phases.

- **Detection:** mixed
- **Signals:** one role owns a large share of steps across phases; its profile mixes dispatch, domain work, arbitration, and synthesis; high degree centrality *and* high step count (C3 measures traffic; this measures workload).
- **Ask the user:** Which of this role's substantive steps require judgment only it has?
- **Anti-patterns:** **god-agent**; **coordinator-does-the-work**.
- **Minimal fix:** migrate domain steps to member roles; retain coordination, arbitration, and final synthesis with the lead.

### R5 · Dead branches

Steps that exist in the definition but can never execute.

- **Detection:** mechanical
- **Signals:** unreachable-from-entry steps; in-edges from nonexistent or mistyped sources; a conditional path subsumed by an always-taken sibling; conditions that can never be true given the entry state.
- **Ask the user:** Rare case worth keeping, or leftover?
- **Anti-patterns:** **dead branch**; **shadowed condition**; **orphan edge** (endpoints resolving to nothing).
- **Minimal fix:** repair the route/condition, or remove the step with a note in the change record.

### R6 · Unowned outputs and exception routing

Every declared deliverable has a producer; every failure or conflict has a landing spot.

- **Detection:** mixed
- **Signals:** output-contract sections/fields with no producing step; branch profiles lacking any failure/disagreement/insufficient-evidence instruction while the output contract assumes clean results; no route for "this branch could not complete".
- **Ask the user:** Where should a failed or conflicting branch land — a report section, a human gate, or a retry?
- **Anti-patterns:** **promised section, no owner**; **exception to nowhere**; **happy-path team** (the definition only describes success).
- **Minimal fix:** name the landing spot — an output-contract section plus an escalation route. Often the highest business value of any finding.

---

## Cluster A — Architecture Fit

*Does the team's shape match the business job?*

### A1 · Shape versus job

The macro control structure matches how the business work actually decomposes.

- **Detection:** judgment
- **Signals:** a deep serial chain whose steps declare independent inputs (independent-checks job wearing a pipeline costume); debate/loop structure around steps with no conflicting mandates; parallel-reduce shape whose branches share a hidden single resource; relay shape for work with no ordering need.
- **Ask the user:** Which business checks could be done with no knowledge of the others' results? Is this job latency-critical (parallelize independent checks) or throughput/cost-critical (batch, collapse ceremonial steps)? Where does the business *require* ordering?
- **Anti-patterns:** **conga line** (six-agent serial team for N independent checks plus one merge); **pipeline for parallelizable checks**; **parallel theater** (declared concurrency serialized by a shared bottleneck); **debate for a lookup**.
- **Minimal fix:** reshape independent segments into concurrent branches plus one join; collapse ceremonial steps into their consumers. Same business outcome, different geometry.

### A2 · Right number of roles

Role count matches the granularity of the work.

- **Detection:** judgment
- **Signals:** roles with a single micro-task; per-role fixed overhead (context loading, handoff messages) comparable to the work itself; coordination-step-to-work-step ratio; conversely, one profile containing many unrelated responsibility blocks.
- **Ask the user:** Which steps repeat often enough to justify a dedicated role's setup cost? Where does accountability actually change hands?
- **Anti-patterns:** **agent sprawl** (a role per trivial step); **monolith agent** (one role, five unrelated jobs).
- **Minimal fix:** merge micro-steps into one role with phased instructions; split monoliths along context boundaries (different input artifacts, not different verbs).

### A3 · Redundant coverage

Verification layers beyond what the job's risk justifies.

- **Detection:** judgment
- **Signals:** multiple roles verifying the same criteria against the same input with no differing mandate; nested check-the-checker chains with uniform criteria.
- **Ask the user:** What risk does each layer address that the previous one does not?
- **Anti-patterns:** **triple coverage**; **check-the-checker-the-checker**.
- **Minimal fix:** collapse redundant layers, or differentiate mandates (distinct acceptance criteria or evidence sources per layer).

### A4 · Human gate placement

Human decisions sit where the business risk actually is.

- **Detection:** judgment
- **Signals:** gate position relative to irreversible or costly actions; gates after all work is sunk versus before the irreversible step; gate count per routine run; gates in front of independent branches that do not depend on them (see S6).
- **Ask the user:** Which decisions are irreversible or high-liability? Which routine approvals could become spot-checks or exception-triggered?
- **Anti-patterns:** **rubber-stamp gate** (approval after everything is decided and sunk); **gate-too-late**; **gate-everything**.
- **Minimal fix:** move gates to just-before-irreversible and after-conflict; convert routine gates to sampling or exception-triggered. **Gate changes are consent-tier-3 work** — see the consent protocol.

### A5 · Escalation and tie-breaking

Disagreement and blocking silence have a declared resolution path.

- **Detection:** mixed
- **Signals:** roles with conflicting mandates but no arbiter named anywhere; blocking expectations with no timeout, close, or escalation rule; no route carrying "we disagree" to a human or lead.
- **Ask the user:** Who decides when experts disagree? How long may a blocking reply stay unanswered before someone escalates?
- **Anti-patterns:** **no escape hatch**; **silent veto** (a role blocks indefinitely by not replying).
- **Minimal fix:** name an arbiter role or human gate for conflicts; give blocking messages a close/timeout rule.

---

## Cluster H — Standardization And Context Hygiene

**Preservation guardrail — binding for this entire cluster.** Hygiene findings may concern only three things: (a) mechanical ambiguity — a name or route resolving to two different things; (b) duplicated maintenance surface — one rule maintained in several places; (c) provably dead references — instructions naming steps, roles, or tools that no longer exist. Style, formatting, language choice, file layout, and structural conventions are the user's and must never appear as findings. When unsure whether something is convention or defect: ask, do not suggest. Default severity: info.

### H1 · Shared-context visibility

Each role sees what it needs, and not a large multiple of what it needs.

- **Detection:** mixed
- **Signals:** a role's declared inputs with no visibility path granting them (**context wall**); roles seeing large shared corpora unrelated to their task (**context flood** — cost, noise, and irrelevant instructions can degrade output); volatile shared items with no owner or update rule (**stale snapshot**).
- **Ask the user:** Which inputs does this role actually consult in practice? Is this shared item stable or per-run?
- **Minimal fix:** narrow visibility to consumers; promote per-role extracts into shared context items with a named owner. Remember: *how context is distributed is a governance decision* — narrowing or redistributing visibility is a plan requiring approval, never a cleanup.

### H2 · Duplicated conventions

- **Detection:** mechanical
- **Signals:** identical or near-identical instruction blocks in multiple profiles; a rule present in both team-level conventions and a profile with divergent wording.
- **Ask the user:** Which copy is canonical?
- **Anti-pattern:** **convention fork** (copies drift apart; agents follow whichever they read last).
- **Minimal fix:** one canonical location; others point to it. Info; escalates to warning only when copies already contradict. Consolidation itself is consent-tier-3 work (it relocates where truth lives).

### H3 · Prompt and profile bloat

- **Detection:** mixed
- **Signals:** profile length far above team peers; instructions referencing removed steps/roles/tools; the same rule restated several times within one profile.
- **Ask the user:** Which instructions have you observed changing behavior? (Only the user knows; never prune on style guesses.)
- **Anti-patterns:** **kitchen-sink profile**; **prompt archaeology**; **zombie instruction** (rules for things that no longer exist).
- **Minimal fix:** delete only the provably dead; propose condensation as a question, apply only on confirmation.

### H4 · Naming and identity consistency

- **Detection:** mechanical
- **Signals:** one entity referenced under name variants; two distinct entities sharing a name; routes resolving by display name where a stable identifier exists.
- **Ask the user:** Are these two names the same role?
- **Anti-patterns:** **role aliasing**; **name collision**.
- **Minimal fix:** canonical identifier everywhere; aliases only where the platform forces display names. Info; escalates when a route resolves to the wrong target.

### H5 · Protocol and version coherence

- **Detection:** mixed — needs the invoking agent's platform knowledge; **tag as `[assumption]` and cap at warning until verified**
- **Signals:** fields/keywords used in some definition files but not others; declarations the runtime may ignore; mixed dialects across files authored at different times.
- **Ask the user:** Which protocol version is canonical for this team?
- **Anti-patterns:** **mixed dialect**; **vestigial field**; **false guardrail** (a protective field the runtime never reads — the definer believes protection exists).
- **Minimal fix:** normalize to one version; move the intent into the mechanism the platform actually consumes. Warning when a vestigial field silently fails to protect; otherwise info.

---

## Worked Examples

Five findings in final-report form, each using a different platform's vocabulary inside the evidence lines while the dimension codes and structure stay neutral.

### F-01 · warning · S1 False serial — Claude Code subagent team

- [fact] Five subagent definitions exist (`pr-reviewer`, `dependency-auditor`, `style-checker`, `perf-sniffer`, `license-scanner`); each declares the same single input ("the diff under review") and none declares reading another reviewer's output (Inputs section of each file).
- [fact] The orchestrating instructions phrase strict sequence: "collect each reviewer's report before starting the next; finally ask the summarizer to merge all reports" (project instructions, review workflow section).
- [inference] The five checks are candidates for concurrent dispatch; as written, total wall-time is expected to be the sum of five runs.
- [question] Does any reviewer need another reviewer's result, or only the raw diff?

Impact: five independent checks each pay for the other four's latency on every run.
Minimal fix: dispatch the five concurrently and hand all five reports to the summarizer (fan-in). Report content and merge logic unchanged.

### F-02 · warning · C2 Orphan result — codex-style file-handoff team

- [fact] `verifier`'s instructions say "post your findings in your final message" (verifier profile, Output section).
- [fact] The routing table declares exactly one route involving the verifier: orchestrator → verifier. No route, file convention, or permission carries verifier output onward.
- [fact] `fixer`'s declared input is "the verifier's findings list" (fixer profile, Inputs section).
- [inference] The fixer's declared input has no producer-to-consumer path; the findings are expected to strand at the verifier's final message.
- [question] How are findings meant to travel — a shared file the fixer reads, or a direct verifier→fixer message?

Impact: verification completes but its consumer never receives it.
Minimal fix: declare one return channel — e.g. the verifier writes a findings artifact at a named shared path, and the fixer's input points at that path.

### F-03 · warning · C1 Reply-storm + C3 God-router — WorkBuddy 专家团

- [fact] The 组长 (lead) expert's collaboration rules instruct: on every incoming task, message all five 专家 and require each one's confirmation reply before any work is assigned (lead profile, 协作规则 section).
- [fact] None of the five member profiles declares a peer channel; every documented exchange routes member → 组长 → member (member profiles, collaboration sections).
- [inference] Every task is expected to pay five blocking acknowledgments before starting, and every cross-member question costs two hops through the lead.
- [question] Which members' acknowledgments actually gate the start, and which are awareness only?

Impact: start-of-task latency scales with the slowest acknowledger; routine peer questions queue behind the lead's other work.
Minimal fix: set the task broadcast to no-reply; require a reply solely from the member whose input gates the work; open a direct channel for routine pairs.

### F-04 · blocker · S3 Eternal wait — teamkit-native team

- [fact] The edge list contains `material_intake → policy_check (relation: parallel)`, but `material_intake` appears in no node declaration; `policy_check` has no other in-edge (team definition, edges block).
- [fact] The `decision` node derives its join from two parallel in-edges, one of which is this orphaned edge; the other is reachable from the entry.
- [inference] `policy_check` can never be activated; the join at `decision` can never be satisfied by structure alone.
- [question] Should that edge originate at the entry (the source was renamed), or was the policy branch retired?

Impact: as written, the team cannot complete the path it declares.
Minimal fix: correct the edge's source, or delete the branch and its join input — the smallest edit that makes every join input reachable.

### F-05 · warning · A2/A3 Agent sprawl + triple coverage — custom scripted pipeline

- [fact] The orchestration script defines six sequential stages, and each stage's prompt template embeds the complete 30-page SOP (script, prompt-templates section).
- [fact] Stages 2, 4, and 5 each contain a "summarize the contract" instruction against the same source document, with outputs consumed by three different later stages.
- [inference] The contract is summarized three times per run, and each stage is expected to pay re-processing cost for the full SOP regardless of relevance; the three summaries can drift apart silently.
- [question] Do the three consumers need materially different summaries, or would one shared summary serve all three?

Impact: per-run cost roughly tripled on summarization, plus consistency risk.
Minimal fix: one summarize stage writing a shared artifact all three consumers read; scope each stage's embedded SOP to the sections it uses. Business outputs unchanged.

---

## Notes For The Reviewer

1. The rubric's center of gravity shifts from mechanical to judgmental across platforms: gather counts first, interpret second, ask third.
2. `[assumption]` is load-bearing: platform-mechanics claims must be verified against the platform's current documentation or capped at warning.
3. R6 (unowned outputs) and A1 (shape versus job) concentrate the business value — and are the most judgment-heavy. Worked examples do the most teaching there.
4. Cluster H's preservation guardrail exists because this cluster most tempts a reviewer into restyling the user's conventions.
5. S4 and H5 cannot be fully evaluated without platform knowledge; both carry explicit "verify mechanics first" language.
