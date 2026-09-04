"""Signed, read-only transport snapshots for the V12 dashboard.

The append-only SQLite ledger remains the source of truth.  This module exports
only the display projection required by Streamlit and verifies an HMAC before a
cloud dashboard accepts that projection.  It never writes to the trading ledger.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import pandas as pd


SCHEMA_VERSION = 1
DISPLAY_EVENT_FIELDS = (
    "sequence",
    "created_at",
    "portfolio_id",
    "event_type",
    "ticker",
    "action",
    "data_asof",
)
DISPLAY_STATE_FIELDS = (
    "frozen_version",
    "formal_forward_rows",
    "portfolio_value",
    "cumulative_return",
    "excess_vs_spy",
    "excess_vs_qqq",
    "max_drawdown",
    "cash",
    "holdings",
    "signal_date",
    "market_regime",
    "v7_selected",
    "v8_selected",
    "agreement_count",
    "target_weights",
    "execution_status",
    "execution_date",
    "rolling_sharpe",
    "sharpe_deviation",
    "t1_return",
    "t2_return",
    "t1_t2_spread",
    "health_status",
    "health_label",
    "trading_blocked",
    "integrity_error",
    "warnings",
    "last_data_asof",
)


class DashboardSnapshotError(RuntimeError):
    """Raised when a cloud snapshot is missing, invalid, or unauthenticated."""


def _supabase_object_url(
    project_url: str,
    bucket: str,
    object_path: str,
) -> str:
    parsed = urlparse(project_url.strip())
    if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
        raise DashboardSnapshotError("SUPABASE_URL must be a valid HTTPS project URL")
    if not bucket.strip() or not object_path.strip():
        raise DashboardSnapshotError("Supabase bucket and object path are required")
    encoded_bucket = quote(bucket.strip(), safe="")
    encoded_path = "/".join(
        quote(part, safe="") for part in object_path.strip("/").split("/") if part
    )
    if not encoded_path:
        raise DashboardSnapshotError("Supabase object path is required")
    base = project_url.strip().rstrip("/")
    return f"{base}/storage/v1/object/{encoded_bucket}/{encoded_path}"


def _supabase_headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise DashboardSnapshotError("SUPABASE_SECRET_KEY is not configured")
    headers = {"apikey": api_key}
    # New sb_secret_ keys authenticate through apikey only.  The legacy
    # service_role value is a JWT and still requires Authorization.
    if not api_key.startswith("sb_secret_"):
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DashboardSnapshotError("dashboard snapshot is not valid JSON") from exc


def _display_payload(state: dict[str, Any]) -> dict[str, Any]:
    curve = state.get("curve")
    if isinstance(curve, pd.DataFrame):
        curve_rows = json.loads(curve.to_json(orient="records", date_format="iso"))
    else:
        curve_rows = list(curve or [])
    events = [
        {field: row.get(field) for field in DISPLAY_EVENT_FIELDS}
        for row in list(state.get("events") or [])[-100:]
    ]
    payload = {field: state.get(field) for field in DISPLAY_STATE_FIELDS}
    payload.update({
        "curve": curve_rows,
        "events": events,
        "latest_signal": None if state.get("latest_signal") is None else {"present": True},
    })
    # Round-trip through canonical JSON to remove pandas/numpy scalar types.
    return json.loads(_canonical(payload))


def create_signed_snapshot(
    state: dict[str, Any],
    secret: str,
    *,
    generated_at: str | None = None,
    source_commit: str | None = None,
) -> dict[str, Any]:
    """Create a signed display-only envelope from a verified dashboard state."""
    if not secret:
        raise DashboardSnapshotError("V12_DASHBOARD_SYNC_SECRET is not configured")
    if state.get("integrity_error"):
        raise DashboardSnapshotError("refusing to export a dashboard state with ledger errors")
    payload = _display_payload(state)
    body = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_commit": source_commit,
        "payload_sha256": hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest(),
        "payload": payload,
    }
    body["signature"] = hmac.new(
        secret.encode("utf-8"),
        _canonical(body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return body


def verify_signed_snapshot(envelope: dict[str, Any], secret: str) -> dict[str, Any]:
    """Authenticate an envelope and reconstruct the Streamlit display state."""
    if not secret:
        raise DashboardSnapshotError("V12_DASHBOARD_SYNC_SECRET is not configured")
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise DashboardSnapshotError("unsupported dashboard snapshot schema")
    signature = str(envelope.get("signature") or "")
    body = {key: value for key, value in envelope.items() if key != "signature"}
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        _canonical(body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise DashboardSnapshotError("dashboard snapshot signature mismatch")
    payload = body.get("payload")
    if not isinstance(payload, dict):
        raise DashboardSnapshotError("dashboard snapshot payload is missing")
    expected_hash = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(body.get("payload_sha256") or ""), expected_hash):
        raise DashboardSnapshotError("dashboard snapshot payload hash mismatch")
    state = dict(payload)
    state["curve"] = pd.DataFrame(
        list(payload.get("curve") or []), columns=["date", "series", "value"]
    )
    state["events"] = list(payload.get("events") or [])
    return state


def write_signed_snapshot(envelope: dict[str, Any], path: str | Path) -> Path:
    """Atomically write a derived snapshot without touching the ledger."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(_canonical(envelope) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return destination


