"""Point-in-time strategy snapshots and fixed-horizon validation helpers."""

from __future__ import annotations

import pandas as pd


HORIZONS = (5, 20, 60)


def current_signal(strategy_name: str, frame: pd.DataFrame, result: dict) -> dict:
    """Describe the latest actionable state without changing strategy rules."""
    row = frame.iloc[-1]
    if bool(row.get("exit_signal", False)) and result.get("open_position"):
        state = "SELL"
        reason = str(row.get("exit_reason", "出場條件成立"))
    elif bool(row.get("entry_signal", False)) and not result.get("open_position"):
        state = "BUY"
        reason = str(row.get("entry_reason", "進場條件成立"))
    elif result.get("open_position"):
        state = "HOLD"
        reason = "策略目前持有部位，尚未出現出場訊號"
    else:
        state = "WAIT"
        reason = "目前沒有符合進場條件"
    return {"strategy": strategy_name, "signal": state, "reason": reason}


def equity_comparison(results: list[dict]) -> pd.DataFrame:
    """Align portfolio values by date for an apples-to-apples chart."""
    comparison = None
    for result in results:
        curve = result["equity_curve"][["date", "equity"]].copy()
        curve = curve.rename(columns={"equity": result["strategy"]})
        comparison = curve if comparison is None else comparison.merge(curve, on="date", how="inner")
    return comparison if comparison is not None else pd.DataFrame()


def fixed_horizon_validation(
    record: dict,
    stock_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    strategy_results: list[dict],
    horizons: tuple[int, ...] = HORIZONS,
) -> dict:
    """Measure future outcomes only after each trading-day horizon has matured."""
    prediction_date = pd.Timestamp(record["timestamp"]).normalize()
    stock = stock_df.copy()
    spy = spy_df.copy()
    stock["date"] = pd.to_datetime(stock["date"])
    spy["date"] = pd.to_datetime(spy["date"])
    stock = stock.sort_values("date").reset_index(drop=True)
    spy = spy.sort_values("date").reset_index(drop=True)
    start_candidates = stock.index[stock["date"] >= prediction_date]
    if len(start_candidates) == 0:
        return {}
    start_i = int(start_candidates[0])
    start_date = stock.loc[start_i, "date"]
    strategy_curves = {}
    for result in strategy_results:
        curve = result["equity_curve"][["date", "equity"]].copy()
        curve["date"] = pd.to_datetime(curve["date"])
        strategy_curves[result["strategy"]] = curve.set_index("date")["equity"]

    validations = {}
    for horizon in horizons:
        end_i = start_i + horizon
        if end_i >= len(stock):
            continue
        end_date = stock.loc[end_i, "date"]
        spy_window = spy[(spy["date"] >= start_date) & (spy["date"] <= end_date)]
        if len(spy_window) < 2:
            continue
        stock_return = stock.loc[end_i, "close"] / stock.loc[start_i, "close"] - 1
        spy_return = spy_window.iloc[-1]["close"] / spy_window.iloc[0]["close"] - 1
        strategy_returns = {}
        for name, curve in strategy_curves.items():
            usable = curve[(curve.index >= start_date) & (curve.index <= end_date)]
            if len(usable) >= 2:
                strategy_returns[name] = float(usable.iloc[-1] / usable.iloc[0] - 1)
        validations[str(horizon)] = {
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "stock_return_pct": round(float(stock_return) * 100, 2),
            "spy_return_pct": round(float(spy_return) * 100, 2),
            "strategies": {
                name: {
                    "return_pct": round(value * 100, 2),
                    "alpha_vs_stock_pct": round((value - stock_return) * 100, 2),
                    "alpha_vs_spy_pct": round((value - spy_return) * 100, 2),
                }
                for name, value in strategy_returns.items()
            },
        }
    return validations


def strategy_scorecard(records: list[dict], horizon: int = 20) -> pd.DataFrame:
    """Aggregate only matured, recorded validations; never infer missing outcomes."""
    rows = []
    names = sorted({
        name
        for record in records
        for name in record.get("strategy_validation", {}).get(str(horizon), {}).get("strategies", {})
    })
    for name in names:
        samples = [
            record["strategy_validation"][str(horizon)]["strategies"][name]
            for record in records
            if name in record.get("strategy_validation", {}).get(str(horizon), {}).get("strategies", {})
        ]
        alpha_spy = [sample["alpha_vs_spy_pct"] for sample in samples]
        alpha_stock = [sample["alpha_vs_stock_pct"] for sample in samples]
        returns = [sample["return_pct"] for sample in samples]
        rows.append({
            "策略": name,
            "已驗證訊號": len(samples),
            "勝過 SPY": sum(value > 0 for value in alpha_spy),
            "勝過 SPY 比率 %": 100 * sum(value > 0 for value in alpha_spy) / len(samples),
            "平均策略報酬 %": sum(returns) / len(returns),
            "平均 Alpha vs SPY %": sum(alpha_spy) / len(alpha_spy),
            "平均 Alpha vs 股票 %": sum(alpha_stock) / len(alpha_stock),
            "中位 Alpha vs SPY %": float(pd.Series(alpha_spy).median()),
        })
    return pd.DataFrame(rows)
