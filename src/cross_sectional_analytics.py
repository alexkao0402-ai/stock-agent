"""Audit-friendly analytics for the cross-sectional portfolio backtest."""
from __future__ import annotations

from collections import defaultdict, deque

import pandas as pd


def _fifo_state(trades: list[dict]) -> tuple[list[dict], dict[str, deque]]:
    lots: dict[str, deque] = defaultdict(deque)
    rows: list[dict] = []
    for trade in trades:
        action = str(trade["action"]).upper()
        symbol = trade["symbol"]
        shares = float(trade["shares"])
        if action == "BUY":
            total_cost = shares * float(trade["execution_price"]) + float(trade["transaction_cost"])
            lots[symbol].append({
                "date": pd.to_datetime(trade["execution_date"]),
                "shares": shares,
                "unit_cost": total_cost / shares,
            })
            continue
        if action != "SELL":
            continue

        remaining = shares
        sell_cost_per_share = float(trade["transaction_cost"]) / shares
        while remaining > 1e-10 and lots[symbol]:
            lot = lots[symbol][0]
            matched = min(remaining, lot["shares"])
            entry_cost = matched * lot["unit_cost"]
            net_proceeds = matched * (float(trade["execution_price"]) - sell_cost_per_share)
            pnl = net_proceeds - entry_cost
            exit_date = pd.to_datetime(trade["execution_date"])
            rows.append({
                "Symbol": symbol,
                "Entry Date": lot["date"],
                "Exit Date": exit_date,
                "Holding Days": int((exit_date - lot["date"]).days),
                "Shares": matched,
                "Entry Cost": entry_cost,
                "Net Proceeds": net_proceeds,
                "Net P&L": pnl,
                "Return %": 100 * pnl / entry_cost if entry_cost else 0.0,
            })
            lot["shares"] -= matched
            remaining -= matched
            if lot["shares"] <= 1e-10:
                lots[symbol].popleft()
        if remaining > 1e-8:
            raise ValueError(f"Sell quantity exceeds recorded lots for {symbol}")
    return rows, lots


def realized_trade_ledger(trades: list[dict]) -> pd.DataFrame:
    """Match partial sells to buy lots with FIFO and include both-side costs."""
    rows, _ = _fifo_state(trades)
    return pd.DataFrame(rows)


def open_position_ledger(result: dict, price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return remaining FIFO cost basis and mark open positions at final close."""
    _, lots = _fifo_state(result.get("trades", []))

    final_date = pd.to_datetime(result["equity_curve"]["date"]).max()
    rows = []
    for symbol, symbol_lots in lots.items():
        shares = sum(lot["shares"] for lot in symbol_lots)
        if shares <= 1e-10:
            continue
        cost_basis = sum(lot["shares"] * lot["unit_cost"] for lot in symbol_lots)
        prices = price_data[symbol].copy()
        prices["date"] = pd.to_datetime(prices["date"])
        eligible = prices[prices["date"] <= final_date]
        if eligible.empty:
            continue
        close = float(eligible.sort_values("date").iloc[-1]["close"])
        market_value = shares * close
        rows.append({
            "Symbol": symbol,
            "Shares": shares,
            "Cost Basis": cost_basis,
            "Last Close": close,
            "Market Value": market_value,
            "Unrealized P&L": market_value - cost_basis,
            "Unrealized Return %": 100 * (market_value / cost_basis - 1) if cost_basis else 0.0,
        })
    return pd.DataFrame(rows)


def rebalance_summary(result: dict) -> pd.DataFrame:
    """One readable row per 20-trading-day selection cycle."""
    logs = result.get("rebalance_log", [])
    if not logs:
        return pd.DataFrame()
    curve = result["equity_curve"][["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    curve = curve.sort_values("date").set_index("date")
    realized = realized_trade_ledger(result.get("trades", []))
    rows = []
    for index, log in enumerate(logs):
        execution_date = pd.to_datetime(log["execution_date"])
        end_date = (
            pd.to_datetime(logs[index + 1]["signal_date"])
            if index + 1 < len(logs)
            else curve.index.max()
        )
        start_value = float(curve.loc[execution_date, "equity"])
        end_value = float(curve.loc[:end_date, "equity"].iloc[-1])
        cycle_pnl = end_value - start_value
        realized_on_date = 0.0
        if not realized.empty:
            realized_on_date = float(realized.loc[realized["Exit Date"] == execution_date, "Net P&L"].sum())
        rows.append({
            "Signal Date": pd.to_datetime(log["signal_date"]),
            "Execution Date": execution_date,
            "Regime": log["market_regime"],
            "Previous Holdings": ", ".join(log["holdings_before"]) or "Cash",
            "Selected Holdings": ", ".join(log["holdings_after"]) or "Cash",
            "Bought": ", ".join(log["bought"]) or "—",
            "Sold": ", ".join(log["sold"]) or "—",
            "Cycle End": end_date,
            "Cycle P&L": cycle_pnl,
            "Cycle Return %": 100 * cycle_pnl / start_value if start_value else 0.0,
            "Realized P&L at Rebalance": realized_on_date,
            "Trading Cost": float(log["transaction_cost"]),
            "Turnover %": 100 * float(log["turnover_notional"]) / float(log["pretrade_value"]),
        })
    return pd.DataFrame(rows)


def monthly_return_matrix(equity_curve: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    curve = equity_curve[["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    monthly = curve.sort_values("date").set_index("date")["equity"].resample("ME").last()
    returns = monthly.pct_change()
    if not returns.empty:
        returns.iloc[0] = monthly.iloc[0] / initial_capital - 1
    frame = returns.rename("Return").reset_index()
    frame["Year"] = frame["date"].dt.year
    frame["Month"] = frame["date"].dt.month
    return frame.pivot(index="Year", columns="Month", values="Return") * 100


def drawdown_series(equity_curve: pd.DataFrame) -> pd.DataFrame:
    curve = equity_curve[["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    curve["Drawdown %"] = (curve["equity"] / curve["equity"].cummax() - 1) * 100
    return curve[["date", "Drawdown %"]]


def stock_contribution(result: dict, price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    closed = realized_trade_ledger(result.get("trades", []))
    opened = open_position_ledger(result, price_data)
    realized = closed.groupby("Symbol", as_index=False)["Net P&L"].sum() if not closed.empty else pd.DataFrame(columns=["Symbol", "Net P&L"])
    unrealized = opened[["Symbol", "Unrealized P&L"]] if not opened.empty else pd.DataFrame(columns=["Symbol", "Unrealized P&L"])
    out = realized.merge(unrealized, on="Symbol", how="outer").fillna(0.0)
    out["Total Contribution"] = out["Net P&L"] + out["Unrealized P&L"]
    return out.sort_values("Total Contribution", ascending=False).reset_index(drop=True)
