# TeamKit Annex — v0.3 Engine Semantics

Load this annex only when the team definition is a TeamKit `team.yaml` at protocol v0.3. Treat it as engine truth: it upgrades otherwise-`[inference]` findings to `[fact]`. It is maintained in lockstep with this repository's core; if a claim here conflicts with the current `teamkit` source, the source wins — say so and follow the source.

This annex covers: the v0.3 parallel semantics, the mechanical review checks that depend on them, the version gate, and a worked YAML example. The universal dimensions (C/S/R/A/H clusters in [review-rubric.md](review-rubric.md)) still apply; this annex sharpens them for TeamKit-native teams.

## Version Gate

Determine protocol by feature presence, not by the `version` field alone. The validator does not check the field's value, and many existing teams carry stale values. Treat a team as v0.3 when it uses `relation: parallel` or `join` semantics, or declares `version: 0.3` or higher. When the definition uses no parallel features at all, apply the universal rubric and skip the parallel checks below — no version notice is needed.

Only when a team declares an old-protocol `version` (below 0.3) **and** uses parallel features should you flag the mismatch to the user:

> This team uses v0.3 parallel semantics but declares an older protocol version. Consider setting `version: 0.3` so tooling reads it correctly.

## Parallel Semantics (engine truth)

1. The join decision is exactly: the target node's parallel in-edge count is greater than 1. The `join: all` annotation on the node is for humans and editors; its absence is not a runtime defect.
2. A fork happens only when: argument-free `advance`, no choice out-edges, and at least 2 parallel out-edges. A single parallel edge is an identity transform — no fork.
3. Mixing parallel and choice out-edges from one source is a modeling dead zone: the parallel branch has no implicit activation command; runtime advance will demand choosing a non-parallel edge.
4. A join's waiting prerequisites are the full static set of parallel predecessors across the graph; unreachable or never-same-round prerequisites make the join wait forever.
5. `max_visits` is consumed on edges only; visit counts accumulate per target node across rounds. Node-level `max_visits` is ignored and receives a mechanical validator warning.
6. `default_response` defaults to optional; only explicitly `required` messages block advancement.
7. `relation` is free text; only the exact string `parallel` participates in forking. `Parallel` is treated as choice — an information note, not a new core check.
8. With multiple active nodes, `graph next` returns `activeNodes`; advance needs `--node` to name the source. `result publish` performs no run-state checks — it only archives the final output; closing the run is a separate `run close`.

Mechanical baseline: run `teamkit team validate --team team.yaml` read-only and record its output as `[fact]`. Explain warnings in the validator's own words without extending them into business judgment.

## Mechanical Review Checks

These sharpen the universal rubric for TeamKit-native definitions:

| Check | Rubric home | TeamKit mechanics |
|---|---|---|
| Mixed parallel + choice out-edges from one source | S3 mixed-signal fork | `blocker`. The parallel branch has no activation command; advance demands a non-parallel edge. |
| `join: all` with fewer than 2 parallel in-edges | S3 signal + H5 | `info`. Dead annotation; also do not report "missing join" as a runtime defect — the engine never reads the annotation. |
| Join prerequisite unreachable from entry | S3 eternal wait | `warning`, provable from the definition; no run data needed to assert the permanent wait. |
| Exactly one parallel out-edge from a source | S3 degenerate fork | `info`. Identity transform; suggest a plain edge or a second genuine branch. |
| Node-level `max_visits` | H5 false guardrail | `warning`. Core consumes edge-level only; the definer believes protection exists that does not. |
| Nodes unreachable from `process.graph.entry` | R5 dead branch | `warning`. BFS/DFS from entry; list orphaned node IDs and edges with mistyped sources. |
| Cycles with no edge-level `max_visits` | S5 unbounded loop | `info` as a candidate. Record the cycle's node/edge IDs; do not predict run counts or performance. |
| Required-reply census | C1 | Count `default_response` and every `response: required` rule; build the per-expert in/out degree table. `warning` when defaults and dispatch rules are all required with no stated reason. |
| Graph edges duplicated in `process.communication.rules` | C4 | `info`. Normalize `from → to` against edge endpoints; flag pairs with no extra `when` or different `response`. |
| Fork branch with no return channel to the join consumer | C2 | `warning`. Check graph edge, communication rule, and `allow_expert_requests` for at least one permitted path back. |
| Expert absent from all nodes and rules | R1 ghost agent | `info`. Count expert occurrences, in/out degrees. |
| Parallel nodes pointing at the same single expert | S4 single-instance contention | `info` signal, `warning` only after platform semantics are confirmed. |

