"""Record all due Frozen V12, SPY and QQQ simulated open fills after the session close."""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.forward_execution import execute_due_portfolios
from src.paper_ledger import AppendOnlyLedger


REPO_ROOT = Path(__file__).resolve().parents[1]


def fetch_exact_raw_opens(tickers: list[str], execution_date: str) -> dict[str, float]:
    if not tickers:
        return {}
    date = pd.Timestamp(execution_date)
    end = (date + timedelta(days=1)).date().isoformat()
    prices = {}
    for ticker in tickers:
        frame = yf.download(
            ticker,
            start=date.date().isoformat(),
            end=end,
            auto_adjust=False,
            actions=True,
            progress=False,
            threads=False,
        )
        if frame.empty:
            raise RuntimeError(f"missing exact execution-session data for {ticker}")
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = frame.columns.get_level_values(0)
        if "Open" not in frame or pd.isna(frame["Open"].iloc[0]) or float(frame["Open"].iloc[0]) <= 0:
            raise RuntimeError(f"invalid raw open for {ticker} on {execution_date}")
        observed = pd.Timestamp(frame.index[0]).date().isoformat()
        if observed != execution_date:
            raise RuntimeError(f"wrong price date for {ticker}: {observed}")
        prices[ticker] = float(frame["Open"].iloc[0])
    return prices


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-date", required=True, help="NYSE session in YYYY-MM-DD format")
    parser.add_argument("--whole-shares", action="store_true", help="Disable fractional-share simulation")
    args = parser.parse_args()
    ledger = AppendOnlyLedger(REPO_ROOT / "paper_ledger" / "v12_events.sqlite3")
    try:
        results = execute_due_portfolios(
            ledger,
            execution_date=pd.Timestamp(args.execution_date).date().isoformat(),
            price_fetcher=fetch_exact_raw_opens,
            fractional_shares=not args.whole_shares,
        )
    except Exception as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(
        {
            "status": "EXECUTED" if results else "ALREADY_PROCESSED_OR_NOT_DUE",
            "execution_date": args.execution_date,
            "portfolios": results,
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
