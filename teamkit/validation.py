"""Team definition validation.

Errors make a definition unusable; warnings flag shapes the engine accepts but
that usually indicate a modelling mistake.
"""

from __future__ import annotations

from typing import Any

from teamkit.errors import TeamKitError
from teamkit.team import (
    COMMUNICATION_MODES,
    CONTEXT_SCOPES,
    ID_PATTERN,
    MESSAGE_TYPES,
    PROCESS_MODES,
    RESPONSE_MODES,
    TeamContext,
)

WORKSPACE_KEYS = {
    "run_root", "message_log", "event_log", "context_items_log",
    "context_item_dir", "human_review_log", "decision_log", "state", "topic",
    "expert_workspace_dir", "expert_result_dir",
}
GRAPH_NODE_KEYS = {"id", "expert", "task", "join"}
GRAPH_EDGE_KEYS = {"id", "from", "to", "when", "relation", "max_visits"}
EDGE_RELATIONS = {"next", "parallel"}


def _identifier(value: Any, field: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not ID_PATTERN.match(value):
        errors.append(f"{field} must match {ID_PATTERN.pattern}")


def validate_team_definition(ctx: TeamContext) -> list[str]:
    errors: list[str] = []
    data = ctx.team

    team = data.get("team")
    if not isinstance(team, dict):
        errors.append("team must be an object")
    else:
        for field in ("id", "name", "purpose"):
            if not team.get(field):
                errors.append(f"team.{field} is required")
        if team.get("id"):
            _identifier(team.get("id"), "team.id", errors)

    raw_experts = data.get("experts")
    if not isinstance(raw_experts, list) or not raw_experts:
        errors.append("experts must be a non-empty list")
        raw_experts = []
    seen: set[str] = set()
    for index, expert in enumerate(raw_experts):
        if not isinstance(expert, dict):
            errors.append(f"experts[{index}] must be an object")
            continue
        expert_id = expert.get("id")
        if not expert_id:
            errors.append(f"experts[{index}].id is required")
        else:
            _identifier(expert_id, f"experts[{index}].id", errors)
            if expert_id in seen:
                errors.append(f"duplicate expert id: {expert_id}")
            seen.add(str(expert_id))
        if not expert.get("name"):
            errors.append(f"experts[{index}].name is required")
        profile = expert.get("profile")
        if not profile:
            errors.append(f"experts[{index}].profile is required")
        elif not ctx.profile_path(expert).is_file():
            errors.append(f"expert profile not found: {profile}")
        references = expert.get("references") or []
        if not isinstance(references, list):
            errors.append(f"experts[{index}].references must be a list")
            references = []
        for ref in references:
            if not ctx.reference_path(str(ref)).exists():
                errors.append(f"reference not found for {expert_id}: {ref}")

    _validate_contexts(ctx, data, errors)
    _validate_process(ctx, data, errors)
    _validate_human_review(data, errors)
    _validate_output(data, errors)

    workspace = data.get("workspace") or {}
    if workspace and not isinstance(workspace, dict):
        errors.append("workspace must be an object")
    elif isinstance(workspace, dict):
        for key, value in workspace.items():
            if not isinstance(value, str):
                errors.append(f"workspace.{key} must be a string path")
    return errors


def _validate_contexts(ctx: TeamContext, data: dict[str, Any], errors: list[str]) -> None:
    contexts = data.get("contexts") or []
    if contexts and not isinstance(contexts, list):
        errors.append("contexts must be a list")
        return
    ids: set[str] = set()
    for index, item in enumerate(contexts):
        if not isinstance(item, dict):
            errors.append(f"contexts[{index}] must be an object")
            continue
        context_id = item.get("id")
        if not context_id:
            errors.append(f"contexts[{index}].id is required")
        else:
            _identifier(context_id, f"contexts[{index}].id", errors)
            if context_id in ids:
                errors.append(f"duplicate context id: {context_id}")
            ids.add(str(context_id))
        if not item.get("name"):
            errors.append(f"contexts[{index}].name is required")
        raw_path = item.get("path") or item.get("file")
        if raw_path:
            path = ctx.reference_path(str(raw_path))
            if not path.exists():
                errors.append(f"context file not found: {raw_path}")
            elif not path.is_file():
                errors.append(f"context path must be a file, not a directory: {raw_path}")
        scope = str(item.get("scope") or "team")
        if scope not in CONTEXT_SCOPES:
            errors.append(f"contexts[{index}].scope must be team or agents")
        visible_to = item.get("visible_to") or []
        if visible_to and not isinstance(visible_to, list):
            errors.append(f"contexts[{index}].visible_to must be a list")
            visible_to = []
        if scope == "agents" and not visible_to:
            errors.append(f"contexts[{index}].visible_to is required when scope is agents")
        for expert_id in visible_to:
            if expert_id not in ctx.experts:
                errors.append(f"contexts[{index}].visible_to references unknown expert: {expert_id}")


def _validate_process(ctx: TeamContext, data: dict[str, Any], errors: list[str]) -> None:
    process = data.get("process")
    if not isinstance(process, dict):
        errors.append("process must be an object")
        process = {}
    if process.get("mode") not in PROCESS_MODES:
        errors.append("process.mode must be graph")
    if "main_steps" in process:
        errors.append("process.main_steps is not part of TeamKit v0.1; use process.graph.nodes")
    for field in ("lead", "coordinator"):
        value = process.get(field)
        if value and value not in ctx.experts:
            errors.append(f"process.{field} references unknown expert: {value}")

    communication = process.get("communication") or {}
    if not isinstance(communication, dict):
        errors.append("process.communication must be an object")
        communication = {}
    if communication.get("mode") and communication.get("mode") not in COMMUNICATION_MODES:
        errors.append("process.communication.mode must be manual, hybrid, or lead")
    default_response = communication.get("default_response")
    if default_response and default_response not in RESPONSE_MODES:
        errors.append("process.communication.default_response is invalid")
    for message_type in communication.get("allowed_message_types") or []:
        if message_type not in MESSAGE_TYPES:
            errors.append(f"unknown allowed message type: {message_type}")
    rules = communication.get("rules") or []
    if rules and not isinstance(rules, list):
        errors.append("process.communication.rules must be a list")
        rules = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"process.communication.rules[{index}] must be an object")
            continue
        for field in ("from", "to", "when"):
            if not rule.get(field):
                errors.append(f"process.communication.rules[{index}].{field} is required")
        for field in ("from", "to"):
            if rule.get(field) and rule[field] not in ctx.experts:
                errors.append(
                    f"process.communication.rules[{index}].{field} references unknown expert: {rule[field]}"
                )
        if rule.get("response") and rule["response"] not in RESPONSE_MODES:
            errors.append(f"process.communication.rules[{index}].response is invalid")

    graph = process.get("graph")
    if not isinstance(graph, dict):
        errors.append("process.graph must be an object")
        graph = {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        errors.append("process.graph.nodes must be a non-empty list")
        nodes = []
    if not isinstance(edges, list):
        errors.append("process.graph.edges must be a list")
        edges = []
    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"process.graph.nodes[{index}] must be an object")
            continue
        node_id = node.get("id")
        if not node_id:
            errors.append(f"process.graph.nodes[{index}].id is required")
        else:
            _identifier(node_id, f"process.graph.nodes[{index}].id", errors)
            if node_id in node_ids:
                errors.append(f"duplicate graph node id: {node_id}")
            node_ids.add(str(node_id))
        expert = node.get("expert")
        if not expert:
            errors.append(f"process.graph.nodes[{index}].expert is required")
        elif expert not in ctx.experts:
            errors.append(f"process.graph.nodes[{index}].expert references unknown expert: {expert}")
        if not node.get("task"):
            errors.append(f"process.graph.nodes[{index}].task is required")
        if "join" in node and node.get("join") != "all":
            errors.append(f"process.graph.nodes[{index}].join must be all")
    entry = graph.get("entry")
    if not entry:
        errors.append("process.graph.entry is required")
    elif entry not in node_ids:
        errors.append(f"process.graph.entry references unknown node: {entry}")
    edge_ids: set[str] = set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"process.graph.edges[{index}] must be an object")
            continue
        for field in ("from", "to"):
            if not edge.get(field):
                errors.append(f"process.graph.edges[{index}].{field} is required")
            elif edge[field] not in node_ids:
                errors.append(f"process.graph.edges[{index}].{field} references unknown node: {edge[field]}")
        if edge.get("id"):
            if edge["id"] in edge_ids:
                errors.append(f"duplicate graph edge id: {edge['id']}")
            edge_ids.add(str(edge["id"]))
        relation = edge.get("relation")
        if relation is not None and relation not in EDGE_RELATIONS:
            errors.append(f"process.graph.edges[{index}].relation must be next or parallel")
        if "max_visits" in edge:
            max_visits = edge["max_visits"]
            if not isinstance(max_visits, int) or isinstance(max_visits, bool) or max_visits < 1:
                errors.append(f"process.graph.edges[{index}].max_visits must be a positive integer")


