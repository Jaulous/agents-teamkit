"""File-system primitives: atomic writes, tolerant JSONL ledgers, locks, ids.

Every ledger write in TeamKit goes through this module so crash safety and
encoding rules live in one place.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator
import uuid

from teamkit.errors import TeamKitError

try:  # Prefer an installed PyYAML (it may carry the faster C binding).
    import yaml  # type: ignore[import-untyped]
except ImportError:  # Runtime packages ship a pure-Python copy.
    from teamkit._vendor import yaml  # type: ignore[no-redef]

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore[assignment]


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> float | None:
    """Parse an ISO timestamp or epoch milliseconds into epoch seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 10**11 else float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def iso_from_epoch(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("\0".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- YAML


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TeamKitError(f"file not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise TeamKitError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise TeamKitError(f"expected YAML object: {path}")
    return data


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_yaml(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, dump_yaml(data))


# --------------------------------------------------------------------------- atomic files


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


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_copyfile(source: Path, target: Path) -> None:
    if not source.is_file():
        raise TeamKitError(f"source file not found: {source}")
    atomic_write_bytes(target, source.read_bytes())


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TeamKitError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# --------------------------------------------------------------------------- JSONL ledgers


def read_jsonl_with_errors(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read a JSONL ledger, skipping damaged lines instead of failing the run.

    A crash during an append can leave a truncated last line. Treating the
    whole ledger as unreadable would stall every later command, so damaged
    lines are reported and skipped; ``run audit`` surfaces them.
    """
    if not path.exists():
        return [], []
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"{path.name}:{number}: invalid JSON line skipped")
            continue
        if not isinstance(record, dict):
            errors.append(f"{path.name}:{number}: non-object line skipped")
            continue
        records.append(record)
    return records, errors


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return read_jsonl_with_errors(path)[0]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    append_jsonl_many(path, [record])


def append_jsonl_many(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                prefix = "\n"  # never glue a record onto a truncated line
    payload = prefix + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


# --------------------------------------------------------------------------- locks


@contextmanager
def file_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive inter-process lock held for the duration of the block."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


# --------------------------------------------------------------------------- CLI text input


def read_text_option(value: str | None, file_value: str | None, label: str, required: bool = True) -> str:
    """Resolve ``--x`` / ``--x-file`` pairs. ``-`` reads stdin."""
    if file_value:
        if file_value == "-":
            return sys.stdin.read().strip()
        path = Path(file_value).expanduser()
        if not path.is_file():
            raise TeamKitError(f"{label} file not found: {path}")
        return path.read_text(encoding="utf-8").strip()
    if value:
        return value.strip()
    if required:
        raise TeamKitError(f"{label} is required")
    return ""


def display_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)
