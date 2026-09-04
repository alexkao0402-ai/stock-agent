"""Daily point-in-time signal snapshots for unbiased forward validation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


SNAPSHOT_DIR = Path("signal_snapshots")


def save_daily_signal_snapshot(
    as_of_date: str,
    signals: list[dict[str, Any]],
    market_regime: str,
    directory: Path | str = SNAPSHOT_DIR,
) -> Path:
    """Save one immutable universe snapshot per market date.

    Re-running the same date returns the existing file. This prevents a later
    run from silently rewriting the point-in-time signals used for validation.
    """
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"signals_{as_of_date}.json"
    if target.exists():
        return target

    payload = {
        "schema_version": 1,
        "as_of_date": as_of_date,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "market_regime": market_regime,
        "signals": signals,
    }
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
    return target
