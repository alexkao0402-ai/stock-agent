"""Authenticated private backup for the complete V12 Forward runner state.

GitHub-hosted runners are ephemeral.  This module moves only the ignored,
allowlisted Forward evidence and SQLite ledger to a private Supabase object.
The Streamlit application never imports this module and never writes this
object.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from src.dashboard_cloud_snapshot import _supabase_headers, _supabase_object_url
from src.paper_ledger import AppendOnlyLedger


FORWARD_STATE_SCHEMA_VERSION = 1
MANAGED_PATHS = (
    "paper_ledger/v12_events.sqlite3",
    "live_forward_inputs",
    "live_forward_signals",
    "live_forward_runs",
)


class ForwardStateError(RuntimeError):
    """Raised when durable Forward state is missing, stale, or unauthenticated."""


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _ledger_hashes(path: Path) -> list[str]:
    ledger = AppendOnlyLedger(path)
    ledger.verify_integrity()
    return [str(row["event_hash"]) for row in ledger.events()]


def _consistent_ledger_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise ForwardStateError("local Forward ledger is missing")
    AppendOnlyLedger(path).verify_integrity()
    with tempfile.TemporaryDirectory() as temp:
        destination = Path(temp) / "ledger.sqlite3"
        source_uri = f"file:{path.resolve().as_posix()}?mode=ro"
        source = sqlite3.connect(source_uri, uri=True, timeout=10)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        AppendOnlyLedger(destination).verify_integrity()
        return destination.read_bytes()


def _state_files(root: Path) -> dict[str, bytes]:
    files = {"paper_ledger/v12_events.sqlite3": _consistent_ledger_bytes(
        root / "paper_ledger" / "v12_events.sqlite3"
    )}
    for directory_name in MANAGED_PATHS[1:]:
        directory = root / directory_name
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ForwardStateError(f"symlink is not allowed in Forward state: {path}")
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                files[relative] = path.read_bytes()
    return files


def create_forward_state_bundle(
    root: str | Path,
    secret: str,
    *,
    generated_at: str | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    if not secret:
        raise ForwardStateError("V12_DASHBOARD_SYNC_SECRET is not configured")
    root_path = Path(root)
    files = _state_files(root_path)
    ledger_path = root_path / "paper_ledger" / "v12_events.sqlite3"
    ledger_hashes = _ledger_hashes(ledger_path)
    manifest = {
        name: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in sorted(files.items())
    }
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    archive_bytes = archive_buffer.getvalue()
    body = {
        "schema_version": FORWARD_STATE_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "manifest": manifest,
        "ledger_event_count": len(ledger_hashes),
        "ledger_head_hash": ledger_hashes[-1] if ledger_hashes else "GENESIS",
    }
    signature = hmac.new(
        secret.encode("utf-8"), _canonical(body).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        **body,
        "archive_b64": base64.b64encode(archive_bytes).decode("ascii"),
        "signature": signature,
    }


def verify_forward_state_bundle(bundle: dict[str, Any], secret: str) -> bytes:
    if not secret:
        raise ForwardStateError("V12_DASHBOARD_SYNC_SECRET is not configured")
    if bundle.get("schema_version") != FORWARD_STATE_SCHEMA_VERSION:
        raise ForwardStateError("unsupported Forward state schema")
    signed_fields = {
        key: bundle.get(key)
        for key in (
            "schema_version", "generated_at", "source_commit", "archive_sha256",
            "manifest", "ledger_event_count", "ledger_head_hash",
        )
    }
    expected = hmac.new(
        secret.encode("utf-8"), _canonical(signed_fields).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(str(bundle.get("signature") or ""), expected):
        raise ForwardStateError("Forward state signature mismatch")
    try:
        archive_bytes = base64.b64decode(str(bundle.get("archive_b64") or ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise ForwardStateError("Forward state archive is not valid base64") from exc
    actual_hash = hashlib.sha256(archive_bytes).hexdigest()
    if not hmac.compare_digest(str(bundle.get("archive_sha256") or ""), actual_hash):
        raise ForwardStateError("Forward state archive hash mismatch")
    return archive_bytes


def _unpack_verified(bundle: dict[str, Any], secret: str, destination: Path) -> Path:
    archive_bytes = verify_forward_state_bundle(bundle, secret)
    manifest = bundle.get("manifest")
    if not isinstance(manifest, dict) or "paper_ledger/v12_events.sqlite3" not in manifest:
        raise ForwardStateError("Forward state manifest is incomplete")
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
        names = archive.namelist()
        if set(names) != set(manifest):
            raise ForwardStateError("Forward state archive does not match its manifest")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ForwardStateError("unsafe path in Forward state archive")
            if path.parts[0] not in {"paper_ledger", *MANAGED_PATHS[1:]}:
                raise ForwardStateError("unexpected path in Forward state archive")
            content = archive.read(name)
            metadata = manifest[name]
            if len(content) != int(metadata["size"]):
                raise ForwardStateError(f"Forward state size mismatch: {name}")
            if hashlib.sha256(content).hexdigest() != str(metadata["sha256"]):
                raise ForwardStateError(f"Forward state file hash mismatch: {name}")
            output = destination.joinpath(*path.parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(content)
    ledger_path = destination / "paper_ledger" / "v12_events.sqlite3"
    hashes = _ledger_hashes(ledger_path)
    if len(hashes) != int(bundle.get("ledger_event_count", -1)):
        raise ForwardStateError("Forward ledger event count mismatch")
    head = hashes[-1] if hashes else "GENESIS"
    if head != str(bundle.get("ledger_head_hash")):
        raise ForwardStateError("Forward ledger head hash mismatch")
    return ledger_path


def restore_forward_state_bundle(
    bundle: dict[str, Any],
    root: str | Path,
    secret: str,
) -> str:
    """Restore authenticated state without ever overwriting a divergent ledger."""
    root_path = Path(root)
    local_ledger = root_path / "paper_ledger" / "v12_events.sqlite3"
    with tempfile.TemporaryDirectory() as temp:
        extracted = Path(temp) / "state"
        remote_ledger = _unpack_verified(bundle, secret, extracted)
        remote_hashes = _ledger_hashes(remote_ledger)
        if local_ledger.is_file():
            local_hashes = _ledger_hashes(local_ledger)
            common = min(len(local_hashes), len(remote_hashes))
            if local_hashes[:common] != remote_hashes[:common]:
                raise ForwardStateError("local and cloud Forward ledgers have diverged")
            if len(local_hashes) > len(remote_hashes):
                return "LOCAL_AHEAD_NOT_OVERWRITTEN"
            if len(local_hashes) == len(remote_hashes):
                local_files_current = all(
                    (candidate := root_path.joinpath(*PurePosixPath(name).parts)).is_file()
                    and candidate.stat().st_size == int(metadata["size"])
                    and hashlib.sha256(candidate.read_bytes()).hexdigest()
                    == str(metadata["sha256"])
                    for name, metadata in bundle["manifest"].items()
                    if name != "paper_ledger/v12_events.sqlite3"
                )
                if local_files_current:
                    return "ALREADY_CURRENT"
        for name in sorted(bundle["manifest"]):
            source = extracted.joinpath(*PurePosixPath(name).parts)
            destination = root_path.joinpath(*PurePosixPath(name).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_suffix(destination.suffix + ".restore.tmp")
            temporary.write_bytes(source.read_bytes())
            os.replace(temporary, destination)
    AppendOnlyLedger(local_ledger).verify_integrity()
    return "RESTORED"


def _load_remote_bundle(
    project_url: str,
    api_key: str,
    *,
    bucket: str,
    object_path: str,
    timeout: int,
) -> dict[str, Any] | None:
    url = _supabase_object_url(project_url, bucket, object_path)
    request = Request(url, headers=_supabase_headers(api_key), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        try:
            error_payload = json.loads(error_body)
        except ValueError:
            error_payload = {}
        object_missing = (
            exc.code == 404
            or (
                exc.code == 400
                and str(error_payload.get("statusCode")) == "404"
                and str(error_payload.get("code")) == "NoSuchKey"
            )
        )
        if object_missing:
            return None
        raise ForwardStateError(f"Forward state download failed with HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise ForwardStateError("unable to download Forward state") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ForwardStateError("cloud Forward state is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ForwardStateError("cloud Forward state envelope is invalid")
    return value


def download_forward_state(
    root: str | Path,
    project_url: str,
    api_key: str,
    secret: str,
    *,
    bucket: str = "v12-dashboard",
    object_path: str = "forward_state/v12_forward_state.json",
    timeout: int = 30,
) -> str:
    bundle = _load_remote_bundle(
        project_url, api_key, bucket=bucket, object_path=object_path, timeout=timeout
    )
    if bundle is None:
        raise ForwardStateError("cloud Forward state has not been bootstrapped")
    return restore_forward_state_bundle(bundle, root, secret)


def upload_forward_state(
    root: str | Path,
    project_url: str,
    api_key: str,
    secret: str,
    *,
    bucket: str = "v12-dashboard",
    object_path: str = "forward_state/v12_forward_state.json",
    source_commit: str | None = None,
    allow_create: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    root_path = Path(root)
    local_ledger = root_path / "paper_ledger" / "v12_events.sqlite3"
    local_hashes = _ledger_hashes(local_ledger)
    remote = _load_remote_bundle(
        project_url, api_key, bucket=bucket, object_path=object_path, timeout=timeout
    )
    if remote is None and not allow_create:
        raise ForwardStateError("cloud Forward state is missing; explicit bootstrap is required")
    if remote is not None:
        with tempfile.TemporaryDirectory() as temp:
            remote_ledger = _unpack_verified(remote, secret, Path(temp))
            remote_hashes = _ledger_hashes(remote_ledger)
        if len(remote_hashes) > len(local_hashes) or local_hashes[:len(remote_hashes)] != remote_hashes:
            raise ForwardStateError("refusing to overwrite a newer or divergent cloud ledger")

    bundle = create_forward_state_bundle(
        root_path, secret, source_commit=source_commit
    )
    url = _supabase_object_url(project_url, bucket, object_path)
    headers = _supabase_headers(api_key)
    headers.update({"Content-Type": "application/json", "x-upsert": "true"})
    request = Request(
        url,
        headers=headers,
        data=(_canonical(bundle) + "\n").encode("utf-8"),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
    except HTTPError as exc:
        raise ForwardStateError(f"Forward state upload failed with HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise ForwardStateError("unable to upload Forward state") from exc
    if not 200 <= status < 300:
        raise ForwardStateError(f"Forward state upload failed with HTTP {status}")
    return {
        "status": "UPLOADED",
        "ledger_event_count": bundle["ledger_event_count"],
        "ledger_head_hash": bundle["ledger_head_hash"],
        "file_count": len(bundle["manifest"]),
    }