def _validate_human_review(data: dict[str, Any], errors: list[str]) -> None:
    human_review = data.get("human_review") or {}
    if human_review and not isinstance(human_review, dict):
        errors.append("human_review must be an object")
        return
    if "conditions" in human_review:
        errors.append("human_review.conditions is not part of TeamKit v0.1; use human_review.required_when")
    for key in human_review:
        if key != "required_when":
            errors.append(f"human_review.{key} is not part of TeamKit v0.1")
    required_when = human_review.get("required_when") or []
    if required_when and not isinstance(required_when, list):
        errors.append("human_review.required_when must be a list")
    elif isinstance(required_when, list):
        for index, item in enumerate(required_when):
            if not isinstance(item, str):
                errors.append(f"human_review.required_when[{index}] must be a string")


def _validate_output(data: dict[str, Any], errors: list[str]) -> None:
    output = data.get("output")
    if not isinstance(output, dict):
        errors.append("output must be an object")
        return
    if not output.get("name"):
        errors.append("output.name is required")
    if "final_report" in output:
        errors.append("output.final_report is not part of TeamKit v0.1; use output.name, output.format, and output.sections")
    for key in output:
        if key not in {"name", "format", "sections"}:
            errors.append(f"output.{key} is not part of TeamKit v0.1")
    sections = output.get("sections") or []
    if sections and not isinstance(sections, list):
        errors.append("output.sections must be a list")
    elif isinstance(sections, list):
        for index, item in enumerate(sections):
            if not isinstance(item, str):
                errors.append(f"output.sections[{index}] must be a string")


