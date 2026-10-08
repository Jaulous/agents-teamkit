"""TeamKit command-line interface.

This module only parses arguments and prints results; behavior lives in the
core modules (``runs``, ``graph``, ``contexts``, ``batch``, ``audit``) and in
host adapters (``teamkit.adapters.*``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable

if __package__ in (None, ""):  # ``python teamkit/cli.py`` source-mode entrypoint
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from teamkit import __version__  # noqa: E402
from teamkit import audit, batch, contexts, runs  # noqa: E402
from teamkit.adapters import sync_bound_run  # noqa: E402
from teamkit.errors import TeamKitError  # noqa: E402
from teamkit.fsutil import dump_yaml, read_text_option, write_json  # noqa: E402
from teamkit.plan import build_execution_plan  # noqa: E402
from teamkit.runs import RunStore  # noqa: E402
from teamkit.team import CONTEXT_SCOPES, RESPONSE_MODES, TeamContext, teamkit_home  # noqa: E402
from teamkit.validation import validate_team_definition, validation_warnings  # noqa: E402

TOPIC_STATUSES = {"active", "waiting", "resolved", "archived"}


# ---------------------------------------------------------------------- helpers


def emit(payload: Any, as_json: bool, plain: Callable[[Any], str] | str | None = None) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif callable(plain):
        print(plain(payload))
    elif isinstance(plain, str):
        print(plain)
    else:
        print(dump_yaml(payload).strip())


def team_ctx(args: argparse.Namespace) -> TeamContext:
    return TeamContext(Path(args.team))


def store_for(args: argparse.Namespace) -> RunStore:
    return RunStore(team_ctx(args), args.run)


def synced(store: RunStore, enabled: bool = True) -> dict[str, Any] | None:
    """Pull native host activity into the ledgers (caller holds the run lock)."""
    if not enabled:
        return None
    report = sync_bound_run(store)
    if report and report.get("error"):
        print(f"warning: native sync failed: {report['error']}", file=sys.stderr)
    return report


def optional_text(value: str | None, file_value: str | None) -> str | None:
    if value is None and not file_value:
        return None
    return read_text_option(value, file_value, "text", required=False)


def topic_response(store: RunStore) -> dict[str, Any]:
    from teamkit import graph as graph_engine

    response = runs.topic_view(store)
    view = runs.graph_next(store)
    response.update(graph_engine.summarize_next(view))
    response["graph"] = view
    return response


# ---------------------------------------------------------------------- home / team


def cmd_home(args: argparse.Namespace) -> int:
    ctx = team_ctx(args)
    probe = str(args.run or "_probe")
    payload = {
        "toolHome": str(teamkit_home()),
        "teamRoot": str(ctx.root),
        "teamFile": str(ctx.team_file),
        "runBase": str(ctx.run_base(probe)),
        "teamBase": str(ctx.team_base()),
        "runBaseSource": ctx.run_base_source(),
        "runId": probe,
        "teamkitVersion": __version__,
    }
    emit(payload, args.json, lambda p: "\n".join(f"{k}: {v}" for k, v in p.items()))
    return 0


def cmd_team_validate(args: argparse.Namespace) -> int:
    ctx = team_ctx(args)
    errors = validate_team_definition(ctx)
    warnings = validation_warnings(ctx) if not errors else []
    if args.json:
        emit({"valid": not errors, "errors": errors, "warnings": warnings, "teamFile": str(ctx.team_file)}, True)
        return 2 if errors else 0
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 2
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"valid team definition: {ctx.team_file}")
    return 0


def cmd_team_compile(args: argparse.Namespace) -> int:
    plan = build_execution_plan(team_ctx(args))
    if args.out:
        out = Path(args.out).expanduser()
        out = out if out.is_absolute() else Path.cwd() / out
        write_json(out, plan)
        print(str(out))
    else:
        emit(plan, True)
    return 0


def cmd_team_context_list(args: argparse.Namespace) -> int:
    items = contexts.list_team_contexts(team_ctx(args), args.expert or args.visible_to or "")
    emit(items, args.json, lambda rows: "\n".join(
        f"{r['id']}\t{r['name']}\t{'team' if r['scope'] == 'team' else ', '.join(r['visibleTo'])}\t{r['path'] or r['source']}"
        for r in rows
    ))
    return 0


def cmd_team_context_add(args: argparse.Namespace) -> int:
    record = contexts.add_team_context(
        team_ctx(args), context_id=args.id, name=args.name or "", file=args.file, source=args.source or "",
        scope=args.scope, visible_to=args.visible_to, force=args.force,
        summary=read_text_option(args.summary, args.summary_file, "summary", required=False),
    )
    emit(contexts.team_context_view(record), args.json, record["id"])
    return 0


def cmd_team_context_assign(args: argparse.Namespace) -> int:
    item = contexts.assign_team_context(team_ctx(args), args.context, args.visible_to or [])
    emit(contexts.team_context_view(item), args.json, args.context)
    return 0


def cmd_team_context_unassign(args: argparse.Namespace) -> int:
    item = contexts.unassign_team_context(team_ctx(args), args.context, args.visible_to or [])
    emit(contexts.team_context_view(item), args.json, args.context)
    return 0


def cmd_team_context_remove(args: argparse.Namespace) -> int:
    item = contexts.remove_team_context(team_ctx(args), args.context)
    emit(contexts.team_context_view(item), args.json, args.context)
    return 0


# ---------------------------------------------------------------------- run


def cmd_run_init(args: argparse.Namespace) -> int:
    store = store_for(args)
    host = runs.host_binding_from_env()
    if args.native_team:
        host = {**(host or {"platform": "workbuddy", "boundAt": ""}), "nativeTeam": args.native_team}
    with store.lock(create=True):
        result = runs.init_run(store, brief=args.brief, force=args.force, host=host)
        view = runs.status_view(store)
    if args.json:
        emit({**result, "nextStep": view.get("nextStep"), "nextExpert": view.get("nextExpert"),
              "nextTask": view.get("nextTask")}, True)
    else:
        print(f"initialized run {store.run_id} at {store.base}")
        if result.get("archivedPrevious"):
            print(f"previous run moved to {result['archivedPrevious']}")
        print(f"nextStep: {view.get('nextStep')}")
    return 0


def cmd_run_bind(args: argparse.Namespace) -> int:
    store = store_for(args)
    binding = runs.host_binding_from_env() or {"platform": args.platform}
    binding["platform"] = args.platform or binding.get("platform")
    if args.native_team:
        binding["nativeTeam"] = args.native_team
    if args.session_id:
        binding["sessionId"] = args.session_id
    with store.lock():
        merged = runs.bind_host(store, binding)
        report = synced(store)
    emit({"host": merged, "sync": report}, args.json, lambda p: json.dumps(p, ensure_ascii=False))
    return 0


def cmd_run_status(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        report = synced(store, not args.no_sync)
        view = runs.status_view(store)
    if report is not None:
        view["sync"] = report
    emit(view, args.json)
    return 0


def cmd_run_close(args: argparse.Namespace) -> int:
    store = store_for(args)
    summary = optional_text(args.summary, args.summary_file)
    with store.lock():
        synced(store)
        result = runs.close_run(store, status=args.status, summary=summary, by=args.by or "")
    emit(result, args.json, store.run_id)
    return 0


def cmd_run_audit(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        report = synced(store, not args.no_sync)
        result = audit.audit_run(store, report)
    if args.json:
        emit(result, True)
    else:
        print(f"run {result['runId']}: {result['verdict']} (status {result['runStatus']})")
        for item in result["checks"]:
            print(f"  [{item['status']}] {item['check']}: {item['detail']}")
    return 1 if result["verdict"] == "FAIL" and args.strict else 0


# ---------------------------------------------------------------------- topic / graph


def cmd_topic_status(args: argparse.Namespace) -> int:
    store = store_for(args)
    store.load_state()
    emit(runs.topic_view(store), args.json)
    return 0


def cmd_topic_update(args: argparse.Namespace) -> int:
    store = store_for(args)
    waiting = None
    if args.waiting_type or args.waiting_ref or args.waiting_summary:
        if not args.waiting_type or not args.waiting_summary:
            raise TeamKitError("--waiting-type and --waiting-summary are required when setting waiting")
        waiting = {"type": args.waiting_type, "ref": args.waiting_ref or "", "summary": args.waiting_summary}
    with store.lock():
        topic = runs.update_topic(
            store, status=args.status, responsible=args.responsible, current_node=args.current_node,
            summary=optional_text(args.summary, args.summary_file), clear_waiting=args.clear_waiting,
            waiting=waiting, evidence_refs=args.evidence_ref, by=args.by or "",
        )
        response = topic_response(store) if args.json else None
    emit(response, args.json, str(topic.get("id")))
    return 0


def cmd_topic_link(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        runs.link_evidence(store, args.ref, args.label or "", args.by or "")
    print(args.ref)
    return 0


def cmd_graph_next(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        synced(store, not args.no_sync)
        result = runs.graph_next(store, args.from_node or "", args.ignore_waiting)
    if args.json:
        emit(result, True)
        return 0
    if result.get("blocked"):
        print(f"blocked: {result.get('reason')}")
        for msg_id in result.get("openMessages", []):
            print(f"- open message: {msg_id}")
        return 0
    if not result.get("actions"):
        print(result.get("reason") or "no next actions")
        return 0
    for action in result["actions"]:
        suffix = "" if action["allowed"] else f" ({action['reason']})"
        print(f"{action['id']}: {action['from']} -> {action['to']} [{action['expert']}] when {action['when']}{suffix}")
    return 0


def cmd_graph_advance(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        synced(store)
        transition = runs.graph_advance(
            store, node=args.node or "", edge=args.edge or "", to=args.to or "", force=args.force,
            reason=args.reason or "", summary=optional_text(args.summary, args.summary_file), by=args.by or "",
        )
        response = topic_response(store)
    if args.json:
        response.pop("graph", None)
        emit({**response, "transition": transition}, True)
    else:
        targets = transition["toNodes"]
        print(targets[0] if len(targets) == 1 else json.dumps(response.get("active_nodes", []), ensure_ascii=False))
        print(f"nextStep: {runs.next_step_hint(store, store.load_state(), store.load_topic(), response.get('graph') or runs.graph_next(store))}",
              file=sys.stderr)
    return 0


# ---------------------------------------------------------------------- messages


def cmd_msg_send(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        msg = runs.send_message(
            store, sender=args.from_expert, recipient=args.to, subject=args.subject,
            body=read_text_option(args.body, args.body_file, "body"), message_type=args.type,
            response=args.response, intent=args.intent or "", topic_id=args.topic, node=args.node,
            artifact_refs=args.artifact_ref, evidence_refs=args.evidence_ref, priority=args.priority, force=args.force,
        )
    print(msg["id"])
    return 0


def cmd_msg_reply(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        reply = runs.reply_message(
            store, sender=args.from_expert, reply_to=args.reply_to,
            body=read_text_option(args.body, args.body_file, "body"), subject=args.subject,
            artifact_refs=args.artifact_ref, evidence_refs=args.evidence_ref,
        )
    print(reply["id"])
    return 0


def cmd_msg_close(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        runs.close_message(store, by=args.from_expert, message_id=args.message, resolution=args.resolution, reason=args.reason)
    print(args.message)
    return 0


def cmd_msg_list(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        synced(store, not args.no_sync)
        messages = runs.list_messages(store, args.status or "", args.expert or "")
    emit(messages, args.json, lambda rows: "\n".join(
        f"{m.get('id')} [{m.get('status')}] {m.get('from')} -> {m.get('to')}: {m.get('subject')}" for m in rows
    ))
    return 0


# ---------------------------------------------------------------------- artifacts / contexts / human / result


def cmd_artifact_publish(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        store.load_state()
        record = runs.publish_artifact(store, args.from_expert, runs.resolve_input_file(store.ctx, args.file, args.run), args.kind)
    emit(record, args.json, record["id"])
    return 0


def cmd_artifact_list(args: argparse.Namespace) -> int:
    records = runs.list_artifacts(store_for(args), args.kind or "")
    emit(records, args.json, lambda rows: "\n".join(
        f"{r.get('id')} [{r.get('kind')}] {r.get('owner')}: {r.get('path')}" for r in rows
    ))
    return 0


def cmd_context_add(args: argparse.Namespace) -> int:
    store = store_for(args)
    text = optional_text(args.text, args.text_file)
    with store.lock():
        record = contexts.add_run_context(
            store, file=args.file, text=text, context_id=args.id or "", name=args.name or "",
            source_type=args.source_type or "", scope=args.scope, visible_to=args.visible_to,
            summary=read_text_option(args.summary, args.summary_file, "summary", required=False), by=args.by or "",
        )
    emit(record, args.json, record["id"])
    return 0


def cmd_context_list(args: argparse.Namespace) -> int:
    records = contexts.list_run_contexts(store_for(args), args.visible_to or "", args.scope or "")
    emit(records, args.json, lambda rows: "\n".join(
        f"{r.get('id')} [{'team' if r.get('scope') == 'team' else ','.join(r.get('visibleTo') or [])}] {r.get('name')}: {r.get('path')}"
        for r in rows
    ))
    return 0


def cmd_human_request(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        review = runs.request_human(
            store, sender=args.from_expert, reason=args.reason,
            question=read_text_option(args.question, args.question_file, "question"),
            blocking=not args.non_blocking, artifact_refs=args.artifact_ref, evidence_refs=args.evidence_ref,
        )
    print(review["id"])
    return 0


def cmd_human_resolve(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        runs.resolve_human(store, review_id=args.review, resolution=args.resolution,
                           answer=read_text_option(args.answer, args.answer_file, "answer"), by=args.by, force=args.force)
    print(args.review)
    return 0


def cmd_human_list(args: argparse.Namespace) -> int:
    records = runs.list_human(store_for(args), args.status or "")
    emit(records, args.json, lambda rows: "\n".join(
        f"{r.get('id')} [{r.get('status')}{'' if r.get('blocking', True) else ', non-blocking'}] {r.get('from')}: {r.get('reason')}"
        for r in rows
    ))
    return 0


def cmd_result_publish(args: argparse.Namespace) -> int:
    store = store_for(args)
    with store.lock():
        store.load_state()
        source = runs.resolve_input_file(store.ctx, args.file, args.run)
        if not source.is_file():
            raise TeamKitError(f"result file not found: {source}")
        record = runs.publish_result(store, args.from_expert, source)
    emit(record, args.json, record["id"])
    return 0


# ---------------------------------------------------------------------- batch


def cmd_batch_init(args: argparse.Namespace) -> int:
    result = batch.init_batch(team_ctx(args), args.batch, Path(args.cases_dir), args.force)
    emit(result, args.json, result["batchId"])
    return 0


def cmd_batch_next(args: argparse.Namespace) -> int:
    emit(batch.next_cases(team_ctx(args), args.batch, int(args.max)), True)
    return 0


def cmd_batch_update(args: argparse.Namespace) -> int:
    batch.update_case(team_ctx(args), args.batch, args.case, args.status, args.run)
    print(args.case)
    return 0


def cmd_batch_status(args: argparse.Namespace) -> int:
    payload = batch.batch_status(team_ctx(args), args.batch)

    def plain(p: dict[str, Any]) -> str:
        counts = p["counts"]
        lines = [f"{p['batchId']} pending={counts['pending']} running={counts['running']} done={counts['done']} failed={counts['failed']}"]
        lines += [f"{expert}: {count}" for expert, count in p["runningByExpert"].items()]
        return "\n".join(lines)

    emit(payload, args.json, plain)
    return 0


def cmd_batch_recover(args: argparse.Namespace) -> int:
    if args.stale is None:
        raise TeamKitError("batch recover requires explicit --stale <minutes>")
    recovered = batch.recover_batch(team_ctx(args), args.batch, args.stale)
    emit({"batchId": args.batch, "recovered": recovered}, args.json, "\n".join(recovered))
    return 0


# ---------------------------------------------------------------------- workbuddy


def cmd_workbuddy_detect(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import installer, paths

    info = installer.detect(paths.config_dir(args.config_dir))
    emit(info, args.json, lambda p: "\n".join(f"{k}: {v}" for k, v in p.items()))
    return 0


def cmd_workbuddy_doctor(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import installer, paths

    report = installer.doctor(paths.config_dir(args.config_dir))
    if args.json:
        emit(report, True)
    else:
        print(f"WorkBuddy doctor: {report['verdict']} (TeamKit {report['teamkitVersion']})")
        for item in report["checks"]:
            print(f"  [{item['status']}] {item['check']}: {item['detail']}")
    return 1 if report["verdict"] == "FAIL" else 0


def cmd_workbuddy_export(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import package, paths

    ctx = team_ctx(args)
    name = paths.package_name_for(ctx, args.name)
    out_root = Path(args.out).expanduser() if args.out else teamkit_home() / "build" / "workbuddy"
    package_dir = package.export_team_package(ctx, out_root, name, args.force)
    emit({"packageDir": str(package_dir), "packageName": name}, args.json, str(package_dir))
    return 0


def cmd_workbuddy_export_init(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import package

    out_root = Path(args.out).expanduser() if args.out else teamkit_home() / "build" / "workbuddy"
    package_dir = package.export_workbench_package(out_root, args.name or package.WORKBENCH_NAME, args.force)
    emit({"packageDir": str(package_dir), "packageName": package_dir.name}, args.json, str(package_dir))
    return 0


def cmd_workbuddy_install(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import installer, paths

    result = installer.install(Path(args.package), paths.config_dir(args.config_dir), force=args.force,
                               strict=args.strict, session_id=args.session_id or "")
    for warning in result.get("warnings") or []:
        print(f"warning: {warning}", file=sys.stderr)
    emit(result, args.json, result["installedDir"])
    return 0


def cmd_workbuddy_uninstall(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import installer, paths

    result = installer.uninstall(args.package, paths.config_dir(args.config_dir), args.force)
    emit(result, args.json, result["packageName"])
    return 0


def cmd_workbuddy_sync(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import native, paths

    store = store_for(args)
    with store.lock():
        if args.native_team:
            runs.bind_host(store, {"platform": "workbuddy", "nativeTeam": args.native_team})
        report = native.sync_run(store, paths.config_dir(args.config_dir))
    emit(report, args.json, lambda p: json.dumps(p, ensure_ascii=False))
    return 0 if report.get("ok") else 1


def cmd_workbuddy_teams(args: argparse.Namespace) -> int:
    from teamkit.adapters.workbuddy import native, paths

    config = paths.config_dir(args.config_dir)
    if args.native_team:
        emit(native.native_overview(config, args.native_team), True)
        return 0
    teams = sorted(native.list_teams(config), key=lambda t: float(t["config"].get("createdAt") or 0), reverse=True)
    rows = [{"team": t["name"], "leadSessionId": t["config"].get("leadSessionId"),
             "members": len(t["config"].get("members") or []), "createdAt": t["config"].get("createdAt")}
            for t in teams[: args.limit]]
    emit(rows, args.json, lambda items: "\n".join(f"{r['team']}\tmembers={r['members']}\tlead={r['leadSessionId']}" for r in items))
    return 0


# ---------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="teamkit",
        description="Deterministic command layer for TeamKit. Pass --team PATH anywhere; default is team.yaml.",
    )
    parser.add_argument("--version", action="version", version=f"teamkit {__version__}")
    sub = parser.add_subparsers(dest="area", required=True)

    def command(parent: Any, name: str, func: Callable[[argparse.Namespace], int], *, run: bool = False,
                json_flag: bool = False, help_text: str | None = None) -> argparse.ArgumentParser:
        p = parent.add_parser(name, help=help_text)
        if run:
            p.add_argument("--run", required=True)
        if json_flag:
            p.add_argument("--json", action="store_true")
        p.set_defaults(func=func)
        return p

    home = command(sub, "home", cmd_home, json_flag=True, help_text="show tool home and run locations")
    home.add_argument("--run")

    team = sub.add_parser("team", help="validate, compile and edit a team definition")
    team_sub = team.add_subparsers(dest="command", required=True)
    command(team_sub, "validate", cmd_team_validate, json_flag=True)
    command(team_sub, "compile", cmd_team_compile).add_argument("--out")
    team_context = team_sub.add_parser("context")
    tc_sub = team_context.add_subparsers(dest="context_command", required=True)
    p = command(tc_sub, "list", cmd_team_context_list, json_flag=True)
    p.add_argument("--expert")
    p.add_argument("--visible-to")
    p = command(tc_sub, "add", cmd_team_context_add, json_flag=True)
    p.add_argument("--id", required=True)
    p.add_argument("--name")
    p.add_argument("--file")
    p.add_argument("--source")
    p.add_argument("--scope", default="team", choices=sorted(CONTEXT_SCOPES))
    p.add_argument("--visible-to", action="append")
    p.add_argument("--summary")
    p.add_argument("--summary-file")
    p.add_argument("--force", action="store_true")
    for name, func in (("assign", cmd_team_context_assign), ("unassign", cmd_team_context_unassign)):
        p = command(tc_sub, name, func, json_flag=True)
        p.add_argument("--context", required=True)
        p.add_argument("--visible-to", action="append", required=True)
    command(tc_sub, "remove", cmd_team_context_remove, json_flag=True).add_argument("--context", required=True)

    run = sub.add_parser("run", help="run lifecycle")
    run_sub = run.add_subparsers(dest="command", required=True)
    p = command(run_sub, "init", cmd_run_init, run=True, json_flag=True)
    p.add_argument("--brief")
    p.add_argument("--force", action="store_true", help="start over; the previous run is archived, not deleted")
    p.add_argument("--native-team", help="bind to a known host team name")
    p = command(run_sub, "status", cmd_run_status, run=True, json_flag=True)
    p.add_argument("--no-sync", action="store_true", help="do not ingest native host activity first")
    p = command(run_sub, "close", cmd_run_close, run=True, json_flag=True)
    p.add_argument("--by")
    p.add_argument("--status", default="completed", choices=sorted(runs.RUN_CLOSED_STATUSES))
    p.add_argument("--summary")
    p.add_argument("--summary-file")
    p = command(run_sub, "audit", cmd_run_audit, run=True, json_flag=True, help_text="check protocol compliance")
    p.add_argument("--no-sync", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 when the verdict is FAIL")
    p = command(run_sub, "bind", cmd_run_bind, run=True, json_flag=True, help_text="bind a run to a host session/team")
    p.add_argument("--platform", default="workbuddy")
    p.add_argument("--native-team")
    p.add_argument("--session-id")

    topic = sub.add_parser("topic")
    topic_sub = topic.add_subparsers(dest="command", required=True)
    command(topic_sub, "status", cmd_topic_status, run=True, json_flag=True)
    p = command(topic_sub, "update", cmd_topic_update, run=True, json_flag=True)
    p.add_argument("--status", choices=sorted(TOPIC_STATUSES))
    p.add_argument("--responsible")
    p.add_argument("--current-node")
    p.add_argument("--summary")
    p.add_argument("--summary-file")
    p.add_argument("--waiting-type")
    p.add_argument("--waiting-ref")
    p.add_argument("--waiting-summary")
    p.add_argument("--clear-waiting", action="store_true")
    p.add_argument("--evidence-ref", action="append")
    p.add_argument("--by")
    p = command(topic_sub, "link", cmd_topic_link, run=True)
    p.add_argument("--ref", required=True)
    p.add_argument("--label")
    p.add_argument("--by")

    graph = sub.add_parser("graph")
    graph_sub = graph.add_subparsers(dest="command", required=True)
    p = command(graph_sub, "next", cmd_graph_next, run=True, json_flag=True)
    p.add_argument("--from-node")
    p.add_argument("--ignore-waiting", action="store_true")
    p.add_argument("--no-sync", action="store_true")
    p = command(graph_sub, "advance", cmd_graph_advance, run=True, json_flag=True)
    p.add_argument("--node")
    p.add_argument("--edge")
    p.add_argument("--to")
    p.add_argument("--summary")
    p.add_argument("--summary-file")
    p.add_argument("--force", action="store_true", help="skip unanswered-message/waiting blockers (needs --reason)")
    p.add_argument("--reason")
    p.add_argument("--by")

    msg = sub.add_parser("msg")
    msg_sub = msg.add_subparsers(dest="command", required=True)
    p = command(msg_sub, "send", cmd_msg_send, run=True)
    p.add_argument("--from", dest="from_expert", required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("--response", choices=sorted(RESPONSE_MODES))
    p.add_argument("--type", default="request")
    p.add_argument("--intent")
    p.add_argument("--topic")
    p.add_argument("--node")
    p.add_argument("--artifact-ref", action="append")
    p.add_argument("--evidence-ref", action="append")
    p.add_argument("--priority", default="normal")
    p.add_argument("--force", action="store_true")
    p = command(msg_sub, "reply", cmd_msg_reply, run=True)
    p.add_argument("--from", dest="from_expert", required=True)
    p.add_argument("--reply-to", required=True)
    p.add_argument("--subject")
    p.add_argument("--body")
    p.add_argument("--body-file")
    p.add_argument("--artifact-ref", action="append")
    p.add_argument("--evidence-ref", action="append")
    p = command(msg_sub, "close", cmd_msg_close, run=True)
    p.add_argument("--from", dest="from_expert", required=True)
    p.add_argument("--message", required=True)
    p.add_argument("--resolution", required=True, choices=["no_reply", "cancelled", "superseded", "completed_elsewhere"])
    p.add_argument("--reason", required=True)
    p = command(msg_sub, "list", cmd_msg_list, run=True, json_flag=True)
    p.add_argument("--status")
    p.add_argument("--expert")
    p.add_argument("--no-sync", action="store_true")

    artifact = sub.add_parser("artifact")
    artifact_sub = artifact.add_subparsers(dest="command", required=True)
    p = command(artifact_sub, "publish", cmd_artifact_publish, run=True, json_flag=True)
    p.add_argument("--from", dest="from_expert", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--kind", default="expert_result", choices=["expert_result", "final", "other"])
    command(artifact_sub, "list", cmd_artifact_list, run=True, json_flag=True).add_argument("--kind")

    context = sub.add_parser("context")
    context_sub = context.add_subparsers(dest="command", required=True)
    p = command(context_sub, "add", cmd_context_add, run=True, json_flag=True)
    p.add_argument("--file")
    p.add_argument("--text")
    p.add_argument("--text-file")
    p.add_argument("--id")
    p.add_argument("--name")
    p.add_argument("--source-type")
    p.add_argument("--scope", choices=sorted(CONTEXT_SCOPES))
    p.add_argument("--visible-to", action="append")
    p.add_argument("--summary")
    p.add_argument("--summary-file")
    p.add_argument("--by")
    p = command(context_sub, "list", cmd_context_list, run=True, json_flag=True)
    p.add_argument("--scope", choices=sorted(CONTEXT_SCOPES))
    p.add_argument("--visible-to")

    human = sub.add_parser("human")
    human_sub = human.add_subparsers(dest="command", required=True)
    p = command(human_sub, "request", cmd_human_request, run=True)
    p.add_argument("--from", dest="from_expert", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--question")
    p.add_argument("--question-file")
    p.add_argument("--non-blocking", action="store_true", help="record a follow-up without pausing the run")
    p.add_argument("--artifact-ref", action="append")
    p.add_argument("--evidence-ref", action="append")
    p = command(human_sub, "resolve", cmd_human_resolve, run=True)
    p.add_argument("--review", required=True)
    p.add_argument("--by", default="human")
    p.add_argument("--resolution", required=True)
    p.add_argument("--answer")
    p.add_argument("--answer-file")
    p.add_argument("--force", action="store_true")
    command(human_sub, "list", cmd_human_list, run=True, json_flag=True).add_argument("--status")

    result = sub.add_parser("result")
    result_sub = result.add_subparsers(dest="command", required=True)
    p = command(result_sub, "publish", cmd_result_publish, run=True, json_flag=True)
    p.add_argument("--from", dest="from_expert", required=True)
    p.add_argument("--file", required=True)

    batch_parser = sub.add_parser("batch")
    batch_sub = batch_parser.add_subparsers(dest="command", required=True)
    p = command(batch_sub, "init", cmd_batch_init, json_flag=True)
    p.add_argument("--batch", required=True)
    p.add_argument("--cases-dir", required=True)
    p.add_argument("--force", action="store_true")
    p = command(batch_sub, "next", cmd_batch_next)
    p.add_argument("--batch", required=True)
    p.add_argument("--max", type=int, default=1)
    p = command(batch_sub, "update", cmd_batch_update)
    p.add_argument("--batch", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--run")
    command(batch_sub, "status", cmd_batch_status, json_flag=True).add_argument("--batch", required=True)
    p = command(batch_sub, "recover", cmd_batch_recover, json_flag=True)
    p.add_argument("--batch", required=True)
    p.add_argument("--stale", type=float)

    workbuddy = sub.add_parser("workbuddy", help="WorkBuddy adapter")
    wb_sub = workbuddy.add_subparsers(dest="command", required=True)
    command(wb_sub, "detect", cmd_workbuddy_detect, json_flag=True).add_argument("--config-dir")
    command(wb_sub, "doctor", cmd_workbuddy_doctor, json_flag=True).add_argument("--config-dir")
    for name, func in (("export", cmd_workbuddy_export), ("export-init", cmd_workbuddy_export_init)):
        p = command(wb_sub, name, func, json_flag=True)
        p.add_argument("--out")
        p.add_argument("--name")
        p.add_argument("--force", action="store_true")
    p = command(wb_sub, "install", cmd_workbuddy_install, json_flag=True)
    p.add_argument("--package", required=True)
    p.add_argument("--config-dir")
    p.add_argument("--session-id")
    p.add_argument("--force", action="store_true")
    p.add_argument("--strict", action="store_true", help="require WorkBuddy's official validator")
    p = command(wb_sub, "uninstall", cmd_workbuddy_uninstall, json_flag=True)
    p.add_argument("--package", required=True)
    p.add_argument("--config-dir")
    p.add_argument("--force", action="store_true")
    p = command(wb_sub, "sync", cmd_workbuddy_sync, run=True, json_flag=True, help_text="ingest native team activity")
    p.add_argument("--native-team")
    p.add_argument("--config-dir")
    p = command(wb_sub, "teams", cmd_workbuddy_teams, json_flag=True, help_text="list native Agent Teams")
    p.add_argument("--native-team")
    p.add_argument("--config-dir")
    p.add_argument("--limit", type=int, default=20)
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
        else:
            cleaned.append(token)
        index += 1
    return team, cleaned


def main(argv: list[str] | None = None) -> int:
    try:
        team, cleaned = extract_team_argument(argv)
    except TeamKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    args = build_parser().parse_args(cleaned)
    args.team = team
    try:
        return int(args.func(args) or 0)
    except TeamKitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
