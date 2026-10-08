"""Team definition access: experts, graph, contexts, communication policy, paths.

``TeamContext`` is a read-mostly view over ``team.yaml``. It never touches run
ledgers; run state lives in :mod:`teamkit.runs`.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from teamkit.errors import TeamKitError
from teamkit.fsutil import load_yaml

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MESSAGE_TYPES = {"request", "reply", "notify", "handoff", "question", "escalation", "result"}
RESPONSE_MODES = {"required", "optional", "none"}
COMMUNICATION_MODES = {"manual", "hybrid", "lead"}
CONTEXT_SCOPES = {"team", "agents"}
PROCESS_MODES = {"graph"}


def teamkit_home() -> Path:
    """Tool-owned home directory used for default build output."""
    return Path(os.environ.get("TEAMKIT_HOME", "~/.teamkit")).expanduser().resolve()


class TeamContext:
    def __init__(self, team_file: Path):
        self.team_file = Path(team_file).expanduser().resolve()
        self.root = self.team_file.parent
        self.team = load_yaml(self.team_file)
        raw_experts = self.team.get("experts", [])
        self.experts: dict[str, dict[str, Any]] = {
            str(expert.get("id")): expert
            for expert in (raw_experts if isinstance(raw_experts, list) else [])
            if isinstance(expert, dict) and expert.get("id")
        }

    # ------------------------------------------------------------------ identity

    @property
    def team_id(self) -> str:
        team = self.team.get("team") or {}
        return str(team.get("id") or self.root.name) if isinstance(team, dict) else self.root.name

    @property
    def team_name(self) -> str:
        team = self.team.get("team") or {}
        if isinstance(team, dict):
            return str(team.get("name") or team.get("id") or self.root.name)
        return self.root.name

    def team_meta(self) -> dict[str, Any]:
        team = self.team.get("team") or {}
        return team if isinstance(team, dict) else {}

    def expert_name(self, expert_id: str) -> str:
        return str((self.experts.get(expert_id) or {}).get("name") or expert_id)

    def require_expert(self, expert_id: str) -> None:
        if expert_id not in self.experts:
            raise TeamKitError(f"unknown expert: {expert_id}")

    # ------------------------------------------------------------------ process

    def process(self) -> dict[str, Any]:
        process = self.team.get("process") or {}
        return process if isinstance(process, dict) else {}

    def coordinator_id(self) -> str:
        """The expert who owns orchestration (becomes the host lead agent)."""
        process = self.process()
        for key in ("coordinator", "lead"):
            value = str(process.get(key) or "")
            if value in self.experts:
                return value
        entry = self.graph_node_map().get(self.graph_entry_node_id())
        if entry and str(entry.get("expert")) in self.experts:
            return str(entry["expert"])
        return next(iter(self.experts), "")

    def communication(self) -> dict[str, Any]:
        communication = self.process().get("communication") or {}
        return communication if isinstance(communication, dict) else {}

    def communication_mode(self) -> str:
        mode = str(self.communication().get("mode") or "hybrid").strip().lower()
        return mode if mode in COMMUNICATION_MODES else "hybrid"

    def graph(self) -> dict[str, Any]:
        graph = self.process().get("graph") or {}
        return graph if isinstance(graph, dict) else {}

    def graph_nodes(self) -> list[dict[str, Any]]:
        nodes = self.graph().get("nodes") or []
        return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []

    def graph_edges(self) -> list[dict[str, Any]]:
        edges = self.graph().get("edges") or []
        return [edge for edge in edges if isinstance(edge, dict)] if isinstance(edges, list) else []

    def graph_node_map(self) -> dict[str, dict[str, Any]]:
        return {str(node.get("id")): node for node in self.graph_nodes() if node.get("id")}

    def graph_entry_node_id(self) -> str:
        graph = self.graph()
        if graph.get("entry"):
            return str(graph["entry"])
        nodes = self.graph_nodes()
        return str(nodes[0].get("id")) if nodes else ""

    def require_graph_node(self, node_id: str) -> dict[str, Any]:
        node = self.graph_node_map().get(node_id)
        if not node:
            raise TeamKitError(f"unknown graph node: {node_id}")
        return node

    def nodes_for_expert(self, expert_id: str) -> list[str]:
        return [str(node["id"]) for node in self.graph_nodes() if node.get("id") and node.get("expert") == expert_id]

    # ------------------------------------------------------------------ contexts

    def declared_contexts(self) -> list[dict[str, Any]]:
        contexts = self.team.get("contexts") or []
        return [item for item in contexts if isinstance(item, dict)] if isinstance(contexts, list) else []

    def declared_context_for(self, value: str) -> dict[str, Any] | None:
        for item in self.declared_contexts():
            if value and value in {str(item.get("id") or ""), str(item.get("name") or "")}:
                return item
        return None

    def contexts_visible_to(self, expert_id: str) -> list[dict[str, Any]]:
        visible = []
        for item in self.declared_contexts():
            scope = str(item.get("scope") or "team")
            if scope == "team" or expert_id in [str(v) for v in item.get("visible_to") or []]:
                visible.append(item)
        return visible

    def profile_path(self, expert: dict[str, Any]) -> Path:
        return self.root / str(expert.get("profile", ""))

    def reference_path(self, value: str) -> Path:
        return self.root / value

    # ------------------------------------------------------------------ communication policy

    def communication_rule(self, sender: str, recipient: str) -> dict[str, Any] | None:
        for rule in self.communication().get("rules") or []:
            if isinstance(rule, dict) and str(rule.get("from")) == sender and str(rule.get("to")) == recipient:
                return rule
        return None

    def graph_adjacent(self, sender: str, recipient: str) -> bool:
        node_map = self.graph_node_map()
        for edge in self.graph_edges():
            source = node_map.get(str(edge.get("from")))
            target = node_map.get(str(edge.get("to")))
            if source and target and source.get("expert") == sender and target.get("expert") == recipient:
                return True
        return False

    def communication_allowed(self, sender: str, recipient: str, open_fallback: bool = True) -> bool:
        """Who may message whom.

        * The coordinator channel (coordinator <-> any member) is always open:
          hub platforms such as WorkBuddy require dispatch and report-back.
        * Explicit ``communication.rules`` always grant a route.
        * ``lead`` mode allows nothing else (strict hub-and-spoke).
        * ``hybrid`` (default) also allows graph-adjacent experts; with no
          rules and ``allow_expert_requests`` (default true) every pair is open,
          which preserves v0.3 behavior for teams that never declared rules.
          Hub platforms pass ``open_fallback=False`` to drop that open default.
        * ``manual`` allows only the coordinator channel and explicit rules.
        """
        if not sender or not recipient or sender == recipient:
            return False
        coordinator = self.coordinator_id()
        if coordinator and coordinator in {sender, recipient}:
            return True
        if self.communication_rule(sender, recipient) is not None:
            return True
        mode = self.communication_mode()
        if mode in {"lead", "manual"}:
            return False
        if self.graph_adjacent(sender, recipient):
            return True
        if not open_fallback:
            return False
        has_rules = bool(self.communication().get("rules"))
        return not has_rules and bool(self.communication().get("allow_expert_requests", True))

    def allowed_peers(self, expert_id: str, open_fallback: bool = True) -> list[str]:
        return [
            other
            for other in self.experts
            if other != expert_id and self.communication_allowed(expert_id, other, open_fallback)
        ]

    def response_mode_for(self, sender: str, recipient: str) -> str:
        rule = self.communication_rule(sender, recipient)
        if rule and rule.get("response") in RESPONSE_MODES:
            return str(rule["response"])
        response = str(self.communication().get("default_response") or "optional")
        return response if response in RESPONSE_MODES else "optional"

    def message_type_allowed(self, message_type: str) -> bool:
        allowed = self.communication().get("allowed_message_types")
        if not allowed:
            return message_type in MESSAGE_TYPES
        return message_type in {str(item) for item in allowed} | {"reply"}

    # ------------------------------------------------------------------ run locations

    def run_base(self, run_id: str) -> Path:
        """The single directory that holds every artifact of one run."""
        workspace = self.team.get("workspace") or {}
        explicit = workspace.get("run_root") if isinstance(workspace, dict) else None
        if explicit:
            path = Path(str(explicit).replace("{run_id}", run_id))
            return (path if path.is_absolute() else self.root / path).resolve()
        injected = os.environ.get("TEAMKIT_RUNS_DIR", "").strip()
        if injected:
            return (Path(injected).expanduser() / run_id).resolve()
        return (self.root / "runs" / run_id).resolve()

    def run_base_source(self) -> str:
        workspace = self.team.get("workspace") or {}
        if isinstance(workspace, dict) and workspace.get("run_root"):
            return "workspace.run_root"
        if os.environ.get("TEAMKIT_RUNS_DIR", "").strip():
            return "TEAMKIT_RUNS_DIR"
        return "default"

    def team_base(self) -> Path:
        return self.run_base("_probe").parent

    def workspace_path(self, key: str, run_id: str, default_relative: str) -> Path:
        """Resolve a run file, honoring advanced ``workspace.<key>`` overrides."""
        workspace = self.team.get("workspace") or {}
        explicit = workspace.get(key) if isinstance(workspace, dict) else None
        if explicit:
            path = Path(str(explicit).replace("{run_id}", run_id))
            return (path if path.is_absolute() else self.root / path).resolve()
        return (self.run_base(run_id) / default_relative).resolve()


def kebab_case(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    text = re.sub(r"-+", "-", text)
    if not text or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", text):
        return fallback
    return text
