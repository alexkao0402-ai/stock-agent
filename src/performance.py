"""Consistent performance definitions for all strategies."""

from __future__ import annotations

import math

import pandas as pd


def completed_round_trips(trades: list[dict]) -> list[dict]:
    completed = []
    entry = None
    for trade in trades:
        if trade["action"] == "BUY":
            entry = trade
        elif trade["action"] == "SELL" and entry is not None:
            gross_buy = entry["execution_price"] * entry["shares"]
            gross_sell = trade["execution_price"] * trade["shares"]
            pnl = gross_sell - trade["transaction_cost"] - gross_buy - entry["transaction_cost"]
            completed.append({"entry": entry, "exit": trade, "pnl": pnl})
            entry = None
    return completed


def calculate_metrics(result: dict) -> dict:
    curve = result["equity_curve"].copy()
    equity = curve["equity"].astype(float)
    returns = equity.pct_change().dropna()
    total_return = result["final_value"] / result["initial_capital"] - 1
    years = max((pd.to_datetime(curve["date"].iloc[-1]) - pd.to_datetime(curve["date"].iloc[0])).days / 365.25, 0)
    cagr = (result["final_value"] / result["initial_capital"]) ** (1 / years) - 1 if years > 0 else 0.0
    volatility = returns.std(ddof=0)
    sharpe = returns.mean() / volatility * math.sqrt(252) if volatility > 0 else 0.0
    downside = returns[returns < 0].std(ddof=0)
    sortino = returns.mean() / downside * math.sqrt(252) if downside and downside > 0 else 0.0
    drawdown = equity / equity.cummax() - 1
    trips = completed_round_trips(result["trades"])
    wins = [t["pnl"] for t in trips if t["pnl"] > 0]
    losses = [t["pnl"] for t in trips if t["pnl"] < 0]
    return {
        "Strategy": result["strategy"],
        "Total Return %": total_return * 100,
        "CAGR %": cagr * 100,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Max Drawdown %": drawdown.min() * 100,
        "Win Rate %": 100 * len(wins) / len(trips) if trips else 0.0,
        "Profit Factor": sum(wins) / abs(sum(losses)) if losses else (float("inf") if wins else 0.0),
        "Trades": len(trips),
        "Exposure %": result["exposure_pct"],
    }


def calculate_equity_metrics(result: dict) -> dict:
    """Metrics for portfolio engines whose trades are not single-symbol round trips."""
    curve = result["equity_curve"].copy()
    equity = curve["equity"].astype(float)
    returns = equity.pct_change().dropna()
    volatility = returns.std(ddof=0)
    drawdown = equity / equity.cummax() - 1
    return {
        "Strategy": result["strategy"],
        "Final Value": result["final_value"],
        "Total Return %": (result["final_value"] / result["initial_capital"] - 1) * 100,
        "Max Drawdown %": drawdown.min() * 100,
        "Sharpe": returns.mean() / volatility * math.sqrt(252) if volatility > 0 else 0.0,
        "Transactions": len(result.get("trades", [])),
    }
