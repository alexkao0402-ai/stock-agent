"""Bootstrap, upload, or restore the private durable V12 Forward state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from dotenv import load_dotenv

from src.config import get_secret
from src.forward_state_cloud import download_forward_state, upload_forward_state


REPO_ROOT = Path(__file__).resolve().parents[1]


def _configuration() -> dict[str, str]:
    values = {
        "project_url": get_secret("SUPABASE_URL") or "",
        "api_key": (
            get_secret("SUPABASE_SECRET_KEY")
            or get_secret("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ),
        "secret": get_secret("V12_DASHBOARD_SYNC_SECRET") or "",
        "bucket": get_secret("V12_DASHBOARD_SUPABASE_BUCKET") or "v12-dashboard",
        "object_path": (
            get_secret("V12_FORWARD_STATE_SUPABASE_OBJECT")
            or "forward_state/v12_forward_state.json"
        ),
    }
    missing = [name for name in ("project_url", "api_key", "secret") if not values[name]]
    if missing:
        raise RuntimeError(f"missing required cloud configuration: {', '.join(missing)}")
    return values


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("direction", choices=("download", "upload"))
    parser.add_argument(
        "--bootstrap", action="store_true",
        help="Allow the first upload when no durable cloud state exists.",
    )
    args = parser.parse_args()
    try:
        config = _configuration()
        if args.direction == "download":
            status = download_forward_state(REPO_ROOT, **config)
            result = {"status": status, "direction": "download"}
        else:
            result = upload_forward_state(
                REPO_ROOT,
                **config,
                source_commit=_commit(),
                allow_create=args.bootstrap,
            )
            result["direction"] = "upload"
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
