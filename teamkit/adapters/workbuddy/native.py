"""Ingest WorkBuddy Agent Teams data into TeamKit ledgers.

WorkBuddy persists every native collaboration act on disk:

* ``teams/<team>/config.json`` — lead session, members (name, agentType,
  spawn prompt, joinedAt);
* ``teams/<team>/inboxes/<member>.json`` — every message delivered to that
  member (``from``, ``text``, ``summary``, ``timestamp``);
* ``tasks/<team>/<n>.json`` — the shared task list.

Agents therefore never have to double-book a message: the sender uses the
native ``Agent`` / ``SendMessage`` tools and TeamKit reads the result. Sync is
idempotent (stable keys) and attributes records to runs through the
``[TeamKit run=... node=...]`` header, falling back to the run time window.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from teamkit.fsutil import append_jsonl_many, iso_from_epoch, load_yaml, now, parse_time, stable_id, write_jsonl
from teamkit.runs import (
    OPEN_MESSAGE_STATUSES,
    RunStore,
    correlate_reply,
    parse_header,
    read_native_index,
    write_native_index,
)
from teamkit.adapters.workbuddy import paths

REACTIVATED = re.compile(r'^Teammate "([^"]+)" has been reactivated')
AUTO_NOTIFICATION = re.compile(r'Teammate "([^"]+)" (completed successfully|failed|was cancelled|has been terminated|stopped)')
BIND_WINDOW_SECONDS = 15 * 60


# ---------------------------------------------------------------------- native team readers


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def read_team(config: Path, team: str) -> dict[str, Any] | None:
    root = paths.teams_dir(config) / team
    data = _read_json(root / "config.json", None)
    if not isinstance(data, dict):
        return None
    inboxes: dict[str, list[dict[str, Any]]] = {}
    inbox_dir = root / "inboxes"
    if inbox_dir.is_dir():
        for inbox in sorted(inbox_dir.glob("*.json")):
            entries = _read_json(inbox, [])
            inboxes[inbox.stem] = [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []
    tasks: list[dict[str, Any]] = []
    task_dir = paths.tasks_dir(config) / team
    if task_dir.is_dir():
        for task_file in sorted(task_dir.glob("*.json"), key=lambda p: (len(p.stem), p.stem)):
            task = _read_json(task_file, None)
            if isinstance(task, dict):
                tasks.append(task)
    return {"name": team, "config": data, "inboxes": inboxes, "tasks": tasks, "dir": str(root)}


def list_teams(config: Path) -> list[dict[str, Any]]:
    root = paths.teams_dir(config)
    if not root.is_dir():
        return []
    teams = []
    for folder in root.iterdir():
        data = _read_json(folder / "config.json", None)
        if isinstance(data, dict):
            teams.append({"name": folder.name, "config": data})
    return teams


def _lead_cwd(config: dict[str, Any]) -> str:
    for member in config.get("members") or []:
        if isinstance(member, dict) and member.get("name") == paths.NATIVE_LEAD_NAME:
            return str(member.get("cwd") or "")
    return ""


def _belongs_to_package(config: dict[str, Any], roster: dict[str, Any]) -> bool:
    agent_ids = {str(info.get("agentId")) for info in (roster.get("experts") or {}).values()}
    for member in config.get("members") or []:
        if isinstance(member, dict) and str(member.get("agentType") or "") in agent_ids:
            return True
    return False


def find_team(config: Path, host: dict[str, Any], roster: dict[str, Any], run_created: float | None) -> tuple[str, str]:
    """Return (native team name, matchedBy) for a run binding, or ("", reason)."""
    explicit = str(host.get("nativeTeam") or "")
    if explicit:
        if (paths.teams_dir(config) / explicit / "config.json").is_file():
            return explicit, "explicit"
        return "", f"bound native team not found: {explicit}"
    teams = list_teams(config)
    session = str(host.get("sessionId") or "")
    if session:
        by_session = [team for team in teams if str(team["config"].get("leadSessionId") or "") == session]
        if by_session:
            newest = max(by_session, key=lambda team: float(team["config"].get("createdAt") or 0))
            return newest["name"], "leadSessionId"
    cwd = str(host.get("cwd") or "")
    candidates = []
    for team in teams:
        cfg = team["config"]
        created = parse_time(cfg.get("createdAt"))
        if cwd and _lead_cwd(cfg) != cwd:
            continue
        if not _belongs_to_package(cfg, roster):
            continue
        if run_created and created and created < run_created - BIND_WINDOW_SECONDS:
            continue
        candidates.append((abs((created or 0) - (run_created or 0)), team["name"]))
    if candidates:
        label = "cwd+package" if len(candidates) == 1 else f"cwd+package(nearest of {len(candidates)})"
        return min(candidates)[1], label
    return "", "no native team matched this run yet (TeamCreate not called, or a different session)"


TEAMMATE_MESSAGE = re.compile(r"<teammate-message\s+([^>]*)>(.*?)</teammate-message>", re.S)
ATTRIBUTE = re.compile(r'(\w+)="([^"]*)"')


def lead_transcript_path(config: Path, session_id: str) -> Path | None:
    """WorkBuddy keeps each session transcript at projects/<encoded cwd>/<session>.jsonl."""
    if not session_id:
        return None
    for candidate in (config / "projects").glob(f"*/{session_id}.jsonl"):
        return candidate
    return None


def read_lead_transcript(config: Path, session_id: str, cursor: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return teammate messages delivered to the lead since the stored byte offset."""
    path = lead_transcript_path(config, session_id)
    if path is None:
        return [], cursor
    offset = int(cursor.get("offset") or 0) if cursor.get("path") == str(path) else 0
    size = path.stat().st_size
    if offset > size:
        offset = 0  # rewritten or truncated transcript: start over (keys de-duplicate)
    entries: list[dict[str, Any]] = []
    pending: dict[str, Any] = dict(cursor.get("pendingSubagents") or {}) if cursor.get("path") == str(path) else {}
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    complete = data.rfind(b"\n") + 1  # never consume a half-written last line
    for raw in data[:complete].splitlines():
        try:
            row = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("type") == "function_call" and row.get("name") == "Agent":
            try:
                arguments = json.loads(row.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if isinstance(arguments, dict) and not arguments.get("team_name"):
                pending[str(row.get("callId"))] = {
                    "subagentType": str(arguments.get("subagent_type") or ""),
                    "prompt": str(arguments.get("prompt") or ""),
                    "description": str(arguments.get("description") or ""),
                    "timestamp": row.get("timestamp"),
                }
                entries.append({"_kind": "subagent_call", "callId": str(row.get("callId")), **pending[str(row.get("callId"))]})
            continue
        if row.get("type") == "function_call_result" and str(row.get("callId")) in pending:
            call = pending.pop(str(row.get("callId")))
            output = row.get("output")
            text = output.get("text") if isinstance(output, dict) else output if isinstance(output, str) else ""
            entries.append({"_kind": "subagent_result", "callId": str(row.get("callId")), "subagentType": call["subagentType"],
                            "text": str(text or ""), "timestamp": row.get("timestamp"), "status": row.get("status")})
            continue
        if row.get("type") != "message" or row.get("role") != "user":
            continue
        content = row.get("content")
        parts = content if isinstance(content, list) else [{"text": content}] if isinstance(content, str) else []
        for part in parts:
            text = part.get("text") if isinstance(part, dict) else None
            if not isinstance(text, str) or "<teammate-message" not in text:
                continue
            for attrs, body in TEAMMATE_MESSAGE.findall(text):
                fields = dict(ATTRIBUTE.findall(attrs))
                entries.append({
                    "from": fields.get("teammate_id", ""),
                    "summary": fields.get("summary", ""),
                    "text": body.strip(),
                    "timestamp": row.get("timestamp"),
                    "_via": "transcript",
                })
    return entries, {"path": str(path), "offset": offset + complete, "pendingSubagents": pending}


# ---------------------------------------------------------------------- conversion


def _text_key(*parts: Any) -> str:
    return hashlib.sha256("\0".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:20]


def _subject(entry: dict[str, Any], text: str) -> str:
    summary = str(entry.get("summary") or "").strip()
    if summary:
        return summary[:120]
    for line in text.splitlines():
        line = line.strip().strip("#").strip()
        if line and not line.startswith("[TeamKit"):
            return line[:120]
    return "(no subject)"


def _infer_type(sender: str, recipient: str, coordinator: str, header: dict[str, str]) -> str:
    declared = header.get("type", "")
    if declared:
        return declared
    if sender == coordinator:
        return "request"
    if recipient == coordinator:
        return "result"
    return "notify"


def _run_window(state: dict[str, Any]) -> tuple[float, float]:
    start = parse_time(state.get("createdAt")) or 0.0
    end = parse_time(state.get("closedAt")) or float("inf")
    return start - 60.0, end + 60.0


def _sibling_runs(store: RunStore, team: str) -> list[tuple[str, dict[str, Any]]]:
    """Other runs of this team bound to the same native team."""
    siblings = []
    base = store.ctx.team_base()
    if not base.is_dir():
        return siblings
    for state_file in base.glob("*/state.yaml"):
        run_id = state_file.parent.name
        if run_id == store.run_id:
            continue
        try:
            state = load_yaml(state_file)
        except Exception:  # noqa: BLE001 - a damaged sibling must not block sync
            continue
        host = state.get("host") if isinstance(state.get("host"), dict) else {}
        if host.get("nativeTeam") == team:
            siblings.append((run_id, state))
    return siblings


def _belongs_here(ts: float | None, header: dict[str, str], store: RunStore, state: dict[str, Any],
                  siblings: list[tuple[str, dict[str, Any]]]) -> bool | None:
    """True/False when attribution is certain, None when ambiguous."""
    run = header.get("run")
    if run:
        return run == store.run_id
    if ts is None:
        return None
    start, end = _run_window(state)
    if not start <= ts <= end:
        return False
    for _, sibling in siblings:
        s_start, s_end = _run_window(sibling)
        if s_start <= ts <= s_end:
            return None
    return True


# ---------------------------------------------------------------------- sync


def sync_run(store: RunStore, config: Path | None = None) -> dict[str, Any]:
    ctx = store.ctx
    state = store.load_state()
    host = state.get("host") if isinstance(state.get("host"), dict) else {}
    config = config or paths.config_dir()
    roster = paths.load_roster(ctx, str(host.get("package") or ""))
    report: dict[str, Any] = {"ok": True, "nativeTeam": "", "newMessages": 0, "newEvents": 0,
                              "unattributed": 0, "violations": 0}

    team_name = str(host.get("nativeTeam") or "")
    if not team_name:
        team_name, matched_by = find_team(config, host, roster, parse_time(state.get("createdAt")))
        if not team_name:
            report.update({"ok": False, "reason": matched_by})
            return report
        host = {**host, "nativeTeam": team_name, "matchedBy": matched_by}
        state["host"] = host
        store.save_state(state)
        store.event("run.host_bound", host=host)
    report["nativeTeam"] = team_name
    team = read_team(config, team_name)
    if team is None:
        report.update({"ok": False, "reason": f"native team data not found (deleted?): {team_name}"})
        return report

    index = read_native_index(store)
    seen = set(index.get("keys") or [])
    unattributed = set(index.get("unattributedKeys") or [])
    coordinator = ctx.coordinator_id()
    members = [m for m in team["config"].get("members") or [] if isinstance(m, dict)]
    agent_type_by_name = {str(m.get("name")): str(m.get("agentType") or "") for m in members}
    siblings = _sibling_runs(store, team_name)

    def expert_of(name: str) -> str:
        return paths.resolve_member(roster, name, agent_type_by_name.get(name, ""))

    new_messages: list[dict[str, Any]] = []
    new_events: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    def add_event(key: str, event_type: str, created: str, **extra: Any) -> None:
        if key in seen:
            return
        seen.add(key)
        record = {"id": stable_id("evt", key), "type": event_type, "runId": store.run_id,
                  "createdAt": created, "source": "workbuddy.native", "nativeTeam": team_name}
        record.update({k: v for k, v in extra.items() if v not in (None, "")})
        new_events.append(record)

    def add_violation(key: str, kind: str, created: str, **extra: Any) -> None:
        if key in seen:
            return
        add_event(key, "protocol.violation", created, kind=kind, **extra)
        violations.append({"kind": kind, **extra})

    # Member identity: canonical names, duplicates, unknown agent types.
    agent_ids = {str(info.get("agentId")): expert for expert, info in (roster.get("experts") or {}).items()}
    by_type: dict[str, list[str]] = {}
    for member in members:
        name = str(member.get("name") or "")
        if name == paths.NATIVE_LEAD_NAME:
            continue
        agent_type = str(member.get("agentType") or "")
        joined = parse_time(member.get("joinedAt"))
        if joined is not None and _belongs_here(joined, {}, store, state, siblings) is False:
            continue
        expert = expert_of(name)
        created = iso_from_epoch(joined) if joined else now()
        add_event(f"member:{name}:{member.get('joinedAt')}", "member.spawned", created,
                  member=name, agentType=agent_type, expert=expert or None)
        if agent_type not in agent_ids:
            add_violation(f"violation:unknown:{name}", "unknown_member", created, member=name, agentType=agent_type,
                          detail="spawned with a subagent_type that is not one of this team's agents")
        elif name != agent_type:
            add_violation(f"violation:name:{name}", "noncanonical_member_name", created, member=name,
                          agentType=agent_type, detail=f"spawn name should equal the Agent ID {agent_type}")
        by_type.setdefault(agent_type, []).append(name)
        prompt = str(member.get("prompt") or "")
        if prompt and expert:
            header = parse_header(prompt)
            belongs = _belongs_here(joined, header, store, state, siblings)
            key = f"spawn:{name}:{member.get('joinedAt')}"
            if belongs is None and key not in seen:
                unattributed.add(key)
            elif belongs and key not in seen:
                seen.add(key)
                new_messages.append(_message(store, key, coordinator, expert, prompt, {"summary": f"派发任务给 {name}"},
                                             header, created, ctx, coordinator, "handoff",
                                             native={"team": team_name, "kind": "spawn", "member": name}))
    # Inbox messages, lead transcript messages and platform notifications.
    # The lead's inbox is pruned by WorkBuddy, so messages *to the lead* are
    # also read from the lead session transcript; both sources share a
    # content key so each message is recorded once.
    transcript_entries, transcript_cursor = read_lead_transcript(
        config, str(team["config"].get("leadSessionId") or ""), index.get("transcript") or {}
    )
    subagent_records = [entry for entry in transcript_entries if entry.get("_kind")]
    entries_by_owner = [(owner, entry) for owner, entries in team["inboxes"].items() for entry in entries]
    entries_by_owner += [(paths.NATIVE_LEAD_NAME, entry) for entry in transcript_entries if not entry.get("_kind")]
    for owner, entry in entries_by_owner:
        text = str(entry.get("text") or "").strip()
        sender_name = str(entry.get("from") or "")
        ts = parse_time(entry.get("timestamp"))
        created = iso_from_epoch(ts) if ts is not None else now()
        if owner == paths.NATIVE_LEAD_NAME:
            key = f"lead:{sender_name}:{_text_key(text)}"
        else:
            key = f"inbox:{owner}:{sender_name}:{entry.get('timestamp')}:{_text_key(text)}"
        if key in seen:
            continue
        notification = None
        if sender_name == "system" or text.startswith("[Framework Auto-Notification]"):
            match = AUTO_NOTIFICATION.search(text)
            notification = ("member." + _status_word(match.group(2)), match.group(1)) if match else ("native.notification", "")
        else:
            match = REACTIVATED.match(text)
            if match:
                notification = ("member.reactivated", match.group(1))
        header = parse_header(text)
        belongs = _belongs_here(ts, header, store, state, siblings)
        if belongs is False:
            seen.add(key)
            continue
        if belongs is None:
            unattributed.add(key)
            continue
        if notification:
            event_type, member = notification
            add_event(key, event_type, created, member=member or None, expert=expert_of(member) if member else None,
                      detail=text[:240])
            continue
        sender = expert_of(sender_name)
        recipient = expert_of(owner)
        seen.add(key)
        message = _message(store, key, sender or f"native:{sender_name}", recipient or f"native:{owner}", text, entry,
                           header, created, ctx, coordinator, None,
                           native={"team": team_name, "kind": "message", "from": sender_name, "to": owner,
                                   "via": entry.get("_via", "inbox")})
        new_messages.append(message)
        if sender and recipient and not ctx.communication_allowed(sender, recipient, open_fallback=False):
            add_violation(f"violation:route:{key}", "unauthorized_route", created, messageId=message["id"],
                          detail=f"{sender} -> {recipient} is not an allowed route; relay through the coordinator")

    # Members called as one-shot subagents (Agent without team_name): record the
    # dispatch and the returned result, and flag the bypass of the team.
    for record in subagent_records:
        ts = parse_time(record.get("timestamp"))
        created = iso_from_epoch(ts) if ts is not None else now()
        expert = agent_ids.get(record.get("subagentType", ""), "")
        call_id = record.get("callId")
        text = str(record.get("prompt") if record["_kind"] == "subagent_call" else record.get("text") or "").strip()
        key = f"{record['_kind']}:{call_id}"
        header = parse_header(text)
        belongs = _belongs_here(ts, header, store, state, siblings)
        if key in seen or belongs is False:
            seen.add(key)
            continue
        if belongs is None:
            unattributed.add(key)
            continue
        seen.add(key)
        if not expert:
            continue  # generic helper subagents are not team members
        if record["_kind"] == "subagent_call":
            new_messages.append(_message(store, key, coordinator, expert, text, {"summary": record.get("description") or f"派发给 {expert}"},
                                         header, created, ctx, coordinator, "handoff",
                                         native={"team": team_name, "kind": "subagent", "callId": call_id}))
            add_violation(f"violation:subagent:{call_id}", "subagent_dispatch", created, expert=expert,
                          detail=f"{expert} was called as a one-shot subagent (Agent without name/team_name); "
                                 "it cannot receive follow-ups or use SendMessage")
        else:
            new_messages.append(_message(store, key, expert, coordinator, text, {"summary": f"{expert} 子代理返回结果"},
                                         header, created, ctx, coordinator, "result",
                                         native={"team": team_name, "kind": "subagent_result", "callId": call_id,
                                                 "status": record.get("status")}))

    # Duplicate spawns are a violation unless the earlier member had failed.
    failed_members = {str(e.get("member")) for e in new_events if e.get("type") == "member.failed"}
    failed_members |= {str(e.get("member")) for e in store.events() if e.get("type") == "member.failed"}
    for agent_type, names in by_type.items():
        if len(names) > 1 and agent_type in agent_ids:
            healthy = [name for name in names[:-1] if name not in failed_members]
            if healthy:
                add_violation(f"violation:dup:{agent_type}:{len(names)}", "duplicate_member", now(), agentType=agent_type,
                              members=names, detail="the same agent was spawned again while an earlier copy was healthy; "
                                                    "message the existing member instead")
            else:
                add_event(f"respawn:{agent_type}:{len(names)}", "member.respawned", now(), agentType=agent_type, members=names)

    # Shared task list snapshot: record status transitions.
    task_states = dict(index.get("tasks") or {})
    for task in team["tasks"]:
        task_id = str(task.get("id") or "")
        status = str(task.get("status") or "")
        if not task_id or task_states.get(task_id) == status:
            continue
        task_states[task_id] = status
        stamp = parse_time(task.get("updatedAt"))
        add_event(f"task:{task_id}:{status}", "native.task", iso_from_epoch(stamp) if stamp else now(),
                  taskId=task_id, status=status, subject=str(task.get("subject") or "")[:120],
                  owner=str(task.get("owner") or "") or None)

    if new_messages:
        messages = store.messages()
        known = {str(m.get("id")) for m in messages}
        for message in sorted(new_messages, key=lambda m: parse_time(m.get("createdAt")) or 0):
            if message["id"] in known:
                continue
            messages.append(message)
            answered = correlate_reply(messages, message, message["createdAt"])
            if answered and not message.get("replyTo"):
                message["replyTo"] = answered
        write_jsonl(store.messages_path, messages)
        state = store.load_state()
        state["open_messages"] = [str(m["id"]) for m in messages
                                  if m.get("response") == "required" and m.get("status") in OPEN_MESSAGE_STATUSES]
        if state.get("status") == "prepared":
            state["status"] = "running"
        store.save_state(state)
    if new_events:
        append_jsonl_many(store.events_path, sorted(new_events, key=lambda e: parse_time(e.get("createdAt")) or 0))
    unattributed -= seen
    index.update({"keys": sorted(seen), "nativeTeam": team_name, "tasks": task_states,
                  "transcript": transcript_cursor, "unattributedKeys": sorted(unattributed)})
    report["unattributed"] = len(unattributed)
    write_native_index(store, index)
    report.update({"newMessages": len(new_messages), "newEvents": len(new_events), "violations": len(violations)})
    if violations:
        report["violationKinds"] = sorted({v["kind"] for v in violations})
    return report


def _status_word(phrase: str) -> str:
    phrase = phrase.lower()
    if "completed" in phrase:
        return "completed"
    if "failed" in phrase:
        return "failed"
    return "stopped"


def _message(store: RunStore, key: str, sender: str, recipient: str, text: str, entry: dict[str, Any],
             header: dict[str, str], created: str, ctx: Any, coordinator: str, forced_type: str | None,
             native: dict[str, Any]) -> dict[str, Any]:
    node = header.get("node", "")
    if node and node not in ctx.graph_node_map():
        node = ""
    message_type = forced_type or _infer_type(sender, recipient, coordinator, header)
    # Only a dispatch that names its node is precise enough to gate the graph.
    if sender == coordinator and node and message_type in {"request", "handoff"}:
        response = "required"
    elif message_type in {"question", "escalation"}:
        response = "optional"
    else:
        response = "none"
    return {
        "id": stable_id("msg", key),
        "runId": store.run_id,
        "topicId": store.run_id,
        "nodeId": node,
        "from": sender,
        "to": recipient,
        "type": message_type,
        "intent": "",
        "subject": _subject(entry, text),
        "body": text,
        "response": response,
        "replyTo": header.get("re") or None,
        "artifactRefs": re.findall(r"\bart_[0-9a-f]{24}\b", text),
        "evidenceRefs": [],
        "priority": "normal",
        "status": "sent",
        "resolution": "",
        "source": "workbuddy.native",
        "native": native,
        "createdAt": created,
        "updatedAt": created,
    }


def native_overview(config: Path, team: str) -> dict[str, Any]:
    """A compact description of one native team for diagnostics."""
    data = read_team(config, team)
    if data is None:
        return {"team": team, "exists": False}
    members = [m for m in data["config"].get("members") or [] if isinstance(m, dict)]
    return {
        "team": team,
        "exists": True,
        "leadSessionId": data["config"].get("leadSessionId"),
        "members": [{"name": m.get("name"), "agentType": m.get("agentType")} for m in members],
        "inboxMessages": {owner: len(entries) for owner, entries in data["inboxes"].items()},
        "tasks": [{"id": t.get("id"), "status": t.get("status"), "subject": t.get("subject")} for t in data["tasks"]],
    }