Business-dependent judgments (which messages must gate, whether a segment is truly independent) still degrade to `[inference]`/`[question]` exactly as the universal rubric requires. Engine truth upgrades *mechanical* claims only.

## Good Shape: Member Nodes Fork, Join Collects

```yaml
process:
  graph:
    entry: intake
    nodes:
      - id: intake
        expert: coordinator
        task: Organize materials and launch independent checks
      - id: evidence_check
        expert: evidence
        task: Verify factual evidence
      - id: policy_check
        expert: policy
        task: Determine applicable rules
      - id: decision
        expert: coordinator
        join: all
        task: Merge facts and rules into a conclusion
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
```

Parallel edges appear in pairs; two member nodes work independently; `decision` collects. `join: all` helps humans read intent, but the engine relies on decision's two parallel in-edges.

## Bad Shapes

Single parallel edge — no fork, just a plain edge in disguise:

```yaml
edges:
  - from: intake
    to: evidence_check
    relation: parallel
```

Mixed parallel + choice — the parallel branch never starts:

```yaml
edges:
  - from: intake
    to: evidence_check
    relation: parallel
  - from: intake
    to: manual_review
    when: high risk found
```

Either both edges are "do simultaneously" (mark both parallel, join them), or they are alternatives (drop `relation`, keep the condition). The engine does not infer "parallel first, then choose".

Required everywhere — every dispatch becomes a blocking wait:

```yaml
communication:
  allow_expert_requests: true
  default_response: required
```

Prefer `optional` as the default; make only handoffs, aggregations, reports, and rulings explicitly `required`.

## Worked Example (full rhythm, TeamKit-native)

```text
F-03 · blocker · S3 mixed-signal fork
[fact] material_intake has one out-edge marked relation: parallel and one
unmarked choice edge; Core defines no implicit fork command for this mix, so
the parallel branch is never activated (team.yaml, edges block; annex §Parallel
Semantics item 3).
Impact: the same starting point reads as both "do both" and "pick one"; the
engine cannot start both paths as the team intends.
Proposed benefit: with one unambiguous form, the flow starts as expected and
is easier to audit.

User: fix F-03.

before:
  - from: material_intake
    to: evidence_check
    relation: parallel
  - from: material_intake
    to: policy_review
    when: rule anomaly found

after (candidate, pending user confirmation):
  - from: material_intake
    to: evidence_check
    relation: parallel
  - from: material_intake
    to: policy_review
    relation: parallel
  - from: evidence_check
    to: decision_draft
    relation: parallel
  - from: policy_review
    to: decision_draft
    relation: parallel

nodes:
  - id: decision_draft
    expert: decision
    join: all
    task: Merge both check results into a conclusion draft

In plain terms: when both paths must run, mark both starting edges and both
return edges "simultaneous", and let the join node collect them. If it is
actually either/or, remove `relation: parallel` and keep the condition.
Benefit: avoids a path that never receives a start command.

After user approval: edit only the affected edges in team.yaml, run
teamkit team validate, show the diff.
```

The `after` above demonstrates notation only; it does not authorize copying nodes or edges mechanically. A real plan reflects the user-confirmed business dependencies with minimal edits.

## Reviewer Reminders

- `current_node` remains the first active node for old readers; parallel state lives in `active_nodes`/`activeNodes`.
- Graph edges are the default step-to-step permission; do not copy every edge into communication rules.
- This annex states mechanical semantics only; "is parallelism worth it here" returns to the expert profiles and business dependencies, as `[question]`.
