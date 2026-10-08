"""Install, uninstall, detect and diagnose WorkBuddy expert packages."""

from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from typing import Any
import uuid

from teamkit import __version__
from teamkit.errors import TeamKitError
from teamkit.fsutil import atomic_write_text, now, write_json
from teamkit.team import kebab_case
from teamkit.adapters.workbuddy import paths
from teamkit.adapters.workbuddy.package import publish_directory, validate_package_closure

PLACEHOLDER = "{{TEAMKIT_SCRIPT}}"


def backups_dir(config: Path) -> Path:
    return config / "teamkit-backups"


def detect(config: Path) -> dict[str, Any]:
    app = paths.app_path()
    info_plist = app / "Contents" / "Info.plist"
    plist: dict[str, Any] = {}
    if info_plist.exists():
        with info_plist.open("rb") as handle:
            plist = plistlib.load(handle)
    resources = app / "Contents" / "Resources" / "app.asar.unpacked"
    cli = resources / "cli" / "bin" / "codebuddy"
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
        "officialValidator": str(paths.official_validator() or ""),
        "configDir": str(config),
        "expertsDir": str(paths.plugins_dir(config)),
        "teamsDir": str(paths.teams_dir(config)),
        "marketplacePath": str(paths.marketplace_dir(config) / ".codebuddy-plugin" / "marketplace.json"),
    }


def run_official_validator(package_dir: Path, config: Path) -> str:
    validator = paths.official_validator()
    if validator is None:
        return "skipped"
    env = os.environ.copy()
    env["WORKBUDDY_CONFIG_DIR"] = str(config)
    result = subprocess.run([sys.executable, str(validator), str(package_dir)], text=True,
                            capture_output=True, check=False, env=env)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr or "official validator failed").strip()
        raise TeamKitError(f"WorkBuddy official validation failed:\n{detail}")
    return "passed"


def render_launcher_paths(package_dir: Path, installed_root: Path) -> None:
    """Replace ``{{TEAMKIT_SCRIPT}}`` in prompt files with the installed launcher path."""
    launchers = sorted(package_dir.glob("skills/*/scripts/teamkit"))
    if not launchers:
        return
    final = (installed_root / launchers[0].relative_to(package_dir)).as_posix()
    replacement = f'"{final}"' if any(ch.isspace() for ch in final) else final
    for root in (package_dir / "agents", package_dir / "skills"):
        if not root.is_dir():
            continue
        for path in root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if PLACEHOLDER in text:
                atomic_write_text(path, text.replace(PLACEHOLDER, replacement))
    for launcher in launchers:
        launcher.chmod(0o755)


def register(package_dir: Path, config: Path, session_id: str = "") -> Path:
    plugin = json.loads((package_dir / ".codebuddy-plugin" / "plugin.json").read_text(encoding="utf-8"))
    name = str(plugin.get("name") or package_dir.name)
    manifest_path = paths.marketplace_dir(config) / ".codebuddy-plugin" / "marketplace.json"
    manifest: dict[str, Any] = {"name": paths.MARKETPLACE, "description": "my-experts marketplace (auto-generated)", "plugins": []}
    if manifest_path.exists():
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            manifest.update(loaded)
    plugins = manifest.get("plugins") if isinstance(manifest.get("plugins"), list) else []
    source = f"./plugins/{name}"
    entry = {"name": name, "source": source, "description": str(plugin.get("description") or "")}
    existing = next((item for item in plugins if isinstance(item, dict) and (item.get("name") == name or item.get("source") == source)), None)
    if existing:
        existing.update(entry)
    else:
        plugins.append(entry)
    manifest["plugins"] = plugins
    write_json(manifest_path, manifest)
    if session_id:
        (package_dir / ".created-by-session").write_text(session_id, encoding="utf-8")
    return manifest_path


def unregister(name: str, config: Path) -> tuple[Path, bool]:
    manifest_path = paths.marketplace_dir(config) / ".codebuddy-plugin" / "marketplace.json"
    if not manifest_path.exists():
        return manifest_path, False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plugins = manifest.get("plugins") if isinstance(manifest, dict) and isinstance(manifest.get("plugins"), list) else []
    kept = [item for item in plugins if not (isinstance(item, dict) and item.get("name") == name)]
    manifest["plugins"] = kept
    write_json(manifest_path, manifest)
    return manifest_path, len(kept) != len(plugins)


def _safe_paths(source: Path, target: Path) -> None:
    source, target = source.resolve(), target.resolve()
    if source == target:
        raise TeamKitError("WorkBuddy install source and target must be different paths")
    for inner, outer in ((source, target), (target, source)):
        try:
            inner.relative_to(outer)
        except ValueError:
            continue
        raise TeamKitError(f"WorkBuddy install source and target must not contain one another; source={source}, target={target}")


