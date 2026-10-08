"""Batch ledger: a case queue for teams that process many inputs, one run per case."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from teamkit.errors import TeamKitError
from teamkit.fsutil import file_lock, now, parse_time, read_json, write_json
from teamkit.runs import RunStore
from teamkit.team import TeamContext, kebab_case

CASE_STATUSES = ("pending", "running", "done", "failed")


def batch_dir(ctx: TeamContext, batch_id: str) -> Path:
    if "/" in batch_id or "\\" in batch_id or ".." in batch_id:
        raise TeamKitError(f"invalid batch id: {batch_id}")
    return ctx.team_base() / "batches" / batch_id


def _manifest_path(ctx: TeamContext, batch_id: str) -> Path:
    return batch_dir(ctx, batch_id) / "manifest.json"


def _load(path: Path, batch_id: str) -> dict[str, Any]:
    data = read_json(path, default=None)
    if data is None:
        raise TeamKitError(f"batch not found: {batch_id}")
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list):
        raise TeamKitError(f"invalid batch manifest: {path}")
    return data


def _case_summary(ctx: TeamContext, case: dict[str, Any]) -> dict[str, Any]:
    summary = {key: case.get(key, "") for key in ("caseId", "inputRef", "status", "runId")}
    run_id = str(case.get("runId") or "")
    if case.get("status") == "running" and run_id:
        try:
            state = RunStore(ctx, run_id).load_state()
            node = ctx.graph_node_map().get(str(state.get("active_node") or ""), {})
            summary["expert"] = node.get("expert", "")
            summary["runStatus"] = state.get("status")
        except TeamKitError:
            summary["expert"] = ""
    return summary


def _payload(ctx: TeamContext, data: dict[str, Any], selected: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cases = data.get("cases", [])
    counts = {status: sum(1 for case in cases if case.get("status") == status) for status in CASE_STATUSES}
    running_by_expert: dict[str, int] = {}
    for case in cases:
        if case.get("status") != "running":
            continue
        expert = _case_summary(ctx, case).get("expert")
        if expert:
            running_by_expert[expert] = running_by_expert.get(expert, 0) + 1
    result: dict[str, Any] = {
        "batchId": data.get("batchId"),
        "teamId": data.get("teamId"),
        "counts": counts,
        "runningByExpert": running_by_expert,
    }
    if selected is not None:
        result["cases"] = [_case_summary(ctx, case) for case in selected]
    return result


def init_batch(ctx: TeamContext, label: str, cases_dir: Path, force: bool = False) -> dict[str, Any]:
    cases_dir = cases_dir.expanduser().resolve()
    if not cases_dir.is_dir():
        raise TeamKitError(f"cases directory not found: {cases_dir}")
    batch_id = f"{ctx.team_id}@{kebab_case(label, 'batch')}"
    path = _manifest_path(ctx, batch_id)
    with file_lock(path.parent / ".batch.lock"):
        if path.exists() and not force:
            raise TeamKitError(f"batch already exists: {batch_id}; use --force")
        cases = [
            {"caseId": item.stem, "inputRef": str(item), "status": "pending", "runId": "", "dispatchedAt": "", "updatedAt": now()}
            for item in sorted(cases_dir.iterdir())
            if item.is_file() and not item.name.startswith(".")
        ]
        if not cases:
            raise TeamKitError(f"cases directory has no case files: {cases_dir}")
        write_json(path, {
            "manifestVersion": "teamkit.batch.v0.1",
            "batchId": batch_id,
            "teamId": ctx.team_id,
            "label": kebab_case(label, "batch"),
            "casesDir": str(cases_dir),
            "createdAt": now(),
            "updatedAt": now(),
            "cases": cases,
        })
    return {"batchId": batch_id, "caseCount": len(cases)}


def next_cases(ctx: TeamContext, batch_id: str, limit: int = 1) -> dict[str, Any]:
    path = _manifest_path(ctx, batch_id)
    selected: list[dict[str, Any]] = []
    with file_lock(path.parent / ".batch.lock"):
        data = _load(path, batch_id)
        for case in data["cases"]:
            if case.get("status") == "pending" and len(selected) < max(1, limit):
                stamp = now()
                case.update({"status": "running", "dispatchedAt": stamp, "updatedAt": stamp})
                selected.append(case)
        data["updatedAt"] = now()
        write_json(path, data)
    return _payload(ctx, data, selected)


def update_case(ctx: TeamContext, batch_id: str, case_id: str, status: str, run_id: str | None = None) -> None:
    if status not in CASE_STATUSES:
        raise TeamKitError(f"invalid batch status: {status}")
    path = _manifest_path(ctx, batch_id)
    with file_lock(path.parent / ".batch.lock"):
        data = _load(path, batch_id)
        case = next((item for item in data["cases"] if item.get("caseId") == case_id), None)
        if case is None:
            raise TeamKitError(f"case not found: {case_id}")
        case["status"] = status
        if run_id is not None:
            case["runId"] = run_id
        case["updatedAt"] = now()
        data["updatedAt"] = now()
        write_json(path, data)


def batch_status(ctx: TeamContext, batch_id: str) -> dict[str, Any]:
    path = _manifest_path(ctx, batch_id)
    return _payload(ctx, _load(path, batch_id))


def recover_batch(ctx: TeamContext, batch_id: str, stale_minutes: float) -> list[str]:
    """Return stale running cases to pending; mark cases whose run closed as done."""
    path = _manifest_path(ctx, batch_id)
    cutoff = datetime.now(timezone.utc).timestamp() - float(stale_minutes) * 60
    recovered: list[str] = []
    with file_lock(path.parent / ".batch.lock"):
        data = _load(path, batch_id)
        for case in data["cases"]:
            if case.get("status") != "running":
                continue
            run_id = str(case.get("runId") or "")
            if run_id:
                try:
                    state = RunStore(ctx, run_id).load_state()
                except TeamKitError:
                    state = {}
                if state.get("status") == "completed":
                    case.update({"status": "done", "updatedAt": now()})
                    continue
                if state.get("status") in {"cancelled", "failed"}:
                    case.update({"status": "failed", "updatedAt": now()})
                    continue
            stamp = parse_time(case.get("updatedAt") or case.get("dispatchedAt")) or 0
            if stamp > cutoff:
                continue
            case.update({"status": "pending", "updatedAt": now()})
            recovered.append(str(case.get("caseId")))
        data["updatedAt"] = now()
        write_json(path, data)
    return recovered
