"""Export a signed, display-only V12 dashboard snapshot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from dotenv import load_dotenv

from src.config import get_secret
from src.dashboard_cloud_snapshot import (
    create_signed_snapshot,
    upload_supabase_snapshot,
    write_signed_snapshot,
)
from src.dashboard_read_model import DEFAULT_LEDGER_PATH, build_dashboard_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]


def _current_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Create a signed read-only snapshot for a cloud dashboard."
    )
    parser.add_argument(
        "--ledger",
        default=str(REPO_ROOT / DEFAULT_LEDGER_PATH),
        help="Existing append-only SQLite ledger path.",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "dashboard_exports" / "v12_dashboard.json"),
        help="Derived JSON output path.",
    )
    parser.add_argument(
        "--upload-supabase",
        action="store_true",
        help="Upload the signed snapshot to the configured private Supabase bucket.",
    )
    args = parser.parse_args()
    secret = get_secret("V12_DASHBOARD_SYNC_SECRET")
    try:
        state = build_dashboard_snapshot(args.ledger)
        envelope = create_signed_snapshot(
            state,
            secret or "",
            source_commit=_current_commit(),
        )
        destination = write_signed_snapshot(envelope, args.output)
        if args.upload_supabase:
            project_url = get_secret("SUPABASE_URL") or ""
            api_key = (
                get_secret("SUPABASE_SECRET_KEY")
                or get_secret("SUPABASE_SERVICE_ROLE_KEY")
                or ""
            )
            upload_supabase_snapshot(
                envelope,
                project_url,
                api_key,
                bucket=get_secret("V12_DASHBOARD_SUPABASE_BUCKET") or "v12-dashboard",
                object_path=get_secret("V12_DASHBOARD_SUPABASE_OBJECT")
                or "v12_dashboard.json",
            )
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "EXPORTED",
        "path": str(destination),
        "schema_version": envelope["schema_version"],
        "generated_at": envelope["generated_at"],
        "source_commit": envelope["source_commit"],
        "supabase_uploaded": bool(args.upload_supabase),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
