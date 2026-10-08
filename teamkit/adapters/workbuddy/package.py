"""Export TeamKit teams (and the Workbench) as WorkBuddy expert packages."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
import uuid

from teamkit import __version__
from teamkit.errors import TeamKitError
from teamkit.fsutil import load_yaml, write_json, yaml
from teamkit.team import ID_PATTERN, TeamContext, kebab_case
from teamkit.validation import validate_or_raise
from teamkit.adapters.workbuddy import paths, prompts

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # the importable ``teamkit`` package
AUTHOR = {"name": "Agents TeamKit contributors", "url": "https://github.com/Jaulous/agents-teamkit"}
WORKBENCH_NAME = "agents-teamkit-workbench"
VALID_CATEGORIES = {
    "01-ProductDesign", "02-Engineering", "03-GameSpatial", "04-DataAI", "05-MarketingGrowth",
    "06-ContentCreative", "07-SalesCommerce", "08-FinanceInvestment", "09-OperationsHR",
    "10-ProjectQuality", "11-SecurityCompliance", "12-IndustryConsultant",
}

LAUNCHER = """#!/bin/sh
# Agents TeamKit launcher (generated). Finds Python 3.9+ and runs the vendored CLI.
# No network access or pip install is needed: all dependencies are vendored.
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLUGIN_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
CONFIG_DIR=${WORKBUDDY_CONFIG_DIR:-$HOME/.workbuddy}
ENTRY="$PLUGIN_ROOT/vendor/teamkit_entry.py"
usable() {
  [ -n "$1" ] || return 1
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1
}
for candidate in "$TEAMKIT_PYTHON" "$CONFIG_DIR/binaries/python/envs/default/bin/python3" \\
    "$CONFIG_DIR"/binaries/python/versions/*/bin/python3 python3 python; do
  if usable "$candidate"; then
    exec "$candidate" "$ENTRY" "$@"
  fi
done
echo "error: Agents TeamKit needs Python 3.9+; install one or set TEAMKIT_PYTHON" >&2
exit 127
"""

ENTRY = '''"""Agents TeamKit runtime entry for WorkBuddy packages (generated)."""
import json
import os
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent
PLUGIN_ROOT = VENDOR.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(VENDOR))


def team_argument(argv):
    for index, token in enumerate(argv):
        if token == "--team" and index + 1 < len(argv):
            return argv[index + 1]
        if token.startswith("--team="):
            return token.split("=", 1)[1]
    return ""


def main():
    settings = json.loads((VENDOR / "teamkit_entry.json").read_text(encoding="utf-8"))
    argv = list(sys.argv[1:])
    config_dir = Path(os.environ.get("WORKBUDDY_CONFIG_DIR") or Path.home() / ".workbuddy").expanduser()
    team_file = team_argument(argv)
    if not team_file and settings.get("mode") == "team":
        team_file = os.environ.get("TEAMKIT_TEAM_FILE") or str(PLUGIN_ROOT / "teamkit-workspace" / "team.yaml")
        argv = ["--team", team_file, *argv]
    if team_file:
        roster = Path(team_file).expanduser().resolve().parent / "roster.json"
        if roster.is_file():
            data = json.loads(roster.read_text(encoding="utf-8"))
            os.environ.setdefault("TEAMKIT_HOST", "workbuddy")
            os.environ.setdefault("TEAMKIT_HOST_PACKAGE", str(data.get("package") or ""))
            os.environ.setdefault("TEAMKIT_RUNS_DIR", str(config_dir / "teamkit-runs" / str(data.get("teamId"))))
    from teamkit.cli import main as teamkit_main

    return teamkit_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
'''


# ---------------------------------------------------------------------- adapter manifest (workbuddy.yaml)


def adapter_manifest(ctx: TeamContext) -> dict[str, Any]:
    """Optional WorkBuddy-only settings kept beside team.yaml, never inside it."""
    path = ctx.root / "workbuddy.yaml"
    return load_yaml(path) if path.exists() else {}


def skill_specs(ctx: TeamContext, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw_skills = manifest.get("skills") or []
    if not isinstance(raw_skills, list):
        raise TeamKitError("workbuddy.yaml skills must be a list")
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_skills):
        if isinstance(raw, str):
            name, source_value, agents = Path(raw).name, raw, []
        elif isinstance(raw, dict):
            name = str(raw.get("name") or "").strip()
            source_value = str(raw.get("path") or raw.get("source") or "").strip()
            agents = raw.get("agents") or raw.get("required_by") or []
            if not isinstance(agents, list) or not all(isinstance(item, str) for item in agents):
                raise TeamKitError(f"workbuddy.yaml skills[{index}].agents must be a list of expert ids")
        else:
            raise TeamKitError(f"workbuddy.yaml skills[{index}] must be a string or object")
        if not name:
            raise TeamKitError(f"workbuddy.yaml skills[{index}].name is required")
        if not ID_PATTERN.match(name):
            raise TeamKitError(f"workbuddy.yaml skills[{index}].name is not a valid id: {name}")
        if name == "teamkit-runtime":
            raise TeamKitError("workbuddy.yaml must not redeclare the built-in teamkit-runtime skill")
        if name in seen:
            raise TeamKitError(f"duplicate WorkBuddy skill: {name}")
        seen.add(name)
        if not source_value:
            raise TeamKitError(f"workbuddy.yaml skills[{index}].path is required")
        source = (ctx.root / source_value).expanduser().resolve()
        if not (source / "SKILL.md").is_file():
            raise TeamKitError(f"WorkBuddy skill must be a directory containing SKILL.md: {source}")
        for expert_id in agents:
            ctx.require_expert(expert_id)
        specs.append({"name": name, "source": source, "agents": list(agents)})
    return specs


def skills_for(specs: list[dict[str, Any]], expert_id: str) -> list[str]:
    return ["teamkit-runtime", *[spec["name"] for spec in specs if not spec["agents"] or expert_id in spec["agents"]]]


def _i18n(value: Any, fallback_zh: str, fallback_en: str) -> dict[str, str]:
    if isinstance(value, dict):
        return {"zh": str(value.get("zh") or fallback_zh), "en": str(value.get("en") or fallback_en)}
    if isinstance(value, str) and value:
        return {"zh": value, "en": fallback_en}
    return {"zh": fallback_zh, "en": fallback_en}


def _category(ctx: TeamContext, display: dict[str, Any]) -> str:
    declared = str(display.get("category") or "")
    if declared:
        if declared not in VALID_CATEGORIES:
            raise TeamKitError(f"workbuddy.yaml display.category is not a WorkBuddy category: {declared}")
        return declared
    text = json.dumps(ctx.team_meta(), ensure_ascii=False)
    if any(token in text for token in ("合规", "法务", "隐私", "安全", "风控", "风险", "审核")):
        return "11-SecurityCompliance"
    if any(token in text for token in ("金融", "投资", "结汇", "支付", "财务")):
        return "08-FinanceInvestment"
    if any(token in text for token in ("数据", "模型", "智能", "AI")):
        return "04-DataAI"
    if any(token in text for token in ("运营", "人力", "流程")):
        return "09-OperationsHR"
    return "10-ProjectQuality"


def _three(items: Any, defaults: list[dict[str, str]], label: str) -> list[dict[str, str]]:
    if not items:
        return defaults
    if not isinstance(items, list) or len(items) != 3:
        raise TeamKitError(f"workbuddy.yaml display.{label} must list exactly 3 items")
    return [_i18n(item, str(item), str(item)) for item in items]


def _zh_description(ctx: TeamContext) -> str:
    """WorkBuddy cards expect a 40-50 character Chinese summary."""
    purpose = " ".join(str(ctx.team_meta().get("purpose") or "").split()).rstrip("。；;. ")
    text = purpose or f"{ctx.team_name}多专家协作完成业务任务"
    if len(text) < 40:
        text = f"{text}；{len(ctx.experts)}位专家按流程图分工协作，全程可追踪、可审计"
    if len(text) < 40:
        text = f"{text}，结论有据可查"
    return text if len(text) <= 50 else text[:49] + "…"


# ---------------------------------------------------------------------- shared helpers


def copy_runtime(staging: Path, mode: str, roster: dict[str, Any] | None = None) -> None:
    """Vendor the TeamKit package plus the launcher entry into ``staging``."""
    vendor = staging / "vendor"
    shutil.copytree(
        PACKAGE_ROOT,
        vendor / "teamkit",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    (vendor / "teamkit_entry.py").write_text(ENTRY, encoding="utf-8")
    settings = {"mode": mode, "teamkitVersion": __version__}
    if roster:
        settings.update({"package": roster["package"], "teamId": roster["teamId"]})
    write_json(vendor / "teamkit_entry.json", settings)


def write_launcher(skill_dir: Path) -> Path:
    launcher = skill_dir / "scripts" / "teamkit"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_bytes(LAUNCHER.encode("utf-8"))  # LF endings even on Windows (Git Bash runs it)
    launcher.chmod(0o755)
    return launcher


def skill_text_for_package(source_skill: Path, allowed_tools: str) -> str:
    text = (source_skill / "SKILL.md").read_text(encoding="utf-8")
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
    rendered = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, width=1_000_000).strip()
    return f"---\n{rendered}\n---{body}"


def copy_skill(source: Path, target: Path, allowed_tools: str) -> None:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc"))
    (target / "SKILL.md").write_text(skill_text_for_package(source, allowed_tools), encoding="utf-8")


def copy_avatars(source_root: Path, target_root: Path) -> set[str]:
    source = source_root / "avatars"
    copied: set[str] = set()
    if not source.is_dir():
        return copied
    for path in source.rglob("*"):
        if not path.is_file() or path.name in {".DS_Store", ".gitkeep"}:
            continue
        relative = path.relative_to(source)
        destination = target_root / "avatars" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        copied.add(str(Path("avatars") / relative).replace(os.sep, "/"))
    return copied


def validate_package_closure(package_dir: Path) -> None:
    """Every reference in plugin.json and agent frontmatter must resolve."""
    plugin_path = package_dir / ".codebuddy-plugin" / "plugin.json"
    if not plugin_path.is_file():
        raise TeamKitError(f"WorkBuddy plugin.json not found: {plugin_path}")
    try:
        plugin = json.loads(plugin_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TeamKitError(f"invalid WorkBuddy plugin.json: {plugin_path}: {exc}") from exc
    for field in ("agents", "skills"):
        values = plugin.get(field, [])
        if not isinstance(values, list):
            raise TeamKitError(f"WorkBuddy plugin.json {field} must be a list")
        for value in values:
            if not isinstance(value, str):
                raise TeamKitError(f"WorkBuddy plugin.json {field} entries must be strings")
            target = package_dir / (value[2:] if value.startswith("./") else value)
            if field == "skills":
                target = target / "SKILL.md"
            if not target.is_file():
                raise TeamKitError(f"WorkBuddy package reference does not exist: {value}")
    for forbidden in ("hooks", "commands"):
        if (package_dir / forbidden).exists():
            raise TeamKitError(f"WorkBuddy expert packages must not contain {forbidden}/")
    agent_names = {Path(v[2:] if v.startswith("./") else v).stem for v in plugin.get("agents", []) if isinstance(v, str)}
    for agent_file in (package_dir / "agents").glob("*.md"):
        content = agent_file.read_text(encoding="utf-8")
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        try:
            metadata = yaml.safe_load(match.group(1)) if match else None
        except yaml.YAMLError as exc:
            raise TeamKitError(f"invalid WorkBuddy agent frontmatter: {agent_file.name}: {exc}") from exc
        if not isinstance(metadata, dict):
            raise TeamKitError(f"invalid WorkBuddy agent frontmatter: {agent_file}")
        if "tools:" in match.group(1):
            raise TeamKitError(f"WorkBuddy agent frontmatter must not contain tools: {agent_file.name}")
        if metadata.get("name") != agent_file.stem:
            raise TeamKitError(f"WorkBuddy agent name does not match filename: {agent_file.name}")
        skills = metadata.get("skills") or []
        if not isinstance(skills, list):
            raise TeamKitError(f"WorkBuddy agent skills must be a list: {agent_file}")
        for skill in skills:
            if not isinstance(skill, str) or not (package_dir / "skills" / skill / "SKILL.md").is_file():
                raise TeamKitError(f"WorkBuddy agent {agent_file.name} references missing skill: {skill}")
    if plugin.get("agentName") and plugin["agentName"] not in agent_names:
        raise TeamKitError("WorkBuddy plugin.json agentName is not listed in agents")
    references = [plugin["avatar"]] if isinstance(plugin.get("avatar"), str) else []
    references += [m["avatar"] for m in plugin.get("members", []) or [] if isinstance(m, dict) and isinstance(m.get("avatar"), str)]
    for relative in references:
        if not (package_dir / relative).is_file():
            raise TeamKitError(f"WorkBuddy package avatar reference does not exist: {relative}")


def publish_directory(staging: Path, target: Path, force: bool, backup_root: Path | None = None) -> Path | None:
    """Atomically replace ``target`` with ``staging``; return where the old copy went."""
    backup: Path | None = None
    if target.exists():
        if not force:
            raise TeamKitError(f"WorkBuddy package already exists: {target}; use --force")
        stamp = uuid.uuid4().hex[:8]
        if backup_root is not None:
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / f"{target.name}-{stamp}"
        else:
            backup = target.parent / f".{target.name}.backup-{stamp}"
        shutil.move(str(target), str(backup))
    try:
        os.replace(staging, target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            shutil.move(str(backup), str(target))
        raise
    if backup is not None and backup_root is None:
        shutil.rmtree(backup, ignore_errors=True)  # export output only: the source is team.yaml
        return None
    return backup


def _staging(out_root: Path, name: str) -> Path:
    out_root.mkdir(parents=True, exist_ok=True)
    staging = out_root / f".{name}.staging-{uuid.uuid4().hex[:12]}"
    staging.mkdir(parents=True)
    return staging


# ---------------------------------------------------------------------- team package


def export_team_package(ctx: TeamContext, out_root: Path, package_name: str, force: bool = False) -> Path:
    validate_or_raise(ctx)
    manifest = adapter_manifest(ctx)
    specs = skill_specs(ctx, manifest)
    display = manifest.get("display") or {}
    if not isinstance(display, dict):
        raise TeamKitError("workbuddy.yaml display must be an object")
    roster = paths.build_roster(ctx, package_name)
    lead_id = roster["leadAgentId"]
    agent_ids = [info["agentId"] for info in roster["experts"].values()]
    if any(info["agentId"] == lead_id for expert, info in roster["experts"].items() if expert != roster["coordinator"]):
        raise TeamKitError("an expert id collides with the generated lead Agent ID; rename the expert (avoid 'team-lead')")
    if len(set(agent_ids)) != len(agent_ids):
        raise TeamKitError("two experts map to the same WorkBuddy Agent ID; rename one expert id")

    out_root = out_root.expanduser().resolve()
    package_dir = out_root / package_name
    staging = _staging(out_root, package_name)
    try:
        team_name = ctx.team_name
        agents_dir = staging / "agents"
        agents_dir.mkdir()
        coordinator = roster["coordinator"]
        (agents_dir / f"{lead_id}.md").write_text(
            prompts.lead_markdown(ctx, roster, skills_for(specs, coordinator)), encoding="utf-8"
        )
        for expert_id, info in roster["experts"].items():
            if info["role"] == "lead":
                continue
            (agents_dir / f"{info['agentId']}.md").write_text(
                prompts.member_markdown(ctx, roster, expert_id, skills_for(specs, expert_id)), encoding="utf-8"
            )

        runtime_skill = staging / "skills" / "teamkit-runtime"
        runtime_skill.mkdir(parents=True)
        (runtime_skill / "SKILL.md").write_text(prompts.runtime_skill_markdown(roster), encoding="utf-8")
        write_launcher(runtime_skill)
        for spec in specs:
            copy_skill(spec["source"], staging / "skills" / spec["name"], "Read,Bash")

        workspace = staging / "teamkit-workspace"
        workspace.mkdir()
        shutil.copyfile(ctx.team_file, workspace / "team.yaml")
        for folder in ("experts", "references", "contexts"):
            if (ctx.root / folder).is_dir():
                shutil.copytree(ctx.root / folder, workspace / folder,
                                ignore=shutil.ignore_patterns(".DS_Store", "__pycache__"))
        write_json(workspace / "roster.json", roster)
        copy_runtime(staging, "team", roster)
        avatars = copy_avatars(ctx.root, staging)
        (staging / "settings.json").write_text(json.dumps({"agent": lead_id}, indent=2) + "\n", encoding="utf-8")

        members = [info for info in roster["experts"].values() if info["role"] == "member"]
        prompt_one = {"zh": "请用这个专家团处理一个任务，先帮我初始化运行。", "en": "Use this expert team to handle a task and initialize the run first."}
        quick = _three(display.get("quick_prompts"), [
            prompt_one,
            {"zh": "帮我查看当前运行的进度、待办和下一步。", "en": "Show the current run progress, pending items, and next step."},
            {"zh": "审计这次运行是否遵守了团队协作协议。", "en": "Audit whether this run followed the team protocol."},
        ], "quick_prompts")
        plugin = {
            "name": package_name,
            "version": __version__,
            "description": str(ctx.team_meta().get("description") or f"Agents TeamKit team: {ctx.team_meta().get('purpose', team_name)}"),
            "author": AUTHOR,
            "agents": [f"./agents/{lead_id}.md", *[f"./agents/{info['agentId']}.md" for info in members]],
            "skills": ["./skills/teamkit-runtime", *[f"./skills/{spec['name']}" for spec in specs]],
            "expertType": "team",
            "agentName": lead_id,
            "teamInfo": {"leadAgent": lead_id, "memberAgents": [info["agentId"] for info in members]},
            "displayName": {"en": team_name, "zh": team_name},
            "profession": {"en": team_name, "zh": team_name},
            "displayDescription": {
                "zh": str(display.get("description_zh") or _zh_description(ctx)),
                "en": str(display.get("description_en") or f"Runs {team_name} as a WorkBuddy expert team with a TeamKit process graph and audited collaboration."),
            },
            "categoryId": _category(ctx, display),
            "defaultInitPrompt": quick[0],
            "plugin": package_name,
            "tags": _three(display.get("tags"), [
                {"en": "Multi-agent", "zh": "多专家协作"},
                {"en": "Process graph", "zh": "流程编排"},
                {"en": "Audited runs", "zh": "协作可审计"},
            ], "tags"),
            "quickPrompts": quick,
            "members": [
                {
                    "id": lead_id,
                    "displayName": {"en": team_name, "zh": team_name},
                    "profession": {"en": "Task Orchestrator", "zh": "任务编排官"},
                    **({"avatar": f"avatars/{lead_id}.png"} if f"avatars/{lead_id}.png" in avatars else {}),
                    "role": "lead",
                },
                *[
                    {
                        "id": info["agentId"],
                        "displayName": {"en": info["name"], "zh": info["name"]},
                        "profession": {"en": info["name"], "zh": info["name"]},
                        **({"avatar": f"avatars/{info['agentId']}.png"} if f"avatars/{info['agentId']}.png" in avatars else {}),
                        "role": "member",
                    }
                    for info in members
                ],
            ],
        }
        if "avatars/team.png" in avatars:
            plugin["avatar"] = "avatars/team.png"
        write_json(staging / ".codebuddy-plugin" / "plugin.json", plugin)
        readme = str(ctx.team_meta().get("readme") or "")
        (staging / "README.md").write_text(readme or _team_readme(ctx, roster), encoding="utf-8")
        validate_package_closure(staging)
        publish_directory(staging, package_dir, force)
        return package_dir
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _team_readme(ctx: TeamContext, roster: dict[str, Any]) -> str:
    rows = "\n".join(f"| `{info['agentId']}` | {info['name']} | {info['role']} |" for info in roster["experts"].values())
    return f"""# {ctx.team_name}

WorkBuddy expert team generated by Agents TeamKit {__version__}.

{ctx.team_meta().get('purpose', '')}

| Agent ID | Expert | Role |
|---|---|---|
{rows}

The lead follows the SOP compiled from `teamkit-workspace/team.yaml`. Members talk through WorkBuddy's native
`Agent` and `SendMessage` tools; TeamKit syncs that traffic into the run ledger under
`~/.workbuddy/teamkit-runs/{roster['teamId']}/` and audits it with `run audit`.
"""


# ---------------------------------------------------------------------- workbench package


def repo_skills_dir() -> Path:
    override = os.environ.get("TEAMKIT_SOURCE_DIR", "").strip()
    root = Path(override).expanduser().resolve() if override else PACKAGE_ROOT.parent
    skills = root / "skills"
    if not skills.is_dir():
        raise TeamKitError(f"TeamKit source skills directory not found: {skills} (set TEAMKIT_SOURCE_DIR)")
    return skills


def workbench_skill_names(skills_root: Path) -> list[str]:
    return sorted(item.name for item in skills_root.iterdir() if item.is_dir() and (item / "SKILL.md").is_file())


def export_workbench_package(out_root: Path, package_name: str = WORKBENCH_NAME, force: bool = False) -> Path:
    package_name = kebab_case(package_name, WORKBENCH_NAME)
    out_root = out_root.expanduser().resolve()
    package_dir = out_root / package_name
    if package_dir.exists() and not force:
        raise TeamKitError(f"WorkBuddy package already exists: {package_dir}; use --force")
    skills_root = repo_skills_dir()
    names = workbench_skill_names(skills_root)
    staging = _staging(out_root, package_name)
    try:
        agent_id = kebab_case(f"{package_name}-lead", f"{WORKBENCH_NAME}-lead")
        (staging / "agents").mkdir()
        runtime_name = "agents-teamkit-workbench-runtime"
        (staging / "agents" / f"{agent_id}.md").write_text(
            prompts.workbench_lead_markdown(agent_id, [*names, runtime_name], package_name), encoding="utf-8"
        )
        for name in names:
            copy_skill(skills_root / name, staging / "skills" / name, "Read,Write,Edit,Bash")
        runtime_dir = staging / "skills" / runtime_name
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "SKILL.md").write_text(prompts.workbench_runtime_skill_markdown(), encoding="utf-8")
        write_launcher(runtime_dir)
        copy_runtime(staging, "workbench")
        for folder in ("docs", "schemas"):
            source = skills_root.parent / folder
            if source.is_dir():
                shutil.copytree(source, staging / folder,
                                ignore=shutil.ignore_patterns(".DS_Store", "plans", "__pycache__"))
        (staging / "settings.json").write_text(json.dumps({"agent": agent_id}, indent=2) + "\n", encoding="utf-8")
        first = {"zh": "帮我创建一个新的多 Agent 团队。", "en": "Help me create a new multi-agent team."}
        plugin = {
            "name": package_name,
            "version": __version__,
            "description": "Agents TeamKit workbench for creating, validating, exporting, installing and improving multi-agent teams in WorkBuddy.",
            "author": AUTHOR,
            "agents": [f"./agents/{agent_id}.md"],
            "skills": [*[f"./skills/{name}" for name in names], f"./skills/{runtime_name}"],
            "expertType": "team",
            "agentName": agent_id,
            "teamInfo": {"leadAgent": agent_id, "memberAgents": []},
            "displayName": {"en": "Agents TeamKit Workbench", "zh": "Agents TeamKit 工作台"},
            "profession": {"en": "Agents TeamKit Workbench", "zh": "Agents TeamKit 工作台"},
            "displayDescription": {
                "en": "Create, validate, export, install and improve Agents TeamKit multi-agent teams for WorkBuddy.",
                "zh": "引导业务人员设计多专家团队，校验导出为 WorkBuddy 专家团，并审计和优化真实运行效果",
            },
            "categoryId": "04-DataAI",
            "defaultInitPrompt": first,
            "plugin": package_name,
            "tags": [
                {"en": "Agents TeamKit", "zh": "Agents TeamKit"},
                {"en": "Team Builder", "zh": "团队创建"},
                {"en": "Run Audit", "zh": "运行审计"},
            ],
            "quickPrompts": [
                first,
                {"zh": "帮我把已经定义好的团队导出并安装到 WorkBuddy。", "en": "Export my defined team and install it into WorkBuddy."},
                {"zh": "帮我审计一次团队运行，看协作协议有没有执行到位。", "en": "Audit a team run and check whether the protocol held."},
            ],
            "members": [{
                "id": agent_id,
                "displayName": {"en": "Agents TeamKit Workbench", "zh": "Agents TeamKit 工作台"},
                "profession": {"en": "Agents TeamKit Team Workbench", "zh": "Agents TeamKit 团队工作台"},
                "role": "lead",
            }],
        }
        write_json(staging / ".codebuddy-plugin" / "plugin.json", plugin)
        (staging / "README.md").write_text(
            "# Agents TeamKit 工作台\n\nWorkBuddy entry package for creating, validating, exporting, installing, "
            "auditing and improving Agents TeamKit multi-agent teams.\n",
            encoding="utf-8",
        )
        validate_package_closure(staging)
        publish_directory(staging, package_dir, force)
        return package_dir
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
