# Change Consent Protocol

The safety core of this skill. Read it before writing any change plan, and again before any write. The catastrophe this protocol exists to prevent: an optimizer took a convention the user had deliberately extracted into one standalone global-spec file and, without asking, dissolved it and injected the pieces into every agent's system prompt. Verbatim relocation is not equivalence — it changes where truth lives and what must be edited to change the rule.

Three load-bearing decisions:

1. **Consent attaches to exact diffs, not to goals, findings, or sessions.** The user approves a shown before/after, nothing more.
2. **Uncertainty classifies upward.** Any artifact whose deliberateness cannot be established is treated as deliberate user convention.
3. **For an LLM agent, prompt text and visible context ARE the executable.** "Just reorganizing text" is the disguise most behavioral changes wear.

## Protected Invariants

Never change these silently. Tier 3 changes to them additionally require the artifact to have been explicitly de-protected by the user during intent confirmation.

1. **Shared-spec carriers** — any standalone file or section that is the single source of a rule, convention, or spec consumed by more than one agent. Moving its content into per-agent prompts — even verbatim — is a Tier 3 convention change, never a cleanup.
2. **Business semantics of any agent** — what it is responsible for, what it decides, what it consumes and produces, when it collaborates.
3. **Human-approval gates** — every condition under which a human must decide or be asked. Removing or weakening a gate is a transfer of authority, never an optimization.
4. **Explicitly marked intent** — "do not touch", "intentional", "keep serial", recorded decisions. The user already answered this question.
5. **Deliberate layout and naming** — directory structure, file naming systems, centralized versus distributed truth.
6. **Externally referenced paths** — anything a script, config, other team, or host platform may reference by name. If you cannot prove nothing references it, you cannot rename or move it.
7. **Run history and records** — ledgers, past runs, decision logs, artifacts. Evidence, not design.
8. **Anything whose purpose is to constrain you** — the skill's own files, permission settings, memory, consent mechanisms. Not even with approval in passing; ask the user to make such a change themselves.

### Classification: convention vs clutter

Classify every artifact you intend to touch, and show the classification with evidence in the protected map.

Signals of **deliberate convention** (any one strong, two conclusive):

- *Single-point reference* — the content exists in exactly one place, and other artifacts point to it, follow its naming, or quote it. Uniqueness + reference = design.
- *Coherent naming membership* — the file follows a consistent scheme with siblings.
- *Structural position* — it sits where canonical material lives, not in scratch locations.
- *Authored quality* — version-controlled, header comments, changelog entries, hand-tuned wording, cross-links that resolve.
- *Stated intent* — markers, README mention, a design note anywhere in the repo.

Signals of **incidental clutter**: duplicated content that has drifted between copies, dead/broken references, empty stubs, scratch/temp naming, files nothing references AND nothing follows the naming of.

**The cost-asymmetry override:** if removing, renaming, moving, or rewriting the artifact would silently change what any agent reads, receives, or is asked to decide — the artifact is load-bearing regardless of how it looks. Load-bearing beats clutter. When you cannot decide, the artifact is a convention: uncertainty classifies upward, always. "Probably leftover" is not evidence.

Your classification is a proposal, not a verdict. Only the user can de-protect an artifact, and only in words during intent confirmation. Anything not confirmed as fair game stays protected for the whole session.

## Behavior-Preservation Contract

You optimize how the team works, never what it concludes or who decides. A proposed change is structural only if you can write its behavior contract:

```text
Consumer:      <agent or human>
Receives now:  <information / obligations / decisions>
Receives then: <same, minus the exact delta>
Delta:         <what is added or removed>
Why inert:     <why no business conclusion, output obligation,
                authority, or gate timing can change>
```

One line per affected consumer. If a line cannot be written, the change is behavioral and out of scope.

Run the replay test and state it to the user in their terms: if the same real task ran once before and once after this change, and a business reviewer compared only the outputs and the moments a human was asked, the only permitted differences are speed, cost, message count, and internal file arrangement.

Gray zones resolve as follows:

- Trimming context an agent sees is behavioral unless the removed information is unused-by-contract or derivable from what remains.
- Rewording a prompt is behavioral unless you can argue semantic equivalence in one sentence. When in doubt, it is not equivalent.
- Deleting a user-authored file is Tier 3 even when its content is fully relocated. Propose archiving (move aside, with a note) as the default; deletion happens only if the user says "delete" in their own words.

Behavioral changes are out of scope. If the user wants one, stop and say so — that is a re-scoping the user must state in their own words before you record it as new scope.

## Risk Tiers And Consent

A change is assigned the tier of its *strongest* aspect, never its average, and never downgraded mid-session without a stated reason. Mixed-change bundles split into their parts.

```text
Tier 0 — Read-only diagnosis.
  Reading team files, running validators, counting, reporting.
  Consent: invocation itself. Write nothing anywhere; reports stay in
  the conversation unless the user names a destination.

Tier 1 — Reversible, behavior-inert cosmetics.
  Comment/documentation additions, formatting normalization, metadata
  nothing consumes, fixing references provably dead (you showed the
  target does not exist and nothing resolves it).
  Consent: ONE itemized list approval. Batching allowed only if every
  item is Tier 1 and homogeneous in kind. Plain "yes" suffices.

Tier 2 — Structural, behavior-preserving by argument.
  Scheduling rework (serial→parallel with confirmed independence),
  deduplicating communication rules, adding a missing return channel,
  layout changes not touching a protected invariant.
  Consent: itemized per proposal, with before/after and the behavior
  contract. The user may approve several by ID in one reply ("apply
  P-02, P-04"); consent is still itemized, execution applies them one
  at a time, re-validating between.

Tier 3 — Convention- or authority-touching.
  Dissolving, creating, merging, or relocating a shared-spec carrier;
  changing the naming system or deliberate layout; moving truth between
  centralized and distributed; deleting or archiving any user-authored
  artifact; touching anything on the protected map.
  Consent: per proposal, never batched, three mechanisms required:
    a. PRECONDITION — the artifact was explicitly de-protected by the
       user during intent confirmation. Ask the de-protection question
       first; you cannot ask for Tier 3 approval on unconfirmed ground.
    b. ECHO — restate the consequence in the user's own vocabulary
       ("this dissolves the handbook every role reads today").
    c. NAMED APPROVAL — the reply must contain the proposal ID
       ("Apply P-03"). A bare "ok" does NOT execute a Tier 3 change;
       re-ask once, showing the ID. Silence never does.

OUT — Behavioral. Not a tier. See the re-scoping rule above.
```

