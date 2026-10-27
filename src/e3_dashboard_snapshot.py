"""Signed E3-only display transport; never processes a paper trading cycle."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import math
from urllib.request import Request, urlopen

from src.dashboard_cloud_snapshot import _supabase_headers, _supabase_object_url, upload_supabase_snapshot

SCHEMA = "E3_FORWARD_PAPER_DISPLAY_V1"
OBJECT_PATH = "e3_forward_dashboard.json"
DOMAIN = b"E3_FORWARD_DISPLAY_V1\0"


class E3DisplayError(ValueError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get("version") != "F1-E3-PAPER-V1" or payload.get("paper_only") is not True:
        raise E3DisplayError("Unsupported E3 paper display")
    if payload.get("ledger_integrity") is not True:
        raise E3DisplayError("E3 ledger verification failed")
    for field in ("frozen_at", "first_signal_session", "first_possible_fill_session", "status"):
        if not isinstance(payload.get(field), str) or not payload[field]:
            raise E3DisplayError("E3 start metadata is missing")
    expected = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"}
    if not isinstance(payload.get("rules"), dict) or set(payload["rules"].get("universe", [])) != expected:
        raise E3DisplayError("Frozen E3 universe is missing or changed")
    for field in ("forward_sessions", "primary_fill_count", "ledger_events"):
        if type(payload.get(field)) is not int or payload[field] < 0:
            raise E3DisplayError("Invalid E3 sample count")
    freeze_hash = payload.get("freeze_sha256", "")
    if len(freeze_hash) != 64 or any(c not in "0123456789abcdef" for c in freeze_hash):
        raise E3DisplayError("Invalid E3 freeze receipt")
    if set(payload.get("accounts", {})) != {"E3", "CSM", "SPY", "EW"}:
        raise E3DisplayError("Missing independent comparison accounts")
    for account in payload["accounts"].values():
        for field in ("cash", "equity", "dividend_receivable"):
            value = account.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < -1e-6:
                raise E3DisplayError("Invalid E3 account value")
        if not isinstance(account.get("positions"), dict):
            raise E3DisplayError("Invalid E3 positions")
        if payload["forward_sessions"] == 0 and (account.get("return_pct") is not None or account["positions"]):
            raise E3DisplayError("Startup cash must not be displayed as forward performance")
    if payload["forward_sessions"] == 0 and (payload["primary_fill_count"] or payload.get("curve") or payload.get("trades")):
        raise E3DisplayError("A startup display cannot contain forward trades or performance")
    if payload["forward_sessions"] > 0 and not payload.get("last_close"):
        raise E3DisplayError("Forward observations require a valuation date")
    return payload


def create_envelope(payload, secret, generated_at=None, source_commit=None):
    if not secret:
        raise E3DisplayError("E3 display signing secret is unavailable")
    validate_payload(payload)
    body = {"schema": SCHEMA, "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
            "source_commit": source_commit, "payload_sha256": hashlib.sha256(_json(payload).encode()).hexdigest(), "payload": payload}
    body["signature"] = hmac.new(secret.encode(), DOMAIN + _json(body).encode(), hashlib.sha256).hexdigest()
    return body


def verify_envelope(envelope, secret, now=None):
    if not secret or not isinstance(envelope, dict) or envelope.get("schema") != SCHEMA:
        raise E3DisplayError("E3 signed display is unavailable or unsupported")
    body = {key: value for key, value in envelope.items() if key != "signature"}
    expected = hmac.new(secret.encode(), DOMAIN + _json(body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(envelope.get("signature", "")), expected):
        raise E3DisplayError("E3 display signature verification failed")
    checksum = hashlib.sha256(_json(body.get("payload")).encode()).hexdigest()
    if not hmac.compare_digest(str(body.get("payload_sha256", "")), checksum):
        raise E3DisplayError("E3 display payload verification failed")
    try:
        generated = datetime.fromisoformat(body["generated_at"].replace("Z", "+00:00"))
        if generated.tzinfo is None or generated > (now or datetime.now(timezone.utc)) + timedelta(minutes=5):
            raise ValueError("future or naive timestamp")
    except (KeyError, TypeError, ValueError):
        raise E3DisplayError("Invalid E3 publication time") from None
    result = dict(validate_payload(body["payload"]))
    result["published_at"] = body["generated_at"]
    result["source_commit"] = body.get("source_commit")
    return result


def load_display(url, api_key, secret):
    if not all((url, api_key, secret)):
        raise E3DisplayError("E3 display requires the existing server-side snapshot configuration")
    try:
        request = Request(_supabase_object_url(url, "v12-dashboard", OBJECT_PATH), headers=_supabase_headers(api_key), method="GET")
        with urlopen(request, timeout=20) as response:
            envelope = json.loads(response.read(2_000_001).decode("utf-8"))
        return verify_envelope(envelope, secret)
    except E3DisplayError:
        raise
    except Exception:
        raise E3DisplayError("E3 signed display could not be loaded; no substitute performance is shown") from None


def publish_display(envelope, url, api_key):
    if envelope.get("schema") != SCHEMA or OBJECT_PATH == "v12_dashboard.json":
        raise E3DisplayError("Refusing to publish a non-E3 display")
    upload_supabase_snapshot(envelope, url, api_key, bucket="v12-dashboard", object_path=OBJECT_PATH)


def build_local_projection(home):
    """Called only by the trusted local exporter in the frozen runtime."""
    from src.e3_forward import CONTROL, read_freeze, read_state, status
    freeze = read_freeze(home)
    ledger, _ = read_state(home, freeze)
    info = status(home)
    events = ledger.events()
    closes = [item for item in events if item["portfolio_id"] == CONTROL and item["event_type"] == "CLOSE_PROCESSED"]
    if len(events) != info["ledger_events"] or len(closes) != info["forward_sessions"]:
        raise E3DisplayError("E3 state changed during display capture; retry")
    curve = []
    for item in closes:
        for name, valuation in item["payload"]["valuations"].items():
            curve.append({"date": item["payload"]["session"], "series": name, "value": valuation["equity"]})
    accounts = {}
    for name, account in info["accounts"].items():
        valuation = info["valuations"].get(name, {})
        accounts[name] = {"cash": account["cash"], "equity": valuation.get("equity", 10000.0),
                          "dividend_receivable": account["dividend_receivable"], "positions": account["positions"],
                          "return_pct": valuation.get("return_pct") if info["forward_sessions"] else None}
    trades = []
    for item in events:
        if item["portfolio_id"] == "E3" and item["event_type"] == "PAPER_FILL":
            payload = item["payload"]
            trades.append({key: payload[key] for key in ("signal_date", "execution_date", "symbol", "action", "shares", "execution_price", "commission")}
                          | {"recorded_at": item["created_at"]})
    projection = {key: info[key] for key in ("status", "version", "frozen_at", "first_signal_session", "first_possible_fill_session",
                  "forward_sessions", "primary_fill_count", "last_close", "pending", "ledger_integrity", "freeze_sha256", "ledger_events", "paper_only")}
    projection.update({"accounts": accounts, "rules": freeze["rules"], "curve": curve, "trades": trades[-100:],
                       "last_observed_at": closes[-1]["payload"]["observed_at"] if closes else None})
    return validate_payload(projection)
