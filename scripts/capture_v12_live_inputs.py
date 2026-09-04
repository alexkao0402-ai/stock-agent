"""Capture the frozen V12 month-end universe and price inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from dotenv import load_dotenv

from src.live_large_cap_data import (
    DEFAULT_SEC_USER_AGENT,
    LiveDataError,
    capture_v12_live_inputs,
)
from src.forward_evidence import prepare_forward_evidence
from src.v12_live_signal import write_immutable_v12_signal


REPO_ROOT = Path(__file__).resolve().parents[1]
CRITICAL_FORWARD_FILES = [
    "src/live_large_cap_data.py",
    "src/v12_live_signal.py",
    "src/trading_calendar.py",
    "src/paper_accounting.py",
    "src/paper_ledger.py",
    "src/forward_evidence.py",
    "src/forward_execution.py",
    "src/forward_valuation.py",
    "src/forward_state_cloud.py",
    "scripts/capture_v12_live_inputs.py",
    "scripts/process_v12_paper_open.py",
    "scripts/run_v12_forward_automation.py",
    "scripts/sync_v12_forward_state.py",
]


def _git_evidence() -> tuple[str, dict[str, str]]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", *CRITICAL_FORWARD_FILES],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise LiveDataError(f"Git evidence check failed: {exc}") from exc
    if dirty:
        raise LiveDataError(
            "Critical forward files are not committed; official evidence creation is blocked"
        )
    hashes = {
        relative: hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest()
        for relative in CRITICAL_FORWARD_FILES
    }
    return commit, hashes


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Archive free point-in-time inputs for V12 after the US market close."
    )
    parser.add_argument(
        "--candidate-count",
        type=int,
        default=100,
        help="Number of Yahoo market-cap candidates to inspect (20-250; default 100).",
    )
    args = parser.parse_args()
    try:
        root, created, summary = capture_v12_live_inputs(
            candidate_count=args.candidate_count,
            sec_user_agent=os.getenv("SEC_USER_AGENT") or DEFAULT_SEC_USER_AGENT,
        )
        signal_path, signal_created, signal = write_immutable_v12_signal(root)
        git_commit, implementation_hashes = _git_evidence()
        evidence_path, evidence_status, evidence = prepare_forward_evidence(
            root,
            signal_path,
            ledger_path=REPO_ROOT / "paper_ledger" / "v12_events.sqlite3",
            output_directory=REPO_ROOT / "live_forward_runs",
            git_commit=git_commit,
            implementation_hashes=implementation_hashes,
        )
    except LiveDataError as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {
                "status": "CAPTURED" if created else "ALREADY_EXISTS_NOT_OVERWRITTEN",
                "directory": str(root),
                "signal_date": summary["signal_date"],
                "selected_tickers": [row["ticker"] for row in summary["selected"]],
                "coverage": summary["coverage"],
                "signal_status": signal["status"],
                "consensus_type": signal["consensus_type"],
                "target_weights": signal["target_weights"],
                "signal_file": str(signal_path),
                "signal_created": signal_created,
                "evidence_status": evidence_status,
                "evidence_directory": str(evidence_path),
                "run_id": evidence["run_id"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
