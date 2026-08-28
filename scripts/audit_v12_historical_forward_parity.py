"""Audit Frozen V12 historical/forward implementation parity on known month-ends.

Licensed CRSP files are read locally and never copied into the repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.v12_live_signal import compute_frozen_v12_signal


DEFAULT_DATES = ["2000-01-31", "2008-09-30", "2020-03-31", "2025-08-29", "2025-12-31"]


def _selection(value: object) -> set[str]:
    text = str(value).strip()
    if not text or text.lower() == "cash":
        return set()
    return {item.strip() for item in text.split(",") if item.strip()}


def audit_parity(
    monthly_universe_path: str | Path,
    daily_crsp_path: str | Path,
    spy_path: str | Path,
    selection_path: str | Path,
    signal_history_path: str | Path,
    monthly_rankings_path: str | Path,
    dates: list[str],
) -> dict:
    dates = [pd.Timestamp(value).date().isoformat() for value in dates]
    universe_all = pd.read_csv(monthly_universe_path, parse_dates=["MthCalDt"])
    universe_all["signal_date"] = universe_all["MthCalDt"].dt.date.astype(str)
    universe_subset = universe_all[universe_all["signal_date"].isin(dates)].copy()
    missing_dates = sorted(set(dates) - set(universe_subset["signal_date"]))
    if missing_dates:
        raise ValueError(f"historical universe is missing: {', '.join(missing_dates)}")
    permnos = set(universe_subset["PERMNO"].astype(int))
    raw = pd.read_csv(
        daily_crsp_path,
        usecols=["PERMNO", "DlyCalDt", "DlyRet", "DlyOpen", "DlyClose"],
    )
    raw = raw[raw["PERMNO"].isin(permnos)].copy()
    raw["DlyCalDt"] = pd.to_datetime(raw["DlyCalDt"])
    raw["DlyRet"] = pd.to_numeric(raw["DlyRet"], errors="coerce")
    raw["DlyOpen"] = pd.to_numeric(raw["DlyOpen"], errors="coerce")
    raw["DlyClose"] = pd.to_numeric(raw["DlyClose"], errors="coerce")
    raw = raw.sort_values(["PERMNO", "DlyCalDt"]).drop_duplicates(["PERMNO", "DlyCalDt"], keep="last")
    raw["adjusted_close"] = raw.groupby("PERMNO")["DlyRet"].transform(
        lambda values: 100.0 * (1.0 + values.fillna(0.0).clip(lower=-1.0)).cumprod()
    )
    spy = pd.read_csv(spy_path, parse_dates=["date"]).sort_values("date")
    selections = pd.read_csv(selection_path)
    history = pd.read_csv(signal_history_path)
    rankings = pd.read_csv(monthly_rankings_path)

    results = []
    for signal_date in dates:
        names = universe_subset[universe_subset["signal_date"].eq(signal_date)].sort_values("Rank")
        forward_universe = pd.DataFrame(
            {
                "signal_date": signal_date,
                "stable_company_id": names["PERMCO"].astype(int).map(lambda value: f"CRSP-PERMCO-{value}"),
                "stable_security_id": names["PERMNO"].astype(int).map(lambda value: f"CRSP-PERMNO-{value}"),
                "ticker": names["Ticker"].astype(str),
                "company_market_cap": names["CompanyMthCap"].astype(float),
                "market_cap_rank": names["Rank"].astype(int),
            }
        )
        price_rows = []
        for item in names.itertuples(index=False):
            security = raw[
                raw["PERMNO"].eq(int(item.PERMNO))
                & raw["DlyCalDt"].le(pd.Timestamp(signal_date))
            ]
            price_rows.extend(
                {
                    "ticker": str(item.Ticker),
                    "trade_date": row.DlyCalDt.date().isoformat(),
                    "adjusted_close": float(row.adjusted_close),
                }
                for row in security.itertuples(index=False)
                if pd.notna(row.adjusted_close)
            )
        spy_rows = spy[spy["date"].le(pd.Timestamp(signal_date))]
        price_rows.extend(
            {
                "ticker": "SPY",
                "trade_date": row.date.date().isoformat(),
                "adjusted_close": float(row.adj_close),
            }
            for row in spy_rows.itertuples(index=False)
            if pd.notna(row.adj_close)
        )
        forward = compute_frozen_v12_signal(forward_universe, pd.DataFrame(price_rows))
        expected = selections[selections["signal_date"].astype(str).eq(signal_date)].iloc[0]
        expected_v7 = _selection(expected["V7_selection"])
        expected_v8 = _selection(expected["V8_selection"])
        expected_v12 = _selection(expected["V12_selection"])
        expected_weight_rows = history[history["signal_date"].astype(str).eq(signal_date)]
        expected_weights = dict(
            zip(expected_weight_rows["ticker"].astype(str), expected_weight_rows["target_weight"].astype(float))
        )
        expected_regime = bool(
            rankings[rankings["signal_date"].astype(str).eq(signal_date)].iloc[0]["spy_bull"]
        )
        actual_weights = {str(key): float(value) for key, value in forward["target_weights"].items()}
        row = {
            "signal_date": signal_date,
            "universe_match": list(forward_universe.sort_values("market_cap_rank")["ticker"])
            == list(names.sort_values("Rank")["Ticker"].astype(str)),
            "v7_match": set(forward["v7_selected"]) == expected_v7,
            "v8_match": set(forward["v8_selected"]) == expected_v8,
            "v12_match": set(forward["target_weights"]) == expected_v12,
            "weights_match": set(actual_weights) == set(expected_weights)
            and all(np.isclose(actual_weights[key], expected_weights[key], atol=1e-12) for key in actual_weights),
            "regime_match": bool(forward["spy_bull"]) == expected_regime,
            "actual_v7": sorted(forward["v7_selected"]),
            "actual_v8": sorted(forward["v8_selected"]),
            "actual_weights": actual_weights,
            "actual_regime": "BULL" if forward["spy_bull"] else "CASH",
        }
        row["pass"] = all(row[key] for key in [
            "universe_match", "v7_match", "v8_match", "v12_match", "weights_match", "regime_match"
        ])
        results.append(row)
    passed = all(row["pass"] for row in results)
    return {
        "status": "PASS" if passed else "FAIL",
        "dates_tested": dates,
        "months_passed": sum(row["pass"] for row in results),
        "months_total": len(results),
        "results": results,
        "note": "Equivalent CRSP point-in-time inputs were adapted to the forward input schema; no Frozen V12 rule was changed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--monthly-universe", required=True)
    parser.add_argument("--daily-crsp", required=True)
    parser.add_argument("--spy", required=True)
    parser.add_argument("--selections", required=True)
    parser.add_argument("--signal-history", required=True)
    parser.add_argument("--monthly-rankings", required=True)
    parser.add_argument("--dates", nargs="+", default=DEFAULT_DATES)
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit_parity(
        args.monthly_universe,
        args.daily_crsp,
        args.spy,
        args.selections,
        args.signal_history,
        args.monthly_rankings,
        args.dates,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