def install(package: Path, config: Path, *, force: bool = False, strict: bool = False, session_id: str = "") -> dict[str, Any]:
    source = package.expanduser().resolve()
    plugin_json = source / ".codebuddy-plugin" / "plugin.json"
    if not plugin_json.is_file():
        raise TeamKitError(f"WorkBuddy plugin.json not found: {plugin_json}")
    plugin = json.loads(plugin_json.read_text(encoding="utf-8"))
    name = str(plugin.get("name") or source.name)
    target = paths.plugins_dir(config) / name
    _safe_paths(source, target)
    if target.exists() and not force:
        raise TeamKitError(f"WorkBuddy package already installed: {target}; use --force")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{name}.install-{uuid.uuid4().hex[:12]}"
    warnings: list[str] = []
    try:
        shutil.copytree(source, staging, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        validate_package_closure(staging)
        validation = run_official_validator(staging, config)
        if validation == "skipped":
            if strict:
                raise TeamKitError("WorkBuddy official validator not found; --strict requires it")
            warnings.append("WorkBuddy official validator not found; only TeamKit closure checks ran")
        legacy_runs = target / "teamkit-workspace" / "runs"
        if legacy_runs.is_dir() and any(item.name != ".gitkeep" for item in legacy_runs.iterdir()):
            warnings.append(f"legacy run data found in {legacy_runs}; it is kept in the backup copy")
        render_launcher_paths(staging, target)
        backup = publish_directory(staging, target, force, backup_root=backups_dir(config))
        manifest_path = register(target, config, session_id or "teamkit-local-install")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    result: dict[str, Any] = {
        "installedDir": str(target),
        "marketplacePath": str(manifest_path),
        "packageName": name,
        "officialValidation": validation,
        "warnings": warnings,
    }
    if backup is not None:
        result["previousVersionBackup"] = str(backup)
    return result


def uninstall(name: str, config: Path, force: bool = False) -> dict[str, Any]:
    name = kebab_case(name, name)
    target = paths.plugins_dir(config) / name
    existed = target.exists()
    backup = None
    if existed:
        root = backups_dir(config)
        root.mkdir(parents=True, exist_ok=True)
        backup = root / f"{name}-uninstalled-{uuid.uuid4().hex[:8]}"
        shutil.move(str(target), str(backup))
    elif not force:
        raise TeamKitError(f"WorkBuddy package is not installed: {name}; use --force to ignore")
    manifest_path, registered = unregister(name, config)
    return {
        "packageName": name,
        "removedDir": str(target),
        "directoryExisted": existed,
        "backup": str(backup) if backup else "",
        "marketplacePath": str(manifest_path),
        "registrationRemoved": registered,
    }


def doctor(config: Path) -> dict[str, Any]:
    """Diagnose the local WorkBuddy + TeamKit setup; never modifies anything."""
    checks: list[dict[str, Any]] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    info = detect(config)
    check("app", "PASS" if info["appExists"] else "WARN",
          f"WorkBuddy {info['version']} at {info['appPath']}" if info["appExists"] else "WorkBuddy app not found (set WORKBUDDY_APP_PATH)")
    check("validator", "PASS" if info["officialValidator"] else "WARN",
          info["officialValidator"] or "official expert validator not found; installs run TeamKit checks only")
    pythons = [str(p) for p in paths.bundled_python_candidates(config) if p.exists()]
    system_python = shutil.which("python3")
    if pythons or system_python:
        check("python", "PASS", pythons[0] if pythons else f"{system_python} (WorkBuddy bundled Python not found)")
    else:
        check("python", "FAIL", "no Python 3 found; generated launchers cannot run")
    marketplace = Path(info["marketplacePath"])
    registered: set[str] = set()
    if marketplace.exists():
        try:
            data = json.loads(marketplace.read_text(encoding="utf-8"))
            registered = {str(item.get("name")) for item in data.get("plugins", []) if isinstance(item, dict)}
        except (json.JSONDecodeError, AttributeError):
            check("marketplace", "FAIL", f"marketplace.json is not valid JSON: {marketplace}")
    packages = []
    plugins_root = paths.plugins_dir(config)
    if plugins_root.is_dir():
        for folder in sorted(plugins_root.iterdir()):
            plugin_file = folder / ".codebuddy-plugin" / "plugin.json"
            if folder.name.startswith(".") or not plugin_file.is_file():
                continue
            if not ((folder / "vendor" / "teamkit").exists() or (folder / "teamkit-workspace").exists()):
                continue
            try:
                plugin = json.loads(plugin_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                check(f"package:{folder.name}", "FAIL", "plugin.json is not valid JSON")
                continue
            version = str(plugin.get("version") or "")
            launcher = next(iter(folder.glob("skills/*/scripts/teamkit")), None)
            legacy_wrapper = next(iter(folder.glob("skills/*/scripts/teamkit.py")), None)
            status, notes = "PASS", []
            if version != __version__:
                status, notes = "WARN", [f"built with TeamKit {version or 'unknown'}, current is {__version__}: re-export and reinstall"]
            if launcher is None and legacy_wrapper is not None:
                status = "WARN"
                notes.append("legacy launcher (needs a networked venv); reinstall to switch to the vendored runtime")
            if folder.name not in registered:
                status = "FAIL"
                notes.append("not registered in marketplace.json")
            packages.append({"name": folder.name, "version": version})
            check(f"package:{folder.name}", status, "; ".join(notes) or f"TeamKit {version}")
    if not packages:
        check("packages", "WARN", "no TeamKit packages installed")
    stray = [p.name for p in plugins_root.glob(".*.backup-*")] if plugins_root.is_dir() else []
    if stray:
        check("backups", "WARN", f"old install backups inside the experts dir: {', '.join(stray)} (safe to move out)")
    order = {"FAIL": 2, "WARN": 1, "PASS": 0}
    verdict = max((c["status"] for c in checks), key=lambda s: order[s], default="PASS")
    return {"verdict": verdict, "teamkitVersion": __version__, "checkedAt": now(), "environment": info,
            "packages": packages, "checks": checks}
