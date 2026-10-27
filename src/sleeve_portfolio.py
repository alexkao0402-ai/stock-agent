"""Cash-backed portfolio composition and disjoint return-period accounting."""
from __future__ import annotations

from collections import deque
import math

import numpy as np
import pandas as pd


def normalized_curve(result: dict) -> pd.DataFrame:
    curve = result["equity_curve"].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    if curve["date"].duplicated().any():
        raise ValueError("Duplicate equity dates")
    curve = curve.sort_values("date").reset_index(drop=True)
    if len(curve) < 2 or not np.isfinite(curve["equity"]).all() or (curve["equity"] <= 0).any():
        raise ValueError("At least two finite positive NAV observations are required")
    return curve


def combine_sleeves(sleeves: dict[str, dict], name: str) -> dict:
    """Add actual sleeve dollars without rebalancing or cash transfers."""
    if not sleeves:
        raise ValueError("At least one funded sleeve is required")
    curves = {key: normalized_curve(result) for key, result in sleeves.items()}
    first = next(iter(curves.values()))
    for curve in curves.values():
        if not curve["date"].equals(first["date"]):
            raise ValueError("Sleeves must have exactly aligned dates; missing dates cannot be filled")
        if "cash" not in curve or (curve["cash"] < -1e-6).any():
            raise ValueError("Sleeve cash is missing or negative")
    curve = first[["date"]].copy()
    curve["equity"] = sum(item["equity"].astype(float) for item in curves.values())
    curve["cash"] = sum(item["cash"].astype(float) for item in curves.values())
    curve["invested_value"] = curve["equity"] - curve["cash"]
    trades = []
    for key, result in sleeves.items():
        curve[f"{key}_equity"] = curves[key]["equity"].astype(float)
        curve[f"{key}_weight"] = curve[f"{key}_equity"] / curve["equity"]
        trades.extend({**trade, "sleeve": key} for trade in result["trades"])
    trades.sort(key=lambda t: (pd.Timestamp(t["execution_date"]), t["sleeve"], 0 if str(t["action"]).upper() == "SELL" else 1, t["symbol"]))
    return {"strategy": name, "initial_capital": sum(float(r["initial_capital"]) for r in sleeves.values()),
            "final_value": float(curve["equity"].iloc[-1]), "equity_curve": curve, "trades": trades}


