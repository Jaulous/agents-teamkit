"""Context Items: team-level declarations in team.yaml and per-run managed copies."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from teamkit.errors import TeamKitError
from teamkit.fsutil import (
    append_jsonl,
    atomic_copyfile,
    atomic_write_bytes,
    display_path,
    now,
    read_jsonl,
    sha256_bytes,
    write_json,
    write_yaml,
)
from teamkit.runs import RunStore, resolve_input_file
from teamkit.team import CONTEXT_SCOPES, ID_PATTERN, TeamContext


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


# ---------------------------------------------------------------------- run-level managed copies


def managed_context_record(
    store: RunStore,
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
    ctx = store.ctx
    if scope not in CONTEXT_SCOPES:
        raise TeamKitError(f"context scope must be one of: {', '.join(sorted(CONTEXT_SCOPES))}")
    visible = normalize_visible_to(ctx, scope, visible_to or [])
    final_name = name or (source_path.name if source_path else "context-item")
    digest = sha256_bytes(final_name.encode("utf-8") + b"\0" + data)
    final_id = context_id or "ctx_" + digest[:24]
    if not ID_PATTERN.match(final_id):
        raise TeamKitError(f"context id must match {ID_PATTERN.pattern}")
    existing = next((item for item in read_jsonl(store.context_items_path) if item.get("id") == final_id), None)
    if existing:
        return existing
    target_dir = store.context_dir / final_id
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    content_path = target_dir / f"content{suffix}"
    if not content_path.exists():
        atomic_write_bytes(content_path, data)
    record = {
        "id": final_id,
        "runId": store.run_id,
        "name": final_name,
        "sourceType": source_type,
        "sourcePath": display_path(ctx.root, source_path) if source_path else "",
        "path": display_path(ctx.root, content_path),
        "absolutePath": str(content_path),
        "scope": scope,
        "visibleTo": visible,
        "owner": owner,
        "summary": summary,
        "sha256": sha256_bytes(data),
        "size": len(data),
        "createdAt": now(),
    }
    manifest_path = target_dir / "manifest.json"
    write_json(manifest_path, {**record, "manifestVersion": "teamkit.context_item.v0.1"})
    record["manifestPath"] = display_path(ctx.root, manifest_path)
    append_jsonl(store.context_items_path, record)
    return record


def materialize_declared_contexts(store: RunStore) -> list[dict[str, Any]]:
    ctx = store.ctx
    records = []
    for item in ctx.declared_contexts():
        raw_path = item.get("path") or item.get("file")
        if not raw_path:
            continue
        source = resolve_input_file(ctx, str(raw_path))
        if not source.is_file():
            raise TeamKitError(f"context file not found: {source}")
        records.append(
            managed_context_record(
                store,
                source.read_bytes(),
                context_id=str(item.get("id") or ""),
                name=str(item.get("name") or source.name),
                source_type=str(item.get("source") or "file"),
                source_path=source,
                suffix=source.suffix,
                scope=str(item.get("scope") or "team"),
                visible_to=[str(value) for value in item.get("visible_to") or []],
                owner=str(item.get("owner") or "team"),
                summary=str(item.get("summary") or ""),
            )
        )
    return records


def add_run_context(
    store: RunStore,
    *,
    file: str | None,
    text: str | None,
    context_id: str = "",
    name: str = "",
    source_type: str = "",
    scope: str | None = None,
    visible_to: list[str] | None = None,
    summary: str = "",
    by: str = "",
) -> dict[str, Any]:
    ctx = store.ctx
    store.load_state()
    declared = ctx.declared_context_for(context_id or name or "") or {}
    declared_path = str(declared.get("path") or declared.get("file") or "")
    if file and text is not None:
        raise TeamKitError("use either --file or --text/--text-file, not both")
    source_arg = file or ("" if text is not None else declared_path)
    final_scope = scope or str(declared.get("scope") or "team")
    final_visible = [str(v) for v in (visible_to or declared.get("visible_to") or [])]
    final_id = context_id or str(declared.get("id") or "")
    final_source_type = source_type or str(declared.get("source") or ("file" if source_arg else "text"))
    final_summary = summary or str(declared.get("summary") or "")
    if source_arg:
        source = resolve_input_file(ctx, source_arg, store.run_id)
        if not source.is_file():
            raise TeamKitError(f"context file not found: {source}")
        record = managed_context_record(
            store, source.read_bytes(), context_id=final_id,
            name=name or str(declared.get("name") or source.name), source_type=final_source_type,
            source_path=source, suffix=source.suffix, scope=final_scope, visible_to=final_visible,
            owner=by or "user", summary=final_summary,
        )
    else:
        if not text:
            raise TeamKitError("--file, --text, or --text-file is required")
        record = managed_context_record(
            store, text.encode("utf-8"), context_id=final_id,
            name=name or str(declared.get("name") or "Context Item"), source_type=final_source_type,
            suffix=".md", scope=final_scope, visible_to=final_visible, owner=by or "user", summary=final_summary,
        )
    state = store.load_state()
    items = state.setdefault("context_items", [])
    if not any(isinstance(item, dict) and item.get("id") == record["id"] for item in items):
        items.append({"id": record["id"], "name": record["name"], "scope": record["scope"],
                      "visibleTo": record["visibleTo"], "path": record["path"]})
    store.save_state(state)
    if store.topic_path.exists():
        topic = store.load_topic()
        refs = topic.get("context_refs")
        if not isinstance(refs, list):
            refs = []
            topic["context_refs"] = refs
        if not any(isinstance(ref, dict) and ref.get("id") == record["id"] for ref in refs):
            refs.append({"id": record["id"], "name": record["name"], "scope": record["scope"],
                         "visibleTo": record["visibleTo"], "linkedBy": by or "user", "createdAt": now()})
            store.save_topic(topic)
    store.event("context.added", actor=by or "user", contextId=record["id"], name=record["name"], scope=record["scope"])
    return record


def list_run_contexts(store: RunStore, visible_to: str = "", scope: str = "") -> list[dict[str, Any]]:
    store.load_state()
    records = read_jsonl(store.context_items_path)
    if visible_to:
        store.ctx.require_expert(visible_to)
        records = [r for r in records if r.get("scope") == "team" or visible_to in (r.get("visibleTo") or [])]
    if scope:
        records = [r for r in records if r.get("scope") == scope]
    return records


# ---------------------------------------------------------------------- team.yaml editing


def team_context_view(item: dict[str, Any]) -> dict[str, Any]:
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


def _declared_for_update(ctx: TeamContext) -> list[dict[str, Any]]:
    contexts = ctx.team.setdefault("contexts", [])
    if not isinstance(contexts, list):
        raise TeamKitError("contexts must be a list")
    return contexts


def _index(contexts: list[dict[str, Any]], context_id: str) -> int:
    for index, item in enumerate(contexts):
        if isinstance(item, dict) and str(item.get("id") or "") == context_id:
            return index
    return -1


def _save_team(ctx: TeamContext) -> None:
    from teamkit.validation import validate_team_definition

    errors = validate_team_definition(ctx)
    if errors:
        raise TeamKitError("team definition update is invalid:\n- " + "\n- ".join(errors))
    write_yaml(ctx.team_file, ctx.team)


def list_team_contexts(ctx: TeamContext, expert: str = "") -> list[dict[str, Any]]:
    if expert:
        ctx.require_expert(expert)
    views = []
    for item in ctx.declared_contexts():
        view = team_context_view(item)
        if expert and view["scope"] == "agents" and expert not in view["visibleTo"]:
            continue
        views.append(view)
    return views


def add_team_context(ctx: TeamContext, *, context_id: str, name: str = "", file: str | None = None,
                     source: str = "", scope: str = "team", visible_to: list[str] | None = None,
                     summary: str = "", force: bool = False) -> dict[str, Any]:
    contexts = _declared_for_update(ctx)
    context_id = context_id.strip()
    if not ID_PATTERN.match(context_id):
        raise TeamKitError(f"context id must match {ID_PATTERN.pattern}")
    index = _index(contexts, context_id)
    if index >= 0 and not force:
        raise TeamKitError(f"context already exists: {context_id}; use --force to replace")
    visible = normalize_visible_to(ctx, scope, [str(v) for v in visible_to or []])
    source_path = ""
    if file:
        resolved = resolve_input_file(ctx, file)
        if not resolved.is_file():
            raise TeamKitError(f"context source file not found: {resolved}")
        try:
            source_path = str(resolved.resolve().relative_to(ctx.root))
        except ValueError:
            target = ctx.root / "references" / f"{context_id}{resolved.suffix}"
            if target.exists() and not force and target.read_bytes() != resolved.read_bytes():
                raise TeamKitError(f"context target already exists: {display_path(ctx.root, target)}; use --force to overwrite")
            atomic_copyfile(resolved, target)
            source_path = display_path(ctx.root, target)
    source = source.strip() or ("" if source_path else "user_material")
    if not name.strip():
        base = Path(source_path).stem if source_path else context_id
        name = base.replace("-", " ").replace("_", " ")
    record: dict[str, Any] = {"id": context_id, "name": name.strip(), "scope": scope}
    if source_path:
        record["path"] = source_path
    if source:
        record["source"] = source
    if visible:
        record["visible_to"] = visible
    if summary:
        record["summary"] = summary
    if index >= 0:
        contexts[index] = record
    else:
        contexts.append(record)
    _save_team(ctx)
    return record


def assign_team_context(ctx: TeamContext, context_id: str, experts: list[str]) -> dict[str, Any]:
    contexts = _declared_for_update(ctx)
    index = _index(contexts, context_id)
    if index < 0:
        raise TeamKitError(f"context not found: {context_id}")
    item = contexts[index]
    visible = [str(v) for v in item.get("visible_to") or []]
    for expert_id in experts:
        ctx.require_expert(expert_id)
        if expert_id not in visible:
            visible.append(expert_id)
    if not visible:
        raise TeamKitError("at least one --visible-to expert is required")
    item["scope"] = "agents"
    item["visible_to"] = visible
    _save_team(ctx)
    return item


def unassign_team_context(ctx: TeamContext, context_id: str, experts: list[str]) -> dict[str, Any]:
    contexts = _declared_for_update(ctx)
    index = _index(contexts, context_id)
    if index < 0:
        raise TeamKitError(f"context not found: {context_id}")
    item = contexts[index]
    if str(item.get("scope") or "team") == "team":
        raise TeamKitError(f"context is visible to the whole team: {context_id}")
    remove = set(experts)
    if not remove:
        raise TeamKitError("at least one --visible-to expert is required")
    for expert_id in remove:
        ctx.require_expert(expert_id)
    visible = [str(v) for v in item.get("visible_to") or [] if str(v) not in remove]
    if not visible:
        raise TeamKitError("unassign would leave no visible experts; remove the context or assign another expert first")
    item["visible_to"] = visible
    _save_team(ctx)
    return item


def remove_team_context(ctx: TeamContext, context_id: str) -> dict[str, Any]:
    contexts = _declared_for_update(ctx)
    index = _index(contexts, context_id)
    if index < 0:
        raise TeamKitError(f"context not found: {context_id}")
    removed = contexts.pop(index)
    _save_team(ctx)
    return removed