def load_signed_snapshot(
    source: str | Path,
    secret: str,
    *,
    timeout: int = 10,
) -> dict[str, Any]:
    """Load a signed snapshot from a local path or an HTTPS URL."""
    location = str(source)
    try:
        if location.startswith("https://"):
            with urlopen(Request(location, method="GET"), timeout=timeout) as response:
                envelope = json.loads(response.read().decode("utf-8"))
        elif location.startswith("http://"):
            raise DashboardSnapshotError("cloud snapshots must use HTTPS")
        else:
            envelope = json.loads(Path(source).read_text(encoding="utf-8"))
    except DashboardSnapshotError:
        raise
    except HTTPError as exc:
        raise DashboardSnapshotError(
            f"unable to load dashboard snapshot: HTTP {exc.code}"
        ) from exc
    except (OSError, ValueError, URLError) as exc:
        raise DashboardSnapshotError(f"unable to load dashboard snapshot: {exc}") from exc
    if not isinstance(envelope, dict):
        raise DashboardSnapshotError("dashboard snapshot envelope is invalid")
    return verify_signed_snapshot(envelope, secret)


def upload_supabase_snapshot(
    envelope: dict[str, Any],
    project_url: str,
    api_key: str,
    *,
    bucket: str = "v12-dashboard",
    object_path: str = "v12_dashboard.json",
    timeout: int = 15,
) -> None:
    """Upload one signed display projection to private Supabase Storage."""
    if not isinstance(envelope, dict) or not envelope.get("signature"):
        raise DashboardSnapshotError("refusing to upload an unsigned dashboard snapshot")
    url = _supabase_object_url(project_url, bucket, object_path)
    headers = _supabase_headers(api_key)
    headers.update({
        "Content-Type": "application/json",
        "x-upsert": "true",
    })
    request = Request(
        url,
        headers=headers,
        data=_canonical(envelope).encode("utf-8"),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
    except HTTPError as exc:
        raise DashboardSnapshotError(
            f"Supabase snapshot upload failed with HTTP {exc.code}"
        ) from exc
    except (OSError, URLError) as exc:
        raise DashboardSnapshotError("unable to upload dashboard snapshot") from exc
    if not 200 <= status < 300:
        raise DashboardSnapshotError(
            f"Supabase snapshot upload failed with HTTP {status}"
        )


def load_supabase_snapshot(
    project_url: str,
    api_key: str,
    secret: str,
    *,
    bucket: str = "v12-dashboard",
    object_path: str = "v12_dashboard.json",
    timeout: int = 10,
) -> dict[str, Any]:
    """Download, authenticate and reconstruct a private Supabase snapshot."""
    url = _supabase_object_url(project_url, bucket, object_path)
    request = Request(url, headers=_supabase_headers(api_key), method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            raw = response.read()
    except HTTPError as exc:
        raise DashboardSnapshotError(
            f"Supabase snapshot download failed with HTTP {exc.code}"
        ) from exc
    except (OSError, URLError) as exc:
        raise DashboardSnapshotError("unable to download dashboard snapshot") from exc
    if not 200 <= status < 300:
        raise DashboardSnapshotError(
            f"Supabase snapshot download failed with HTTP {status}"
        )
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DashboardSnapshotError("Supabase dashboard snapshot is not valid JSON") from exc
    if not isinstance(envelope, dict):
        raise DashboardSnapshotError("dashboard snapshot envelope is invalid")
    return verify_signed_snapshot(envelope, secret)
