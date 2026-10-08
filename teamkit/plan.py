"""Compile a team definition into a platform-neutral execution plan."""

from __future__ import annotations

from typing import Any

from teamkit.fsutil import display_path, now
from teamkit.team import TeamContext
from teamkit.validation import validate_or_raise

COMMAND_CONTRACT = {
    "run": "teamkit run init/status/close/audit/bind",
    "topic": "teamkit topic status/update/link",
    "teamContext": "teamkit team context add/assign/unassign/remove/list",
    "context": "teamkit context add/list",
    "graph": "teamkit graph next/advance",
    "messages": "teamkit msg send/reply/close/list",
    "artifacts": "teamkit artifact publish/list",
    "humanReview": "teamkit human request/resolve/list",
    "result": "teamkit result publish",
    "batch": "teamkit batch init/next/update/status/recover",
}


def build_execution_plan(ctx: TeamContext) -> dict[str, Any]:
    from teamkit.adapters import available_adapters

    validate_or_raise(ctx)
    contexts = []
    for item in ctx.declared_contexts():
        raw_path = item.get("path") or item.get("file") or ""
        contexts.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "path": display_path(ctx.root, ctx.reference_path(str(raw_path))) if raw_path else "",
            "scope": item.get("scope", "team"),
            "visibleTo": item.get("visible_to", []) or [],
            "source": item.get("source", "file"),
            "summary": item.get("summary", ""),
        })
    experts = []
    for expert in ctx.experts.values():
        profile_path = ctx.profile_path(expert)
        experts.append({
            "id": expert["id"],
            "name": expert["name"],
            "role": expert.get("role", ""),
            "profilePath": display_path(ctx.root, profile_path),
            "profile": profile_path.read_text(encoding="utf-8"),
            "allowedPeers": ctx.allowed_peers(str(expert["id"])),
            "references": [
                {"path": display_path(ctx.root, ctx.reference_path(str(ref))), "exists": ctx.reference_path(str(ref)).exists()}
                for ref in expert.get("references") or []
            ],
        })
    return {
        "schemaVersion": "teamkit.execution_plan.v0.1",
        "generatedAt": now(),
        "team": ctx.team_meta(),
        "process": {
            "mode": ctx.process().get("mode"),
            "lead": ctx.process().get("lead", ""),
            "coordinator": ctx.coordinator_id(),
            "communication": {**ctx.communication(), "effectiveMode": ctx.communication_mode()},
            "graph": ctx.graph(),
        },
        "experts": experts,
        "contexts": contexts,
        "materials": ctx.team.get("materials") or {},
        "humanReview": ctx.team.get("human_review") or {},
        "workspace": ctx.team.get("workspace") or {},
        "output": ctx.team.get("output") or {},
        "commandContract": COMMAND_CONTRACT,
        "adapterBoundary": {
            "target": None,
            "status": "not_bound",
            "availableAdapters": available_adapters(),
            "note": "Map this plan to a target runtime in an Adapter layer. WorkBuddy is the first available package-level adapter.",
        },
    }
