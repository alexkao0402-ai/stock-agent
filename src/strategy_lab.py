"""Cross-stock strategy research helpers.

This module compares fixed strategy hypotheses across a fixed stock universe.
It deliberately reports both SPY-relative and same-stock buy-and-hold-relative
performance so a strategy cannot look successful merely because the stock rose.
"""
from __future__ import annotations

import pandas as pd

from src.backtest_engine import BacktestConfig, run_backtest, run_buy_and_hold
from src.cross_sectional import cross_sectional_momentum_backtest, equal_weight_buy_and_hold
from src.performance import calculate_metrics, chronological_split_metrics, completed_round_trips
from src.strategies import mean_reversion_signals, momentum_relative_strength_signals


STRATEGIES = ("Pullback Mean Reversion", "Short-Term Momentum")


def _daily_series(result: dict, name: str) -> pd.DataFrame:
    curve = result["equity_curve"][["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    curve = curve.sort_values("date").drop_duplicates("date")
    curve[name] = curve["equity"].astype(float).pct_change()
    keep = ["date", name]
    if "position" in result["equity_curve"].columns:
        position = result["equity_curve"][["date", "position"]].copy()
        position["date"] = pd.to_datetime(position["date"])
        curve = curve.merge(position, on="date", how="left")
        keep.append("position")
    elif "holdings" in result["equity_curve"].columns:
        holdings = result["equity_curve"][["date", "holdings"]].copy()
        holdings["date"] = pd.to_datetime(holdings["date"])
        holdings["position"] = (holdings["holdings"] > 0).astype(int)
        curve = curve.merge(holdings[["date", "position"]], on="date", how="left")
        keep.append("position")
    return curve[keep]


def _regime_calendar(spy_df: pd.DataFrame) -> pd.DataFrame:
    """Point-in-time regime: today's SPY close versus today's trailing MA200."""
    spy = spy_df[["date", "close"]].copy()
    spy["date"] = pd.to_datetime(spy["date"])
    spy = spy.sort_values("date").drop_duplicates("date")
    spy["spy_ma200"] = spy["close"].astype(float).rolling(200, min_periods=200).mean()
    spy["Market Regime"] = pd.NA
    known = spy["spy_ma200"].notna()
    spy.loc[known & (spy["close"] > spy["spy_ma200"]), "Market Regime"] = "Bull"
    spy.loc[known & (spy["close"] <= spy["spy_ma200"]), "Market Regime"] = "Bear"
    return spy[["date", "Market Regime"]]


def _conditional_metrics(
    result: dict,
    stock_bh: dict,
    spy_bh: dict,
    regime_calendar: pd.DataFrame,
    period: str,
    regime: str,
    split_ratio: float = 0.7,
) -> dict | None:
    strategy = _daily_series(result, "strategy_return")
    stock = _daily_series(stock_bh, "stock_return")
    spy = _daily_series(spy_bh, "spy_return")
    # A return stamped T contains the move from T-1 close to T close, so it must
    # be classified by the regime known at T-1 close, not T close.
    return_calendar = regime_calendar.copy()
    return_calendar["Market Regime"] = return_calendar["Market Regime"].shift(1)
    daily = strategy.merge(stock, on="date", how="inner").merge(spy, on="date", how="inner")
    daily = daily.merge(return_calendar, on="date", how="left").dropna(
        subset=["strategy_return", "stock_return", "spy_return", "Market Regime"]
    )
    if daily.empty:
        return None

    split_i = max(1, min(len(daily) - 1, int(len(daily) * split_ratio)))
    split_date = daily.iloc[split_i]["date"]
    if period == "Recent OOS":
        daily = daily[daily["date"] >= split_date]
    elif period != "Full History":
        raise ValueError(f"Unknown period: {period}")
    daily = daily[daily["Market Regime"] == regime].copy()
    if daily.empty:
        return None

    def compounded(column: str) -> float:
        return float(((1 + daily[column]).prod() - 1) * 100)

    returns = daily["strategy_return"]
    volatility = returns.std(ddof=0)
    downside = returns[returns < 0].std(ddof=0)
    wealth = (1 + returns).cumprod()
    drawdown = wealth / wealth.cummax() - 1

    trips = completed_round_trips(result.get("trades", []))
    selected_trips = []
    regime_by_date = regime_calendar.set_index("date")["Market Regime"]
    for trip in trips:
        entry_date = pd.to_datetime(trip["entry"]["signal_date"])
        if entry_date not in regime_by_date.index or regime_by_date.loc[entry_date] != regime:
            continue
        if period == "Recent OOS" and entry_date < split_date:
            continue
        selected_trips.append(trip)

    strategy_return = compounded("strategy_return")
    stock_return = compounded("stock_return")
    spy_return = compounded("spy_return")
    return {
        "Time Period": period,
        "Market Regime": regime,
        "Start": daily["date"].min().date().isoformat(),
        "End": daily["date"].max().date().isoformat(),
        "Return %": strategy_return,
        "B&H Return %": stock_return,
        "SPY Return %": spy_return,
        "Alpha vs B&H %": strategy_return - stock_return,
        "Alpha vs SPY %": strategy_return - spy_return,
        "Sharpe": float(returns.mean() / volatility * (252 ** 0.5)) if volatility > 0 else 0.0,
        "Sortino": float(returns.mean() / downside * (252 ** 0.5)) if pd.notna(downside) and downside > 0 else 0.0,
        "Max Drawdown %": float(drawdown.min() * 100),
        "Win Rate %": 100 * sum(t["pnl"] > 0 for t in selected_trips) / len(selected_trips) if selected_trips else None,
        "Outperformance vs B&H %": float((daily["strategy_return"] > daily["stock_return"]).mean() * 100),
        "Outperformance vs SPY %": float((daily["strategy_return"] > daily["spy_return"]).mean() * 100),
        "Trades": len(selected_trips),
        "Exposure %": float(daily["position"].mean() * 100) if "position" in daily else None,
        "Sample Size": len(daily),
    }


def build_regime_matrix(
    universe_prices: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    """Strategy × stock × point-in-time regime × chronological period results."""
    calendar = _regime_calendar(spy_df)
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
        for strategy_name, frame in prepared.items():
            result = run_backtest(frame, symbol, strategy_name, config)
            for period in ("Full History", "Recent OOS"):
                for regime in ("Bull", "Bear"):
                    metrics = _conditional_metrics(result, stock_bh, spy_bh, calendar, period, regime)
                    if metrics:
                        rows.append({"Strategy": strategy_name, "Stock": symbol, **metrics})
    return pd.DataFrame(rows)


def build_cross_sectional_regime_matrix(
    universe_prices: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    config: BacktestConfig,
) -> pd.DataFrame:
    """Portfolio-level regime results for cross-sectional momentum."""
    result = cross_sectional_momentum_backtest(universe_prices, spy_df, config)
    universe_bh = equal_weight_buy_and_hold(universe_prices, config)
    spy_bh = run_buy_and_hold(spy_df, "SPY", config)
    calendar = _regime_calendar(spy_df)
    rows = []
    for period in ("Full History", "Recent OOS"):
        for regime in ("Bull", "Bear"):
            row = _conditional_metrics(result, universe_bh, spy_bh, calendar, period, regime)
            if row:
                row["Strategy"] = "Cross-Sectional Momentum"
                row["Stock"] = "10-stock portfolio"
                # Portfolio rebalancing creates partial fills, not single-stock round trips.
                row["Win Rate %"] = None
                regime_by_date = calendar.set_index("date")["Market Regime"]
                curve_dates = pd.to_datetime(result["equity_curve"]["date"]).sort_values().reset_index(drop=True)
                split_i = max(1, min(len(curve_dates) - 1, int(len(curve_dates) * 0.7)))
                split_date = curve_dates.iloc[split_i]
                buys = []
                for trade in result.get("trades", []):
                    signal_date = pd.to_datetime(trade["signal_date"])
                    if str(trade["action"]).upper() != "BUY":
                        continue
                    if signal_date not in regime_by_date.index or regime_by_date.loc[signal_date] != regime:
                        continue
                    if period == "Recent OOS" and signal_date < split_date:
                        continue
                    buys.append(trade)
                row["Trades"] = len(buys)
                rows.append(row)
    return pd.DataFrame(rows)


def _metric_row(symbol: str, strategy: str, result: dict, stock_bh: dict, spy_bh: dict) -> dict:
    metrics = calculate_metrics(result)
    split = chronological_split_metrics(result)
    stock_split = chronological_split_metrics(stock_bh)
    spy_split = chronological_split_metrics(spy_bh)
    recent = split.get("Out-of-Sample 30%", {})
    stock_recent = stock_split.get("Out-of-Sample 30%", {})
    spy_recent = spy_split.get("Out-of-Sample 30%", {})
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
        "OOS Alpha vs B&H %": None if recent_return is None else float(recent_return) - float(stock_recent.get("Return %", 0.0)),
        "OOS Alpha vs SPY %": None if recent_return is None else float(recent_return) - float(spy_recent.get("Return %", 0.0)),
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
