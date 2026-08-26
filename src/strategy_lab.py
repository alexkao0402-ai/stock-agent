"""Cross-stock strategy research helpers.

This module compares fixed strategy hypotheses across a fixed stock universe.
It deliberately reports both SPY-relative and same-stock buy-and-hold-relative
performance so a strategy cannot look successful merely because the stock rose.
"""
from __future__ import annotations

import pandas as pd

from src.backtest_engine import BacktestConfig, run_backtest, run_buy_and_hold
from src.performance import calculate_metrics, chronological_split_metrics
from src.strategies import mean_reversion_signals, momentum_relative_strength_signals


STRATEGIES = ("Pullback Mean Reversion", "Short-Term Momentum")


def _metric_row(symbol: str, strategy: str, result: dict, stock_bh: dict, spy_bh: dict) -> dict:
    metrics = calculate_metrics(result)
    split = chronological_split_metrics(result)
    recent = split.get("Out-of-Sample", split.get("Validation", {}))
    strategy_return = float(metrics.get("Total Return %", 0.0))
    stock_bh_return = float(stock_bh.get("total_return_pct", 0.0))
    spy_return = float(spy_bh.get("total_return_pct", 0.0))
    recent_return = recent.get("Total Return %")
    return {
        "Stock": symbol,
        "Strategy": strategy,
        "Total Return %": strategy_return,
        "Stock B&H %": stock_bh_return,
        "SPY B&H %": spy_return,
        "Alpha vs B&H %": strategy_return - stock_bh_return,
        "Alpha vs SPY %": strategy_return - spy_return,
        "Sharpe": metrics.get("Sharpe"),
        "Sortino": metrics.get("Sortino"),
        "Max Drawdown %": metrics.get("Max Drawdown %"),
        "Trades": metrics.get("Trades"),
        "OOS Return %": recent_return,
        "OOS Alpha vs B&H %": None if recent_return is None else float(recent_return) - stock_bh_return,
    }


def build_strategy_stock_matrix(
    universe_prices: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    """Run the two single-stock hypotheses across every stock in the universe.

    Cross-sectional momentum is a portfolio-level hypothesis and is intentionally
    not duplicated as if it were an independent single-stock backtest.
    """
    spy_bh = run_buy_and_hold(spy_df, "SPY", config)
    rows: list[dict] = []
    for symbol, stock_df in universe_prices.items():
        if stock_df is None or stock_df.empty or len(stock_df) < 201:
            continue
        stock_bh = run_buy_and_hold(stock_df, symbol, config)
        prepared = {
            "Pullback Mean Reversion": mean_reversion_signals(stock_df, max_holding_days=10),
            "Short-Term Momentum": momentum_relative_strength_signals(stock_df, spy_df, max_holding_days=20),
        }
        for strategy, frame in prepared.items():
            result = run_backtest(frame, symbol, strategy, config)
            rows.append(_metric_row(symbol, strategy, result, stock_bh, spy_bh))
    return pd.DataFrame(rows)


def strategy_summary(matrix: pd.DataFrame) -> pd.DataFrame:
    """Aggregate cross-stock robustness; median is emphasized over mean."""
    if matrix.empty:
        return pd.DataFrame()
    rows = []
    for strategy, group in matrix.groupby("Strategy"):
        alpha = pd.to_numeric(group["Alpha vs B&H %"], errors="coerce")
        oos = pd.to_numeric(group["OOS Alpha vs B&H %"], errors="coerce")
        rows.append({
            "Strategy": strategy,
            "Stocks Tested": int(group["Stock"].nunique()),
            "Beat B&H": int((alpha > 0).sum()),
            "Beat B&H %": float((alpha > 0).mean() * 100),
            "Median Alpha vs B&H %": float(alpha.median()),
            "Average Alpha vs B&H %": float(alpha.mean()),
            "Median Alpha vs SPY %": float(pd.to_numeric(group["Alpha vs SPY %"], errors="coerce").median()),
            "Median Sharpe": float(pd.to_numeric(group["Sharpe"], errors="coerce").median()),
            "Median Max Drawdown %": float(pd.to_numeric(group["Max Drawdown %"], errors="coerce").median()),
            "OOS Stocks Available": int(oos.notna().sum()),
            "OOS Beat B&H %": float((oos.dropna() > 0).mean() * 100) if oos.notna().any() else None,
            "Median OOS Alpha vs B&H %": float(oos.median()) if oos.notna().any() else None,
        })
    return pd.DataFrame(rows)


def research_verdict(summary: pd.DataFrame) -> pd.DataFrame:
    """Conservative KEEP / MORE EVIDENCE / KILL labels.

    KEEP requires positive median full-history alpha, a majority of stocks beating
    B&H, and positive median OOS alpha. This is a research screen, not proof of edge.
    """
    if summary.empty:
        return summary.copy()
    out = summary.copy()
    verdicts = []
    for _, row in out.iterrows():
        full_ok = row["Median Alpha vs B&H %"] > 0 and row["Beat B&H %"] > 50
        oos_value = row["Median OOS Alpha vs B&H %"]
        oos_ok = pd.notna(oos_value) and oos_value > 0
        if full_ok and oos_ok:
            verdict = "KEEP"
        elif row["Median Alpha vs B&H %"] < 0 and pd.notna(oos_value) and oos_value < 0:
            verdict = "KILL"
        else:
            verdict = "MORE EVIDENCE"
        verdicts.append(verdict)
    out["Research Verdict"] = verdicts
    return out
