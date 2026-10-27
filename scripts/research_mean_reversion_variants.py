"""Execute every pre-registered Bollinger mean-reversion experiment."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest_engine import BacktestConfig, run_buy_and_hold
from src.candidate_strategies import bollinger_mean_reversion_variant
from src.cross_sectional import cross_sectional_momentum_backtest, equal_weight_buy_and_hold
from src.portfolio_backtest import run_signal_portfolio
from src.stock_data import get_long_history_stock_data

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(10_000, 0.001, 0.0005)
FILTERS = {
    "F0 both filters": (True, True),
    "F1 stock filter only": (False, True),
    "F2 market filter only": (True, False),
    "F3 no filters": (False, False),
}
EXITS = {
    "E0 MA20 or 10D": (True, 10),
    "E1 MA20 or 5D": (True, 5),
    "E2 MA20 or 20D": (True, 20),
    "E3 time only 10D": (False, 10),
    "E4 time only 20D": (False, 20),
}


def returns(result: dict) -> pd.DataFrame:
    out = result["equity_curve"][["date", "equity"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    out["return"] = out["equity"].pct_change()
    return out


def round_trips(trades: list[dict]) -> list[dict]:
    opened, completed = {}, []
    for trade in trades:
        symbol = trade["symbol"]
        if trade["action"] == "BUY":
            opened[symbol] = trade
        elif trade["action"] == "SELL" and symbol in opened:
            entry = opened.pop(symbol)
            cost = entry["execution_price"] * entry["shares"] + entry["transaction_cost"]
            proceeds = trade["execution_price"] * trade["shares"] - trade["transaction_cost"]
            completed.append({"symbol": symbol, "entry": entry, "exit": trade,
                              "return": proceeds / cost - 1, "pnl": proceeds - cost})
    return completed


def segment_metrics(frame: pd.DataFrame) -> dict:
    clean = frame.dropna(subset=["return"])
    ret = clean["return"]
    wealth = (1 + ret).cumprod()
    vol = ret.std(ddof=0)
    downside = ret[ret < 0].std(ddof=0)
    years = max((clean["date"].iloc[-1] - clean["date"].iloc[0]).days / 365.25, 1 / 252)
    total = wealth.iloc[-1] - 1
    return {"Return %": total * 100, "CAGR %": ((1 + total) ** (1 / years) - 1) * 100,
            "Sharpe": ret.mean() / vol * np.sqrt(252) if vol > 0 else 0,
            "Sortino": ret.mean() / downside * np.sqrt(252) if pd.notna(downside) and downside > 0 else 0,
            "Max Drawdown %": (wealth / wealth.cummax() - 1).min() * 100, "Sessions": len(clean)}


def row(name: str, stage: str, result: dict, spy: dict, equal_weight: dict, split: int) -> dict:
    curve = returns(result)
    spy_returns = returns(spy).set_index("date")["return"]
    ew_returns = returns(equal_weight).set_index("date")["return"]
    full, research, oos = segment_metrics(curve), segment_metrics(curve.iloc[:split + 1]), segment_metrics(curve.iloc[split:])
    oos_dates = curve.iloc[split:]["date"]
    spy_oos = ((1 + spy_returns.reindex(oos_dates).dropna()).prod() - 1) * 100
    ew_oos = ((1 + ew_returns.reindex(oos_dates).dropna()).prod() - 1) * 100
    trips = round_trips(result["trades"])
    profits = [trip["pnl"] for trip in trips if trip["pnl"] > 0]
    losses = [trip["pnl"] for trip in trips if trip["pnl"] < 0]
    completed_count = len(trips)
    win_rate = 100 * len(profits) / len(trips) if trips else np.nan
    profit_factor = sum(profits) / abs(sum(losses)) if losses else np.nan
    median_trade = np.median([t["return"] for t in trips]) * 100 if trips else np.nan
    if result.get("rebalance_log"):
        indexed = curve.set_index("date")["equity"]
        execution_dates = [pd.Timestamp(item["execution_date"]) for item in result["rebalance_log"]]
        period_returns = [float(indexed.loc[end] / indexed.loc[start] - 1)
                          for start, end in zip(execution_dates, execution_dates[1:])
                          if start in indexed.index and end in indexed.index]
        completed_count = len(period_returns)
        win_rate = 100 * sum(value > 0 for value in period_returns) / len(period_returns) if period_returns else np.nan
        profit_factor = np.nan
        median_trade = np.median(period_returns) * 100 if period_returns else np.nan
    turnover = sum(trade["notional"] for trade in result["trades"]) / curve["equity"].mean()
    fees = sum(trade["transaction_cost"] for trade in result["trades"])
    return {"Stage": stage, "Variant": name, **{f"Full {k}": v for k, v in full.items()},
            **{f"Research {k}": v for k, v in research.items()}, **{f"OOS {k}": v for k, v in oos.items()},
            "OOS Alpha vs SPY %": oos["Return %"] - spy_oos,
            "OOS Alpha vs Equal Weight %": oos["Return %"] - ew_oos,
            "Completed Trades": completed_count, "Win Rate %": win_rate,
            "Profit Factor": profit_factor, "Median Trade Return %": median_trade,
            "Exposure %": result["exposure_pct"], "Turnover x": turnover, "Transaction Costs $": fees}


def run_variant(prices, spy_df, name, market_filter, stock_filter, ma_exit, max_days):
    prepared = {symbol: bollinger_mean_reversion_variant(frame, spy_df, market_filter, stock_filter, ma_exit)
                for symbol, frame in prices.items()}
    return run_signal_portfolio(prepared, name, CONFIG, 2, max_days)


def main() -> None:
    prices = {symbol: get_long_history_stock_data(symbol, "5y") for symbol in UNIVERSE}
    spy_df = get_long_history_stock_data("SPY", "5y")
    if spy_df.empty or any(frame.empty for frame in prices.values()):
        raise RuntimeError("Required five-year adjusted OHLC data is unavailable")
    common = set(pd.to_datetime(spy_df["date"]))
    for frame in prices.values():
        common &= set(pd.to_datetime(frame["date"]))
    dates = sorted(common)
    prices = {symbol: frame[pd.to_datetime(frame["date"]).isin(dates)].copy() for symbol, frame in prices.items()}
    spy_df = spy_df[pd.to_datetime(spy_df["date"]).isin(dates)].copy()
    split = int(len(dates) * 0.7)
    spy = run_buy_and_hold(spy_df, "SPY", CONFIG)
    equal_weight = equal_weight_buy_and_hold(prices, CONFIG)

    results, rows = {}, []
    for name, (market_filter, stock_filter) in FILTERS.items():
        result = run_variant(prices, spy_df, name, market_filter, stock_filter, True, 10)
        results[f"A {name}"] = result
        rows.append(row(name, "A filters", result, spy, equal_weight, split))
    stage_a = pd.DataFrame(rows)
    # Pre-declared selection: highest research Sharpe, then Sortino, then shallower drawdown.
    chosen_name = stage_a.sort_values(
        ["Research Sharpe", "Research Sortino", "Research Max Drawdown %"], ascending=[False, False, False]
    ).iloc[0]["Variant"]
    chosen_filters = FILTERS[chosen_name]

    for days in (5, 10, 15, 20):
        name = f"H{days} MA20 or {days}D ({chosen_name})"
        result = run_variant(prices, spy_df, name, *chosen_filters, True, days)
        results[f"B {name}"] = result
        rows.append(row(name, "B holding", result, spy, equal_weight, split))
    for name, (ma_exit, days) in EXITS.items():
        label = f"{name} ({chosen_name})"
        result = run_variant(prices, spy_df, label, *chosen_filters, ma_exit, days)
        results[f"C {label}"] = result
        rows.append(row(label, "C exits", result, spy, equal_weight, split))

    cross = cross_sectional_momentum_backtest(prices, spy_df, CONFIG)
    rows.append(row("Cross-Sectional Momentum", "Benchmark strategy", cross, spy, equal_weight, split))
    table = pd.DataFrame(rows)
    out = ROOT / "artifacts" / "mean_reversion_variants"
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / "all_variants.csv", index=False, float_format="%.6f")
    for key, result in results.items():
        safe = "".join(c.lower() if c.isalnum() else "_" for c in key).strip("_")
        pd.DataFrame(result["trades"]).to_csv(out / f"trades_{safe}.csv", index=False)
    selection = table[table["Stage"] != "Benchmark strategy"].sort_values(
        ["Research Sharpe", "Research Sortino", "Research Max Drawdown %"], ascending=[False, False, False]
    )
    selection.to_csv(out / "research_ranking.csv", index=False, float_format="%.6f")
    regime = spy_df[["date", "close"]].copy()
    regime["date"] = pd.to_datetime(regime["date"])
    regime["ma200"] = regime["close"].rolling(200, min_periods=200).mean()
    regime["regime"] = np.where(regime["close"] > regime["ma200"], "Bull", "Bear")
    regime.loc[regime["ma200"].isna(), "regime"] = None
    regime_by_date = regime.set_index("date")["regime"]
    portfolio_rows, entry_rows = [], []
    for key, result in {**results, "Benchmark Cross-Sectional Momentum": cross}.items():
        daily = returns(result)
        daily["regime"] = daily["date"].map(regime_by_date.shift(1))
        for label, group in daily.dropna(subset=["return", "regime"]).groupby("regime"):
            metrics = segment_metrics(group)
            portfolio_rows.append({"Variant": key, "Portfolio Regime": label, **metrics})
        trips = round_trips(result["trades"])
        for label in ("Bull", "Bear"):
            selected = [trip for trip in trips if regime_by_date.get(pd.Timestamp(trip["entry"]["signal_date"])) == label]
            entry_rows.append({"Variant": key, "Entry Regime": label, "Completed Trades": len(selected),
                               "Win Rate %": 100 * sum(t["pnl"] > 0 for t in selected) / len(selected) if selected else np.nan,
                               "Median Trade Return %": np.median([t["return"] for t in selected]) * 100 if selected else np.nan,
                               "Total PnL $": sum(t["pnl"] for t in selected)})
    pd.DataFrame(portfolio_rows).to_csv(out / "portfolio_regime.csv", index=False, float_format="%.6f")
    pd.DataFrame(entry_rows).to_csv(out / "entry_regime.csv", index=False, float_format="%.6f")
    (out / "selection.txt").write_text(
        f"Stage A selected filter: {chosen_name}\nRule: highest research Sharpe, then Sortino, then shallower drawdown.\n"
        f"Research end: {pd.Timestamp(dates[split]).date()}\nOOS start: {pd.Timestamp(dates[split]).date()}\n",
        encoding="utf-8",
    )
    print(f"Stage A selected: {chosen_name}")
    print(table[["Stage", "Variant", "Research Sharpe", "Research Return %", "OOS Sharpe", "OOS Return %",
                 "Full Max Drawdown %", "Completed Trades", "Turnover x"]].to_string(index=False))
    print(f"Artifacts: {out}")


if __name__ == "__main__":
    main()
