"""WorkBuddy host locations and member identity (roster).

Facts confirmed against WorkBuddy 5.3.x on macOS:

* user experts live in ``<config>/plugins/marketplaces/my-experts/plugins``;
* Agent Teams data lives in ``<config>/teams/<team>/config.json`` and
  ``<config>/teams/<team>/inboxes/<member>.json``; tasks in ``<config>/tasks/<team>``;
* the session that calls ``TeamCreate`` is the lead and is always named
  ``team-lead`` inside the native team;
* the official expert spec requires members to be spawned with
  ``name`` = ``subagent_type`` = Agent ID (the agent markdown file name).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from teamkit.team import TeamContext, kebab_case

DEFAULT_APP = Path("/Applications/WorkBuddy.app")
NATIVE_LEAD_NAME = "team-lead"
MARKETPLACE = "my-experts"


def app_path() -> Path:
    raw = os.environ.get("WORKBUDDY_APP_PATH", "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_APP


def config_dir(raw: str | None = None) -> Path:
    value = (raw or os.environ.get("WORKBUDDY_CONFIG_DIR") or "").strip()
    return Path(value).expanduser().resolve() if value else Path.home() / ".workbuddy"


def marketplace_dir(config: Path) -> Path:
    return config / "plugins" / "marketplaces" / MARKETPLACE


def plugins_dir(config: Path) -> Path:
    return marketplace_dir(config) / "plugins"


def teams_dir(config: Path) -> Path:
    return config / "teams"


def tasks_dir(config: Path) -> Path:
    return config / "tasks"


def default_runs_dir(config: Path, team_id: str) -> Path:
    return config / "teamkit-runs" / team_id


def bundled_python_candidates(config: Path) -> list[Path]:
    """WorkBuddy ships a managed Python; prefer it over whatever is on PATH."""
    base = config / "binaries" / "python"
    candidates = [base / "envs" / "default" / "bin" / "python3"]
    versions = base / "versions"
    if versions.is_dir():
        for version in sorted(versions.iterdir(), reverse=True):
            candidates.append(version / "bin" / "python3")
    return candidates


def official_validator() -> Path | None:
    candidate = (
        app_path() / "Contents" / "Resources" / "app.asar.unpacked" / "resources"
        / "builtin-skills" / "expert-manager" / "scripts" / "validate_expert.py"
    )
    return candidate if candidate.is_file() else None


# ---------------------------------------------------------------------- roster


def package_name_for(ctx: TeamContext, override: str | None = None) -> str:
    return kebab_case(override or ctx.team_id, "agent-team")


def lead_agent_id(package: str) -> str:
    return kebab_case(f"{package}-team-lead", "agent-team-team-lead")


def member_agent_id(package: str, expert_id: str) -> str:
    return kebab_case(f"{package}-{expert_id}", f"{package}-expert")


def build_roster(ctx: TeamContext, package: str) -> dict[str, Any]:
    """Single source of truth for expert id <-> agent id <-> native member name."""
    coordinator = ctx.coordinator_id()
    lead = lead_agent_id(package)
    experts: dict[str, Any] = {}
    for expert_id, expert in ctx.experts.items():
        is_lead = expert_id == coordinator
        agent_id = lead if is_lead else member_agent_id(package, expert_id)
        experts[expert_id] = {
            "agentId": agent_id,
            "nativeName": NATIVE_LEAD_NAME if is_lead else agent_id,
            "role": "lead" if is_lead else "member",
            "name": str(expert.get("name") or expert_id),
        }
    return {
        "rosterVersion": "teamkit.workbuddy.roster.v1",
        "package": package,
        "teamId": ctx.team_id,
        "coordinator": coordinator,
        "leadAgentId": lead,
        "leadNativeName": NATIVE_LEAD_NAME,
        "experts": experts,
    }


def load_roster(ctx: TeamContext, package: str = "") -> dict[str, Any]:
    """Load the roster written at export time, or derive it for source checkouts."""
    path = ctx.root / "roster.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("experts"), dict):
                return data
        except json.JSONDecodeError:
            pass
    return build_roster(ctx, package or package_name_for(ctx))


def resolve_member(roster: dict[str, Any], native_name: str, agent_type: str = "") -> str:
    """Map a native member name (and its agentType) back to a TeamKit expert id."""
    if native_name == roster.get("leadNativeName", NATIVE_LEAD_NAME):
        return str(roster.get("coordinator") or "")
    experts: dict[str, Any] = roster.get("experts") or {}
    by_agent = {str(info.get("agentId")): expert for expert, info in experts.items()}
    if agent_type and agent_type in by_agent:
        return by_agent[agent_type]
    if native_name in by_agent:
        return by_agent[native_name]
    if native_name in experts:
        return native_name
    # Platform de-duplication appends "-2", "-3" to reused names.
    stem, _, suffix = native_name.rpartition("-")
    if suffix.isdigit() and stem:
        return resolve_member(roster, stem, "")
    return ""
