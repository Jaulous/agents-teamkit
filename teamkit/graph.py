"""Graph execution over the Topic ledger.

Functions here are pure with respect to storage: they read and mutate a
``topic`` dict and receive open-message information from the caller. The
caller (``teamkit.runs``) owns locking and persistence.
"""

from __future__ import annotations

from typing import Any, Callable

from teamkit.errors import TeamKitError
from teamkit.fsutil import now
from teamkit.team import TeamContext
from teamkit.validation import edge_id

CLOSED_TOPIC_STATUSES = {"resolved", "archived"}

# open_messages(node_id) -> list of open required message ids for that node
OpenMessages = Callable[[str], list[str]]


def topic_active_nodes(topic: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the active-node ledger, synthesizing it for v0.1 topics."""
    raw = topic.get("active_nodes")
    if isinstance(raw, list):
        result = [dict(item) for item in raw if isinstance(item, dict) and item.get("node")]
        if result:
            return result
    current = str(topic.get("current_node") or "")
    return [{"node": current, "status": "active", "waiting_on": []}] if current else []


def active_node_entries(topic: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in topic_active_nodes(topic) if item.get("status") in {"active", "waiting"}]


def save_active_nodes(topic: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    order = {"active": 0, "waiting": 1, "done": 2}
    entries.sort(key=lambda item: (order.get(str(item.get("status")), 3), str(item.get("activatedAt", ""))))
    topic["active_nodes"] = entries
    active = next((item for item in entries if item.get("status") == "active"), None)
    if active:
        topic["current_node"] = str(active.get("node"))
    else:
        fallback = next((item for item in entries if item.get("status") == "waiting"), None)
        topic["current_node"] = str((fallback or {}).get("node") or "")


def bump_visit(topic: dict[str, Any], node_id: str) -> None:
    visits = topic.get("visits")
    if not isinstance(visits, dict):
        visits = {}
        topic["visits"] = visits
    visits[node_id] = int(visits.get(node_id, 0)) + 1


def node_actions(
    ctx: TeamContext,
    topic: dict[str, Any],
    node_id: str,
    open_messages: OpenMessages,
    ignore_waiting: bool = False,
) -> dict[str, Any]:
    node = ctx.require_graph_node(node_id)
    result: dict[str, Any] = {
        "currentNode": node_id,
        "currentExpert": node.get("expert", ""),
        "currentTask": node.get("task", ""),
        "blocked": False,
        "terminal": False,
        "actions": [],
        "openMessages": [],
    }
    entry = next((item for item in topic_active_nodes(topic) if str(item.get("node")) == node_id), None)
    if entry and entry.get("status") == "waiting":
        result["blocked"] = True
        result["reason"] = "node is waiting for parallel predecessors"
        result["waitingOn"] = entry.get("waiting_on", [])
        return result
    if topic.get("status") in CLOSED_TOPIC_STATUSES:
        result["blocked"] = True
        result["reason"] = f"topic is {topic.get('status')}"
        return result
    pending = open_messages(node_id)
    if pending and not ignore_waiting:
        result["blocked"] = True
        result["reason"] = "current node has unresolved required messages"
        result["openMessages"] = pending
        return result
    if (topic.get("status") == "waiting" or topic.get("waiting_on")) and not ignore_waiting:
        result["blocked"] = True
        result["reason"] = "topic is waiting"
        result["waitingOn"] = topic.get("waiting_on")
        return result
    visits = topic.get("visits") if isinstance(topic.get("visits"), dict) else {}
    node_map = ctx.graph_node_map()
    for index, edge in enumerate(ctx.graph_edges()):
        if str(edge.get("from")) != node_id:
            continue
        target_id = str(edge.get("to"))
        target = node_map.get(target_id, {})
        max_visits = edge.get("max_visits")
        current_visits = int(visits.get(target_id, 0))
        allowed = not (isinstance(max_visits, int) and current_visits >= max_visits)
        result["actions"].append({
            "id": edge_id(edge, index),
            "type": "advance",
            "from": node_id,
            "to": target_id,
            "expert": target.get("expert", ""),
            "task": target.get("task", ""),
            "when": edge.get("when", ""),
            "relation": edge.get("relation", "next"),
            "allowed": allowed,
            "reason": "" if allowed else f"max_visits reached for {target_id}",
            "visits": current_visits,
            "maxVisits": max_visits,
        })
    if not result["actions"]:
        result["terminal"] = True
        result["reason"] = "end of graph: publish the result and close the run"
    return result


def next_actions(
    ctx: TeamContext,
    run_id: str,
    topic: dict[str, Any],
    open_messages: OpenMessages,
    from_node: str = "",
    ignore_waiting: bool = False,
) -> dict[str, Any]:
    if not ctx.graph():
        raise TeamKitError("process.graph is not configured")
    entries = active_node_entries(topic)
    if from_node:
        entries = [item for item in entries if str(item.get("node")) == from_node] or [
            {"node": from_node, "status": "active", "waiting_on": []}
        ]
    topic_id = str(topic.get("id") or run_id)
    if topic.get("status") in CLOSED_TOPIC_STATUSES and not from_node:
        return {"runId": run_id, "topicId": topic_id, "activeNodes": [], "actions": [], "blocked": True,
                "reason": f"topic is {topic.get('status')}"}
    if not entries:
        return {"runId": run_id, "topicId": topic_id, "activeNodes": [], "actions": [], "blocked": False, "reason": "no_active_node"}
    views = [node_actions(ctx, topic, str(item["node"]), open_messages, ignore_waiting) for item in entries]
    first = views[0]
    result: dict[str, Any] = {"runId": run_id, "topicId": topic_id, **first, "activeNodes": views}
    result["blocked"] = bool(topic.get("status") in CLOSED_TOPIC_STATUSES or first.get("blocked"))
    return result


def summarize_next(view: dict[str, Any]) -> dict[str, Any]:
    """The nextExpert/nextTask shortcut shown by status-style commands."""
    nodes = view.get("activeNodes") or []
    summary: dict[str, Any] = {"activeNodes": nodes, "nextExpert": None, "nextTask": None}
    if len(nodes) == 1:
        action = next((item for item in nodes[0].get("actions") or [] if item.get("allowed")), None)
        if action:
            summary["nextExpert"] = action.get("expert")
            summary["nextTask"] = action.get("task")
    return summary


def advance(
    ctx: TeamContext,
    run_id: str,
    topic: dict[str, Any],
    open_messages: OpenMessages,
    *,
    node: str = "",
    edge: str = "",
    to: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Advance the graph in ``topic``; return a description of the transition.

    ``force`` skips open-message and topic-waiting blockers (never max_visits
    or closed topics) so a coordinator can recover from a lost reply.
    """
    if edge and to:
        raise TeamKitError("use either --edge or --to, not both")
    if topic.get("status") in CLOSED_TOPIC_STATUSES:
        raise TeamKitError(f"cannot advance graph: topic is {topic.get('status')}")
    entries = active_node_entries(topic)
    if node:
        if not any(str(item.get("node")) == node and item.get("status") == "active" for item in entries):
            raise TeamKitError(f"graph node is not active: {node}")
        source_node = node
    else:
        active = [item for item in entries if item.get("status") == "active"]
        if len(active) > 1:
            names = ", ".join(str(item.get("node")) for item in active)
            raise TeamKitError(f"multiple active graph nodes ({names}); use --node")
        if not active:
            raise TeamKitError("no active graph node")
        source_node = str(active[0]["node"])

    view = node_actions(ctx, topic, source_node, open_messages, ignore_waiting=force)
    if view.get("blocked"):
        detail = view.get("reason")
        if view.get("openMessages"):
            detail = f"{detail}: {', '.join(view['openMessages'])} (reply, close them, or use --force)"
        raise TeamKitError(f"cannot advance graph: {detail}")
    actions = view.get("actions") or []
    if not actions:
        raise TeamKitError(f"cannot advance graph: {source_node} is the end of the graph; close the run instead")
    parallel = [a for a in actions if a.get("relation") == "parallel"]
    choices = [a for a in actions if a.get("relation") != "parallel"]

    if edge or to:
        selected_id = edge
        if to:
            matches = [a for a in actions if a.get("to") == to]
            if not matches:
                raise TeamKitError(f"graph target not available from {source_node}: {to}")
            if len(matches) > 1:
                raise TeamKitError(f"multiple graph edges target {to}; use --edge")
            selected_id = str(matches[0].get("id"))
        selected = next((a for a in actions if a.get("id") == selected_id), None)
        if not selected:
            raise TeamKitError(f"graph edge not available from {source_node}: {selected_id}")
        if selected.get("relation") == "parallel":
            raise TeamKitError(
                f"edge {selected.get('id')} is relation:parallel; a fork activates all parallel branches, omit --edge/--to"
            )
        if not selected.get("allowed"):
            raise TeamKitError(f"graph action is not allowed: {selected.get('reason')}")
        chosen = [selected]
    elif choices:
        if parallel:
            raise TeamKitError("node has parallel branches and selectable branches; use --edge/--to to choose a non-parallel edge")
        allowed = [a for a in choices if a.get("allowed")]
        if not allowed:
            raise TeamKitError("no allowed graph action from current node (max_visits reached)")
        if len(allowed) > 1:
            options = "; ".join(f"--to {a['to']} (when {a.get('when') or '-'})" for a in allowed)
            raise TeamKitError(f"multiple graph actions are available; choose one: {options}")
        chosen = [allowed[0]]
    else:
        chosen = [a for a in parallel if a.get("allowed")]
        if not chosen:
            raise TeamKitError(f"all parallel edges from {source_node} are blocked by max_visits")

    entries = topic_active_nodes(topic)
    source_entry = next((item for item in entries if str(item.get("node")) == source_node), None)
    if source_entry is None:
        raise TeamKitError(f"graph node is not active: {source_node}")
    source_was_parallel = bool(source_entry.get("parallel_branch"))
    source_entry["status"] = "done"

    join_sources: dict[str, list[str]] = {}
    for candidate in ctx.graph_edges():
        if str(candidate.get("relation") or "next") == "parallel":
            join_sources.setdefault(str(candidate.get("to")), []).append(str(candidate.get("from")))

    target_ids: list[str] = []
    for selected in chosen:
        to_node = str(selected["to"])
        target_ids.append(to_node)
        bump_visit(topic, to_node)
        ctx.require_graph_node(to_node)
        existing = next((item for item in entries if str(item.get("node")) == to_node), None)
        is_join = str(selected.get("relation") or "next") == "parallel" and len(join_sources.get(to_node, [])) > 1
        if is_join:
            if existing is None or existing.get("status") == "done":
                predecessors = list(dict.fromkeys([*join_sources.get(to_node, []), source_node]))
                fresh = {
                    "node": to_node,
                    "status": "waiting",
                    "waiting_on": predecessors.copy(),
                    "parallel_predecessors": predecessors,
                    "activatedAt": now(),
                }
                if existing is not None:
                    entries.remove(existing)
                entries.append(fresh)
        elif existing is not None:
            existing.update({"status": "active", "waiting_on": []})
        else:
            entries.append({
                "node": to_node,
                "status": "active",
                "waiting_on": [],
                "parallel_branch": source_was_parallel or len(chosen) > 1,
                "activatedAt": now(),
            })
        if len(chosen) > 1:
            current = next((item for item in entries if str(item.get("node")) == to_node), None)
            if current is not None:
                current["parallel_branch"] = True

    # A join waits on its direct parallel predecessors; satisfy them from
    # completed nodes, including the source that just finished.
    completed = {str(item.get("node")) for item in entries if item.get("status") == "done"}
    completed.add(source_node)
    join_activated = False
    for item in entries:
        if item.get("status") != "waiting":
            continue
        remaining = [str(value) for value in item.get("waiting_on", []) if str(value) not in completed]
        item["waiting_on"] = remaining
        if not remaining:
            item["status"] = "active"
            join_activated = True
    if join_activated:
        entries = [candidate for candidate in entries if candidate.get("status") != "done"]
    elif len(chosen) == 1 and not source_was_parallel:
        entries = [candidate for candidate in entries if candidate is not source_entry]
    save_active_nodes(topic, entries)
    topic["status"] = "active"
    return {
        "fromNode": source_node,
        "toNodes": target_ids,
        "edgeIds": [str(item.get("id")) for item in chosen],
        "experts": [str(item.get("expert") or "") for item in chosen],
        "forced": bool(force),
    }
