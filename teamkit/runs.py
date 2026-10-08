"""Run ledgers: state, topic, messages, events, artifacts, human input, closure.

A run lives in one directory (``TeamContext.run_base``). Mutating operations
must run inside :meth:`RunStore.lock`; the CLI wraps every write command.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
from typing import Any, Iterator

from teamkit import graph as graph_engine
from teamkit.errors import TeamKitError
from teamkit.fsutil import (
    append_jsonl,
    parse_time,
    atomic_copyfile,
    atomic_write_bytes,
    atomic_write_text,
    display_path,
    file_lock,
    load_yaml,
    now,
    prefixed_id,
    read_json,
    read_jsonl,
    read_jsonl_with_errors,
    sha256_bytes,
    write_json,
    write_jsonl,
    write_yaml,
)
from teamkit.team import TeamContext

OPEN_MESSAGE_STATUSES = {"created", "sent"}
RUN_CLOSED_STATUSES = {"completed", "cancelled", "failed"}
NON_CORRELATING_TYPES = {"question", "escalation"}
HEADER_PATTERN = re.compile(r"\[TeamKit\s+([^\]]*)\]")


def parse_header(text: str) -> dict[str, str]:
    """Parse a ``[TeamKit run=... node=... type=... re=...]`` correlation header."""
    match = HEADER_PATTERN.search(text or "")
    if not match:
        return {}
    fields: dict[str, str] = {}
    for token in match.group(1).split():
        if "=" in token:
            key, _, value = token.partition("=")
            fields[key.strip().lower()] = value.strip().strip(",;")
    return fields


def format_header(run_id: str, node_id: str = "", **extra: str) -> str:
    parts = [f"run={run_id}"]
    if node_id:
        parts.append(f"node={node_id}")
    parts.extend(f"{key}={value}" for key, value in extra.items() if value)
    return "[TeamKit " + " ".join(parts) + "]"


class RunStore:
    """Paths and ledger primitives for one run."""

    def __init__(self, ctx: TeamContext, run_id: str):
        if not run_id or not re.match(r"^[^/\\\s.][^/\\\s]*$", run_id) or ".." in run_id:
            raise TeamKitError(f"invalid run id: {run_id!r} (no path separators, whitespace, '..' or leading '.')")
        self.ctx = ctx
        self.run_id = run_id
        self.base = ctx.run_base(run_id)

    # ------------------------------------------------------------------ paths

    def path(self, key: str, default_relative: str) -> Path:
        return self.ctx.workspace_path(key, self.run_id, default_relative)

    @property
    def state_path(self) -> Path:
        return self.path("state", "state.yaml")

    @property
    def topic_path(self) -> Path:
        return self.path("topic", "topic.yaml")

    @property
    def messages_path(self) -> Path:
        return self.path("message_log", "messages.jsonl")

    @property
    def events_path(self) -> Path:
        return self.path("event_log", "events.jsonl")

    @property
    def context_items_path(self) -> Path:
        return self.path("context_items_log", "context-items.jsonl")

    @property
    def context_dir(self) -> Path:
        return self.path("context_item_dir", "contexts")

    @property
    def human_review_path(self) -> Path:
        return self.path("human_review_log", "human-review.jsonl")

    @property
    def decision_log_path(self) -> Path:
        return self.path("decision_log", "decision-log.md")

    @property
    def expert_dir(self) -> Path:
        return self.path("expert_workspace_dir", "experts")

    @property
    def expert_result_dir(self) -> Path:
        return self.path("expert_result_dir", "artifacts/expert-results")

    @property
    def artifact_index_path(self) -> Path:
        return self.base / "artifacts" / "artifacts.jsonl"

    @property
    def native_index_path(self) -> Path:
        return self.base / "native-sync.json"

    @contextmanager
    def lock(self, create: bool = False) -> Iterator[None]:
        """Exclusive lock for one run. The lock file lives beside the run
        directory so ``run init --force`` can archive the directory while
        holding it, and a mistyped run id never creates an empty run."""
        if not create and not self.state_path.exists():
            raise TeamKitError(f"run not initialized: {self.run_id}")
        with file_lock(self.base.parent / ".locks" / f"{self.run_id}.lock"):
            yield

    # ------------------------------------------------------------------ state / topic

    def exists(self) -> bool:
        return self.state_path.exists()

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            raise TeamKitError(f"run not initialized: {self.run_id}")
        return load_yaml(self.state_path)

    def save_state(self, state: dict[str, Any]) -> None:
        state["updatedAt"] = now()
        write_yaml(self.state_path, state)

    def load_topic(self) -> dict[str, Any]:
        if not self.topic_path.exists():
            raise TeamKitError(f"topic not initialized for run: {self.run_id}")
        return load_yaml(self.topic_path)

    def save_topic(self, topic: dict[str, Any], bump: bool = True) -> None:
        if bump:
            topic["version"] = int(topic.get("version") or 1) + 1
        topic["updatedAt"] = now()
        write_yaml(self.topic_path, topic)

    def sync_state_nodes(self, state: dict[str, Any], topic: dict[str, Any]) -> None:
        state["active_node"] = topic.get("current_node", "")
        state["active_nodes"] = topic.get("active_nodes", [])

    def is_closed(self, state: dict[str, Any] | None = None) -> bool:
        return str((state or self.load_state()).get("status")) in RUN_CLOSED_STATUSES

    # ------------------------------------------------------------------ events

    def event(self, event_type: str, actor: str = "", **extra: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "id": prefixed_id("evt"),
            "type": event_type,
            "runId": self.run_id,
            "createdAt": now(),
        }
        if actor:
            record["actor"] = actor
        record.update({key: value for key, value in extra.items() if value is not None})
        append_jsonl(self.events_path, record)
        return record

    def events(self) -> list[dict[str, Any]]:
        return read_jsonl(self.events_path)

    # ------------------------------------------------------------------ messages

    def messages(self) -> list[dict[str, Any]]:
        return read_jsonl(self.messages_path)

    def open_required(self, node_id: str | None = None) -> list[dict[str, Any]]:
        return [
            msg
            for msg in self.messages()
            if msg.get("response") == "required"
            and msg.get("status") in OPEN_MESSAGE_STATUSES
            and (node_id is None or msg.get("nodeId") == node_id)
        ]

    def open_messages_for(self, topic: dict[str, Any]):
        topic_id = str(topic.get("id") or self.run_id)
        messages = self.messages()

        def lookup(node_id: str) -> list[str]:
            return [
                str(msg["id"])
                for msg in messages
                if msg.get("topicId", topic_id) == topic_id
                and msg.get("nodeId") == node_id
                and msg.get("response") == "required"
                and msg.get("status") in OPEN_MESSAGE_STATUSES
            ]

        return lookup


# ---------------------------------------------------------------------- run lifecycle


def initial_topic(ctx: TeamContext, run_id: str) -> dict[str, Any]:
    entry = ctx.graph_entry_node_id()
    stamp = now()
    return {
        "id": run_id,
        "run_id": run_id,
        "title": ctx.team_name,
        "responsible": ctx.coordinator_id(),
        "participants": list(ctx.experts.keys()),
        "status": "active",
        "summary": "",
        "current_node": entry,
        "active_nodes": [{"node": entry, "status": "active", "waiting_on": [], "activatedAt": stamp}] if entry else [],
        "waiting_on": None,
        "context_refs": [],
        "evidence": [],
        "visits": {entry: 1} if entry else {},
        "version": 1,
        "createdAt": stamp,
        "updatedAt": stamp,
    }


def host_binding_from_env(cwd: Path | None = None) -> dict[str, Any] | None:
    """Capture the host session that runs this command, if a host declared one.

    Host wrappers export ``TEAMKIT_HOST`` (e.g. ``workbuddy``); WorkBuddy's
    Bash tool also exports ``CODEBUDDY_SESSION_ID``. Adapters use the binding
    to find the native team that belongs to the run.
    """
    platform = os.environ.get("TEAMKIT_HOST", "").strip()
    session = os.environ.get("CODEBUDDY_SESSION_ID", "").strip()
    if not platform and not session:
        return None
    binding: dict[str, Any] = {
        "platform": platform or "workbuddy",
        "sessionId": session,
        "cwd": str((cwd or Path.cwd()).resolve()),
        "package": os.environ.get("TEAMKIT_HOST_PACKAGE", "").strip(),
        "boundAt": now(),
    }
    native_team = os.environ.get("TEAMKIT_NATIVE_TEAM", "").strip()
    if native_team:
        binding["nativeTeam"] = native_team
    return binding


def resolve_input_file(ctx: TeamContext, raw_path: str, run_id: str | None = None) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    candidates = []
    if run_id:
        candidates.append(ctx.run_base(run_id) / path)
    candidates.extend([ctx.root / path, Path.cwd() / path])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def init_run(
    store: RunStore,
    *,
    brief: str | None = None,
    force: bool = False,
    host: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from teamkit.contexts import materialize_declared_contexts  # local: avoids import cycle
    from teamkit.validation import validate_or_raise

    ctx = store.ctx
    validate_or_raise(ctx)
    archived_to = ""
    if store.exists():
        if not force:
            raise TeamKitError(f"run already initialized: {store.run_id}; use --force to start it over")
        # --force starts a clean run; the previous ledgers are moved aside, never deleted.
        archive_root = store.base.parent / ".archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        target = archive_root / f"{store.run_id}-{now().replace(':', '').replace('-', '')[:15]}"
        shutil.move(str(store.base), str(target))
        archived_to = str(target)

    store.base.mkdir(parents=True, exist_ok=True)
    for folder in (store.base / "shared", store.context_dir, store.expert_result_dir, store.expert_dir):
        folder.mkdir(parents=True, exist_ok=True)
    for expert_id in ctx.experts:
        folder = store.expert_dir / expert_id
        folder.mkdir(parents=True, exist_ok=True)
        atomic_write_text(folder / "scratch.md", f"# Scratch: {expert_id}\n\n")
        atomic_write_text(folder / "result.md", f"# Result: {expert_id}\n\n")

    brief_path = store.base / "brief.md"
    if brief:
        source = resolve_input_file(ctx, brief)
        if not source.is_file():
            raise TeamKitError(f"brief file not found: {source}")
        atomic_copyfile(source, brief_path)
    else:
        meta = ctx.team_meta()
        atomic_write_text(
            brief_path,
            f"# Run {store.run_id}\n\nTeam: {ctx.team_name}\nPurpose: {meta.get('purpose', '')}\n",
        )
    for ledger in (store.messages_path, store.events_path, store.context_items_path,
                   store.human_review_path, store.artifact_index_path):
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.touch(exist_ok=True)
    atomic_write_text(store.decision_log_path, f"# Decision Log: {store.run_id}\n\n")

    topic = initial_topic(ctx, store.run_id)
    records = materialize_declared_contexts(store)
    topic["context_refs"] = [
        {
            "id": record["id"],
            "name": record["name"],
            "scope": record["scope"],
            "visibleTo": record["visibleTo"],
            "linkedBy": "team",
            "createdAt": record["createdAt"],
        }
        for record in records
    ]
    write_yaml(store.topic_path, topic)
    state: dict[str, Any] = {
        "run_id": store.run_id,
        "topic_id": topic["id"],
        "team_id": ctx.team_id,
        "team_name": ctx.team_name,
        "status": "prepared",
        "process_mode": ctx.process().get("mode", "graph"),
        "active_node": topic["current_node"],
        "active_nodes": topic["active_nodes"],
        "open_messages": [],
        "open_human_reviews": [],
        "context_items": [
            {"id": r["id"], "name": r["name"], "scope": r["scope"], "visibleTo": r["visibleTo"], "path": r["path"]}
            for r in records
        ],
        "artifacts": [],
        "final_result": None,
        "createdAt": now(),
        "updatedAt": now(),
    }
    if host:
        state["host"] = host
    write_yaml(store.state_path, state)
    store.event(
        "run.initialized",
        teamId=state["team_id"],
        runRoot=str(store.base),
        topicId=topic["id"],
        currentNode=topic["current_node"],
        contextCount=len(records),
        host=host,
        archivedPrevious=archived_to or None,
    )
    return {"runId": store.run_id, "runRoot": str(store.base), "archivedPrevious": archived_to, "state": state}


def bind_host(store: RunStore, binding: dict[str, Any]) -> dict[str, Any]:
    state = store.load_state()
    current = state.get("host") if isinstance(state.get("host"), dict) else {}
    merged = {**current, **{k: v for k, v in binding.items() if v not in (None, "")}}
    state["host"] = merged
    store.save_state(state)
    store.event("run.host_bound", host=merged)
    return merged


def close_run(store: RunStore, *, status: str = "completed", summary: str | None = None, by: str = "") -> dict[str, Any]:
    if status not in RUN_CLOSED_STATUSES:
        raise TeamKitError(f"run close status must be one of: {', '.join(sorted(RUN_CLOSED_STATUSES))}")
    state = store.load_state()
    if store.is_closed(state):
        raise TeamKitError("run already closed")
    stamp = now()
    messages = store.messages()
    closed_ids: list[str] = []
    for msg in messages:
        if msg.get("response") == "required" and msg.get("status") in OPEN_MESSAGE_STATUSES:
            msg.update({"status": "closed", "resolution": "run_closed", "resolvedBy": by or "system", "resolvedAt": stamp, "updatedAt": stamp})
            closed_ids.append(str(msg["id"]))
    if closed_ids:
        write_jsonl(store.messages_path, messages)
    state["status"] = status
    state["open_messages"] = []
    state["closedAt"] = stamp
    if store.topic_path.exists():
        topic = store.load_topic()
        topic["status"] = "resolved"
        topic["waiting_on"] = None
        for entry in topic.get("active_nodes") or []:
            if isinstance(entry, dict) and entry.get("status") in {"active", "waiting"}:
                entry["status"] = "done"
        if summary is not None:
            topic["summary"] = summary
        store.save_topic(topic)
        store.sync_state_nodes(state, topic)
    store.save_state(state)
    store.event("run.closed", actor=by, status=status, closedMessages=closed_ids or None)
    return {"runId": store.run_id, "status": status, "closedMessages": closed_ids}


# ---------------------------------------------------------------------- status


def status_view(store: RunStore) -> dict[str, Any]:
    state = store.load_state()
    messages, message_errors = read_jsonl_with_errors(store.messages_path)
    artifacts = read_jsonl(store.artifact_index_path)
    contexts = read_jsonl(store.context_items_path)
    reviews = read_jsonl(store.human_review_path)
    view = dict(state)
    view["open_messages"] = [
        msg["id"] for msg in messages if msg.get("response") == "required" and msg.get("status") in OPEN_MESSAGE_STATUSES
    ]
    view["open_human_reviews"] = [item["id"] for item in reviews if item.get("status") == "open"]
    view["message_count"] = len(messages)
    view["context_item_count"] = len(contexts)
    view["artifact_count"] = len(artifacts)
    view["human_review_count"] = len(reviews)
    if message_errors:
        view["ledgerWarnings"] = message_errors
    if store.topic_path.exists():
        topic = store.load_topic()
        next_view = graph_engine.next_actions(store.ctx, store.run_id, topic, store.open_messages_for(topic))
        view.update(graph_engine.summarize_next(next_view))
        view["graph"] = next_view
        view["topic"] = {
            "id": topic.get("id"),
            "status": topic.get("status"),
            "responsible": topic.get("responsible"),
            "current_node": topic.get("current_node"),
            "waiting_on": topic.get("waiting_on"),
            "context_refs": topic.get("context_refs", []),
            "summary": topic.get("summary", ""),
        }
        view["nextStep"] = next_step_hint(store, state, topic, next_view)
    return view


def next_step_hint(store: RunStore, state: dict[str, Any], topic: dict[str, Any], view: dict[str, Any]) -> str:
    """One sentence telling the coordinator what unblocks the run."""
    if str(state.get("status")) in RUN_CLOSED_STATUSES:
        return f"run is {state.get('status')}"
    nodes = view.get("activeNodes") or []
    if not nodes:
        return "no active graph node; close the run"
    hints = []
    for node in nodes:
        name = node.get("currentNode")
        if node.get("openMessages"):
            hints.append(f"{name}: waiting for replies to {', '.join(node['openMessages'])}")
        elif node.get("waitingOn") and isinstance(node.get("waitingOn"), list):
            hints.append(f"{name}: waiting for parallel branches {', '.join(map(str, node['waitingOn']))}")
        elif node.get("blocked"):
            hints.append(f"{name}: {node.get('reason')}")
        elif node.get("terminal"):
            hints.append(f"{name} is the last node: finish it, publish the result, then run close")
        else:
            options = [a for a in node.get("actions") or [] if a.get("allowed")]
            target = ", ".join(f"{a['to']}" for a in options) or "none"
            hints.append(f"{name} ({node.get('currentExpert')}): when done, graph advance to {target}")
    return "; ".join(hints)


# ---------------------------------------------------------------------- topic


def update_topic(store: RunStore, *, status: str | None = None, responsible: str | None = None,
                 current_node: str | None = None, summary: str | None = None,
                 clear_waiting: bool = False, waiting: dict[str, Any] | None = None,
                 evidence_refs: list[str] | None = None, by: str = "") -> dict[str, Any]:
    ctx = store.ctx
    state = store.load_state()
    topic = store.load_topic()
    changed = False
    if status:
        topic["status"] = status
        changed = True
    if responsible:
        ctx.require_expert(responsible)
        topic["responsible"] = responsible
        changed = True
    if current_node:
        ctx.require_graph_node(current_node)
        active = graph_engine.active_node_entries(topic)
        if len(active) > 1:
            nodes = ", ".join(str(item.get("node")) for item in active)
            raise TeamKitError(f"multiple active graph nodes ({nodes}); cannot rewrite current_node directly, use graph advance --node")
        if topic.get("current_node") != current_node:
            graph_engine.bump_visit(topic, current_node)
        topic["current_node"] = current_node
        topic["active_nodes"] = [{"node": current_node, "status": "active", "waiting_on": [], "activatedAt": now()}]
        changed = True
    if summary is not None:
        topic["summary"] = summary
        changed = True
    if clear_waiting:
        topic["waiting_on"] = None
        if topic.get("status") == "waiting":
            topic["status"] = "active"
        changed = True
    if waiting:
        topic["waiting_on"] = {**waiting, "since": now()}
        topic["status"] = "waiting"
        changed = True
    for ref in evidence_refs or []:
        evidence = topic.setdefault("evidence", [])
        if not any(isinstance(item, dict) and item.get("ref") == ref for item in evidence):
            evidence.append({"ref": ref, "label": "", "linkedBy": by, "createdAt": now()})
            changed = True
    if not changed:
        raise TeamKitError("no topic update requested")
    store.save_topic(topic)
    store.sync_state_nodes(state, topic)
    store.save_state(state)
    store.event("topic.updated", actor=by, topicId=topic.get("id"), currentNode=topic.get("current_node"), status=topic.get("status"))
    return topic


def link_evidence(store: RunStore, ref: str, label: str = "", by: str = "") -> None:
    store.load_state()
    topic = store.load_topic()
    evidence = topic.setdefault("evidence", [])
    if not any(isinstance(item, dict) and item.get("ref") == ref for item in evidence):
        evidence.append({"ref": ref, "label": label, "linkedBy": by, "createdAt": now()})
    store.save_topic(topic)
    store.event("topic.evidence_linked", actor=by, topicId=topic.get("id"), ref=ref)


def topic_view(store: RunStore) -> dict[str, Any]:
    topic = store.load_topic()
    view = dict(topic)
    view["open_messages"] = store.open_messages_for(topic)(str(topic.get("current_node") or ""))
    return view


# ---------------------------------------------------------------------- graph


def graph_next(store: RunStore, from_node: str = "", ignore_waiting: bool = False) -> dict[str, Any]:
    store.load_state()
    topic = store.load_topic()
    return graph_engine.next_actions(store.ctx, store.run_id, topic, store.open_messages_for(topic), from_node, ignore_waiting)


def graph_advance(store: RunStore, *, node: str = "", edge: str = "", to: str = "", force: bool = False,
                  reason: str = "", summary: str | None = None, by: str = "") -> dict[str, Any]:
    state = store.load_state()
    if store.is_closed(state):
        raise TeamKitError(f"cannot advance graph: run is {state.get('status')}")
    if force and not reason:
        raise TeamKitError("--force requires --reason so the override is auditable")
    topic = store.load_topic()
    transition = graph_engine.advance(
        store.ctx, store.run_id, topic, store.open_messages_for(topic), node=node, edge=edge, to=to, force=force
    )
    topic["responsible"] = store.ctx.coordinator_id() or (transition["experts"][0] if transition["experts"] else "")
    if summary is not None:
        topic["summary"] = summary
    store.save_topic(topic)
    store.sync_state_nodes(state, topic)
    if state.get("status") == "prepared":
        state["status"] = "running"
    store.save_state(state)
    single = len(transition["toNodes"]) == 1
    store.event(
        "graph.advanced",
        actor=by,
        topicId=topic.get("id"),
        edgeId=transition["edgeIds"][0] if single else transition["edgeIds"],
        fromNode=transition["fromNode"],
        toNode=transition["toNodes"][0] if single else transition["toNodes"],
        expert=transition["experts"][0] if single else transition["experts"],
        forced=True if force else None,
        reason=reason or None,
    )
    return transition


# ---------------------------------------------------------------------- messages


def _resolve_node_for_sender(store: RunStore, sender: str, explicit: str | None) -> str:
    ctx = store.ctx
    if explicit:
        ctx.require_graph_node(explicit)
        return explicit
    if not store.topic_path.exists():
        return ""
    entries = graph_engine.active_node_entries(store.load_topic())
    if len(entries) == 1:
        return str(entries[0].get("node") or "")
    owned = [str(item.get("node")) for item in entries if ctx.graph_node_map().get(str(item.get("node")), {}).get("expert") == sender]
    if len(owned) == 1:
        return owned[0]
    if len(entries) > 1:
        names = ", ".join(str(item.get("node")) for item in entries)
        raise TeamKitError(f"sender {sender} does not map uniquely to a graph node; candidates: {names}; use --node")
    return ""


def correlate_reply(messages: list[dict[str, Any]], new_message: dict[str, Any], stamp: str) -> str | None:
    """Close the oldest open required message the new one answers.

    A message from B to A answers A's open required request to B (same node
    when both carry one). Questions and escalations never auto-close a
    request, so a clarifying question cannot unblock the graph early.
    """
    if new_message.get("type") in NON_CORRELATING_TYPES:
        return None
    sender, recipient = new_message.get("from"), new_message.get("to")
    node = new_message.get("nodeId") or ""
    candidates = [
        msg for msg in messages
        if msg is not new_message
        and msg.get("from") == recipient
        and msg.get("to") == sender
        and msg.get("response") == "required"
        and msg.get("status") in OPEN_MESSAGE_STATUSES
        and (not node or not msg.get("nodeId") or msg.get("nodeId") == node)
        and (parse_time(msg.get("createdAt")) or 0) <= (parse_time(new_message.get("createdAt") or stamp) or 0)
    ]
    if not candidates:
        return None
    preferred = new_message.get("replyTo")
    target = next((msg for msg in candidates if msg.get("id") == preferred), None) or min(
        candidates, key=lambda msg: parse_time(msg.get("createdAt")) or 0
    )
    target.update({
        "status": "replied",
        "resolution": "reply_correlated",
        "resolvedBy": sender,
        "resolvedAt": stamp,
        "updatedAt": stamp,
    })
    return str(target["id"])


def send_message(store: RunStore, *, sender: str, recipient: str, subject: str, body: str,
                 message_type: str = "request", response: str | None = None, intent: str = "",
                 topic_id: str | None = None, node: str | None = None, artifact_refs: list[str] | None = None,
                 evidence_refs: list[str] | None = None, priority: str = "normal", force: bool = False) -> dict[str, Any]:
    ctx = store.ctx
    store.load_state()
    ctx.require_expert(sender)
    ctx.require_expert(recipient)
    if not ctx.message_type_allowed(message_type):
        raise TeamKitError(f"message type is not allowed by team rules: {message_type}")
    if not ctx.communication_allowed(sender, recipient) and not force:
        raise TeamKitError(f"communication rule does not allow {sender} -> {recipient}; use --force to override")
    node_id = _resolve_node_for_sender(store, sender, node)
    stamp = now()
    msg = {
        "id": prefixed_id("msg"),
        "runId": store.run_id,
        "topicId": topic_id or store.run_id,
        "nodeId": node_id,
        "from": sender,
        "to": recipient,
        "type": message_type,
        "intent": intent,
        "subject": subject.strip(),
        "body": body,
        "response": response or ctx.response_mode_for(sender, recipient),
        "replyTo": None,
        "artifactRefs": artifact_refs or [],
        "evidenceRefs": evidence_refs or [],
        "priority": priority,
        "status": "sent",
        "resolution": "",
        "source": "teamkit",
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    messages = store.messages()
    messages.append(msg)
    answered = correlate_reply(messages, msg, stamp)
    if answered:
        msg["replyTo"] = answered
        write_jsonl(store.messages_path, messages)
    else:
        append_jsonl(store.messages_path, msg)
    _refresh_open_messages(store)
    store.event("message.sent", actor=sender, messageId=msg["id"], topicId=msg["topicId"], nodeId=node_id,
                to=recipient, subject=msg["subject"], correlatedReplyTo=answered)
    return msg


def reply_message(store: RunStore, *, sender: str, reply_to: str, body: str, subject: str | None = None,
                  artifact_refs: list[str] | None = None, evidence_refs: list[str] | None = None) -> dict[str, Any]:
    ctx = store.ctx
    store.load_state()
    ctx.require_expert(sender)
    messages = store.messages()
    original = next((m for m in messages if m.get("id") == reply_to), None)
    if original is None:
        raise TeamKitError(f"message not found: {reply_to}")
    if original.get("to") != sender:
        raise TeamKitError(f"{sender} is not the recipient of {reply_to}")
    stamp = now()
    reply = {
        "id": prefixed_id("msg"),
        "runId": store.run_id,
        "topicId": original.get("topicId") or store.run_id,
        "nodeId": original.get("nodeId") or "",
        "from": sender,
        "to": original.get("from"),
        "type": "reply",
        "intent": original.get("intent", ""),
        "subject": subject or "Re: " + str(original.get("subject", "")),
        "body": body,
        "response": "none",
        "replyTo": reply_to,
        "artifactRefs": artifact_refs or [],
        "evidenceRefs": evidence_refs or [],
        "priority": original.get("priority", "normal"),
        "status": "sent",
        "resolution": "reply",
        "source": "teamkit",
        "createdAt": stamp,
        "updatedAt": stamp,
    }
    if original.get("status") in OPEN_MESSAGE_STATUSES:
        original.update({"status": "replied", "resolution": "reply", "resolvedBy": sender, "resolvedAt": stamp, "updatedAt": stamp})
    messages.append(reply)
    write_jsonl(store.messages_path, messages)
    _refresh_open_messages(store)
    store.event("message.replied", actor=sender, messageId=reply["id"], replyTo=reply_to,
                topicId=reply["topicId"], nodeId=reply["nodeId"])
    return reply


def close_message(store: RunStore, *, by: str, message_id: str, resolution: str, reason: str) -> None:
    ctx = store.ctx
    store.load_state()
    ctx.require_expert(by)
    messages = store.messages()
    target = next((m for m in messages if m.get("id") == message_id), None)
    if target is None:
        raise TeamKitError(f"message not found: {message_id}")
    if by not in {target.get("from"), target.get("to"), ctx.coordinator_id()}:
        raise TeamKitError(f"{by} cannot close {message_id}")
    stamp = now()
    target.update({"status": "closed", "resolution": resolution, "resolutionReason": reason,
                   "resolvedBy": by, "resolvedAt": stamp, "updatedAt": stamp})
    write_jsonl(store.messages_path, messages)
    _refresh_open_messages(store)
    store.event("message.closed", actor=by, messageId=message_id, resolution=resolution)


def _refresh_open_messages(store: RunStore) -> None:
    state = store.load_state()
    state["open_messages"] = [str(msg["id"]) for msg in store.open_required()]
    store.save_state(state)


def list_messages(store: RunStore, status: str = "", expert: str = "") -> list[dict[str, Any]]:
    store.load_state()
    messages = store.messages()
    if status == "open":
        messages = [m for m in messages if m.get("response") == "required" and m.get("status") in OPEN_MESSAGE_STATUSES]
    elif status:
        messages = [m for m in messages if m.get("status") == status]
    if expert:
        messages = [m for m in messages if expert in {m.get("from"), m.get("to")}]
    return messages


# ---------------------------------------------------------------------- artifacts and results


def publish_artifact(store: RunStore, owner: str, source: Path, kind: str) -> dict[str, Any]:
    store.ctx.require_expert(owner)
    if not source.is_file():
        raise TeamKitError(f"artifact file not found: {source}")
    data = source.read_bytes()
    digest = sha256_bytes(data)
    art_id = "art_" + digest[:24]
    if kind == "expert_result":
        target_dir = store.expert_result_dir
    else:
        target_dir = store.base / "artifacts" / kind
    target = target_dir / f"{art_id}{source.suffix}"
    if not target.exists():
        atomic_write_bytes(target, data)
    records = read_jsonl(store.artifact_index_path)
    existing = next((r for r in records if r.get("id") == art_id and r.get("kind") == kind), None)
    if existing:
        return existing
    record = {
        "id": art_id,
        "runId": store.run_id,
        "owner": owner,
        "kind": kind,
        "name": source.name,
        "path": display_path(store.ctx.root, target),
        "absolutePath": str(target),
        "sourcePath": display_path(store.ctx.root, source),
        "sha256": digest,
        "size": len(data),
        "createdAt": now(),
    }
    append_jsonl(store.artifact_index_path, record)
    state = store.load_state()
    artifacts = state.setdefault("artifacts", [])
    if not any(item.get("id") == art_id and item.get("kind") == kind for item in artifacts if isinstance(item, dict)):
        artifacts.append({"id": art_id, "kind": kind, "owner": owner, "path": record["path"]})
    store.save_state(state)
    store.event("artifact.published", actor=owner, artifactId=art_id, kind=kind)
    return record


def list_artifacts(store: RunStore, kind: str = "") -> list[dict[str, Any]]:
    store.load_state()
    records = read_jsonl(store.artifact_index_path)
    return [r for r in records if not kind or r.get("kind") == kind]


def publish_result(store: RunStore, owner: str, source: Path) -> dict[str, Any]:
    record = publish_artifact(store, owner, source, "final")
    state = store.load_state()
    state["final_result"] = {
        "artifactId": record["id"],
        "path": record["path"],
        "publishedBy": owner,
        "publishedAt": now(),
    }
    store.save_state(state)
    store.event("result.published", actor=owner, artifactId=record["id"])
    return record


# ---------------------------------------------------------------------- human input


def append_decision_log(store: RunStore, heading: str, body: str) -> None:
    path = store.decision_log_path
    if not path.exists():
        atomic_write_text(path, f"# Decision Log: {store.run_id}\n\n")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"## {heading}\n\n{body.strip()}\n\n")
        handle.flush()
        os.fsync(handle.fileno())


def request_human(store: RunStore, *, sender: str, reason: str, question: str, blocking: bool = True,
                  artifact_refs: list[str] | None = None, evidence_refs: list[str] | None = None) -> dict[str, Any]:
    state = store.load_state()
    store.ctx.require_expert(sender)
    review = {
        "id": prefixed_id("hr"),
        "runId": store.run_id,
        "from": sender,
        "reason": reason,
        "question": question,
        "blocking": blocking,
        "status": "open",
        "artifactRefs": artifact_refs or [],
        "evidenceRefs": evidence_refs or [],
        "createdAt": now(),
        "updatedAt": now(),
    }
    append_jsonl(store.human_review_path, review)
    state.setdefault("open_human_reviews", []).append(review["id"])
    if blocking:
        state["status"] = "waiting_for_human"
        if store.topic_path.exists():
            topic = store.load_topic()
            topic["status"] = "waiting"
            topic["waiting_on"] = {"type": "human_review", "ref": review["id"], "summary": reason, "since": now()}
            store.save_topic(topic)
    store.save_state(state)
    store.event("human_review.requested", actor=sender, reviewId=review["id"], reason=reason, blocking=blocking)
    return review


def resolve_human(store: RunStore, *, review_id: str, resolution: str, answer: str, by: str = "human",
                  force: bool = False) -> dict[str, Any]:
    state = store.load_state()
    reviews = read_jsonl(store.human_review_path)
    target = next((item for item in reviews if item.get("id") == review_id), None)
    if not target:
        raise TeamKitError(f"human input request not found: {review_id}")
    if target.get("status") != "open" and not force:
        raise TeamKitError(f"human input request is already resolved: {review_id}")
    target.update({"status": "resolved", "resolution": resolution, "answer": answer,
                   "resolvedBy": by, "resolvedAt": now(), "updatedAt": now()})
    write_jsonl(store.human_review_path, reviews)
    open_reviews = [item for item in reviews if item.get("status") == "open"]
    open_blocking = [item for item in open_reviews if item.get("blocking", True)]
    state["open_human_reviews"] = [item["id"] for item in open_reviews]
    if state.get("status") == "waiting_for_human" and not open_blocking:
        state["status"] = "running"
    store.save_state(state)
    if store.topic_path.exists():
        topic = store.load_topic()
        waiting = topic.get("waiting_on")
        if isinstance(waiting, dict) and waiting.get("type") == "human_review" and waiting.get("ref") == review_id:
            if open_blocking:
                topic["waiting_on"] = {"type": "human_review", "ref": open_blocking[0]["id"],
                                       "summary": "Unresolved human input request", "since": now()}
                topic["status"] = "waiting"
            else:
                topic["waiting_on"] = None
                if topic.get("status") == "waiting":
                    topic["status"] = "active"
            store.save_topic(topic)
    append_decision_log(store, f"Human Input {review_id}", f"Resolution: {resolution}\n\nBy: {by}\n\n{answer}")
    store.event("human_review.resolved", actor=by, reviewId=review_id, resolution=resolution)
    return target


def list_human(store: RunStore, status: str = "") -> list[dict[str, Any]]:
    store.load_state()
    records = read_jsonl(store.human_review_path)
    return [r for r in records if not status or r.get("status") == status]


def read_native_index(store: RunStore) -> dict[str, Any]:
    data = read_json(store.native_index_path, default=None)
    return data if isinstance(data, dict) else {"keys": [], "nativeTeam": "", "updatedAt": ""}


def write_native_index(store: RunStore, data: dict[str, Any]) -> None:
    data["updatedAt"] = now()
    write_json(store.native_index_path, data)