Rules that hold across all tiers:

- Consent attaches to the exact diff shown. If applying reveals more edit sites than presented, STOP — the new sites are a revised proposal.
- If the user amends a proposal, present the amended before/after and get one plain approval. Never silently apply a variant of what was shown.
- Snapshot every file you will touch BEFORE touching it: version control, or a copy in a stated backup location. No snapshot, no write.
- Write only inside the team definition the user pointed you at. Never host config, never other teams, never the skill's own files.

### When the user is away or says "just do it"

Blanket approval covers only the tiers the user's words actually name.

- "Just do it" / "go ahead" / "you decide", no tier named: authorizes Tier 1 at most. Never Tier 2 or Tier 3, never deletion. Execute the Tier 1 list, then stop and report.
- "Do everything except X": Tier 2 is covered for proposals already shown itemized; Tier 3 still requires its own named approval. X joins the protected map.
- User disengages mid-loop: the session ends in diagnosis-and-proposal state. Proposals stay proposals. Never pre-stage edits to "apply later"; never treat a timeout as consent. Already-approved in-flight changes may complete; no new writes begin.

## Change-Plan Template

Every Tier 1–3 change is presented through this shape. A non-technical owner must be able to judge it.

```text
PROPOSAL P-03  (from finding F-06)  ·  TIER 2 · STRUCTURAL

WHAT I PROPOSE
  One sentence, plain language. Gloss any unavoidable technical term.

FILES
  <path> — edit (3 lines) / create / archive

BEFORE
  <exact excerpt, or a structural sketch the user can recognize>

AFTER
  <the same material after the change — nothing implied>

WHY — IN YOUR TERMS
  Two or three sentences a non-technical owner can judge, using the
  owner's own metaphors: "this file works like the company handbook
  every role reads; my change fixes its table of contents and leaves
  every rule in place."

WHY BEHAVIOR IS PRESERVED
  Consumer: <agent/human> — receives now: …; receives then: …; delta: none.
  (One line per affected consumer; a missing line re-scopes the
  proposal OUT, it does not get shown weaker.)

WHAT COULD BREAK
  Honest failure modes, including "the behavior argument is wrong
  because X". If none identified, say so AND state what you checked —
  "none identified" without evidence is a red flag.

HOW TO ROLL BACK
  One line, exact: version-control revert / backup path / undo command.
  I verified the snapshot exists.

WHAT I WILL NOT TOUCH
  · <restated protected-map entries near this change>
  · <surfaces not part of this proposal>

TO CONFIRM
  Reply "Apply P-03". For Tier 3 the reply must include the ID.
  Anything else is treated as a revision request, not approval.
```

Presentation rules:

- Never mix diagnosis and proposals in one breath: findings report (no diffs) → user names findings → proposals → approval → apply.
- The findings report opens with the protected map, so the user sees the boundary before any temptation.
- One Tier 3 proposal per message. Tier 2 proposals may share a message but must be individually confirmable.
- Every proposal is answerable in one sentence. If it needs a paragraph to be understood, split or simplify it — do not add a preamble.

## Closure Checklist

Run after every applied change; show every line, including failures.

```text
[ ] SNAPSHOT: restorable snapshot of every touched file existed before
    the write. Location: ___
[ ] DIFF FIDELITY: the applied diff matches the approved proposal
    exactly. Drift is reported immediately with an offer to revert —
    never folded in silently and apologized for later.
[ ] MECHANICAL RE-VALIDATION: re-ran the platform's checks → result.
    If the platform offers no validator, say so and show the diff
    instead of inventing assurance.
[ ] PROTECTED MAP RE-CHECK: every entry unchanged — verified against
    the snapshot, not memory.
[ ] HUMAN GATES UNCHANGED: no approval condition removed, weakened,
    or moved. This line appears even when no gate was near the change.
[ ] BEHAVIOR ARGUMENT HOLDS: re-state the behavior contract in one
    line as it applies to the files as they now exist.
[ ] ROLLBACK VERIFIED: the rollback path was checked to exist and be
    usable, not merely written down.

WHAT I DID NOT CHANGE
  · Findings declined or deferred: F-01, F-07 (refusals are part of
    the session record, not just actions).
  · Conventions untouched: <restated protected map>.

WHAT ONLY A REAL RUN CAN CONFIRM
  · e.g. whether the parallel branch actually completes sooner. I do
    not promise performance I have not measured. Recommend the
    follow-up observation explicitly.

CLOSING OFFER
  If anything looks wrong, say "roll back P-03" and I will restore the
  snapshot. Declining everything is a successful review.
```

"Why 'what I did not change' is mandatory:" a session that only reports actions trains the user to read reports as change lists. The negative space — refused findings, untouched conventions, unmeasured claims — is what builds trust, and it makes declining a first-class outcome rather than a failure.