def edge_id(edge: dict[str, Any], index: int) -> str:
    return str(edge.get("id") or f"edge_{index + 1}")


def validation_warnings(ctx: TeamContext) -> list[str]:
    warnings: list[str] = []
    workspace = ctx.team.get("workspace") or {}
    if isinstance(workspace, dict):
        for key in workspace:
            if key not in WORKSPACE_KEYS:
                warnings.append(f"workspace.{key} is unknown and will be ignored")
    process = ctx.process()
    if not process.get("coordinator") and not process.get("lead") and ctx.experts:
        warnings.append(
            f"process.coordinator is not set; {ctx.coordinator_id()} will coordinate the team"
        )

    node_map = ctx.graph_node_map()
    for node in ctx.graph_nodes():
        node_label = node.get("id", "<unknown>")
        for key in node:
            if key not in GRAPH_NODE_KEYS:
                warnings.append(f"graph node {node_label}.{key} is unknown and will be ignored")
        if "max_visits" in node:
            warnings.append(
                f"graph node {node_label} max_visits is not consumed by the execution engine (only edge-level max_visits applies)"
            )

    outgoing: dict[str, list[dict[str, Any]]] = {}
    incoming_parallel: dict[str, int] = {}
    for index, edge in enumerate(ctx.graph_edges()):
        for key in edge:
            if key not in GRAPH_EDGE_KEYS:
                warnings.append(f"graph edge {edge_id(edge, index)}.{key} is unknown and will be ignored")
        outgoing.setdefault(str(edge.get("from")), []).append(edge)
        if str(edge.get("relation") or "next") == "parallel":
            incoming_parallel[str(edge.get("to"))] = incoming_parallel.get(str(edge.get("to")), 0) + 1

    for source, edges in outgoing.items():
        relations = {str(edge.get("relation") or "next") for edge in edges}
        parallel_count = sum(1 for edge in edges if str(edge.get("relation") or "next") == "parallel")
        if relations == {"next", "parallel"}:
            warnings.append(
                f"graph node {source} mixes parallel and choice edges; the parallel branches can never fork"
            )
        elif parallel_count == 1:
            warnings.append(f"graph node {source} has a single parallel edge; a fork needs at least two")
    for target, count in incoming_parallel.items():
        node = node_map.get(target) or {}
        if count > 1 and node.get("join") != "all":
            warnings.append(f"graph node {target} receives {count} parallel edges; declare join: all")

    entry = ctx.graph_entry_node_id()
    if entry in node_map:
        reachable = {entry}
        frontier = [entry]
        while frontier:
            current = frontier.pop()
            for edge in outgoing.get(current, []):
                target = str(edge.get("to"))
                if target in node_map and target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        for node_id in node_map:
            if node_id not in reachable:
                warnings.append(f"graph node {node_id} is unreachable from entry {entry}")
    return warnings


def validate_or_raise(ctx: TeamContext, label: str = "team definition is invalid") -> None:
    errors = validate_team_definition(ctx)
    if errors:
        raise TeamKitError(label + ":\n- " + "\n- ".join(errors))
