from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from teamkit import __version__
except ModuleNotFoundError:  # direct `python teamkit/cli.py` source-mode entrypoint
    _version_text = (Path(__file__).with_name("__init__.py")).read_text(encoding="utf-8")
    _version_match = re.search(r'__version__\s*=\s*["\']([^"\']+)', _version_text)
    __version__ = _version_match.group(1) if _version_match else "0.1.0"

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit("PyYAML is required to run teamkit") from exc


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
MESSAGE_TYPES = {"request", "reply", "notify", "handoff", "question", "escalation", "result"}
RESPONSE_MODES = {"required", "optional", "none"}
PROCESS_MODES = {"graph"}
TOPIC_STATUSES = {"active", "waiting", "resolved", "archived"}
CONTEXT_SCOPES = {"team", "agents"}
DEFAULT_WORKBUDDY_APP = Path("/Applications/WorkBuddy.app")


class TeamKitError(Exception):
    pass


def teamkit_home() -> Path:
    """Return the tool-owned home directory used for default build output."""
    return Path(os.environ.get("TEAMKIT_HOME", "~/.teamkit")).expanduser().resolve()


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TeamKitError(f"file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TeamKitError(f"expected YAML object: {path}")
    return data


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def atomic_copyfile(source: Path, target: Path) -> None:
    if not source.exists() or not source.is_file():
        raise TeamKitError(f"source file not found: {source}")
    atomic_write_bytes(target, source.read_bytes())


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(
        path,
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TeamKitError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(record, dict):
                raise TeamKitError(f"expected JSON object at {path}:{line_number}")
            records.append(record)
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    atomic_write_text(path, text)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def text_from_option(value: str | None, file_value: str | None, label: str) -> str:
    if file_value:
        if file_value == "-":
            return sys.stdin.read().strip()
        path = Path(file_value)
        if not path.exists():
            raise TeamKitError(f"{label} file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    if value:
        return value.strip()
    raise TeamKitError(f"{label} is required")


def optional_text_from_option(value: str | None, file_value: str | None) -> str:
    if file_value:
        if file_value == "-":
            return sys.stdin.read().strip()
        path = Path(file_value)
        if not path.exists():
            raise TeamKitError(f"text file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    return (value or "").strip()


def display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


class TeamContext:
    def __init__(self, team_file: Path):
        self.team_file = team_file.expanduser().resolve()
        self.root = self.team_file.parent
        self.team = load_yaml(self.team_file)
        raw_experts = self.team.get("experts", [])
        self.experts = {
            str(expert.get("id")): expert
            for expert in raw_experts
            if isinstance(expert, dict) and expert.get("id")
        }

    def process(self) -> dict[str, Any]:
        return self.team.get("process", {}) or {}

    def communication(self) -> dict[str, Any]:
        return self.process().get("communication", {}) or {}

    def communication_mode(self) -> str:
        mode = str(self.communication().get("mode") or "hybrid").strip().lower()
        return mode if mode in {"manual", "hybrid", "lead"} else "hybrid"

    def graph(self) -> dict[str, Any]:
        graph = self.process().get("graph", {}) or {}
        return graph if isinstance(graph, dict) else {}

    def graph_nodes(self) -> list[dict[str, Any]]:
        nodes = self.graph().get("nodes", []) or []
        return [node for node in nodes if isinstance(node, dict)]

    def graph_edges(self) -> list[dict[str, Any]]:
        edges = self.graph().get("edges", []) or []
        return [edge for edge in edges if isinstance(edge, dict)]

    def graph_node_map(self) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("id")): node
            for node in self.graph_nodes()
            if node.get("id")
        }

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

    def require_expert(self, expert_id: str) -> None:
        if expert_id not in self.experts:
            raise TeamKitError(f"unknown expert: {expert_id}")

    def profile_path(self, expert: dict[str, Any]) -> Path:
        return self.root / str(expert.get("profile", ""))

    def reference_path(self, value: str) -> Path:
        return self.root / value

    def run_base(self, run_id: str) -> Path:
        """Resolve the one run directory used by every default run artifact."""
        workspace = self.team.get("workspace", {}) or {}
        explicit = workspace.get("run_root") if isinstance(workspace, dict) else None
        if explicit:
            value = str(explicit).replace("{run_id}", run_id)
            path = Path(value)
            if not path.is_absolute():
                path = self.root / path
            return path.resolve()
        injected = os.environ.get("TEAMKIT_RUNS_DIR", "").strip()
        if injected:
            return (Path(injected).expanduser() / run_id).resolve()
        return (self.root / "runs" / run_id).resolve()

    def run_base_source(self) -> str:
        workspace = self.team.get("workspace", {}) or {}
        if isinstance(workspace, dict) and workspace.get("run_root"):
            return "workspace.run_root"
        if os.environ.get("TEAMKIT_RUNS_DIR", "").strip():
            return "TEAMKIT_RUNS_DIR"
        return "default"

    def team_base(self, run_id: str = "_probe") -> Path:
        return self.run_base(run_id).parent

    def path_for(self, key: str, run_id: str, default: str) -> Path:
        workspace = self.team.get("workspace", {}) or {}
        explicit = workspace.get(key) if isinstance(workspace, dict) else None
        if explicit:
            value = str(explicit).replace("{run_id}", run_id)
            path = Path(value)
            if not path.is_absolute():
                path = self.root / path
            return path.resolve()
        marker = f"runs/{run_id}"
        if default.startswith(marker):
            suffix = default[len(marker):].lstrip("/")
            base = self.run_base(run_id)
            return (base / suffix).resolve() if suffix else base
        value = default.replace("{run_id}", run_id)
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        return path.resolve()

    def run_root(self, run_id: str) -> Path:
        return self.run_base(run_id)

    def run_lock_path(self, run_id: str) -> Path:
        return self.run_base(run_id) / ".teamkit.lock"

    def state_path(self, run_id: str) -> Path:
        return self.path_for("state", run_id, f"runs/{run_id}/state.yaml")

    def topic_path(self, run_id: str) -> Path:
        return self.path_for("topic", run_id, f"runs/{run_id}/topic.yaml")

    def messages_path(self, run_id: str) -> Path:
        return self.path_for("message_log", run_id, f"runs/{run_id}/messages.jsonl")

    def events_path(self, run_id: str) -> Path:
        return self.path_for("event_log", run_id, f"runs/{run_id}/events.jsonl")

    def context_items_path(self, run_id: str) -> Path:
        return self.path_for(
            "context_items_log", run_id, f"runs/{run_id}/context-items.jsonl"
        )

    def context_item_dir(self, run_id: str) -> Path:
        return self.path_for("context_item_dir", run_id, f"runs/{run_id}/contexts")

    def human_review_path(self, run_id: str) -> Path:
        return self.path_for(
            "human_review_log", run_id, f"runs/{run_id}/human-review.jsonl"
        )

    def decision_log_path(self, run_id: str) -> Path:
        return self.path_for("decision_log", run_id, f"runs/{run_id}/decision-log.md")

    def expert_workspace_dir(self, run_id: str) -> Path:
        return self.path_for("expert_workspace_dir", run_id, f"runs/{run_id}/experts")

    def expert_result_dir(self, run_id: str) -> Path:
        return self.path_for(
            "expert_result_dir", run_id, f"runs/{run_id}/artifacts/expert-results"
        )

    def artifact_index_path(self, run_id: str) -> Path:
        return self.run_base(run_id) / "artifacts" / "artifacts.jsonl"

    def declared_contexts(self) -> list[dict[str, Any]]:
        contexts = self.team.get("contexts") or []
        return [item for item in contexts if isinstance(item, dict)]

    def declared_context_for(self, value: str) -> dict[str, Any] | None:
        for item in self.declared_contexts():
            if value in {str(item.get("id") or ""), str(item.get("name") or "")}:
                return item
        return None

    def communication_rule(self, sender: str, recipient: str) -> dict[str, Any] | None:
        rules = self.communication().get("rules") or []
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if str(rule.get("from")) == sender and str(rule.get("to")) == recipient:
                return rule
        return None

    def communication_allowed(self, sender: str, recipient: str) -> bool:
        rules = self.communication().get("rules") or []
        mode = self.communication_mode()
        if mode != "manual" and self.graph_communication_allowed(sender, recipient):
            return True
        if rules:
            if self.communication_rule(sender, recipient) is not None:
                return True
            if mode == "manual":
                return self.is_lead_member_pair(sender, recipient)
            return False
        if mode == "manual":
            lead = str(self.process().get("lead") or self.process().get("coordinator") or "")
            return bool(self.communication().get("allow_expert_requests", False)) and recipient == lead and sender != lead
        return bool(self.communication().get("allow_expert_requests", True))

    def is_lead_member_pair(self, sender: str, recipient: str) -> bool:
        lead = str(self.process().get("lead") or self.process().get("coordinator") or "")
        if not lead or sender == recipient or lead not in {sender, recipient}:
            return False
        if sender == lead:
            return True
        return bool(self.communication().get("allow_expert_requests", False))

    def graph_communication_allowed(self, sender: str, recipient: str) -> bool:
        node_map = self.graph_node_map()
        for edge in self.graph_edges():
            from_node = node_map.get(str(edge.get("from")))
            to_node = node_map.get(str(edge.get("to")))
            if not from_node or not to_node:
                continue
            if from_node.get("expert") == sender and to_node.get("expert") == recipient:
                return True
        return False

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
        return message_type in {str(item) for item in allowed}


@contextmanager
def run_lock(ctx: TeamContext, run_id: str):
    path = ctx.run_lock_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def batch_lock(batch_dir: Path):
    batch_dir.mkdir(parents=True, exist_ok=True)
    lock_path = batch_dir / ".batch.lock"
    with lock_path.open("a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def locked_run_command(func: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    @wraps(func)
    def wrapper(args: argparse.Namespace) -> int:
        ctx = TeamContext(Path(args.team))
        with run_lock(ctx, args.run):
            return func(args)

    return wrapper


def event(event_type: str, run_id: str, actor: str = "", **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "evt_" + uuid.uuid4().hex[:16],
        "type": event_type,
        "runId": run_id,
        "createdAt": now(),
    }
    if actor:
        data["actor"] = actor
    data.update({k: v for k, v in extra.items() if v is not None})
    return data


def prefixed_id(prefix: str) -> str:
    return prefix + "_" + uuid.uuid4().hex[:16]


def message_id() -> str:
    return prefixed_id("msg")


def artifact_id_for(data: bytes) -> str:
    return "art_" + hashlib.sha256(data).hexdigest()[:24]


def context_id_for(data: bytes, seed: str = "") -> str:
    digest = hashlib.sha256(seed.encode("utf-8") + b"\0" + data).hexdigest()
    return "ctx_" + digest[:24]


def resolve_input_file(ctx: TeamContext, raw_path: str, run_id: str | None = None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    candidates = []
    if run_id:
        candidates.append(ctx.run_root(run_id) / path)
    candidates.extend([ctx.root / path, Path.cwd() / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def normalize_visible_to(ctx: TeamContext, scope: str, visible_to: list[str]) -> list[str]:
    if scope == "team":
        return []
    normalized: list[str] = []
    for expert_id in visible_to:
        ctx.require_expert(expert_id)
        if expert_id not in normalized:
            normalized.append(expert_id)
    if not normalized:
        raise TeamKitError("visible_to is required when context scope is agents")
    return normalized


def declared_contexts_for_update(ctx: TeamContext) -> list[dict[str, Any]]:
    contexts = ctx.team.setdefault("contexts", [])
    if not isinstance(contexts, list):
        raise TeamKitError("contexts must be a list")
    return contexts


def declared_context_index(contexts: list[dict[str, Any]], context_id: str) -> int:
    for index, item in enumerate(contexts):
        if isinstance(item, dict) and str(item.get("id") or "") == context_id:
            return index
    return -1


def relative_team_file_path(ctx: TeamContext, source: Path, context_id: str, force: bool = False) -> str:
    if not source.exists() or not source.is_file():
        raise TeamKitError(f"context source file not found: {source}")
    try:
        return str(source.resolve().relative_to(ctx.root))
    except ValueError:
        suffix = source.suffix
        target = ctx.root / "references" / f"{context_id}{suffix}"
        if target.exists() and not force and target.read_bytes() != source.read_bytes():
            raise TeamKitError(f"context target already exists: {display_path(ctx.root, target)}; use --force to overwrite")
        atomic_copyfile(source, target)
        return display_path(ctx.root, target)


def team_context_view(ctx: TeamContext, item: dict[str, Any]) -> dict[str, Any]:
    raw_path = item.get("path") or item.get("file") or ""
    return {
        "id": item.get("id", ""),
        "name": item.get("name", ""),
        "path": raw_path,
        "source": item.get("source", "file" if raw_path else ""),
        "scope": item.get("scope", "team"),
        "visibleTo": item.get("visible_to", []) or [],
        "summary": item.get("summary", ""),
    }


def validate_updated_team(ctx: TeamContext) -> None:
    errors = validate_team_definition(ctx)
    if errors:
        raise TeamKitError("team definition update is invalid:\n- " + "\n- ".join(errors))


def topic_context_ref_exists(topic: dict[str, Any], context_id: str) -> bool:
    refs = topic.get("context_refs")
    return isinstance(refs, list) and any(
        isinstance(item, dict) and item.get("id") == context_id for item in refs
    )


def add_context_ref_to_topic(
    ctx: TeamContext,
    run_id: str,
    record: dict[str, Any],
    actor: str = "",
) -> None:
    topic_path = ctx.topic_path(run_id)
    if not topic_path.exists():
        return
    topic = load_yaml(topic_path)
    refs = topic.setdefault("context_refs", [])
    if not isinstance(refs, list):
        refs = []
        topic["context_refs"] = refs
    if not topic_context_ref_exists(topic, str(record["id"])):
        refs.append(
            {
                "id": record["id"],
                "name": record["name"],
                "scope": record["scope"],
                "visibleTo": record["visibleTo"],
                "linkedBy": actor,
                "createdAt": now(),
            }
        )
        topic["version"] = int(topic.get("version") or 1) + 1
        save_topic(ctx, run_id, topic)


def add_state_context_item(ctx: TeamContext, run_id: str, record: dict[str, Any]) -> None:
    add_unique_state_item(
        ctx,
        run_id,
        "context_items",
        {
            "id": record["id"],
            "name": record["name"],
            "scope": record["scope"],
            "visibleTo": record["visibleTo"],
            "path": record["path"],
        },
    )


def managed_context_record(
    ctx: TeamContext,
    run_id: str,
    source: Path,
    *,
    context_id: str = "",
    name: str = "",
    source_type: str = "file",
    scope: str = "team",
    visible_to: list[str] | None = None,
    owner: str = "",
    summary: str = "",
) -> dict[str, Any]:
    if not source.exists() or not source.is_file():
        raise TeamKitError(f"context file not found: {source}")
    return managed_context_bytes_record(
        ctx,
        run_id,
        source.read_bytes(),
        context_id=context_id,
        name=name or source.name,
        source_type=source_type,
        source_path=source,
        suffix=source.suffix,
        scope=scope,
        visible_to=visible_to,
        owner=owner,
        summary=summary,
    )


def managed_context_bytes_record(
    ctx: TeamContext,
    run_id: str,
    data: bytes,
    *,
    context_id: str = "",
    name: str = "",
    source_type: str = "file",
    source_path: Path | None = None,
    suffix: str = "",
    scope: str = "team",
    visible_to: list[str] | None = None,
    owner: str = "",
    summary: str = "",
) -> dict[str, Any]:
    if scope not in CONTEXT_SCOPES:
        raise TeamKitError(f"context scope must be one of: {', '.join(sorted(CONTEXT_SCOPES))}")
    visible = normalize_visible_to(ctx, scope, visible_to or [])
    final_name = name or (source_path.name if source_path else "context-item")
    final_id = context_id or context_id_for(data, final_name)
    if not ID_PATTERN.match(final_id):
        raise TeamKitError(f"context id must match {ID_PATTERN.pattern}")
    existing_records = read_jsonl(ctx.context_items_path(run_id))
    existing = next((item for item in existing_records if item.get("id") == final_id), None)
    if existing:
        return existing
    target_dir = ctx.context_item_dir(run_id) / final_id
    target_dir.mkdir(parents=True, exist_ok=True)
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    content_path = target_dir / f"content{suffix}"
    if not content_path.exists():
        atomic_write_bytes(content_path, data)
    checksum = hashlib.sha256(data).hexdigest()
    record = {
        "id": final_id,
        "runId": run_id,
        "name": final_name,
        "sourceType": source_type,
        "sourcePath": display_path(ctx.root, source_path) if source_path else "",
        "path": display_path(ctx.root, content_path),
        "scope": scope,
        "visibleTo": visible,
        "owner": owner,
        "summary": summary,
        "sha256": checksum,
        "size": len(data),
        "createdAt": now(),
    }
    manifest = dict(record)
    manifest["manifestVersion"] = "teamkit.context_item.v0.1"
    manifest_path = target_dir / "manifest.json"
    write_json(manifest_path, manifest)
    record["manifestPath"] = display_path(ctx.root, manifest_path)
    existing_records.append(record)
    write_jsonl(ctx.context_items_path(run_id), existing_records)
    return record


def materialize_declared_contexts(ctx: TeamContext, run_id: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in ctx.declared_contexts():
        raw_path = item.get("path") or item.get("file")
        if not raw_path:
            continue
        scope = str(item.get("scope") or "team")
        visible_to = [str(value) for value in item.get("visible_to", []) or []]
        source = resolve_input_file(ctx, str(raw_path))
        record = managed_context_record(
            ctx,
            run_id,
            source,
            context_id=str(item.get("id") or ""),
            name=str(item.get("name") or source.name),
            source_type=str(item.get("source") or "file"),
            scope=scope,
            visible_to=visible_to,
            owner=str(item.get("owner") or "team"),
            summary=str(item.get("summary") or ""),
        )
        records.append(record)
    return records


def initial_topic_record(ctx: TeamContext, run_id: str) -> dict[str, Any]:
    team = ctx.team.get("team", {}) or {}
    coordinator = (
        ctx.process().get("coordinator")
        or ctx.process().get("lead")
        or ctx.process().get("entry")
        or ""
    )
    current_node = ctx.graph_entry_node_id()
    visits: dict[str, int] = {}
    if current_node:
        visits[current_node] = 1
    return {
        "id": run_id,
        "run_id": run_id,
        "title": team.get("name") or team.get("id") or run_id,
        "responsible": coordinator,
        "participants": list(ctx.experts.keys()),
        "status": "active",
        "summary": "",
        "current_node": current_node,
        "active_nodes": ([{"node": current_node, "status": "active", "waiting_on": []}] if current_node else []),
        "waiting_on": None,
        "context_refs": [],
        "evidence": [],
        "visits": visits,
        "version": 1,
        "createdAt": now(),
        "updatedAt": now(),
    }


def load_state(ctx: TeamContext, run_id: str) -> dict[str, Any]:
    path = ctx.state_path(run_id)
    if not path.exists():
        raise TeamKitError(f"run not initialized: {run_id}")
    return load_yaml(path)


def load_topic(ctx: TeamContext, run_id: str) -> dict[str, Any]:
    path = ctx.topic_path(run_id)
    if not path.exists():
        raise TeamKitError(f"topic not initialized for run: {run_id}")
    return load_yaml(path)


def save_topic(ctx: TeamContext, run_id: str, topic: dict[str, Any]) -> None:
    topic["updatedAt"] = now()
    write_yaml(ctx.topic_path(run_id), topic)


def save_state(ctx: TeamContext, run_id: str, state: dict[str, Any]) -> None:
    state["updatedAt"] = now()
    write_yaml(ctx.state_path(run_id), state)


def add_unique_state_item(
    ctx: TeamContext,
    run_id: str,
    key: str,
    item: dict[str, Any],
    id_key: str = "id",
) -> None:
    state = load_state(ctx, run_id)
    values = state.setdefault(key, [])
    if not isinstance(values, list):
        values = []
        state[key] = values
    if not any(existing.get(id_key) == item.get(id_key) for existing in values):
        values.append(item)
    save_state(ctx, run_id, state)


def add_state_value(ctx: TeamContext, run_id: str, key: str, value: str) -> None:
    state = load_state(ctx, run_id)
    values = state.setdefault(key, [])
    if not isinstance(values, list):
        values = []
        state[key] = values
    if value not in values:
        values.append(value)
    save_state(ctx, run_id, state)


def remove_state_value(ctx: TeamContext, run_id: str, key: str, value: str) -> None:
    state = load_state(ctx, run_id)
    values = state.get(key)
    if isinstance(values, list) and value in values:
        state[key] = [item for item in values if item != value]
        save_state(ctx, run_id, state)


def validate_identifier(value: Any, field: str, errors: list[str]) -> None:
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
            validate_identifier(team.get("id"), "team.id", errors)

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
            validate_identifier(expert_id, f"experts[{index}].id", errors)
            if expert_id in seen:
                errors.append(f"duplicate expert id: {expert_id}")
            seen.add(str(expert_id))
        if not expert.get("name"):
            errors.append(f"experts[{index}].name is required")
        profile = expert.get("profile")
        if not profile:
            errors.append(f"experts[{index}].profile is required")
        elif not ctx.profile_path(expert).exists():
            errors.append(f"expert profile not found: {profile}")
        for ref in expert.get("references", []) or []:
            if not ctx.reference_path(str(ref)).exists():
                errors.append(f"reference not found for {expert_id}: {ref}")

    contexts = data.get("contexts") or []
    if contexts and not isinstance(contexts, list):
        errors.append("contexts must be a list")
        contexts = []
    context_ids: set[str] = set()
    for index, item in enumerate(contexts):
        if not isinstance(item, dict):
            errors.append(f"contexts[{index}] must be an object")
            continue
        context_id = item.get("id")
        if not context_id:
            errors.append(f"contexts[{index}].id is required")
        else:
            validate_identifier(context_id, f"contexts[{index}].id", errors)
            if context_id in context_ids:
                errors.append(f"duplicate context id: {context_id}")
            context_ids.add(str(context_id))
        if not item.get("name"):
            errors.append(f"contexts[{index}].name is required")
        raw_path = item.get("path") or item.get("file")
        if raw_path:
            context_path = ctx.reference_path(str(raw_path))
            if not context_path.exists():
                errors.append(f"context file not found: {raw_path}")
            elif not context_path.is_file():
                errors.append(f"context path must be a file, not a directory: {raw_path}")
        scope = str(item.get("scope") or "team")
        if scope not in CONTEXT_SCOPES:
            errors.append(f"contexts[{index}].scope must be team or agents")
        visible_to = item.get("visible_to", []) or []
        if scope == "agents" and not visible_to:
            errors.append(f"contexts[{index}].visible_to is required when scope is agents")
        if visible_to and not isinstance(visible_to, list):
            errors.append(f"contexts[{index}].visible_to must be a list")
            visible_to = []
        for expert_id in visible_to:
            if expert_id not in ctx.experts:
                errors.append(
                    f"contexts[{index}].visible_to references unknown expert: {expert_id}"
                )

    process = data.get("process")
    if not isinstance(process, dict):
        errors.append("process must be an object")
        process = {}
    mode = process.get("mode")
    if mode not in PROCESS_MODES:
        errors.append("process.mode must be graph")
    if "main_steps" in process:
        errors.append("process.main_steps is not part of TeamKit v0.1; use process.graph.nodes")
    for field in ("lead", "coordinator"):
        value = process.get(field)
        if value and value not in ctx.experts:
            errors.append(f"process.{field} references unknown expert: {value}")

    communication = process.get("communication", {}) or {}
    if not isinstance(communication, dict):
        errors.append("process.communication must be an object")
        communication = {}
    if communication.get("mode") and communication.get("mode") not in {"manual", "hybrid", "lead"}:
        errors.append("process.communication.mode must be manual, hybrid, or lead")
    default_response = communication.get("default_response")
    if default_response and default_response not in RESPONSE_MODES:
        errors.append("process.communication.default_response is invalid")
    allowed_types = communication.get("allowed_message_types") or []
    for message_type in allowed_types:
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
    nodes = graph.get("nodes", []) or []
    edges = graph.get("edges", []) or []
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
            validate_identifier(node_id, f"process.graph.nodes[{index}].id", errors)
            if node_id in node_ids:
                errors.append(f"duplicate graph node id: {node_id}")
            node_ids.add(str(node_id))
        expert = node.get("expert")
        if not expert:
            errors.append(f"process.graph.nodes[{index}].expert is required")
        elif expert not in ctx.experts:
            errors.append(
                f"process.graph.nodes[{index}].expert references unknown expert: {expert}"
            )
        if not node.get("task"):
            errors.append(f"process.graph.nodes[{index}].task is required")
    entry = graph.get("entry")
    if not entry:
        errors.append("process.graph.entry is required")
    elif entry not in node_ids:
        errors.append(f"process.graph.entry references unknown node: {entry}")
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"process.graph.edges[{index}] must be an object")
            continue
        for field in ("from", "to"):
            if not edge.get(field):
                errors.append(f"process.graph.edges[{index}].{field} is required")
            elif edge[field] not in node_ids:
                errors.append(
                    f"process.graph.edges[{index}].{field} references unknown node: {edge[field]}"
                )
        if "max_visits" in edge:
            max_visits = edge["max_visits"]
            if not isinstance(max_visits, int) or max_visits < 1:
                errors.append(f"process.graph.edges[{index}].max_visits must be a positive integer")

    human_review = data.get("human_review", {}) or {}
    if human_review and not isinstance(human_review, dict):
        errors.append("human_review must be an object")
        human_review = {}
    if isinstance(human_review, dict):
        if "conditions" in human_review:
            errors.append("human_review.conditions is not part of TeamKit v0.1; use human_review.required_when")
        allowed_human_review_keys = {"required_when"}
        for key in human_review:
            if key not in allowed_human_review_keys:
                errors.append(f"human_review.{key} is not part of TeamKit v0.1")
        required_when = human_review.get("required_when") or []
        if required_when and not isinstance(required_when, list):
            errors.append("human_review.required_when must be a list")
        elif isinstance(required_when, list):
            for index, item in enumerate(required_when):
                if not isinstance(item, str):
                    errors.append(f"human_review.required_when[{index}] must be a string")

    output = data.get("output")
    if not isinstance(output, dict):
        errors.append("output must be an object")
    elif not output.get("name"):
        errors.append("output.name is required")
    elif isinstance(output, dict):
        allowed_output_keys = {"name", "format", "sections"}
        if "final_report" in output:
            errors.append("output.final_report is not part of TeamKit v0.1; use output.name, output.format, and output.sections")
        for key in output:
            if key not in allowed_output_keys:
                errors.append(f"output.{key} is not part of TeamKit v0.1")
        sections = output.get("sections") or []
        if sections and not isinstance(sections, list):
            errors.append("output.sections must be a list")
        elif isinstance(sections, list):
            for index, item in enumerate(sections):
                if not isinstance(item, str):
                    errors.append(f"output.sections[{index}] must be a string")

    workspace = data.get("workspace", {}) or {}
    if workspace and not isinstance(workspace, dict):
        errors.append("workspace must be an object")
    elif isinstance(workspace, dict):
        for key, value in workspace.items():
            if not isinstance(value, str):
                errors.append(f"workspace.{key} must be a string path")
    return errors


def validate_or_raise(ctx: TeamContext) -> None:
    errors = validate_team_definition(ctx)
    if errors:
        raise TeamKitError("team definition is invalid:\n- " + "\n- ".join(errors))


WORKSPACE_KEYS = {
    "run_root", "message_log", "event_log", "context_items_log",
    "context_item_dir", "human_review_log", "decision_log", "state", "topic",
    "expert_workspace_dir", "expert_result_dir",
}
GRAPH_NODE_KEYS = {"id", "expert", "task", "join"}
GRAPH_EDGE_KEYS = {"id", "from", "to", "when", "relation", "max_visits"}


def validation_warnings(ctx: TeamContext) -> list[str]:
    warnings: list[str] = []
    workspace = ctx.team.get("workspace", {}) or {}
    if isinstance(workspace, dict):
        for key in workspace:
            if key not in WORKSPACE_KEYS:
                warnings.append(f"workspace.{key} is unknown and will be ignored")
    for node in ctx.graph_nodes():
        for key in node:
            if key not in GRAPH_NODE_KEYS:
                warnings.append(f"graph node {node.get('id', '<unknown>')}.{key} is unknown and will be ignored")
        if "max_visits" in node:
            warnings.append(f"graph node {node.get('id', '<unknown>')} max_visits is not consumed by the execution engine (only edge-level max_visits applies)")
    for index, edge in enumerate(ctx.graph_edges()):
        for key in edge:
            if key not in GRAPH_EDGE_KEYS:
                warnings.append(f"graph edge {edge_id(edge, index)}.{key} is unknown and will be ignored")
    return warnings


def build_execution_plan(ctx: TeamContext) -> dict[str, Any]:
    validate_or_raise(ctx)
    experts: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    for item in ctx.declared_contexts():
        raw_path = item.get("path") or item.get("file") or ""
        path = ctx.reference_path(str(raw_path)) if raw_path else None
        contexts.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "path": display_path(ctx.root, path) if path else "",
                "scope": item.get("scope", "team"),
                "visibleTo": item.get("visible_to", []) or [],
                "source": item.get("source", "file"),
                "summary": item.get("summary", ""),
            }
        )
    for expert in ctx.experts.values():
        profile_path = ctx.profile_path(expert)
        experts.append(
            {
                "id": expert["id"],
                "name": expert["name"],
                "profilePath": display_path(ctx.root, profile_path),
                "profile": profile_path.read_text(encoding="utf-8"),
                "references": [
                    {
                        "path": display_path(ctx.root, ctx.reference_path(str(ref))),
                        "exists": ctx.reference_path(str(ref)).exists(),
                    }
                    for ref in expert.get("references", []) or []
                ],
            }
        )
    return {
        "schemaVersion": "teamkit.execution_plan.v0.1",
        "generatedAt": now(),
        "team": ctx.team.get("team", {}),
        "process": {
            "mode": ctx.process().get("mode"),
            "lead": ctx.process().get("lead", ""),
            "coordinator": ctx.process().get("coordinator", ""),
            "communication": ctx.communication(),
            "graph": ctx.graph(),
        },
        "experts": experts,
        "contexts": contexts,
        "materials": ctx.team.get("materials", {}) or {},
        "humanReview": ctx.team.get("human_review", {}) or {},
        "workspace": ctx.team.get("workspace", {}) or {},
        "output": ctx.team.get("output", {}) or {},
        "commandContract": {
            "run": "teamkit run init/status/close",
            "topic": "teamkit topic status/update/link",
            "teamContext": "teamkit team context add/assign/unassign/remove/list",
            "context": "teamkit context add/list",
            "graph": "teamkit graph next/advance",
            "messages": "teamkit msg send/reply/close/list",
            "artifacts": "teamkit artifact publish/list",
            "humanReview": "teamkit human request/resolve/list",
            "result": "teamkit result publish",
            "batch": "teamkit batch init/next/update/status/recover",
        },
        "adapterBoundary": {
            "target": None,
            "status": "not_bound",
            "availableAdapters": ["workbuddy"],
            "note": "Map this plan to a target runtime in an Adapter layer. WorkBuddy is the first available package-level adapter.",
        },
    }


def cmd_team_validate(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    errors = validate_team_definition(ctx)
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 2
    for warning in validation_warnings(ctx):
        print(f"warning: {warning}", file=sys.stderr)
    print(f"valid team definition: {ctx.team_file}")
    return 0


def cmd_home(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    probe = str(args.run or "_probe")
    payload = {
        "toolHome": str(teamkit_home()),
        "teamRoot": str(ctx.root),
        "teamFile": str(ctx.team_file),
        "runBase": str(ctx.run_base(probe)),
        "teamBase": str(ctx.team_base(probe)),
        "runBaseSource": ctx.run_base_source(),
        "runId": probe,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def cmd_team_compile(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    plan = build_execution_plan(ctx)
    if args.out:
        out = Path(args.out).expanduser()
        if not out.is_absolute():
            out = Path.cwd() / out
        write_json(out, plan)
        print(str(out))
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def cmd_team_context_list(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    expert = args.expert or args.visible_to or ""
    if expert:
        ctx.require_expert(expert)
    items = []
    for item in ctx.declared_contexts():
        view = team_context_view(ctx, item)
        if expert and view["scope"] == "agents" and expert not in view["visibleTo"]:
            continue
        items.append(view)
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
    else:
        for item in items:
            visible = "team" if item["scope"] == "team" else ", ".join(item["visibleTo"])
            source = item["path"] or item["source"]
            print(f"{item['id']}\t{item['name']}\t{visible}\t{source}")
    return 0


def cmd_team_context_add(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    contexts = declared_contexts_for_update(ctx)
    context_id = args.id.strip()
    if not ID_PATTERN.match(context_id):
        raise TeamKitError(f"context id must match {ID_PATTERN.pattern}")
    index = declared_context_index(contexts, context_id)
    if index >= 0 and not args.force:
        raise TeamKitError(f"context already exists: {context_id}; use --force to replace")
    scope = args.scope
    visible_to = normalize_visible_to(ctx, scope, [str(value) for value in args.visible_to or []])
    source_path = ""
    if args.file:
        source_path = relative_team_file_path(ctx, resolve_input_file(ctx, args.file), context_id, args.force)
    source = (args.source or "").strip()
    if not source_path and not source:
        source = "user_material"
    name = (args.name or "").strip()
    if not name:
        if source_path:
            name = Path(source_path).stem.replace("-", " ").replace("_", " ")
        else:
            name = context_id.replace("-", " ").replace("_", " ")
    record: dict[str, Any] = {
        "id": context_id,
        "name": name,
        "scope": scope,
    }
    if source_path:
        record["path"] = source_path
    if source:
        record["source"] = source
    if visible_to:
        record["visible_to"] = visible_to
    summary = optional_text_from_option(args.summary, args.summary_file)
    if summary:
        record["summary"] = summary
    if index >= 0:
        contexts[index] = record
    else:
        contexts.append(record)
    validate_updated_team(ctx)
    write_yaml(ctx.team_file, ctx.team)
    if args.json:
        print(json.dumps(team_context_view(ctx, record), ensure_ascii=False, indent=2))
    else:
        print(context_id)
    return 0


def cmd_team_context_assign(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    contexts = declared_contexts_for_update(ctx)
    context_id = args.context
    index = declared_context_index(contexts, context_id)
    if index < 0:
        raise TeamKitError(f"context not found: {context_id}")
    item = contexts[index]
    visible = [str(value) for value in item.get("visible_to", []) or []]
    for expert_id in args.visible_to or []:
        ctx.require_expert(expert_id)
        if expert_id not in visible:
            visible.append(expert_id)
    if not visible:
        raise TeamKitError("at least one --visible-to expert is required")
    item["scope"] = "agents"
    item["visible_to"] = visible
    validate_updated_team(ctx)
    write_yaml(ctx.team_file, ctx.team)
    if args.json:
        print(json.dumps(team_context_view(ctx, item), ensure_ascii=False, indent=2))
    else:
        print(context_id)
    return 0


def cmd_team_context_unassign(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    contexts = declared_contexts_for_update(ctx)
    context_id = args.context
    index = declared_context_index(contexts, context_id)
    if index < 0:
        raise TeamKitError(f"context not found: {context_id}")
    item = contexts[index]
    if str(item.get("scope") or "team") == "team":
        raise TeamKitError(f"context is visible to the whole team: {context_id}")
    remove = set(args.visible_to or [])
    if not remove:
        raise TeamKitError("at least one --visible-to expert is required")
    for expert_id in remove:
        ctx.require_expert(expert_id)
    visible = [str(value) for value in item.get("visible_to", []) or [] if str(value) not in remove]
    if not visible:
        raise TeamKitError("unassign would leave no visible experts; remove the context or assign another expert first")
    item["visible_to"] = visible
    validate_updated_team(ctx)
    write_yaml(ctx.team_file, ctx.team)
    if args.json:
        print(json.dumps(team_context_view(ctx, item), ensure_ascii=False, indent=2))
    else:
        print(context_id)
    return 0


def cmd_team_context_remove(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    contexts = declared_contexts_for_update(ctx)
    context_id = args.context
    index = declared_context_index(contexts, context_id)
    if index < 0:
        raise TeamKitError(f"context not found: {context_id}")
    removed = contexts.pop(index)
    validate_updated_team(ctx)
    write_yaml(ctx.team_file, ctx.team)
    if args.json:
        print(json.dumps(team_context_view(ctx, removed), ensure_ascii=False, indent=2))
    else:
        print(context_id)
    return 0


def cmd_run_init(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    validate_or_raise(ctx)
    run_id = args.run
    run_root = ctx.run_root(run_id)
    if ctx.state_path(run_id).exists() and not args.force:
        raise TeamKitError(f"run already initialized: {run_id}; use --force to rewrite state")

    run_root.mkdir(parents=True, exist_ok=True)
    for path in (
        run_root / "shared",
        ctx.context_item_dir(run_id),
        ctx.expert_result_dir(run_id),
    ):
        path.mkdir(parents=True, exist_ok=True)

    expert_root = ctx.expert_workspace_dir(run_id)
    for expert_id in ctx.experts:
        folder = expert_root / expert_id
        folder.mkdir(parents=True, exist_ok=True)
        scratch = folder / "scratch.md"
        result = folder / "result.md"
        if not scratch.exists():
            atomic_write_text(scratch, f"# Scratch: {expert_id}\n\n")
        if not result.exists():
            atomic_write_text(result, f"# Result: {expert_id}\n\n")

    brief_path = run_root / "brief.md"
    if args.brief:
        source = resolve_input_file(ctx, args.brief)
        if not source.exists():
            raise TeamKitError(f"brief file not found: {source}")
        atomic_copyfile(source, brief_path)
    elif not brief_path.exists() or args.force:
        team = ctx.team.get("team", {}) or {}
        atomic_write_text(
            brief_path,
            "\n".join(
                [
                    f"# Run {run_id}",
                    "",
                    f"Team: {team.get('name', team.get('id', 'unknown'))}",
                    f"Purpose: {team.get('purpose', '')}",
                    "",
                ]
            ),
        )

    for path in (
        ctx.messages_path(run_id),
        ctx.events_path(run_id),
        ctx.context_items_path(run_id),
        ctx.human_review_path(run_id),
        ctx.artifact_index_path(run_id),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    decision_log = ctx.decision_log_path(run_id)
    if not decision_log.exists() or args.force:
        atomic_write_text(decision_log, f"# Decision Log: {run_id}\n\n")

    topic = initial_topic_record(ctx, run_id)
    context_records = materialize_declared_contexts(ctx, run_id)
    topic["context_refs"] = [
        {
            "id": record["id"],
            "name": record["name"],
            "scope": record["scope"],
            "visibleTo": record["visibleTo"],
            "linkedBy": "team",
            "createdAt": record["createdAt"],
        }
        for record in context_records
    ]
    if not ctx.topic_path(run_id).exists() or args.force:
        write_yaml(ctx.topic_path(run_id), topic)
    state = {
        "run_id": run_id,
        "topic_id": topic["id"],
        "team_id": (ctx.team.get("team", {}) or {}).get("id", ""),
        "team_name": (ctx.team.get("team", {}) or {}).get("name", ""),
        "status": "prepared",
        "process_mode": ctx.process().get("mode", "graph"),
        "active_node": topic["current_node"],
        "active_nodes": topic.get("active_nodes", []),
        "open_messages": [],
        "open_human_reviews": [],
        "context_items": [
            {
                "id": record["id"],
                "name": record["name"],
                "scope": record["scope"],
                "visibleTo": record["visibleTo"],
                "path": record["path"],
            }
            for record in context_records
        ],
        "artifacts": [],
        "final_result": None,
        "createdAt": now(),
        "updatedAt": now(),
    }
    write_yaml(ctx.state_path(run_id), state)
    append_jsonl(
        ctx.events_path(run_id),
        event(
            "run.initialized",
            run_id,
            teamId=state["team_id"],
            runRoot=str(run_root),
            topicId=topic["id"],
            currentNode=topic["current_node"],
            contextCount=len(context_records),
        ),
    )
    print(f"initialized run {run_id} at {run_root}")
    return 0


def open_required_messages(ctx: TeamContext, run_id: str) -> list[dict[str, Any]]:
    messages = read_jsonl(ctx.messages_path(run_id))
    return [
        msg
        for msg in messages
        if msg.get("response") == "required" and msg.get("status") in {"created", "sent"}
    ]


def topic_active_nodes(topic: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the v0.3 active-node ledger, synthesizing it for v0.1 topics."""
    raw = topic.get("active_nodes")
    if isinstance(raw, list):
        result = [dict(item) for item in raw if isinstance(item, dict) and item.get("node")]
        if result:
            return result
    current = str(topic.get("current_node") or "")
    return ([{"node": current, "status": "active", "waiting_on": []}] if current else [])


def save_active_nodes(topic: dict[str, Any], entries: list[dict[str, Any]]) -> None:
    order = {"active": 0, "waiting": 1, "done": 2}
    entries.sort(key=lambda item: (order.get(str(item.get("status")), 3), item.get("activatedAt", "")))
    topic["active_nodes"] = entries
    active = next((item for item in entries if item.get("status") == "active"), None)
    if active:
        topic["current_node"] = str(active.get("node"))
    else:
        fallback = next((item for item in entries if item.get("status") == "waiting"), None)
        topic["current_node"] = str((fallback or {}).get("node") or "")


def active_node_entries(topic: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in topic_active_nodes(topic) if item.get("status") in {"active", "waiting"}]


def cmd_run_status(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    state = load_state(ctx, args.run)
    messages = read_jsonl(ctx.messages_path(args.run))
    artifacts = read_jsonl(ctx.artifact_index_path(args.run))
    contexts = read_jsonl(ctx.context_items_path(args.run))
    human_reviews = read_jsonl(ctx.human_review_path(args.run))
    topic = load_yaml(ctx.topic_path(args.run)) if ctx.topic_path(args.run).exists() else None
    open_messages = [
        msg["id"]
        for msg in open_required_messages(ctx, args.run)
    ]
    open_human_reviews = [
        item["id"] for item in human_reviews if item.get("status") == "open"
    ]
    view = dict(state)
    view["open_messages"] = open_messages
    view["open_human_reviews"] = open_human_reviews
    view["message_count"] = len(messages)
    view["context_item_count"] = len(contexts)
    view["artifact_count"] = len(artifacts)
    view["human_review_count"] = len(human_reviews)
    if topic:
        graph_view = graph_next_actions(ctx, args.run)
        view["activeNodes"] = graph_view.get("activeNodes", [])
        if len(view["activeNodes"]) == 1:
            actions = view["activeNodes"][0].get("actions") or []
            next_action = next((item for item in actions if item.get("allowed")), None)
            view["nextExpert"] = next_action.get("expert") if next_action else None
            view["nextTask"] = next_action.get("task") if next_action else None
        else:
            view["nextExpert"] = None
            view["nextTask"] = None
        view["graph"] = graph_view
        view["topic"] = {
            "id": topic.get("id"),
            "status": topic.get("status"),
            "responsible": topic.get("responsible"),
            "current_node": topic.get("current_node"),
            "waiting_on": topic.get("waiting_on"),
            "context_refs": topic.get("context_refs", []),
            "summary": topic.get("summary", ""),
        }
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(view, allow_unicode=True, sort_keys=False).strip())
    return 0


def cmd_run_close(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    state = load_state(ctx, args.run)
    if state.get("status") == "completed":
        raise TeamKitError("run already closed")
    summary = None
    if args.summary is not None or args.summary_file:
        # Resolve caller-provided text before changing either lifecycle ledger.
        # A missing summary file must not leave a half-closed run behind.
        summary = optional_text_from_option(args.summary, args.summary_file)
    state["status"] = "completed"
    save_state(ctx, args.run, state)
    if ctx.topic_path(args.run).exists():
        topic = load_topic(ctx, args.run)
        topic["status"] = "resolved"
        topic["waiting_on"] = None
        if summary is not None:
            topic["summary"] = summary
        topic["version"] = int(topic.get("version") or 1) + 1
        save_topic(ctx, args.run, topic)
    append_jsonl(
        ctx.events_path(args.run),
        event("run.closed", args.run, actor=args.by or ""),
    )
    print(args.run)
    return 0


def open_messages_for_topic_node(
    ctx: TeamContext,
    run_id: str,
    topic_id: str,
    node_id: str,
) -> list[dict[str, Any]]:
    messages = read_jsonl(ctx.messages_path(run_id))
    return [
        msg
        for msg in messages
        if msg.get("topicId") == topic_id
        and msg.get("nodeId") == node_id
        and msg.get("response") == "required"
        and msg.get("status") in {"created", "sent"}
    ]


def topic_status_view(ctx: TeamContext, run_id: str) -> dict[str, Any]:
    topic = load_topic(ctx, run_id)
    topic_id = str(topic.get("id") or run_id)
    current_node = str(topic.get("current_node") or "")
    view = dict(topic)
    view["open_messages"] = [
        msg["id"] for msg in open_messages_for_topic_node(ctx, run_id, topic_id, current_node)
    ]
    return view


def cmd_topic_status(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    view = topic_status_view(ctx, args.run)
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(view, allow_unicode=True, sort_keys=False).strip())
    return 0


def cmd_topic_update(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    state = load_state(ctx, args.run)
    topic = load_topic(ctx, args.run)
    changed = False
    if args.status:
        if args.status not in TOPIC_STATUSES:
            raise TeamKitError(f"invalid topic status: {args.status}")
        topic["status"] = args.status
        changed = True
    if args.responsible:
        ctx.require_expert(args.responsible)
        topic["responsible"] = args.responsible
        changed = True
    if args.current_node:
        ctx.require_graph_node(args.current_node)
        active_entries = active_node_entries(topic)
        if len(active_entries) > 1:
            nodes = ", ".join(str(item.get("node")) for item in active_entries)
            raise TeamKitError(
                f"multiple active graph nodes ({nodes}); cannot rewrite current_node directly, use graph advance --node"
            )
        if topic.get("current_node") != args.current_node:
            visits = topic.setdefault("visits", {})
            if not isinstance(visits, dict):
                visits = {}
                topic["visits"] = visits
            visits[args.current_node] = int(visits.get(args.current_node, 0)) + 1
        topic["current_node"] = args.current_node
        topic["active_nodes"] = [{"node": args.current_node, "status": "active", "waiting_on": []}]
        state["active_node"] = args.current_node
        changed = True
    if args.summary is not None or args.summary_file:
        topic["summary"] = optional_text_from_option(args.summary, args.summary_file)
        changed = True
    if args.clear_waiting:
        topic["waiting_on"] = None
        if topic.get("status") == "waiting":
            topic["status"] = "active"
        changed = True
    if args.waiting_type or args.waiting_ref or args.waiting_summary:
        if not args.waiting_type or not args.waiting_summary:
            raise TeamKitError("--waiting-type and --waiting-summary are required when setting waiting")
        topic["waiting_on"] = {
            "type": args.waiting_type,
            "ref": args.waiting_ref or "",
            "summary": args.waiting_summary,
            "since": now(),
        }
        topic["status"] = "waiting"
        changed = True
    for ref in args.evidence_ref or []:
        evidence = topic.setdefault("evidence", [])
        if not isinstance(evidence, list):
            evidence = []
            topic["evidence"] = evidence
        if not any(item.get("ref") == ref for item in evidence if isinstance(item, dict)):
            evidence.append({"ref": ref, "label": "", "linkedBy": args.by or "", "createdAt": now()})
            changed = True
    if not changed:
        raise TeamKitError("no topic update requested")
    topic["version"] = int(topic.get("version") or 1) + 1
    save_topic(ctx, args.run, topic)
    save_state(ctx, args.run, state)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "topic.updated",
            args.run,
            actor=args.by or "",
            topicId=topic.get("id"),
            currentNode=topic.get("current_node"),
            status=topic.get("status"),
        ),
    )
    if args.json:
        response = topic_status_view(ctx, args.run)
        next_view = graph_next_actions(ctx, args.run)
        response["activeNodes"] = next_view.get("activeNodes", [])
        if len(response["activeNodes"]) == 1:
            next_actions = response["activeNodes"][0].get("actions") or []
            next_action = next((item for item in next_actions if item.get("allowed")), None)
            response["nextExpert"] = next_action.get("expert") if next_action else None
            response["nextTask"] = next_action.get("task") if next_action else None
        else:
            response["nextExpert"] = None
            response["nextTask"] = None
        response["graph"] = next_view
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(topic.get("id"))
    return 0


def cmd_topic_link(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    topic = load_topic(ctx, args.run)
    evidence = topic.setdefault("evidence", [])
    if not isinstance(evidence, list):
        evidence = []
        topic["evidence"] = evidence
    if not any(item.get("ref") == args.ref for item in evidence if isinstance(item, dict)):
        evidence.append(
            {
                "ref": args.ref,
                "label": args.label or "",
                "linkedBy": args.by or "",
                "createdAt": now(),
            }
        )
    topic["version"] = int(topic.get("version") or 1) + 1
    save_topic(ctx, args.run, topic)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "topic.evidence_linked",
            args.run,
            actor=args.by or "",
            topicId=topic.get("id"),
            ref=args.ref,
        ),
    )
    print(args.ref)
    return 0


def edge_id(edge: dict[str, Any], index: int) -> str:
    return str(edge.get("id") or f"edge_{index + 1}")


def _graph_node_actions(
    ctx: TeamContext,
    run_id: str,
    topic: dict[str, Any],
    node_id: str,
    ignore_waiting: bool = False,
) -> dict[str, Any]:
    node = ctx.require_graph_node(node_id)
    topic_id = str(topic.get("id") or run_id)
    result: dict[str, Any] = {
        "currentNode": node_id,
        "currentExpert": node.get("expert", ""),
        "blocked": False,
        "actions": [],
        "openMessages": [],
    }
    entries = topic_active_nodes(topic)
    entry = next((item for item in entries if str(item.get("node")) == node_id), None)
    if entry and entry.get("status") == "waiting":
        result["blocked"] = True
        result["reason"] = "node is waiting for parallel predecessors"
        result["waitingOn"] = entry.get("waiting_on", [])
        return result
    if topic.get("status") in {"resolved", "archived"}:
        result["blocked"] = True
        result["reason"] = f"topic is {topic.get('status')}"
        return result
    open_messages = open_messages_for_topic_node(ctx, run_id, topic_id, node_id)
    if open_messages and not ignore_waiting:
        result["blocked"] = True
        result["reason"] = "current node has unresolved required messages"
        result["openMessages"] = [msg["id"] for msg in open_messages]
        return result
    if (topic.get("status") == "waiting" or topic.get("waiting_on")) and not ignore_waiting:
        result["blocked"] = True
        result["reason"] = "topic is waiting"
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
        result["reason"] = "no outgoing graph edges"
    return result


def graph_next_actions(ctx: TeamContext, run_id: str, from_node: str = "", ignore_waiting: bool = False) -> dict[str, Any]:
    if not ctx.graph():
        raise TeamKitError("process.graph is not configured")
    topic = load_topic(ctx, run_id)
    entries = active_node_entries(topic)
    if from_node:
        entries = [item for item in entries if str(item.get("node")) == from_node]
        if not entries:
            entries = [{"node": from_node, "status": "active", "waiting_on": []}]
    if not entries:
        return {"runId": run_id, "topicId": str(topic.get("id") or run_id), "activeNodes": [], "blocked": False, "reason": "no_active_node"}
    node_views = [_graph_node_actions(ctx, run_id, topic, str(item["node"]), ignore_waiting) for item in entries]
    first = node_views[0]
    result: dict[str, Any] = {
        "runId": run_id,
        "topicId": str(topic.get("id") or run_id),
        **first,
        "activeNodes": node_views,
    }
    result["blocked"] = bool(topic.get("status") in {"resolved", "archived"} or first.get("blocked"))
    return result


def cmd_graph_next(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    result = graph_next_actions(ctx, args.run, args.from_node or "", args.ignore_waiting)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if result.get("blocked"):
            print(f"blocked: {result.get('reason')}")
            for msg_id in result.get("openMessages", []):
                print(f"- open message: {msg_id}")
            return 0
        if not result["actions"]:
            print(result.get("reason") or "no next actions")
            return 0
        for action in result["actions"]:
            suffix = "" if action["allowed"] else f" ({action['reason']})"
            print(
                f"{action['id']}: {action['from']} -> {action['to']} [{action['expert']}] when {action['when']}{suffix}"
            )
    return 0


def cmd_graph_advance(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    state = load_state(ctx, args.run)
    if args.edge and args.to:
        raise TeamKitError("use either --edge or --to, not both")
    topic = load_topic(ctx, args.run)
    entries = active_node_entries(topic)
    requested_node = getattr(args, "node", None) or ""
    if requested_node:
        if not any(str(item.get("node")) == requested_node and item.get("status") == "active" for item in entries):
            raise TeamKitError(f"graph node is not active: {requested_node}")
        source_node = requested_node
    else:
        active = [item for item in entries if item.get("status") == "active"]
        if len(active) > 1:
            raise TeamKitError("multiple active graph nodes; use --node")
        if not active:
            raise TeamKitError("no active graph node")
        source_node = str(active[0]["node"])
    result = graph_next_actions(ctx, args.run, source_node)
    if result.get("blocked"):
        raise TeamKitError(f"cannot advance graph: {result.get('reason')}")
    actions = result.get("actions") or []
    parallel = [a for a in actions if a.get("relation") == "parallel"]
    choices = [a for a in actions if a.get("relation") != "parallel"]
    if args.edge or args.to:
        selected_id = args.edge
        if args.to:
            matches = [action for action in actions if action.get("to") == args.to]
            if not matches:
                raise TeamKitError(f"graph target not available from current node: {args.to}")
            if len(matches) > 1:
                raise TeamKitError(f"multiple graph edges target {args.to}; use --edge")
            selected_id = matches[0].get("id")
        selected = next((action for action in actions if action.get("id") == selected_id), None)
        if not selected:
            raise TeamKitError(f"graph edge not available from current node: {selected_id}")
        if selected.get("relation") == "parallel":
            raise TeamKitError(f"edge {selected.get('id')} is relation:parallel; fork activates all parallel branches, omit --edge/--to")
        if not selected.get("allowed"):
            raise TeamKitError(f"graph action is not allowed: {selected.get('reason')}")
        chosen = [selected]
    elif choices:
        if parallel:
            raise TeamKitError("node has parallel branches and selectable branches; use --edge/--to to choose a non-parallel edge")
        allowed_actions = [action for action in choices if action.get("allowed")]
        if not allowed_actions:
            raise TeamKitError("no allowed graph action from current node")
        if len(allowed_actions) > 1:
            raise TeamKitError("multiple graph actions are available; use --edge or --to")
        chosen = [allowed_actions[0]]
    elif len(parallel) >= 2:
        allowed_parallel = [action for action in parallel if action.get("allowed")]
        if not allowed_parallel:
            print(f"warning: all parallel edges from {source_node} are blocked by max_visits", file=sys.stderr)
            return 0
        for action in parallel:
            if not action.get("allowed"):
                print(f"warning: parallel edge {action.get('id')} blocked at visits={action.get('visits')}", file=sys.stderr)
        chosen = allowed_parallel
    else:
        allowed_actions = [action for action in actions if action.get("allowed")]
        if not allowed_actions:
            raise TeamKitError("no allowed graph action from current node")
        if len(allowed_actions) > 1:
            raise TeamKitError("multiple graph actions are available; use --edge or --to")
        chosen = [allowed_actions[0]]
    visits = topic.setdefault("visits", {})
    if not isinstance(visits, dict):
        visits = {}
        topic["visits"] = visits
    entries = topic_active_nodes(topic)
    source_entry = next((item for item in entries if str(item.get("node")) == source_node), None)
    if not source_entry:
        raise TeamKitError(f"graph node is not active: {source_node}")
    source_was_parallel = bool(source_entry.get("parallel_branch"))
    source_entry["status"] = "done"
    target_ids = []
    join_sources: dict[str, list[str]] = {}
    for edge in ctx.graph_edges():
        if str(edge.get("relation") or "next") == "parallel":
            join_sources.setdefault(str(edge.get("to")), []).append(str(edge.get("from")))
    for selected in chosen:
        to_node = str(selected["to"])
        target_ids.append(to_node)
        visits[to_node] = int(visits.get(to_node, 0)) + 1
        target_node = ctx.require_graph_node(to_node)
        is_join_entry = (
            str(selected.get("relation") or "next") == "parallel"
            and len(join_sources.get(to_node, [])) > 1
        )
        if is_join_entry:
            existing = next((item for item in entries if str(item.get("node")) == to_node), None)
            if not existing:
                predecessors = list(join_sources.get(to_node, []))
                if source_node not in predecessors:
                    predecessors.append(source_node)
                predecessors = list(dict.fromkeys(predecessors))
                existing = {"node": to_node, "status": "waiting", "waiting_on": predecessors.copy(), "parallel_predecessors": predecessors, "activatedAt": now()}
                entries.append(existing)
        else:
            existing = next((item for item in entries if str(item.get("node")) == to_node), None)
            if existing:
                existing.update({"status": "active", "waiting_on": []})
            else:
                entries.append({"node": to_node, "status": "active", "waiting_on": [], "parallel_branch": source_was_parallel, "activatedAt": now()})
        if len(chosen) > 1:
            existing = next((item for item in entries if str(item.get("node")) == to_node), None)
            if existing:
                existing["parallel_branch"] = True
    # Leave events satisfy any join waiting on this source. Join becomes active eagerly.
    join_activated = False
    # Join predecessor satisfaction is based on completed branch nodes, not on
    # the transient source node that just emitted the leave event.
    completed_nodes = {str(item.get("node")) for item in entries if item.get("status") == "done"}
    completed_nodes.add(source_node)
    for item in list(entries):
        if item.get("status") != "waiting":
            continue
        waiting_on = [str(value) for value in item.get("waiting_on", []) if str(value) not in completed_nodes]
        item["waiting_on"] = waiting_on
        if not waiting_on:
            item["status"] = "active"
            item["waiting_on"] = []
            join_activated = True
    if join_activated:
        entries = [candidate for candidate in entries if candidate.get("status") != "done"]
    elif len(chosen) == 1 and not source_was_parallel:
        entries = [candidate for candidate in entries if candidate is not source_entry]
    save_active_nodes(topic, entries)
    to_node = target_ids[0] if len(target_ids) == 1 else ""
    coordinator = ctx.process().get("coordinator") or ctx.process().get("lead") or ""
    topic["responsible"] = coordinator or str(selected.get("expert") or "")
    topic["status"] = "active"
    if args.summary is not None or args.summary_file:
        topic["summary"] = optional_text_from_option(args.summary, args.summary_file)
    topic["version"] = int(topic.get("version") or 1) + 1
    save_topic(ctx, args.run, topic)
    state["active_node"] = topic.get("current_node", "")
    state["active_nodes"] = topic.get("active_nodes", [])
    save_state(ctx, args.run, state)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "graph.advanced",
            args.run,
            actor=args.by or "",
            topicId=topic.get("id"),
            edgeId=(chosen[0].get("id") if len(chosen) == 1 else [item.get("id") for item in chosen]),
            fromNode=source_node,
            toNode=(to_node or target_ids),
            expert=(chosen[0].get("expert") if len(chosen) == 1 else [item.get("expert") for item in chosen]),
        ),
    )
    if args.json:
        response = topic_status_view(ctx, args.run)
        next_view = graph_next_actions(ctx, args.run)
        response["activeNodes"] = next_view.get("activeNodes", [])
        if len(response["activeNodes"]) == 1:
            next_actions = response["activeNodes"][0].get("actions") or []
            next_action = next((item for item in next_actions if item.get("allowed")), None)
            response["nextExpert"] = next_action.get("expert") if next_action else None
            response["nextTask"] = next_action.get("task") if next_action else None
        else:
            response["nextExpert"] = None
            response["nextTask"] = None
        print(json.dumps(response, ensure_ascii=False, indent=2))
    else:
        print(to_node or json.dumps(topic.get("active_nodes", []), ensure_ascii=False))
    return 0


def update_message(
    messages: list[dict[str, Any]],
    message_id_value: str,
    **updates: Any,
) -> dict[str, Any]:
    for msg in messages:
        if msg.get("id") == message_id_value:
            msg.update(updates)
            msg["updatedAt"] = now()
            return msg
    raise TeamKitError(f"message not found: {message_id_value}")


def default_topic_and_node(ctx: TeamContext, run_id: str, topic_arg: str | None, node_arg: str | None) -> tuple[str, str]:
    topic_id = topic_arg or run_id
    node_id = node_arg or ""
    topic_path = ctx.topic_path(run_id)
    if topic_path.exists():
        topic = load_yaml(topic_path)
        topic_id = topic_arg or str(topic.get("id") or run_id)
        if node_arg:
            node_id = node_arg
        else:
            entries = active_node_entries(topic)
            sender_candidates = entries
            node_id = str(topic.get("current_node") or "")
            if len(sender_candidates) == 1:
                node_id = str(sender_candidates[0].get("node") or node_id)
    if node_id:
        ctx.require_graph_node(node_id)
    return topic_id, node_id


def cmd_msg_send(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    ctx.require_expert(args.from_expert)
    ctx.require_expert(args.to)
    if not ctx.message_type_allowed(args.type):
        raise TeamKitError(f"message type is not allowed by team rules: {args.type}")
    if not ctx.communication_allowed(args.from_expert, args.to) and not args.force:
        raise TeamKitError(
            f"communication rule does not allow {args.from_expert} -> {args.to}; use --force to override"
        )
    response = args.response or ctx.response_mode_for(args.from_expert, args.to)
    topic_id, node_id = default_topic_and_node(ctx, args.run, args.topic, args.node)
    if not args.node:
        topic = load_topic(ctx, args.run)
        candidates = [
            str(item.get("node"))
            for item in topic_active_nodes(topic)
            if item.get("node") and str(ctx.graph_node_map().get(str(item.get("node")), {}).get("expert")) == args.from_expert
        ]
        if len(candidates) == 1:
            node_id = candidates[0]
        elif len(topic_active_nodes(topic)) > 1:
            all_nodes = ", ".join(str(item.get("node")) for item in topic_active_nodes(topic))
            raise TeamKitError(
                f"sender {args.from_expert} does not map uniquely to a graph node; candidates: {all_nodes}; use --node"
            )
    msg = {
        "id": message_id(),
        "runId": args.run,
        "topicId": topic_id,
        "nodeId": node_id,
        "from": args.from_expert,
        "to": args.to,
        "type": args.type,
        "intent": args.intent or "",
        "subject": args.subject.strip(),
        "body": text_from_option(args.body, args.body_file, "body"),
        "response": response,
        "replyTo": None,
        "artifactRefs": args.artifact_ref or [],
        "evidenceRefs": args.evidence_ref or [],
        "priority": args.priority,
        "status": "sent",
        "resolution": "",
        "createdAt": now(),
        "updatedAt": now(),
    }
    append_jsonl(ctx.messages_path(args.run), msg)
    if response == "required":
        add_state_value(ctx, args.run, "open_messages", msg["id"])
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "message.sent",
            args.run,
            actor=args.from_expert,
            messageId=msg["id"],
            topicId=topic_id,
            nodeId=node_id,
            to=args.to,
            subject=msg["subject"],
        ),
    )
    print(msg["id"])
    return 0


def cmd_msg_reply(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    ctx.require_expert(args.from_expert)
    messages = read_jsonl(ctx.messages_path(args.run))
    original = next((m for m in messages if m.get("id") == args.reply_to), None)
    if original is None:
        raise TeamKitError(f"message not found: {args.reply_to}")
    if original.get("to") != args.from_expert:
        raise TeamKitError(f"{args.from_expert} is not the recipient of {args.reply_to}")
    reply = {
        "id": message_id(),
        "runId": args.run,
        "topicId": original.get("topicId") or args.run,
        "nodeId": original.get("nodeId") or "",
        "from": args.from_expert,
        "to": original.get("from"),
        "type": "reply",
        "intent": original.get("intent", ""),
        "subject": args.subject or "Re: " + str(original.get("subject", "")),
        "body": text_from_option(args.body, args.body_file, "body"),
        "response": "none",
        "replyTo": args.reply_to,
        "artifactRefs": args.artifact_ref or [],
        "evidenceRefs": args.evidence_ref or [],
        "priority": original.get("priority", "normal"),
        "status": "sent",
        "resolution": "reply",
        "createdAt": now(),
        "updatedAt": now(),
    }
    update_message(
        messages,
        args.reply_to,
        status="replied",
        resolution="reply",
        resolvedBy=args.from_expert,
        resolvedAt=now(),
    )
    messages.append(reply)
    write_jsonl(ctx.messages_path(args.run), messages)
    remove_state_value(ctx, args.run, "open_messages", args.reply_to)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "message.replied",
            args.run,
            actor=args.from_expert,
            messageId=reply["id"],
            replyTo=args.reply_to,
            topicId=reply["topicId"],
            nodeId=reply["nodeId"],
        ),
    )
    print(reply["id"])
    return 0


def cmd_msg_close(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    ctx.require_expert(args.from_expert)
    messages = read_jsonl(ctx.messages_path(args.run))
    target = next((m for m in messages if m.get("id") == args.message), None)
    if target is None:
        raise TeamKitError(f"message not found: {args.message}")
    if args.from_expert not in {target.get("from"), target.get("to")}:
        raise TeamKitError(f"{args.from_expert} cannot close {args.message}")
    update_message(
        messages,
        args.message,
        status="closed",
        resolution=args.resolution,
        resolutionReason=args.reason,
        resolvedBy=args.from_expert,
        resolvedAt=now(),
    )
    write_jsonl(ctx.messages_path(args.run), messages)
    remove_state_value(ctx, args.run, "open_messages", args.message)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "message.closed",
            args.run,
            actor=args.from_expert,
            messageId=args.message,
            resolution=args.resolution,
        ),
    )
    print(args.message)
    return 0


def cmd_msg_list(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    messages = read_jsonl(ctx.messages_path(args.run))
    if args.status:
        if args.status == "open":
            messages = [
                m
                for m in messages
                if m.get("response") == "required" and m.get("status") in {"created", "sent"}
            ]
        else:
            messages = [m for m in messages if m.get("status") == args.status]
    if args.expert:
        messages = [
            m for m in messages if m.get("from") == args.expert or m.get("to") == args.expert
        ]
    if args.json:
        print(json.dumps(messages, ensure_ascii=False, indent=2))
    else:
        for msg in messages:
            print(
                f"{msg.get('id')} [{msg.get('status')}] {msg.get('from')} -> {msg.get('to')}: {msg.get('subject')}"
            )
    return 0


def artifact_kind_dir(ctx: TeamContext, run_id: str, kind: str) -> Path:
    if kind == "expert_result":
        return ctx.expert_result_dir(run_id)
    if kind == "final":
        return ctx.run_root(run_id) / "artifacts" / "final"
    return ctx.run_root(run_id) / "artifacts" / kind


def publish_artifact(
    ctx: TeamContext,
    run_id: str,
    owner: str,
    source: Path,
    kind: str,
) -> dict[str, Any]:
    ctx.require_expert(owner)
    if not source.exists() or not source.is_file():
        raise TeamKitError(f"artifact file not found: {source}")
    data = source.read_bytes()
    art_id = artifact_id_for(data)
    target_dir = artifact_kind_dir(ctx, run_id, kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix
    target = target_dir / f"{art_id}{suffix}"
    if not target.exists():
        atomic_write_bytes(target, data)
    record = {
        "id": art_id,
        "runId": run_id,
        "owner": owner,
        "kind": kind,
        "name": source.name,
        "path": display_path(ctx.root, target),
        "sourcePath": display_path(ctx.root, source),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "createdAt": now(),
    }
    records = read_jsonl(ctx.artifact_index_path(run_id))
    existing = next(
        (r for r in records if r.get("id") == art_id and r.get("kind") == kind),
        None,
    )
    if existing:
        return existing
    records.append(record)
    write_jsonl(ctx.artifact_index_path(run_id), records)
    return record


def add_state_artifact(ctx: TeamContext, run_id: str, record: dict[str, Any]) -> None:
    add_unique_state_item(
        ctx,
        run_id,
        "artifacts",
        {
            "id": record["id"],
            "kind": record["kind"],
            "owner": record["owner"],
            "path": record["path"],
        },
    )


def cmd_artifact_publish(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    source = resolve_input_file(ctx, args.file, args.run)
    record = publish_artifact(ctx, args.run, args.from_expert, source, args.kind)
    add_state_artifact(ctx, args.run, record)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "artifact.published",
            args.run,
            actor=args.from_expert,
            artifactId=record["id"],
            kind=args.kind,
        ),
    )
    print(record["id"])
    return 0


def cmd_artifact_list(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    records = read_jsonl(ctx.artifact_index_path(args.run))
    if args.kind:
        records = [r for r in records if r.get("kind") == args.kind]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for record in records:
            print(
                f"{record.get('id')} [{record.get('kind')}] {record.get('owner')}: {record.get('path')}"
            )
    return 0


def cmd_context_add(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    declared = ctx.declared_context_for(args.id or args.name or "")
    declared_path = str((declared or {}).get("path") or (declared or {}).get("file") or "")
    source_arg = args.file or declared_path
    has_text = bool(args.text is not None or args.text_file)
    if args.file and has_text:
        raise TeamKitError("use either --file or --text/--text-file, not both")
    summary = optional_text_from_option(args.summary, args.summary_file)
    scope = args.scope or str((declared or {}).get("scope") or "team")
    visible_to = [
        str(value)
        for value in (args.visible_to or (declared or {}).get("visible_to", []) or [])
    ]
    context_id = args.id or str((declared or {}).get("id") or "")
    source_type = args.source_type or str((declared or {}).get("source") or ("file" if source_arg else "text"))
    if source_arg:
        source = resolve_input_file(ctx, source_arg, args.run)
        record = managed_context_record(
            ctx,
            args.run,
            source,
            context_id=context_id,
            name=args.name or str((declared or {}).get("name") or source.name),
            source_type=source_type,
            scope=scope,
            visible_to=visible_to,
            owner=args.by or "user",
            summary=summary or str((declared or {}).get("summary") or ""),
        )
    else:
        text = optional_text_from_option(args.text, args.text_file)
        if not text:
            raise TeamKitError("--file, --text, or --text-file is required")
        record = managed_context_bytes_record(
            ctx,
            args.run,
            text.encode("utf-8"),
            context_id=context_id,
            name=args.name or str((declared or {}).get("name") or "Context Item"),
            source_type=source_type,
            suffix=".md",
            scope=scope,
            visible_to=visible_to,
            owner=args.by or "user",
            summary=summary or str((declared or {}).get("summary") or ""),
        )
    add_state_context_item(ctx, args.run, record)
    add_context_ref_to_topic(ctx, args.run, record, args.by or "user")
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "context.added",
            args.run,
            actor=args.by or "user",
            contextId=record["id"],
            name=record["name"],
            scope=record["scope"],
        ),
    )
    print(record["id"])
    return 0


def cmd_context_list(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    records = read_jsonl(ctx.context_items_path(args.run))
    if args.visible_to:
        ctx.require_expert(args.visible_to)
        records = [
            record
            for record in records
            if record.get("scope") == "team" or args.visible_to in (record.get("visibleTo") or [])
        ]
    if args.scope:
        records = [record for record in records if record.get("scope") == args.scope]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for record in records:
            target = "team" if record.get("scope") == "team" else ",".join(record.get("visibleTo") or [])
            print(f"{record.get('id')} [{target}] {record.get('name')}: {record.get('path')}")
    return 0


def append_decision_log(ctx: TeamContext, run_id: str, heading: str, body: str) -> None:
    path = ctx.decision_log_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        atomic_write_text(path, f"# Decision Log: {run_id}\n\n")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"## {heading}\n\n{body.strip()}\n\n")
        handle.flush()
        os.fsync(handle.fileno())


def cmd_human_request(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    state = load_state(ctx, args.run)
    ctx.require_expert(args.from_expert)
    review = {
        "id": prefixed_id("hr"),
        "runId": args.run,
        "from": args.from_expert,
        "reason": args.reason,
        "question": text_from_option(args.question, args.question_file, "question"),
        "status": "open",
        "artifactRefs": args.artifact_ref or [],
        "evidenceRefs": args.evidence_ref or [],
        "createdAt": now(),
        "updatedAt": now(),
    }
    append_jsonl(ctx.human_review_path(args.run), review)
    open_reviews = state.setdefault("open_human_reviews", [])
    if isinstance(open_reviews, list) and review["id"] not in open_reviews:
        open_reviews.append(review["id"])
    state["status"] = "waiting_for_human"
    save_state(ctx, args.run, state)
    if ctx.topic_path(args.run).exists():
        topic = load_topic(ctx, args.run)
        topic["status"] = "waiting"
        topic["waiting_on"] = {
            "type": "human_review",
            "ref": review["id"],
            "summary": args.reason,
            "since": now(),
        }
        topic["version"] = int(topic.get("version") or 1) + 1
        save_topic(ctx, args.run, topic)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "human_review.requested",
            args.run,
            actor=args.from_expert,
            reviewId=review["id"],
            reason=args.reason,
        ),
    )
    print(review["id"])
    return 0


def cmd_human_resolve(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    state = load_state(ctx, args.run)
    reviews = read_jsonl(ctx.human_review_path(args.run))
    target = next((item for item in reviews if item.get("id") == args.review), None)
    if not target:
        raise TeamKitError(f"human input request not found: {args.review}")
    if target.get("status") != "open" and not args.force:
        raise TeamKitError(f"human input request is already resolved: {args.review}")
    answer = text_from_option(args.answer, args.answer_file, "answer")
    target.update(
        {
            "status": "resolved",
            "resolution": args.resolution,
            "answer": answer,
            "resolvedBy": args.by,
            "resolvedAt": now(),
            "updatedAt": now(),
        }
    )
    write_jsonl(ctx.human_review_path(args.run), reviews)
    open_reviews = [
        item["id"] for item in reviews if item.get("status") == "open"
    ]
    state["open_human_reviews"] = open_reviews
    if state.get("status") == "waiting_for_human" and not open_reviews:
        state["status"] = "running"
    save_state(ctx, args.run, state)
    if ctx.topic_path(args.run).exists():
        topic = load_topic(ctx, args.run)
        waiting = topic.get("waiting_on")
        if (
            isinstance(waiting, dict)
            and waiting.get("type") == "human_review"
            and waiting.get("ref") == args.review
        ):
            if open_reviews:
                topic["waiting_on"] = {
                    "type": "human_review",
                    "ref": open_reviews[0],
                    "summary": "Unresolved human input request",
                    "since": now(),
                }
                topic["status"] = "waiting"
            else:
                topic["waiting_on"] = None
                if topic.get("status") == "waiting":
                    topic["status"] = "active"
            topic["version"] = int(topic.get("version") or 1) + 1
            save_topic(ctx, args.run, topic)
    append_decision_log(
        ctx,
        args.run,
        f"Human Input {args.review}",
        f"Resolution: {args.resolution}\n\nBy: {args.by}\n\n{answer}",
    )
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "human_review.resolved",
            args.run,
            actor=args.by,
            reviewId=args.review,
            resolution=args.resolution,
        ),
    )
    print(args.review)
    return 0


def cmd_human_list(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    records = read_jsonl(ctx.human_review_path(args.run))
    if args.status:
        records = [r for r in records if r.get("status") == args.status]
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for record in records:
            print(
                f"{record.get('id')} [{record.get('status')}] {record.get('from')}: {record.get('reason')}"
            )
    return 0


def cmd_result_publish(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    load_state(ctx, args.run)
    ctx.require_expert(args.from_expert)
    source = resolve_input_file(ctx, args.file, args.run)
    if not source.exists() or not source.is_file():
        raise TeamKitError(f"result file not found: {source}")
    record = publish_artifact(ctx, args.run, args.from_expert, source, "final")
    add_state_artifact(ctx, args.run, record)
    state = load_state(ctx, args.run)
    state["final_result"] = {
        "artifactId": record["id"],
        "path": record["path"],
        "publishedBy": args.from_expert,
        "publishedAt": now(),
    }
    save_state(ctx, args.run, state)
    append_jsonl(
        ctx.events_path(args.run),
        event(
            "result.published",
            args.run,
            actor=args.from_expert,
            artifactId=record["id"],
        ),
    )
    print(record["id"])
    return 0


def batch_root(ctx: TeamContext) -> Path:
    return ctx.team_base("_batch") / "batches"


def batch_manifest_path(ctx: TeamContext, batch_id: str) -> Path:
    return batch_root(ctx) / batch_id / "manifest.json"


def load_batch_manifest(ctx: TeamContext, batch_id: str) -> tuple[Path, dict[str, Any]]:
    path = batch_manifest_path(ctx, batch_id)
    if not path.exists():
        raise TeamKitError(f"batch not found: {batch_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise TeamKitError(f"invalid batch manifest: {path}")
    return path, data


def batch_case_summary(ctx: TeamContext, case: dict[str, Any]) -> dict[str, Any]:
    summary = {key: case.get(key, "") for key in ("caseId", "inputRef", "status", "runId")}
    run_id = str(case.get("runId") or "")
    if case.get("status") == "running" and run_id:
        try:
            state = load_state(ctx, run_id)
            node = state.get("active_node") or ""
            node_data = ctx.graph_node_map().get(str(node), {})
            summary["expert"] = node_data.get("expert", "")
        except TeamKitError:
            summary["expert"] = ""
    return summary


def batch_payload(ctx: TeamContext, data: dict[str, Any], selected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = data.get("cases", [])
    counts = {status: sum(1 for case in cases if case.get("status") == status) for status in ("pending", "running", "done", "failed")}
    running_by_expert: dict[str, int] = {}
    for case in cases:
        summary = batch_case_summary(ctx, case)
        if case.get("status") == "running" and summary.get("expert"):
            expert = str(summary["expert"])
            running_by_expert[expert] = running_by_expert.get(expert, 0) + 1
    result = {
        "batchId": data.get("batchId"),
        "teamId": data.get("teamId"),
        "counts": counts,
        "runningByExpert": running_by_expert,
    }
    if selected is not None:
        result["cases"] = [batch_case_summary(ctx, case) for case in selected]
    return result


def cmd_batch_init(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    cases_dir = Path(args.cases_dir).expanduser().resolve()
    if not cases_dir.is_dir():
        raise TeamKitError(f"cases directory not found: {cases_dir}")
    label = kebab_case(args.batch, "batch")
    team_id = str((ctx.team.get("team", {}) or {}).get("id") or ctx.root.name)
    batch_id = f"{team_id}@{label}"
    path = batch_manifest_path(ctx, batch_id)
    if path.exists() and not args.force:
        raise TeamKitError(f"batch already exists: {batch_id}; use --force")
    cases = []
    for item in sorted(cases_dir.iterdir()):
        if not item.is_file() or item.name.startswith("."):
            continue
        cases.append({"caseId": item.stem, "inputRef": str(item), "status": "pending", "runId": "", "dispatchedAt": "", "updatedAt": now()})
    data = {"manifestVersion": "teamkit.batch.v0.1", "batchId": batch_id, "teamId": team_id, "label": label, "casesDir": str(cases_dir), "createdAt": now(), "updatedAt": now(), "cases": cases}
    path.parent.mkdir(parents=True, exist_ok=True)
    with batch_lock(path.parent):
        write_json(path, data)
    print(json.dumps({"batchId": batch_id, "caseCount": len(cases)}, ensure_ascii=False) if args.json else batch_id)
    return 0


def cmd_batch_next(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    path, data = load_batch_manifest(ctx, args.batch)
    limit = max(1, int(args.max))
    selected: list[dict[str, Any]] = []
    with batch_lock(path.parent):
        # Re-read while holding the lock: selection and state transition are atomic.
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data.get("cases", []):
            if case.get("status") == "pending" and len(selected) < limit:
                case["status"] = "running"
                case["dispatchedAt"] = now()
                case["updatedAt"] = case["dispatchedAt"]
                selected.append(case)
        data["updatedAt"] = now()
        write_json(path, data)
    payload = batch_payload(ctx, data, selected)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_batch_update(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    path, data = load_batch_manifest(ctx, args.batch)
    if args.status not in {"pending", "running", "done", "failed"}:
        raise TeamKitError("invalid batch status")
    with batch_lock(path.parent):
        data = json.loads(path.read_text(encoding="utf-8"))
        case = next((item for item in data.get("cases", []) if item.get("caseId") == args.case), None)
        if case is None:
            raise TeamKitError(f"case not found: {args.case}")
        case["status"] = args.status
        if args.run is not None:
            case["runId"] = args.run
        case["updatedAt"] = now()
        data["updatedAt"] = now()
        write_json(path, data)
    print(args.case)
    return 0


def cmd_batch_status(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    _, data = load_batch_manifest(ctx, args.batch)
    payload = batch_payload(ctx, data)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        counts = payload["counts"]
        print(f"{payload['batchId']} pending={counts['pending']} running={counts['running']} done={counts['done']} failed={counts['failed']}")
        for expert, count in payload["runningByExpert"].items():
            print(f"{expert}: {count}")
    return 0


def cmd_batch_recover(args: argparse.Namespace) -> int:
    if args.stale is None:
        raise TeamKitError("batch recover requires explicit --stale <minutes>")
    ctx = TeamContext(Path(args.team))
    path, data = load_batch_manifest(ctx, args.batch)
    cutoff = datetime.now(timezone.utc).timestamp() - float(args.stale) * 60
    recovered = []
    with batch_lock(path.parent):
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data.get("cases", []):
            if case.get("status") != "running":
                continue
            stamp = str(case.get("updatedAt") or case.get("dispatchedAt") or "")
            try:
                timestamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                timestamp = 0
            if timestamp > cutoff:
                continue
            run_id = str(case.get("runId") or "")
            if run_id:
                try:
                    state = load_state(ctx, run_id)
                    if state.get("status") == "completed":
                        case["status"] = "done"
                        case["updatedAt"] = now()
                        continue
                except TeamKitError:
                    pass
            case["status"] = "pending"
            case["updatedAt"] = now()
            recovered.append(case.get("caseId"))
        data["updatedAt"] = now()
        write_json(path, data)
    print(json.dumps({"batchId": args.batch, "recovered": recovered}, ensure_ascii=False) if args.json else "\n".join(str(item) for item in recovered))
    return 0


def kebab_case(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    text = re.sub(r"-+", "-", text)
    if not text:
        text = fallback
    if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", text):
        text = fallback
    return text


def workbuddy_app_path() -> Path:
    raw = os.environ.get("WORKBUDDY_APP_PATH", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_WORKBUDDY_APP


def workbuddy_config_dir(raw: str | None = None) -> Path:
    value = (raw or os.environ.get("WORKBUDDY_CONFIG_DIR") or "").strip()
    return Path(value).expanduser().resolve() if value else Path.home() / ".workbuddy"


def workbuddy_marketplace_dir(config_dir: Path) -> Path:
    return config_dir / "plugins" / "marketplaces" / "my-experts"


def workbuddy_plugins_dir(config_dir: Path) -> Path:
    return workbuddy_marketplace_dir(config_dir) / "plugins"


def workbuddy_detect_info(config_dir: Path | None = None) -> dict[str, Any]:
    app = workbuddy_app_path()
    info_plist = app / "Contents" / "Info.plist"
    plist: dict[str, Any] = {}
    if info_plist.exists():
        with info_plist.open("rb") as handle:
            plist = plistlib.load(handle)
    resources = app / "Contents" / "Resources" / "app.asar.unpacked"
    cli = resources / "cli" / "bin" / "codebuddy"
    selected_config = config_dir or workbuddy_config_dir()
    schemes: list[str] = []
    for item in plist.get("CFBundleURLTypes", []) or []:
        if isinstance(item, dict):
            schemes.extend(str(s) for s in item.get("CFBundleURLSchemes", []) or [])
    return {
        "appPath": str(app),
        "appExists": app.exists(),
        "bundleIdentifier": plist.get("CFBundleIdentifier", ""),
        "version": plist.get("CFBundleShortVersionString", ""),
        "urlSchemes": schemes,
        "cliPath": str(cli),
        "cliExists": cli.exists(),
        "builtinSkillsDir": str(resources / "resources" / "builtin-skills"),
        "builtinSkillsDirExists": (resources / "resources" / "builtin-skills").exists(),
        "configDir": str(selected_config),
        "expertsDir": str(workbuddy_plugins_dir(selected_config)),
        "marketplacePath": str(workbuddy_marketplace_dir(selected_config) / ".codebuddy-plugin" / "marketplace.json"),
    }


def cmd_workbuddy_detect(args: argparse.Namespace) -> int:
    info = workbuddy_detect_info(workbuddy_config_dir(args.config_dir))
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        for key, value in info.items():
            print(f"{key}: {value}")
    return 0


def workbuddy_package_name(ctx: TeamContext, override: str | None = None) -> str:
    team = ctx.team.get("team", {}) or {}
    base = override or str(team.get("id") or team.get("name") or "agent-team")
    return kebab_case(base, "agent-team")


def workbuddy_category_for(ctx: TeamContext) -> str:
    text = json.dumps(ctx.team, ensure_ascii=False)
    if any(token in text for token in ("合规", "法务", "隐私", "安全", "风控", "风险")):
        return "11-SecurityCompliance"
    if any(token in text for token in ("数据", "模型", "智能", "AI")):
        return "04-DataAI"
    if any(token in text for token in ("运营", "人力", "流程")):
        return "09-OperationsHR"
    return "10-ProjectQuality"


def workbuddy_agent_id(package_name: str, expert_id: str) -> str:
    return kebab_case(f"{package_name}-{expert_id}", f"{package_name}-expert")


def workbuddy_lead_agent_id(package_name: str) -> str:
    return kebab_case(f"{package_name}-team-lead", "agent-team-team-lead")


def workbuddy_team_description(ctx: TeamContext) -> str:
    team = ctx.team.get("team", {}) or {}
    description = str(team.get("description") or "").strip()
    if description:
        return description
    purpose = str(team.get("purpose") or "")
    if purpose:
        return f"WorkBuddy package for an Agents TeamKit team: {purpose}"
    return "WorkBuddy package for an Agents TeamKit team that handles repeatable multi-agent business tasks"


def workbuddy_display_description_zh() -> str:
    return "将业务任务拆成多角色协作流程，按 Topic、Graph、消息和上下文分配稳定推进"


def workbuddy_display_description_en(ctx: TeamContext) -> str:
    team = ctx.team.get("team", {}) or {}
    if team.get("description"):
        return str(team["description"])
    name = str(team.get("name") or team.get("id") or "business team")
    return f"Runs {name} with Agents TeamKit graph, topic, message, context, artifact, and final result commands."


def workbuddy_runtime_skill_text(package_name: str) -> str:
    return f"""---
name: teamkit-runtime
description: This skill runs TeamKit commands for a generated business agent team. Use it to initialize or close task runs, inspect Topic and Graph state, list or add managed Context Items, send or reply to agent messages, request human input, publish artifacts, and archive final results.
agent_created: true
allowed-tools: Read,Bash
---

# TeamKit Runtime

Use this skill when operating the bundled `{package_name}` expert team.

## Command Rule

Stable coordination actions must go through the bundled TeamKit command wrapper:

```bash
{{{{TEAMKIT_SCRIPT}}}} <teamkit arguments>
```

The wrapper defaults `--team` to the packaged `teamkit-workspace/team.yaml`. Use `--team <path>` only when the user explicitly wants to operate another TeamKit team definition.

## Common Flow

The wrapper supports `team validate`, `run init`, `run status`, `run close`, `topic status`, `graph next`, `graph advance`, `msg`, `context`, `human`, `artifact`, `result`, and the batch ledger commands. Use `run close` to close a task run. `run status` includes graph actions, active nodes, and next expert/task information.

Do not edit `topic.yaml`, `messages.jsonl`, `events.jsonl`, `context-items.jsonl`, `human-review.jsonl`, `state.yaml`, or artifact index files directly.
"""


def workbuddy_teamkit_wrapper_text(team_id: str = "") -> str:
    marker = f".workbuddy/teamkit-runs/{team_id}" if team_id else ".workbuddy/teamkit-runs"
    return f"""#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def teamkit_python(plugin_root: Path) -> str:
    configured = os.environ.get("TEAMKIT_PYTHON", "").strip()
    if configured:
        return configured
    managed = plugin_root / ".agents-teamkit-runtime" / "venv" / "bin" / "python"
    if managed.exists():
        return str(managed)
    return sys.executable


def main() -> int:
    script = Path(__file__).resolve()
    plugin_root = script.parents[3]
    os.environ.setdefault("TEAMKIT_RUNS_DIR", str(Path.home() / "{marker}"))
    teamkit_cli = plugin_root / "vendor" / "teamkit" / "teamkit" / "cli.py"
    team_file = Path(os.environ.get("TEAMKIT_TEAM_FILE", plugin_root / "teamkit-workspace" / "team.yaml"))
    args = list(sys.argv[1:])
    if "--team" not in args and not any(arg.startswith("--team=") for arg in args):
        args = ["--team", str(team_file), *args]
    return subprocess.call([teamkit_python(plugin_root), str(teamkit_cli), *args])


if __name__ == "__main__":
    raise SystemExit(main())
"""


def workbuddy_init_wrapper_text() -> str:
    return """#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import os
import sys
from pathlib import Path


def teamkit_python(plugin_root: Path) -> str:
    configured = os.environ.get("TEAMKIT_PYTHON", "").strip()
    if configured:
        return configured
    managed = plugin_root / ".agents-teamkit-runtime" / "venv" / "bin" / "python"
    if managed.exists():
        return str(managed)
    return sys.executable


def main() -> int:
    script = Path(__file__).resolve()
    plugin_root = script.parents[3]
    teamkit_cli = plugin_root / "vendor" / "teamkit" / "teamkit" / "cli.py"
    return subprocess.call([teamkit_python(plugin_root), str(teamkit_cli), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
"""


def workbuddy_agent_frontmatter(
    agent_id: str,
    display_name_zh: str,
    display_name_en: str,
    profession_zh: str,
    profession_en: str,
    description: str,
    max_turns: int,
    skills: list[str] | None = None,
) -> str:
    skill_list = ", ".join(skills or ["teamkit-runtime"])
    return f"""---
name: {agent_id}
description: "{description}"
displayName:
  en: "{display_name_en}"
  zh: "{display_name_zh}"
profession:
  en: "{profession_en}"
  zh: "{profession_zh}"
maxTurns: {max_turns}
skills: [{skill_list}]
---
"""


def workbuddy_lead_markdown(ctx: TeamContext, package_name: str, lead_id: str, member_ids: dict[str, str]) -> str:
    team = ctx.team.get("team", {}) or {}
    team_name = str(team.get("name") or team.get("id") or package_name)
    coordinator = str(ctx.process().get("coordinator") or ctx.process().get("lead") or "")
    rows = [
        "| Agent ID | Expert | Responsibility |",
        "|---|---|---|",
    ]
    for expert_id, expert in ctx.experts.items():
        rows.append(
            f"| `{member_ids.get(expert_id, lead_id)}` | {expert.get('name', expert_id)} | {expert.get('profile', '')} |"
        )
    graph_nodes = [
        f"- `{node.get('id')}` -> `{node.get('expert')}`: {node.get('task', '')}"
        for node in ctx.graph_nodes()
    ]
    graph_edges = [
        f"- `{edge.get('from')}` -> `{edge.get('to')}` ({edge.get('relation', 'next')}) when {edge.get('when', '')}"
        for edge in ctx.graph_edges()
    ]
    mode = ctx.communication_mode()
    allowed_pairs = []
    for sender in ctx.experts:
        for recipient in ctx.experts:
            if sender != recipient and ctx.communication_allowed(sender, recipient):
                allowed_pairs.append(f"{sender} -> {recipient}")
    return (
        workbuddy_agent_frontmatter(
            lead_id,
            team_name,
            team_name,
            "任务编排官",
            "Task Orchestrator",
            f"Coordinates the {team_name} expert team through TeamKit graph and topic commands.",
            180,
        )
        + f"""
# {team_name} - 主理人

你是这个 WorkBuddy Agent 团队的主理人，负责使用 TeamKit 协议记录可执行的 run、Topic、Graph、Message 和 Context Item。

## 团队成员

{chr(10).join(rows)}

## 协议能力

可用命令包括 `team validate`、`run init/status/close`、`topic status/update`、`graph next/advance`、`msg`、`context`、`human`、`artifact`、`result` 以及 `batch init/next/update/status/recover`。账本文件只能由 TeamKit 命令修改；只有主理人或被明确授权者可以使用 `graph advance` 或 `topic update` 推进共享状态。
`run status` 聚合当前 Graph actions、active nodes、next expert/task、消息、Context、artifact 和 human review 信息；`graph advance` 返回推进后的下一步信息。

## Graph Nodes

{chr(10).join(graph_nodes) if graph_nodes else "- 未配置 process.graph；请先修正团队定义。"}

## Graph Edges

{chr(10).join(graph_edges) if graph_edges else "- 未配置 process.graph edges。"}

## 通信事实

- communication.mode: `{mode}`
- 图节点与边定义了当前团队的流程事实；并行边使用 `relation: parallel`，汇聚节点可声明 `join: all`。
- 当前 core 派生的可通信专家对：{", ".join(allowed_pairs) if allowed_pairs else "（无额外许可）"}
- 消息 reply/close、required message、human review 和 Topic waiting 的状态由协议账本记录。

## Coordinator

TeamKit coordinator expert id: `{coordinator or 'not configured'}`
"""
    )


def workbuddy_member_markdown(ctx: TeamContext, package_name: str, expert_id: str, agent_id: str) -> str:
    expert = ctx.experts[expert_id]
    name = str(expert.get("name") or expert_id)
    profile_path = ctx.profile_path(expert)
    profile = profile_path.read_text(encoding="utf-8") if profile_path.exists() else ""
    return (
        workbuddy_agent_frontmatter(
            agent_id,
            name,
            name,
            name,
            name,
            f"Handles the {name} responsibility in the {package_name} TeamKit workflow.",
            80,
        )
        + f"""
# {name}

你是 `{expert_id}` 专家，负责完成 TeamKit 团队定义中分配给你的业务职责。

## 原始专家 Profile

{profile.strip()}

## TeamKit 能力

- 可使用 `{{{{TEAMKIT_SCRIPT}}}} run status` 查看聚合状态，并按团队通信许可使用 `msg send/reply/close`。
- 可使用 `{{{{TEAMKIT_SCRIPT}}}} context list` 读取已授权 Context Item，使用 `context add` 追加受管资料。
- 可使用 `artifact publish` 发布可引用产出；消息正文应保持简洁并通过 `artifactRefs` 引用文件。
- 不直接编辑 TeamKit ledgers；以 Topic、Graph、Message 状态为准。
"""
    )


def workbuddy_init_runtime_skill_text() -> str:
    return """---
name: agents-teamkit-workbench-runtime
description: Run TeamKit commands from the Agents TeamKit 工作台 package. Use this to validate team definitions, manage team Context visibility, compile execution plans, export user-created teams as WorkBuddy packages, and install generated packages.
agent_created: true
allowed-tools: Read,Bash
---

# Agents TeamKit Workbench Runtime

Use this skill when the user wants to validate, compile, export, or install a TeamKit team they are creating in WorkBuddy.

## Command Rule

Run TeamKit through the bundled wrapper:

```bash
{{TEAMKIT_SCRIPT}} <teamkit arguments>
```

This workbench package is not bound to one team. Always pass `--team <path-to-team.yaml>` for team-specific commands.

## Common Commands

```bash
{{TEAMKIT_SCRIPT}} --team <team-dir>/team.yaml team validate
{{TEAMKIT_SCRIPT}} --team <team-dir>/team.yaml team context list
{{TEAMKIT_SCRIPT}} --team <team-dir>/team.yaml team context add --id <context-id> --name "<display-name>" --file <uploaded-file> --scope agents --visible-to <expert-id>
{{TEAMKIT_SCRIPT}} --team <team-dir>/team.yaml team context assign --context <context-id> --visible-to <expert-id>
{{TEAMKIT_SCRIPT}} --team <team-dir>/team.yaml team compile --out <team-dir>/build/execution-plan.json
{{TEAMKIT_SCRIPT}} --team <team-dir>/team.yaml workbuddy export --out <team-dir>/build/workbuddy --force
{{TEAMKIT_SCRIPT}} workbuddy install --package <team-dir>/build/workbuddy/<package-name> --force
```

Use `context`, `topic`, `graph`, `msg`, `human`, `artifact`, and `result` commands only after a concrete team run exists.
"""


def workbuddy_init_agent_markdown(package_name: str, agent_id: str) -> str:
    return (
        workbuddy_agent_frontmatter(
            agent_id,
            "Agents TeamKit 工作台",
            "Agents TeamKit Workbench",
            "Agents TeamKit 团队工作台",
            "Agents TeamKit Team Workbench",
            "Helps business users create, manage, validate, export, and improve Agents TeamKit multi-agent teams for WorkBuddy trial use.",
            180,
            ["agent-team-builder", "agent-prompt-optimizer", "agents-teamkit-workbench-runtime"],
        )
        + f"""
# Agents TeamKit 工作台

你是 WorkBuddy 里的 Agents TeamKit 工作台，负责帮助业务用户设计、创建、管理、校验、导出和迭代他们自己的 TeamKit 多 Agent 团队。

## 你要坚持的产品模型

- 用户定义 Team、Agent role、Flow Graph、Topic、Context Item 和 Output。
- TeamKit 负责让协作、通信、Topic、Context Item、artifact 和结果记录稳定可见。
- WorkBuddy 和用户自己的 Agent 配置负责工具、Skill、MCP、API 权限。
- 不把工具注册表、API schema、MCP 配置暴露给业务用户。

## 标准工作流

1. 使用 `agent-team-builder` 引导用户定义团队、角色、流程、Context Item 可见范围和输出。
2. 将团队保存为用户可编辑的 `team.yaml`、`experts/*.md`、`references/*` 或 `contexts/*`。
3. 当用户上传资料、指定专家可见范围或要求你推荐资料分配时，使用 `agent-team-builder` 的上下文管理流程，并通过 `agents-teamkit-workbench-runtime` 里的 `team context` 命令修改 `team.yaml`。
4. 使用 `agents-teamkit-workbench-runtime` 校验和编译团队定义。
5. 用户准备试用时，将该团队导出为 WorkBuddy Team 包并安装。
6. 用户跑过真实任务后，使用 `agent-prompt-optimizer` 优化具体 Agent 定义。

## 团队定义工作目录规则

这里的目录是 TeamKit 团队定义工作目录，用于保存 `team.yaml`、`experts/*.md`、`references/*`、`contexts/*` 等可编辑文件，不是 WorkBuddy 专家团安装目录。

如果用户没有指定工作目录，不要自行选择本机路径。先询问用户希望把团队定义保存在哪里，并说明将创建的文件清单。

WorkBuddy 专家团安装目录由 `workbuddy install` 写入 WorkBuddy 固定的用户专家 marketplace 插件目录，不要让用户手动选择或混淆这两个位置。

在真正写入文件前，必须确认团队 ID、团队定义工作目录和将要创建的文件清单。

## 工作台边界

- 可以定义角色需要看到哪些 Context Items。
- 可以根据用户上传文件、文件内容和专家职责推荐 Context Item 可见范围。
- 可以在角色 profile 中记录“这个角色工作时可能需要使用某类 WorkBuddy 能力”。
- 不直接让用户修改 profile 中的 TeamKit Rules 或协议性命令说明。
- 不直接绑定、分配或配置 WorkBuddy Skill、MCP、API 工具。
- 不替用户做业务结论；工作台只创建、管理和优化团队。

Package id: `{package_name}`
"""
    )


def workbuddy_skill_text_for_package(source_skill: Path, allowed_tools: str) -> str:
    skill_md = source_skill / "SKILL.md"
    if not skill_md.exists():
        raise TeamKitError(f"skill not found: {skill_md}")
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return text
    try:
        header, body = text[4:].split("\n---", 1)
    except ValueError:
        return text
    metadata = yaml.safe_load(header) or {}
    if not isinstance(metadata, dict):
        return text
    metadata["agent_created"] = True
    metadata["allowed-tools"] = allowed_tools
    rendered = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{rendered}\n---{body}"


def copy_workbuddy_skill(source_skill: Path, target_skill: Path, allowed_tools: str) -> None:
    shutil.copytree(
        source_skill,
        target_skill,
        ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc"),
    )
    (target_skill / "SKILL.md").write_text(
        workbuddy_skill_text_for_package(source_skill, allowed_tools),
        encoding="utf-8",
    )


def copy_if_exists(source: Path, target: Path) -> None:
    if source.exists():
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def export_workbuddy_package(ctx: TeamContext, out_root: Path, package_name: str, force: bool = False) -> Path:
    validate_or_raise(ctx)
    package_dir = out_root.expanduser().resolve() / package_name
    if package_dir.exists():
        if not force:
            raise TeamKitError(f"WorkBuddy package already exists: {package_dir}; use --force")
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    team = ctx.team.get("team", {}) or {}
    team_name = str(team.get("name") or package_name)
    coordinator = str(ctx.process().get("coordinator") or ctx.process().get("lead") or "")
    lead_id = workbuddy_lead_agent_id(package_name)
    member_ids = {
        expert_id: (lead_id if expert_id == coordinator else workbuddy_agent_id(package_name, expert_id))
        for expert_id in ctx.experts
    }
    if coordinator not in ctx.experts:
        first_expert = next(iter(ctx.experts), "")
        if first_expert:
            member_ids[first_expert] = lead_id

    agents_dir = package_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / f"{lead_id}.md").write_text(
        workbuddy_lead_markdown(ctx, package_name, lead_id, member_ids),
        encoding="utf-8",
    )
    for expert_id, agent_id in member_ids.items():
        if agent_id == lead_id:
            continue
        (agents_dir / f"{agent_id}.md").write_text(
            workbuddy_member_markdown(ctx, package_name, expert_id, agent_id),
            encoding="utf-8",
        )

    skill_dir = package_dir / "skills" / "teamkit-runtime"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(workbuddy_runtime_skill_text(package_name), encoding="utf-8")
    wrapper = skill_dir / "scripts" / "teamkit.py"
    team_id = str((ctx.team.get("team", {}) or {}).get("id") or package_name)
    wrapper.write_text(workbuddy_teamkit_wrapper_text(team_id), encoding="utf-8")
    wrapper.chmod(0o755)

    workspace = package_dir / "teamkit-workspace"
    workspace.mkdir()
    shutil.copyfile(ctx.team_file, workspace / "team.yaml")
    copy_if_exists(ctx.root / "experts", workspace / "experts")
    copy_if_exists(ctx.root / "references", workspace / "references")
    copy_if_exists(ctx.root / "contexts", workspace / "contexts")

    vendor_teamkit = package_dir / "vendor" / "teamkit" / "teamkit"
    vendor_teamkit.mkdir(parents=True)
    source_teamkit = Path(__file__).resolve().parent
    shutil.copyfile(source_teamkit / "cli.py", vendor_teamkit / "cli.py")
    shutil.copyfile(source_teamkit / "__init__.py", vendor_teamkit / "__init__.py")

    (package_dir / "avatars").mkdir()
    (package_dir / "avatars" / ".gitkeep").touch()
    (package_dir / "settings.json").write_text(json.dumps({"agent": lead_id}, indent=2) + "\n", encoding="utf-8")

    agents = [f"./agents/{lead_id}.md"] + [
        f"./agents/{agent_id}.md"
        for expert_id, agent_id in member_ids.items()
        if agent_id != lead_id
    ]
    member_agents = [
        agent_id
        for agent_id in member_ids.values()
        if agent_id != lead_id
    ]
    plugin = {
        "name": package_name,
        "version": __version__,
        "description": workbuddy_team_description(ctx),
        "author": {"name": "Agents TeamKit contributors", "url": "https://github.com/Jaulous/agents-teamkit"},
        "agents": agents,
        "skills": ["./skills/teamkit-runtime"],
        "expertType": "team",
        "agentName": lead_id,
        "teamInfo": {"leadAgent": lead_id, "memberAgents": member_agents},
        "displayName": {"en": team_name, "zh": team_name},
        "profession": {"en": team_name, "zh": team_name},
        "displayDescription": {
            "en": workbuddy_display_description_en(ctx),
            "zh": workbuddy_display_description_zh(),
        },
        "avatar": "avatars/team.png",
        "categoryId": workbuddy_category_for(ctx),
        "defaultInitPrompt": {
            "zh": "请使用这个 Agent 团队处理一个任务，并先帮我初始化运行空间。",
            "en": "Use this agent team to handle one task and initialize the run workspace first.",
        },
        "plugin": package_name,
        "tags": [
            {"en": "Multi-agent", "zh": "多专家协作"},
            {"en": "Team", "zh": "团队编排"},
            {"en": "Context", "zh": "上下文分配"},
        ],
        "quickPrompts": [
            {
                "zh": "请使用这个 Agent 团队处理一个任务，并先帮我初始化运行空间。",
                "en": "Use this agent team to handle one task and initialize the run workspace first.",
            },
            {
                "zh": "帮我查看当前 run 的 Topic、Graph、Context 和待处理消息。",
                "en": "Show the current run topic, graph, context, and open messages.",
            },
            {
                "zh": "根据这次运行结果，帮我优化团队成员定义。",
                "en": "Improve the team member definitions based on this run.",
            },
        ],
        "members": [
            {
                "id": lead_id,
                "displayName": {"en": team_name, "zh": team_name},
                "profession": {"en": "Task Orchestrator", "zh": "任务编排官"},
                "avatar": f"avatars/{lead_id}.png",
                "role": "lead",
            },
            *[
                {
                    "id": agent_id,
                    "displayName": {
                        "en": str(ctx.experts[expert_id].get("name") or expert_id),
                        "zh": str(ctx.experts[expert_id].get("name") or expert_id),
                    },
                    "profession": {
                        "en": str(ctx.experts[expert_id].get("name") or expert_id),
                        "zh": str(ctx.experts[expert_id].get("name") or expert_id),
                    },
                    "avatar": f"avatars/{agent_id}.png",
                    "role": "member",
                }
                for expert_id, agent_id in member_ids.items()
                if agent_id != lead_id
            ],
        ],
    }
    write_json(package_dir / ".codebuddy-plugin" / "plugin.json", plugin)
    readme_text = str(team.get("readme") or "")
    (package_dir / "README.md").write_text(
        readme_text or f"""# {team_name}

This is a WorkBuddy Team expert package generated from Agents TeamKit.

## Try It

Ask the team to initialize a task run, then use Topic, Graph, Context, Message, Human, Artifact, and Result commands through the bundled TeamKit Runtime skill.
""",
        encoding="utf-8",
    )
    return package_dir


def export_workbuddy_init_package(
    out_root: Path,
    package_name: str = "agents-teamkit-workbench",
    force: bool = False,
) -> Path:
    package_name = kebab_case(package_name, "agents-teamkit-workbench")
    package_dir = out_root.expanduser().resolve() / package_name
    if package_dir.exists():
        if not force:
            raise TeamKitError(f"WorkBuddy package already exists: {package_dir}; use --force")
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    repo_root = Path(__file__).resolve().parent.parent
    agent_id = kebab_case(f"{package_name}-lead", "agents-teamkit-workbench-lead")
    agents_dir = package_dir / "agents"
    agents_dir.mkdir()
    (agents_dir / f"{agent_id}.md").write_text(
        workbuddy_init_agent_markdown(package_name, agent_id),
        encoding="utf-8",
    )

    skills_dir = package_dir / "skills"
    copy_workbuddy_skill(
        repo_root / "skills" / "agent-team-builder",
        skills_dir / "agent-team-builder",
        "Read,Write,Edit,Bash",
    )
    copy_workbuddy_skill(
        repo_root / "skills" / "agent-prompt-optimizer",
        skills_dir / "agent-prompt-optimizer",
        "Read,Write,Edit,Bash",
    )
    runtime_dir = skills_dir / "agents-teamkit-workbench-runtime"
    (runtime_dir / "scripts").mkdir(parents=True)
    (runtime_dir / "SKILL.md").write_text(workbuddy_init_runtime_skill_text(), encoding="utf-8")
    wrapper = runtime_dir / "scripts" / "teamkit.py"
    wrapper.write_text(workbuddy_init_wrapper_text(), encoding="utf-8")
    wrapper.chmod(0o755)

    vendor_teamkit = package_dir / "vendor" / "teamkit" / "teamkit"
    vendor_teamkit.mkdir(parents=True)
    source_teamkit = Path(__file__).resolve().parent
    shutil.copyfile(source_teamkit / "cli.py", vendor_teamkit / "cli.py")
    shutil.copyfile(source_teamkit / "__init__.py", vendor_teamkit / "__init__.py")

    copy_if_exists(repo_root / "docs", package_dir / "docs")
    copy_if_exists(repo_root / "schemas", package_dir / "schemas")

    (package_dir / "avatars").mkdir()
    (package_dir / "avatars" / ".gitkeep").touch()
    (package_dir / "settings.json").write_text(json.dumps({"agent": agent_id}, indent=2) + "\n", encoding="utf-8")

    plugin = {
        "name": package_name,
        "version": __version__,
        "description": "Agents TeamKit workbench package for creating, managing, validating, exporting, and improving multi-agent teams for WorkBuddy trial use.",
        "author": {"name": "Agents TeamKit contributors", "url": "https://github.com/Jaulous/agents-teamkit"},
        "agents": [f"./agents/{agent_id}.md"],
        "skills": [
            "./skills/agent-team-builder",
            "./skills/agent-prompt-optimizer",
            "./skills/agents-teamkit-workbench-runtime",
        ],
        "expertType": "team",
        "agentName": agent_id,
        "teamInfo": {"leadAgent": agent_id, "memberAgents": []},
        "displayName": {"en": "Agents TeamKit Workbench", "zh": "Agents TeamKit 工作台"},
        "profession": {"en": "Agents TeamKit Workbench", "zh": "Agents TeamKit 工作台"},
        "displayDescription": {
            "en": "Create, manage context visibility, validate, export, and improve Agents TeamKit multi-agent teams for WorkBuddy trial use.",
            "zh": "创建团队、分配上下文、校验导出并优化 Agents TeamKit 多 Agent 团队",
        },
        "avatar": "avatars/team.png",
        "categoryId": "04-DataAI",
        "defaultInitPrompt": {
            "zh": "帮我创建一个新的多 Agent 团队。",
            "en": "Help me create a new multi-agent team.",
        },
        "plugin": package_name,
        "tags": [
            {"en": "Agents TeamKit", "zh": "Agents TeamKit"},
            {"en": "Team Builder", "zh": "团队创建"},
            {"en": "Prompt Optimizer", "zh": "提示词优化"},
        ],
        "quickPrompts": [
            {
                "zh": "帮我创建一个新的多 Agent 团队。",
                "en": "Help me create a new multi-agent team.",
            },
            {
                "zh": "帮我给团队资料分配可见专家。",
                "en": "Help me assign team materials to the right experts.",
            },
            {
                "zh": "帮我把已经定义好的团队导出成 WorkBuddy 团队包。",
                "en": "Export my defined team as a WorkBuddy team package.",
            },
        ],
        "members": [
            {
                "id": agent_id,
                "displayName": {"en": "Agents TeamKit Workbench", "zh": "Agents TeamKit 工作台"},
                "profession": {"en": "Agents TeamKit Team Workbench", "zh": "Agents TeamKit 团队工作台"},
                "avatar": f"avatars/{agent_id}.png",
                "role": "lead",
            }
        ],
    }
    write_json(package_dir / ".codebuddy-plugin" / "plugin.json", plugin)
    (package_dir / "README.md").write_text(
        """# Agents TeamKit 工作台

This is the WorkBuddy Skill carrier for Agents TeamKit team creation and management.

Use it to create or update a user-owned multi-agent team, manage Context Item visibility, validate the generated `team.yaml`, export that team as a WorkBuddy Team package, and improve agent profiles after real runs.
""",
        encoding="utf-8",
    )
    return package_dir


def cmd_workbuddy_export(args: argparse.Namespace) -> int:
    ctx = TeamContext(Path(args.team))
    package_name = workbuddy_package_name(ctx, args.name)
    out_root = Path(args.out).expanduser() if args.out else teamkit_home() / "build" / "workbuddy"
    package_dir = export_workbuddy_package(ctx, out_root, package_name, args.force)
    if args.json:
        print(json.dumps({"packageDir": str(package_dir), "packageName": package_name}, ensure_ascii=False, indent=2))
    else:
        print(str(package_dir))
    return 0


def cmd_workbuddy_export_init(args: argparse.Namespace) -> int:
    out_root = Path(args.out).expanduser() if args.out else teamkit_home() / "build" / "workbuddy"
    package_dir = export_workbuddy_init_package(
        out_root,
        args.name or "agents-teamkit-workbench",
        args.force,
    )
    if args.json:
        print(json.dumps({"packageDir": str(package_dir), "packageName": package_dir.name}, ensure_ascii=False, indent=2))
    else:
        print(str(package_dir))
    return 0


def find_workbuddy_plugin_json(package_dir: Path) -> Path:
    plugin_json = package_dir / ".codebuddy-plugin" / "plugin.json"
    if not plugin_json.exists():
        raise TeamKitError(f"WorkBuddy plugin.json not found: {plugin_json}")
    return plugin_json


def register_workbuddy_package(package_dir: Path, config_dir: Path, session_id: str = "") -> Path:
    plugin_data = json.loads(find_workbuddy_plugin_json(package_dir).read_text(encoding="utf-8"))
    package_name = str(plugin_data.get("name") or package_dir.name)
    marketplace_dir = workbuddy_marketplace_dir(config_dir)
    manifest_path = marketplace_dir / ".codebuddy-plugin" / "marketplace.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = {
            "name": "my-experts",
            "description": "my-experts marketplace (auto-generated)",
            "plugins": [],
        }
    plugins = manifest.setdefault("plugins", [])
    source = f"./plugins/{package_name}"
    existing = next(
        (item for item in plugins if item.get("name") == package_name or item.get("source") == source),
        None,
    )
    entry = {
        "name": package_name,
        "source": source,
        "description": str(plugin_data.get("description") or ""),
    }
    if existing:
        existing.update(entry)
    else:
        plugins.append(entry)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if session_id:
        (package_dir / ".created-by-session").write_text(session_id, encoding="utf-8")
    return manifest_path


def unregister_workbuddy_package(package_name: str, config_dir: Path) -> tuple[Path, bool]:
    marketplace_dir = workbuddy_marketplace_dir(config_dir)
    manifest_path = marketplace_dir / ".codebuddy-plugin" / "marketplace.json"
    manifest = {
        "name": "my-experts",
        "displayName": "My Experts",
        "plugins": [],
    }
    removed = False
    if manifest_path.exists():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            manifest.update(loaded)
    plugins = manifest.get("plugins")
    if not isinstance(plugins, list):
        plugins = []
    kept = []
    for item in plugins:
        if isinstance(item, dict) and item.get("name") == package_name:
            removed = True
            continue
        kept.append(item)
    manifest["plugins"] = kept
    write_json(manifest_path, manifest)
    return manifest_path, removed


def runtime_python_path(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def pip_runtime_env(strip_proxy: bool = False) -> dict[str, str]:
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_CACHE_DIR"] = "1"
    if strip_proxy:
        for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"):
            env.pop(key, None)
    return env


def run_python_module(python: Path, module: str, args: list[str], strip_proxy: bool = False) -> None:
    cmd = [str(python), "-m", module, *args]
    result = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
        env=pip_runtime_env(strip_proxy=strip_proxy),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise TeamKitError(f"failed to run {' '.join(cmd)}: {detail}")


def ensure_workbuddy_runtime_env(package_dir: Path) -> Path | None:
    if os.environ.get("TEAMKIT_SKIP_RUNTIME_ENV", "").strip().lower() in {"1", "true", "yes"}:
        return None
    teamkit_cli = package_dir / "vendor" / "teamkit" / "teamkit" / "cli.py"
    if not teamkit_cli.exists():
        return None
    runtime_dir = package_dir / ".agents-teamkit-runtime"
    venv_dir = runtime_dir / "venv"
    python = runtime_python_path(venv_dir)
    venv_result = subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        text=True,
        capture_output=True,
        check=False,
    )
    if venv_result.returncode != 0:
        detail = (venv_result.stderr or venv_result.stdout or "").strip()
        raise TeamKitError(f"failed to create package-local runtime at {venv_dir}: {detail}")
    proxy_text = "".join(
        os.environ.get(key, "")
        for key in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy")
    )
    try:
        run_python_module(python, "pip", ["install", "PyYAML>=6.0"], strip_proxy=("socks" in proxy_text.lower()))
    except TeamKitError:
        run_python_module(python, "pip", ["install", "PyYAML>=6.0"], strip_proxy=True)
    run_python_module(python, "pip", ["show", "PyYAML"], strip_proxy=True)
    (runtime_dir / "README.md").write_text(
        "Package-local Python runtime for Agents TeamKit. Safe to remove together with this WorkBuddy plugin.\n",
        encoding="utf-8",
    )
    return runtime_dir


def render_installed_teamkit_script_paths(target: Path) -> None:
    wrappers = [path for path in target.glob("skills/*/scripts/teamkit.py") if path.is_file()]
    if not wrappers:
        return
    replacement = str(wrappers[0].resolve())
    # Render generated prompt-bearing files only. Vendored cli.py contains the
    # template source itself and must remain portable for future exports.
    roots = [target / "agents", target / "skills"]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path in wrappers:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if "{{TEAMKIT_SCRIPT}}" in text:
                atomic_write_text(path, text.replace("{{TEAMKIT_SCRIPT}}", replacement))


def cmd_workbuddy_install(args: argparse.Namespace) -> int:
    source = Path(args.package).expanduser().resolve()
    if not source.exists() or not source.is_dir():
        raise TeamKitError(f"WorkBuddy package directory not found: {source}")
    plugin_data = json.loads(find_workbuddy_plugin_json(source).read_text(encoding="utf-8"))
    package_name = str(plugin_data.get("name") or source.name)
    config_dir = workbuddy_config_dir(args.config_dir)
    target = workbuddy_plugins_dir(config_dir) / package_name
    if target.exists():
        if not args.force:
            raise TeamKitError(f"WorkBuddy package already installed: {target}; use --force")
        legacy_runs = target / "teamkit-workspace" / "runs"
        if legacy_runs.exists():
            retained = [item for item in legacy_runs.iterdir() if item.name != ".gitkeep"]
            if retained:
                print(f"warning: {legacy_runs} contains runtime data and will be deleted", file=sys.stderr)
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    render_installed_teamkit_script_paths(target)
    runtime_dir = ensure_workbuddy_runtime_env(target)
    manifest_path = register_workbuddy_package(target, config_dir, args.session_id or "teamkit-local-install")
    result = {
        "installedDir": str(target),
        "marketplacePath": str(manifest_path),
        "packageName": package_name,
    }
    if runtime_dir:
        result["runtimeDir"] = str(runtime_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(str(target))
    return 0


def cmd_workbuddy_uninstall(args: argparse.Namespace) -> int:
    package_name = kebab_case(args.package, args.package)
    config_dir = workbuddy_config_dir(args.config_dir)
    target = workbuddy_plugins_dir(config_dir) / package_name
    existed = target.exists()
    if existed:
        legacy_runs = target / "teamkit-workspace" / "runs"
        if legacy_runs.exists():
            retained = [item for item in legacy_runs.iterdir() if item.name != ".gitkeep"]
            if retained:
                print(f"warning: {legacy_runs} contains runtime data and will be deleted", file=sys.stderr)
        shutil.rmtree(target)
    elif not args.force:
        raise TeamKitError(f"WorkBuddy package is not installed: {package_name}; use --force to ignore")
    manifest_path, registered = unregister_workbuddy_package(package_name, config_dir)
    result = {
        "packageName": package_name,
        "removedDir": str(target),
        "directoryExisted": existed,
        "marketplacePath": str(manifest_path),
        "registrationRemoved": registered,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(package_name)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="teamkit",
        description="Deterministic command layer for TeamKit. Pass --team PATH anywhere; default is team.yaml.",
    )
    sub = parser.add_subparsers(dest="area", required=True)

    home = sub.add_parser("home")
    home.add_argument("--run")
    home.add_argument("--json", action="store_true")
    home.set_defaults(func=cmd_home)

    team = sub.add_parser("team")
    team_sub = team.add_subparsers(dest="command", required=True)
    team_validate = team_sub.add_parser("validate")
    team_validate.set_defaults(func=cmd_team_validate)
    team_compile = team_sub.add_parser("compile")
    team_compile.add_argument("--out")
    team_compile.set_defaults(func=cmd_team_compile)
    team_context = team_sub.add_parser("context")
    team_context_sub = team_context.add_subparsers(dest="context_command", required=True)
    team_context_list = team_context_sub.add_parser("list")
    team_context_list.add_argument("--expert")
    team_context_list.add_argument("--visible-to")
    team_context_list.add_argument("--json", action="store_true")
    team_context_list.set_defaults(func=cmd_team_context_list)
    team_context_add = team_context_sub.add_parser("add")
    team_context_add.add_argument("--id", required=True)
    team_context_add.add_argument("--name")
    team_context_add.add_argument("--file")
    team_context_add.add_argument("--source")
    team_context_add.add_argument("--scope", default="team", choices=sorted(CONTEXT_SCOPES))
    team_context_add.add_argument("--visible-to", action="append")
    team_context_add.add_argument("--summary")
    team_context_add.add_argument("--summary-file")
    team_context_add.add_argument("--force", action="store_true")
    team_context_add.add_argument("--json", action="store_true")
    team_context_add.set_defaults(func=cmd_team_context_add)
    team_context_assign = team_context_sub.add_parser("assign")
    team_context_assign.add_argument("--context", required=True)
    team_context_assign.add_argument("--visible-to", action="append", required=True)
    team_context_assign.add_argument("--json", action="store_true")
    team_context_assign.set_defaults(func=cmd_team_context_assign)
    team_context_unassign = team_context_sub.add_parser("unassign")
    team_context_unassign.add_argument("--context", required=True)
    team_context_unassign.add_argument("--visible-to", action="append", required=True)
    team_context_unassign.add_argument("--json", action="store_true")
    team_context_unassign.set_defaults(func=cmd_team_context_unassign)
    team_context_remove = team_context_sub.add_parser("remove")
    team_context_remove.add_argument("--context", required=True)
    team_context_remove.add_argument("--json", action="store_true")
    team_context_remove.set_defaults(func=cmd_team_context_remove)

    run = sub.add_parser("run")
    run_sub = run.add_subparsers(dest="command", required=True)
    run_init = run_sub.add_parser("init")
    run_init.add_argument("--run", required=True)
    run_init.add_argument("--brief")
    run_init.add_argument("--force", action="store_true")
    run_init.set_defaults(func=locked_run_command(cmd_run_init))
    run_status = run_sub.add_parser("status")
    run_status.add_argument("--run", required=True)
    run_status.add_argument("--json", action="store_true")
    run_status.set_defaults(func=cmd_run_status)
    run_close = run_sub.add_parser("close")
    run_close.add_argument("--run", required=True)
    run_close.add_argument("--by")
    run_close.add_argument("--summary")
    run_close.add_argument("--summary-file")
    run_close.set_defaults(func=locked_run_command(cmd_run_close))

    topic = sub.add_parser("topic")
    topic_sub = topic.add_subparsers(dest="command", required=True)
    topic_status = topic_sub.add_parser("status")
    topic_status.add_argument("--run", required=True)
    topic_status.add_argument("--json", action="store_true")
    topic_status.set_defaults(func=cmd_topic_status)
    topic_update = topic_sub.add_parser("update")
    topic_update.add_argument("--run", required=True)
    topic_update.add_argument("--status", choices=sorted(TOPIC_STATUSES))
    topic_update.add_argument("--responsible")
    topic_update.add_argument("--current-node")
    topic_update.add_argument("--summary")
    topic_update.add_argument("--summary-file")
    topic_update.add_argument("--waiting-type")
    topic_update.add_argument("--waiting-ref")
    topic_update.add_argument("--waiting-summary")
    topic_update.add_argument("--clear-waiting", action="store_true")
    topic_update.add_argument("--evidence-ref", action="append")
    topic_update.add_argument("--by")
    topic_update.add_argument("--json", action="store_true")
    topic_update.set_defaults(func=locked_run_command(cmd_topic_update))
    topic_link = topic_sub.add_parser("link")
    topic_link.add_argument("--run", required=True)
    topic_link.add_argument("--ref", required=True)
    topic_link.add_argument("--label")
    topic_link.add_argument("--by")
    topic_link.set_defaults(func=locked_run_command(cmd_topic_link))

    graph = sub.add_parser("graph")
    graph_sub = graph.add_subparsers(dest="command", required=True)
    graph_next = graph_sub.add_parser("next")
    graph_next.add_argument("--run", required=True)
    graph_next.add_argument("--from-node")
    graph_next.add_argument("--ignore-waiting", action="store_true")
    graph_next.add_argument("--json", action="store_true")
    graph_next.set_defaults(func=cmd_graph_next)
    graph_advance = graph_sub.add_parser("advance")
    graph_advance.add_argument("--run", required=True)
    graph_advance.add_argument("--node")
    graph_advance.add_argument("--edge")
    graph_advance.add_argument("--to")
    graph_advance.add_argument("--summary")
    graph_advance.add_argument("--summary-file")
    graph_advance.add_argument("--by")
    graph_advance.add_argument("--json", action="store_true")
    graph_advance.set_defaults(func=locked_run_command(cmd_graph_advance))

    msg = sub.add_parser("msg")
    msg_sub = msg.add_subparsers(dest="command", required=True)
    send = msg_sub.add_parser("send")
    send.add_argument("--run", required=True)
    send.add_argument("--from", dest="from_expert", required=True)
    send.add_argument("--to", required=True)
    send.add_argument("--subject", required=True)
    send.add_argument("--body")
    send.add_argument("--body-file")
    send.add_argument("--response", choices=sorted(RESPONSE_MODES))
    send.add_argument("--type", default="request")
    send.add_argument("--intent")
    send.add_argument("--topic")
    send.add_argument("--node")
    send.add_argument("--artifact-ref", action="append")
    send.add_argument("--evidence-ref", action="append")
    send.add_argument("--priority", default="normal")
    send.add_argument("--force", action="store_true")
    send.set_defaults(func=locked_run_command(cmd_msg_send))

    reply = msg_sub.add_parser("reply")
    reply.add_argument("--run", required=True)
    reply.add_argument("--from", dest="from_expert", required=True)
    reply.add_argument("--reply-to", required=True)
    reply.add_argument("--subject")
    reply.add_argument("--body")
    reply.add_argument("--body-file")
    reply.add_argument("--artifact-ref", action="append")
    reply.add_argument("--evidence-ref", action="append")
    reply.set_defaults(func=locked_run_command(cmd_msg_reply))

    close = msg_sub.add_parser("close")
    close.add_argument("--run", required=True)
    close.add_argument("--from", dest="from_expert", required=True)
    close.add_argument("--message", required=True)
    close.add_argument(
        "--resolution",
        required=True,
        choices=["no_reply", "cancelled", "superseded", "completed_elsewhere"],
    )
    close.add_argument("--reason", required=True)
    close.set_defaults(func=locked_run_command(cmd_msg_close))

    list_cmd = msg_sub.add_parser("list")
    list_cmd.add_argument("--run", required=True)
    list_cmd.add_argument("--status")
    list_cmd.add_argument("--expert")
    list_cmd.add_argument("--json", action="store_true")
    list_cmd.set_defaults(func=cmd_msg_list)

    artifact = sub.add_parser("artifact")
    artifact_sub = artifact.add_subparsers(dest="command", required=True)
    artifact_publish = artifact_sub.add_parser("publish")
    artifact_publish.add_argument("--run", required=True)
    artifact_publish.add_argument("--from", dest="from_expert", required=True)
    artifact_publish.add_argument("--file", required=True)
    artifact_publish.add_argument(
        "--kind",
        default="expert_result",
        choices=["expert_result", "final", "other"],
    )
    artifact_publish.set_defaults(func=locked_run_command(cmd_artifact_publish))

    artifact_list = artifact_sub.add_parser("list")
    artifact_list.add_argument("--run", required=True)
    artifact_list.add_argument("--kind")
    artifact_list.add_argument("--json", action="store_true")
    artifact_list.set_defaults(func=cmd_artifact_list)

    context = sub.add_parser("context")
    context_sub = context.add_subparsers(dest="command", required=True)
    context_add = context_sub.add_parser("add")
    context_add.add_argument("--run", required=True)
    context_add.add_argument("--file")
    context_add.add_argument("--text")
    context_add.add_argument("--text-file")
    context_add.add_argument("--id")
    context_add.add_argument("--name")
    context_add.add_argument("--source-type")
    context_add.add_argument("--scope", default="team", choices=sorted(CONTEXT_SCOPES))
    context_add.add_argument("--visible-to", action="append")
    context_add.add_argument("--summary")
    context_add.add_argument("--summary-file")
    context_add.add_argument("--by")
    context_add.set_defaults(func=locked_run_command(cmd_context_add))
    context_list = context_sub.add_parser("list")
    context_list.add_argument("--run", required=True)
    context_list.add_argument("--scope", choices=sorted(CONTEXT_SCOPES))
    context_list.add_argument("--visible-to")
    context_list.add_argument("--json", action="store_true")
    context_list.set_defaults(func=cmd_context_list)

    human = sub.add_parser("human")
    human_sub = human.add_subparsers(dest="command", required=True)
    human_request = human_sub.add_parser("request")
    human_request.add_argument("--run", required=True)
    human_request.add_argument("--from", dest="from_expert", required=True)
    human_request.add_argument("--reason", required=True)
    human_request.add_argument("--question")
    human_request.add_argument("--question-file")
    human_request.add_argument("--artifact-ref", action="append")
    human_request.add_argument("--evidence-ref", action="append")
    human_request.set_defaults(func=locked_run_command(cmd_human_request))
    human_resolve = human_sub.add_parser("resolve")
    human_resolve.add_argument("--run", required=True)
    human_resolve.add_argument("--review", required=True)
    human_resolve.add_argument("--by", default="human")
    human_resolve.add_argument("--resolution", required=True)
    human_resolve.add_argument("--answer")
    human_resolve.add_argument("--answer-file")
    human_resolve.add_argument("--force", action="store_true")
    human_resolve.set_defaults(func=locked_run_command(cmd_human_resolve))
    human_list = human_sub.add_parser("list")
    human_list.add_argument("--run", required=True)
    human_list.add_argument("--status")
    human_list.add_argument("--json", action="store_true")
    human_list.set_defaults(func=cmd_human_list)

    result = sub.add_parser("result")
    result_sub = result.add_subparsers(dest="command", required=True)
    result_publish = result_sub.add_parser("publish")
    result_publish.add_argument("--run", required=True)
    result_publish.add_argument("--from", dest="from_expert", required=True)
    result_publish.add_argument("--file", required=True)
    result_publish.set_defaults(func=locked_run_command(cmd_result_publish))

    batch = sub.add_parser("batch")
    batch_sub = batch.add_subparsers(dest="command", required=True)
    batch_init_parser = batch_sub.add_parser("init")
    batch_init_parser.add_argument("--batch", required=True)
    batch_init_parser.add_argument("--cases-dir", required=True)
    batch_init_parser.add_argument("--force", action="store_true")
    batch_init_parser.add_argument("--json", action="store_true")
    batch_init_parser.set_defaults(func=cmd_batch_init)
    batch_next_parser = batch_sub.add_parser("next")
    batch_next_parser.add_argument("--batch", required=True)
    batch_next_parser.add_argument("--max", type=int, default=1)
    batch_next_parser.set_defaults(func=cmd_batch_next)
    batch_update_parser = batch_sub.add_parser("update")
    batch_update_parser.add_argument("--batch", required=True)
    batch_update_parser.add_argument("--case", required=True)
    batch_update_parser.add_argument("--status", required=True)
    batch_update_parser.add_argument("--run")
    batch_update_parser.set_defaults(func=cmd_batch_update)
    batch_status_parser = batch_sub.add_parser("status")
    batch_status_parser.add_argument("--batch", required=True)
    batch_status_parser.add_argument("--json", action="store_true")
    batch_status_parser.set_defaults(func=cmd_batch_status)
    batch_recover_parser = batch_sub.add_parser("recover")
    batch_recover_parser.add_argument("--batch", required=True)
    batch_recover_parser.add_argument("--stale", type=float)
    batch_recover_parser.add_argument("--json", action="store_true")
    batch_recover_parser.set_defaults(func=cmd_batch_recover)

    workbuddy = sub.add_parser("workbuddy")
    workbuddy_sub = workbuddy.add_subparsers(dest="command", required=True)
    workbuddy_detect = workbuddy_sub.add_parser("detect")
    workbuddy_detect.add_argument("--config-dir")
    workbuddy_detect.add_argument("--json", action="store_true")
    workbuddy_detect.set_defaults(func=cmd_workbuddy_detect)
    workbuddy_export = workbuddy_sub.add_parser("export")
    workbuddy_export.add_argument("--out")
    workbuddy_export.add_argument("--name")
    workbuddy_export.add_argument("--force", action="store_true")
    workbuddy_export.add_argument("--json", action="store_true")
    workbuddy_export.set_defaults(func=cmd_workbuddy_export)
    workbuddy_export_init = workbuddy_sub.add_parser("export-init")
    workbuddy_export_init.add_argument("--out")
    workbuddy_export_init.add_argument("--name")
    workbuddy_export_init.add_argument("--force", action="store_true")
    workbuddy_export_init.add_argument("--json", action="store_true")
    workbuddy_export_init.set_defaults(func=cmd_workbuddy_export_init)
    workbuddy_install = workbuddy_sub.add_parser("install")
    workbuddy_install.add_argument("--package", required=True)
    workbuddy_install.add_argument("--config-dir")
    workbuddy_install.add_argument("--session-id")
    workbuddy_install.add_argument("--force", action="store_true")
    workbuddy_install.add_argument("--json", action="store_true")
    workbuddy_install.set_defaults(func=cmd_workbuddy_install)
    workbuddy_uninstall = workbuddy_sub.add_parser("uninstall")
    workbuddy_uninstall.add_argument("--package", required=True)
    workbuddy_uninstall.add_argument("--config-dir")
    workbuddy_uninstall.add_argument("--force", action="store_true")
    workbuddy_uninstall.add_argument("--json", action="store_true")
    workbuddy_uninstall.set_defaults(func=cmd_workbuddy_uninstall)
    return parser


def extract_team_argument(argv: list[str] | None) -> tuple[str, list[str]]:
    raw = list(sys.argv[1:] if argv is None else argv)
    team = "team.yaml"
    cleaned: list[str] = []
    index = 0
    while index < len(raw):
        token = raw[index]
        if token == "--team":
            if index + 1 >= len(raw):
                raise TeamKitError("--team requires a path")
            team = raw[index + 1]
            index += 2
            continue
        if token.startswith("--team="):
            team = token.split("=", 1)[1]
            index += 1
            continue
        cleaned.append(token)
        index += 1
    return team, cleaned


def main(argv: list[str] | None = None) -> int:
    try:
        team, cleaned = extract_team_argument(argv)
    except TeamKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    parser = build_parser()
    args = parser.parse_args(cleaned)
    args.team = team
    try:
        return args.func(args)
    except TeamKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