def replay_fills(result: dict, prices: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Independently reconstruct cash, stock holdings and NAV from fills."""
    curve = normalized_curve(result)
    indexed = {}
    for symbol, raw in prices.items():
        frame = raw.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        indexed[symbol] = frame.set_index("date")
    calendar = curve["date"].tolist()
    calendar_index = {date: i for i, date in enumerate(calendar)}
    by_date = {}
    for trade in result["trades"]:
        execution = pd.Timestamp(trade["execution_date"])
        signal = pd.Timestamp(trade["signal_date"])
        if execution not in calendar_index or signal not in calendar_index or calendar_index[execution] != calendar_index[signal] + 1:
            raise ValueError("Every fill must execute on the next common session")
        by_date.setdefault(execution, []).append(trade)
    cash, holdings, rows, position_rows = float(result["initial_capital"]), {}, [], []
    for date in calendar:
        for trade in by_date.get(date, []):
            symbol, qty = trade["symbol"], float(trade["shares"])
            notional = qty * float(trade["execution_price"])
            fee = float(trade["transaction_cost"])
            if qty <= 0 or not math.isfinite(qty):
                raise ValueError("Invalid fill quantity")
            if str(trade["action"]).upper() == "BUY":
                cash -= notional + fee
                holdings[symbol] = holdings.get(symbol, 0.0) + qty
            else:
                if qty > holdings.get(symbol, 0.0) + 1e-7:
                    raise ValueError("Cannot sell more than held")
                cash += notional - fee
                holdings[symbol] = holdings.get(symbol, 0.0) - qty
        holdings = {s: q for s, q in holdings.items() if q > 1e-8}
        if cash < -1e-6:
            raise ValueError("Negative cash in fill reconstruction")
        values = {s: q * float(indexed[s].loc[date, "close"]) for s, q in holdings.items()}
        equity = cash + sum(values.values())
        rows.append({"date": date, "equity": equity, "cash": cash, "invested_value": sum(values.values()),
                     "holdings": len(values), "max_name_weight": max(values.values(), default=0.0) / equity})
        for symbol, value in values.items():
            position_rows.append({"date": date, "symbol": symbol, "shares": holdings[symbol], "value": value,
                                  "portfolio_weight": value / equity})
    replay = pd.DataFrame(rows)
    if not np.allclose(replay["equity"], curve["equity"], rtol=1e-9, atol=1e-5):
        raise ValueError("Fill reconstruction differs from engine NAV")
    return replay, pd.DataFrame(position_rows)


def fifo_sell_fills(trades: list[dict]) -> list[dict]:
    """Net realized PnL for each sell fill, retaining independent sleeve lots."""
    books, realized = {}, []
    for trade in sorted(enumerate(trades), key=lambda item: (pd.Timestamp(item[1]["execution_date"]), item[0])):
        trade = trade[1]
        key = (trade.get("sleeve", "standalone"), trade["symbol"])
        lots = books.setdefault(key, deque())
        qty = float(trade["shares"])
        if str(trade["action"]).upper() == "BUY":
            lots.append([qty, float(trade["execution_price"]) + float(trade["transaction_cost"]) / qty])
            continue
        remaining, basis = qty, 0.0
        while remaining > 1e-8 and lots:
            matched = min(remaining, lots[0][0])
            basis += matched * lots[0][1]
            remaining -= matched
            lots[0][0] -= matched
            if lots[0][0] < 1e-8:
                lots.popleft()
        if remaining > 1e-6:
            raise ValueError("Unfunded FIFO sell")
        proceeds = qty * float(trade["execution_price"]) - float(trade["transaction_cost"])
        realized.append({"execution_date": pd.Timestamp(trade["execution_date"]), "symbol": key[1], "sleeve": key[0],
                         "shares": qty, "cost_basis": basis, "net_proceeds": proceeds, "net_pnl": proceeds - basis})
    return realized


def disjoint_periods(dates: pd.Series, boundary: str) -> dict[str, pd.DatetimeIndex]:
    """Assign every close-to-close return exactly once at the date boundary."""
    dates = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values()
    if dates.has_duplicates or len(dates) < 3:
        raise ValueError("Unique return calendar required")
    return_dates = dates[1:]
    cutoff = pd.Timestamp(boundary)
    research = return_dates[return_dates < cutoff]
    oos = return_dates[return_dates >= cutoff]
    if not len(research) or not len(oos):
        raise ValueError("Boundary must leave returns on both sides")
    return {"Full": return_dates, "Research": research, "Explored OOS": oos}


def period_metrics(result: dict, return_dates, spy: dict, equal_weight: dict) -> dict:
    """Measure the same selected return dates with the prior-close NAV anchor."""
    curve = normalized_curve(result).set_index("date")
    selected = pd.DatetimeIndex(return_dates).sort_values()
    daily = curve["equity"].pct_change()
    returns = daily.reindex(selected)
    if returns.isna().any() or selected.empty:
        raise ValueError("Selected returns must all exist")
    start = curve.index[curve.index.get_loc(selected[0]) - 1]
    years = (selected[-1] - start).days / 365.25
    wealth = np.concatenate(([1.0], (1 + returns).cumprod().to_numpy()))
    total = float(wealth[-1] - 1)
    vol = float(returns.std(ddof=0))
    downside = float(np.sqrt(np.square(np.minimum(returns.to_numpy(), 0)).mean()))
    fill_subset = [t for t in result["trades"] if pd.Timestamp(t["execution_date"]) in selected]
    realized = [t for t in fifo_sell_fills(result["trades"]) if t["execution_date"] in selected]
    def benchmark_return(other):
        values = normalized_curve(other).set_index("date")["equity"].pct_change().reindex(selected)
        if values.isna().any():
            raise ValueError("Misaligned benchmark")
        return float(((1 + values).prod() - 1) * 100)
    # Turnover denominator includes the segment's starting NAV.
    nav = curve.loc[selected, "equity"]
    mean_nav = float(np.concatenate(([float(curve.loc[start, "equity"])], nav.to_numpy())).mean())
    turnover = sum(float(t.get("notional", t["execution_price"] * t["shares"])) for t in fill_subset) / mean_nav
    return {"Strategy": result["strategy"], "Start Anchor": start.date().isoformat(),
            "First Return": selected[0].date().isoformat(), "Last Return": selected[-1].date().isoformat(),
            "Sessions": len(selected), "Return %": total * 100,
            "CAGR %": ((1 + total) ** (1 / years) - 1) * 100 if years > 0 else None,
            "Sharpe": float(returns.mean() / vol * np.sqrt(252)) if vol > 0 else None,
            "Sortino": float(returns.mean() / downside * np.sqrt(252)) if downside > 0 else None,
            "Max Drawdown %": float(np.min(wealth / np.maximum.accumulate(wealth) - 1) * 100),
            "Turnover x": turnover, "Annualized Turnover x": turnover / years if years > 0 else None,
            "Fill Count": len(fill_subset), "Realized Sell Fills": len(realized),
            "Sell Fill Win Rate %": 100 * sum(t["net_pnl"] > 0 for t in realized) / len(realized) if realized else None,
            "Commission $": sum(float(t["transaction_cost"]) for t in fill_subset),
            "Exposure %": float(((curve.loc[selected, "equity"] - curve.loc[selected, "cash"]) / curve.loc[selected, "equity"]).mean() * 100),
            "Excess vs SPY pp": total * 100 - benchmark_return(spy),
            "Excess vs Equal Weight pp": total * 100 - benchmark_return(equal_weight)}
