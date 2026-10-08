"""Run audit: did a run actually follow the team protocol?

The audit reads only ledgers (after an optional native sync) and reports one
row per check with PASS / WARN / FAIL / UNVERIFIED. A run whose collaboration
cannot be observed is never reported as PASS.
"""

from __future__ import annotations

from typing import Any

from teamkit.fsutil import now, parse_time, read_jsonl, read_jsonl_with_errors
from teamkit.runs import OPEN_MESSAGE_STATUSES, RUN_CLOSED_STATUSES, RunStore

STALE_SECONDS = 30 * 60


def audit_run(store: RunStore, sync_report: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = store.ctx
    state = store.load_state()
    topic = store.load_topic() if store.topic_path.exists() else {}
    messages, message_errors = read_jsonl_with_errors(store.messages_path)
    events, event_errors = read_jsonl_with_errors(store.events_path)
    reviews = read_jsonl(store.human_review_path)
    coordinator = ctx.coordinator_id()
    checks: list[dict[str, Any]] = []

    def check(name: str, status: str, detail: str, **extra: Any) -> None:
        checks.append({"check": name, "status": status, "detail": detail, **extra})

    # 1. Ledger integrity
    problems = message_errors + event_errors
    closed = str(state.get("status")) in RUN_CLOSED_STATUSES
    if closed and topic and topic.get("status") != "resolved":
        problems.append(f"run is {state.get('status')} but topic is {topic.get('status')}")
    check("ledger_integrity", "FAIL" if problems else "PASS", "; ".join(problems) or "ledgers parse and agree")

    # 2. Host binding and native observation
    host = state.get("host") if isinstance(state.get("host"), dict) else None
    native_messages = [m for m in messages if m.get("source") == "workbuddy.native"]
    if not host:
        check("host_binding", "UNVERIFIED",
              "run is not bound to a host session; native collaboration was not observed")
    elif not host.get("nativeTeam"):
        reason = (sync_report or {}).get("reason") or "no native team matched yet"
        check("host_binding", "WARN" if not closed else "FAIL", f"{host.get('platform')}: {reason}")
    else:
        check("host_binding", "PASS",
              f"{host.get('platform')} team {host.get('nativeTeam')} (matched by {host.get('matchedBy', 'binding')}); "
              f"{len(native_messages)} native messages observed")
    if sync_report and sync_report.get("unattributed"):
        check("attribution", "WARN",
              f"{sync_report['unattributed']} native records could not be assigned to a run; "
              "dispatches and replies should start with [TeamKit run=<run-id> node=<node>]")

    # 3. Protocol violations recorded by sync
    violations = [e for e in events if e.get("type") == "protocol.violation"]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in violations:
        by_kind.setdefault(str(item.get("kind")), []).append(item)
    severity = {"unauthorized_route": "FAIL", "unknown_member": "FAIL", "subagent_dispatch": "FAIL",
                "duplicate_member": "WARN", "noncanonical_member_name": "WARN"}
    if not violations:
        check("communication_policy", "PASS" if host and host.get("nativeTeam") else "UNVERIFIED",
              "no protocol violations recorded")
    for kind, items in sorted(by_kind.items()):
        sample = items[0].get("detail") or ""
        check(f"violation:{kind}", severity.get(kind, "WARN"), f"{len(items)} occurrence(s); e.g. {sample}",
              occurrences=len(items))

    # 4. Member-owned nodes must be backed by that member's own messages
    advanced = [e for e in events if e.get("type") == "graph.advanced"]
    left_nodes = {str(e.get("fromNode")) for e in advanced}
    node_map = ctx.graph_node_map()
    missing = []
    for node_id in sorted(left_nodes):
        expert = str((node_map.get(node_id) or {}).get("expert") or "")
        if not expert or expert == coordinator:
            continue
        spoke = any(m.get("from") == expert for m in messages)
        if not spoke:
            missing.append(f"{node_id} ({expert})")
    if left_nodes:
        observed = bool(host and host.get("nativeTeam")) or any(m.get("source") == "teamkit" for m in messages)
        if missing and observed:
            check("member_results", "FAIL",
                  "nodes advanced with no message from their owner (lead may have written the result itself): "
                  + ", ".join(missing))
        elif missing:
            check("member_results", "UNVERIFIED", "member messages were not observed for: " + ", ".join(missing))
        else:
            check("member_results", "PASS", "every member-owned node that advanced has messages from its owner")

    # 4b. Collaboration that ran ahead of the graph: members delivered results
    # for work whose nodes the ledger never reached (lead skipped graph advance).
    visits = topic.get("visits") if isinstance(topic.get("visits"), dict) else {}
    reached = {str(node) for node, count in visits.items() if count}
    ahead = []
    for expert in sorted({str(m.get("from")) for m in messages if m.get("type") == "result"}):
        owned = ctx.nodes_for_expert(expert)
        if expert != coordinator and owned and not reached.intersection(owned):
            ahead.append(f"{expert} ({', '.join(owned)})")
    if ahead:
        check("graph_followed", "WARN",
              "results arrived from experts whose nodes the graph never reached; the lead did not run graph advance: "
              + ", ".join(ahead))

    # 5. Open required messages
    open_required = [m for m in messages if m.get("response") == "required" and m.get("status") in OPEN_MESSAGE_STATUSES]
    if open_required:
        oldest = min(str(m.get("createdAt") or "") for m in open_required)
        check("open_requests", "WARN", f"{len(open_required)} required message(s) unanswered since {oldest}",
              messages=[m.get("id") for m in open_required])
    else:
        check("open_requests", "PASS", "no unanswered required messages")

    # 6. Forced advances
    forced = [e for e in advanced if e.get("forced")]
    if forced:
        reasons = "; ".join(f"{e.get('fromNode')}: {e.get('reason')}" for e in forced)
        check("forced_advances", "WARN", f"{len(forced)} forced graph advance(s): {reasons}")

    # 7. Progress and closure
    active = [item for item in topic.get("active_nodes") or [] if isinstance(item, dict) and item.get("status") in {"active", "waiting"}]
    last = max((parse_time(e.get("createdAt")) or 0 for e in events), default=0)
    if closed:
        terminal = {str(n) for n in node_map if not any(str(e.get("from")) == n for e in ctx.graph_edges())}
        final_nodes = {str(e.get("toNode")) for e in advanced[-1:]} if advanced else {ctx.graph_entry_node_id()}
        if state.get("status") == "completed" and not (final_nodes & terminal):
            check("graph_progress", "WARN", f"run completed before reaching an end node (last node: {', '.join(sorted(final_nodes))})")
        else:
            check("graph_progress", "PASS", f"run {state.get('status')}")
        if state.get("status") == "completed" and ctx.team.get("output") and not state.get("final_result"):
            check("final_result", "WARN", "run completed without result publish")
    else:
        idle = (parse_time(now()) or 0) - last if last else 0
        nodes = ", ".join(str(item.get("node")) for item in active) or "none"
        if idle > STALE_SECONDS:
            check("graph_progress", "WARN", f"run open and idle for {int(idle // 60)} min at node(s) {nodes}")
        else:
            check("graph_progress", "PASS", f"run open at node(s) {nodes}")

    open_blocking = [r for r in reviews if r.get("status") == "open" and r.get("blocking", True)]
    if open_blocking:
        check("human_input", "WARN" if not closed else "FAIL",
              f"{len(open_blocking)} blocking human request(s) open: {', '.join(r['id'] for r in open_blocking)}")

    statuses = {c["status"] for c in checks}
    if "FAIL" in statuses:
        verdict = "FAIL"
    elif "UNVERIFIED" in statuses and not any(c["status"] == "PASS" and c["check"] == "host_binding" for c in checks):
        verdict = "UNVERIFIED"
    elif "WARN" in statuses or "UNVERIFIED" in statuses:
        verdict = "PASS_WITH_WARNINGS"
    else:
        verdict = "PASS"
    return {
        "runId": store.run_id,
        "verdict": verdict,
        "runStatus": state.get("status"),
        "auditedAt": now(),
        "counts": {"messages": len(messages), "nativeMessages": len(native_messages), "events": len(events),
                   "violations": len(violations)},
        "sync": sync_report,
        "checks": checks,
    }
