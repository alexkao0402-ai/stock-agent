"""Run the pre-registered large-cap strategy comparison and write evidence files."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest_engine import BacktestConfig, run_buy_and_hold
from src.candidate_strategies import PRICE_STRATEGIES, pead_availability
from src.cross_sectional import cross_sectional_momentum_backtest, equal_weight_buy_and_hold
from src.portfolio_backtest import run_signal_portfolio
from src.stock_data import get_long_history_stock_data


UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(initial_capital=10_000, transaction_cost_pct=0.001, slippage_pct=0.0005)
PERIOD = "5y"


def _round_trips(trades: list[dict]) -> list[dict]:
    open_entries, trips = {}, []
    for trade in trades:
        symbol = trade["symbol"]
        if trade["action"].upper() == "BUY":
            open_entries[symbol] = trade
        elif trade["action"].upper() == "SELL" and symbol in open_entries:
            entry = open_entries.pop(symbol)
            pnl = (trade["execution_price"] * trade["shares"] - trade["transaction_cost"]
                   - entry["execution_price"] * entry["shares"] - entry["transaction_cost"])
            trips.append({"symbol": symbol, "entry": entry, "exit": trade, "pnl": pnl})
    return trips


def _returns(result: dict) -> pd.DataFrame:
    curve = result["equity_curve"][["date", "equity"]].copy()
    curve["date"] = pd.to_datetime(curve["date"])
    curve["return"] = curve["equity"].astype(float).pct_change()
    return curve


def _summary(result: dict, spy: dict, equal_weight: dict) -> dict:
    curve = _returns(result)
    returns = curve["return"].dropna()
    years = (curve["date"].iloc[-1] - curve["date"].iloc[0]).days / 365.25
    total = result["final_value"] / result["initial_capital"] - 1
    dd = curve["equity"] / curve["equity"].cummax() - 1
    downside = returns[returns < 0].std(ddof=0)
    volatility = returns.std(ddof=0)
    trips = _round_trips(result.get("trades", []))
    if result.get("rebalance_log"):
        execution_dates = [pd.Timestamp(item["execution_date"]) for item in result["rebalance_log"]]
        indexed = curve.set_index("date")["equity"]
        period_pnl = []
        for start, end in zip(execution_dates, execution_dates[1:]):
            if start in indexed.index and end in indexed.index:
                period_pnl.append(float(indexed.loc[end] / indexed.loc[start] - 1))
        completed_count = len(period_pnl)
        win_rate = 100 * sum(value > 0 for value in period_pnl) / completed_count if completed_count else np.nan
    else:
        completed_count = len(trips)
        win_rate = 100 * sum(t["pnl"] > 0 for t in trips) / len(trips) if trips else np.nan
    turnover = sum(float(t.get("notional", t["execution_price"] * t["shares"])) for t in result.get("trades", []))
    average_equity = float(curve["equity"].mean())
    spy_total = spy["final_value"] / spy["initial_capital"] - 1
    ew_total = equal_weight["final_value"] / equal_weight["initial_capital"] - 1
    return {"Strategy": result["strategy"], "Start": curve["date"].min().date().isoformat(),
            "End": curve["date"].max().date().isoformat(), "CAGR %": ((1 + total) ** (1 / years) - 1) * 100,
            "Total Return %": total * 100, "Sharpe": returns.mean() / volatility * np.sqrt(252) if volatility > 0 else 0,
            "Sortino": returns.mean() / downside * np.sqrt(252) if pd.notna(downside) and downside > 0 else 0,
            "Max Drawdown %": dd.min() * 100, "Turnover x": turnover / average_equity,
            "Transaction Count": len(result.get("trades", [])), "Completed Trades": completed_count,
            "Win Rate %": win_rate,
            "Exposure %": result.get("exposure_pct", np.nan), "Alpha vs SPY %": (total - spy_total) * 100,
            "Alpha vs Equal Weight %": (total - ew_total) * 100}


def _period_rows(results: dict[str, dict], spy_df: pd.DataFrame, spy_result: dict, equal_weight: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    spy = spy_df[["date", "close"]].copy()
    spy["date"] = pd.to_datetime(spy["date"])
    spy["ma200"] = spy["close"].rolling(200, min_periods=200).mean()
    spy["regime"] = np.where(spy["close"] > spy["ma200"], "Bull", "Bear")
    spy.loc[spy["ma200"].isna(), "regime"] = None
    spy["regime"] = spy["regime"].shift(1)
    calendar, oos = [], []
    benchmark_returns = {
        "spy": _returns(spy_result).set_index("date")["return"],
        "equal_weight": _returns(equal_weight).set_index("date")["return"],
    }
    for name, result in results.items():
        daily = _returns(result).merge(spy[["date", "regime"]], on="date", how="left")
        for year, group in daily.dropna(subset=["return"]).groupby(daily["date"].dt.year):
            calendar.append({"Strategy": name, "Year": int(year), "Return %": ((1 + group["return"]).prod() - 1) * 100,
                             "Sessions": len(group)})
        for regime, group in daily.dropna(subset=["return", "regime"]).groupby("regime"):
            calendar.append({"Strategy": name, "Year": str(regime), "Return %": ((1 + group["return"]).prod() - 1) * 100,
                             "Sessions": len(group)})
        split = int(len(daily) * 0.7)
        group = daily.iloc[split:].dropna(subset=["return"])
        ret = ((1 + group["return"]).prod() - 1) * 100
        spy_ret = ((1 + benchmark_returns["spy"].reindex(group["date"]).dropna()).prod() - 1) * 100
        ew_ret = ((1 + benchmark_returns["equal_weight"].reindex(group["date"]).dropna()).prod() - 1) * 100
        vol = group["return"].std(ddof=0)
        oos.append({"Strategy": name, "Start": group["date"].min().date().isoformat(),
                    "End": group["date"].max().date().isoformat(), "Return %": ret,
                    "Sharpe": group["return"].mean() / vol * np.sqrt(252) if vol > 0 else 0,
                    "Alpha vs SPY %": ret - spy_ret, "Alpha vs Equal Weight %": ret - ew_ret,
                    "Sessions": len(group)})
    return pd.DataFrame(calendar), pd.DataFrame(oos)


def main() -> None:
    prices = {symbol: get_long_history_stock_data(symbol, period=PERIOD) for symbol in UNIVERSE}
    spy_df = get_long_history_stock_data("SPY", period=PERIOD)
    missing = [symbol for symbol, frame in prices.items() if frame.empty]
    if missing or spy_df.empty:
        raise RuntimeError(f"Missing price data: stocks={missing}, SPY={spy_df.empty}")
    common = set(pd.to_datetime(spy_df["date"]))
    for frame in prices.values():
        common &= set(pd.to_datetime(frame["date"]))
    dates = sorted(common)
    prices = {s: f[pd.to_datetime(f["date"]).isin(dates)].copy() for s, f in prices.items()}
    spy_df = spy_df[pd.to_datetime(spy_df["date"]).isin(dates)].copy()

    results = {}
    for name, (builder, max_days) in PRICE_STRATEGIES.items():
        prepared = {symbol: builder(frame) for symbol, frame in prices.items()}
        results[name] = run_signal_portfolio(prepared, name, CONFIG, max_positions=2, max_holding_days=max_days)
    results["Cross-Sectional Momentum"] = cross_sectional_momentum_backtest(prices, spy_df, CONFIG)
    equal_weight = equal_weight_buy_and_hold(prices, CONFIG)
    spy = run_buy_and_hold(spy_df, "SPY", CONFIG)

    summaries = pd.DataFrame([_summary(result, spy, equal_weight) for result in results.values()])
    calendar, oos = _period_rows(results, spy_df, spy, equal_weight)
    out = ROOT / "artifacts" / "candidate_strategy_comparison"
    out.mkdir(parents=True, exist_ok=True)
    summaries.to_csv(out / "comparison.csv", index=False, float_format="%.6f")
    calendar.to_csv(out / "calendar_and_regime.csv", index=False, float_format="%.6f")
    oos.to_csv(out / "chronological_oos.csv", index=False, float_format="%.6f")
    for name, result in results.items():
        safe = name.lower().replace(" ", "_").replace("-", "_")
        pd.DataFrame(result["trades"]).to_csv(out / f"trades_{safe}.csv", index=False)
    data_audit = {"provider": "yfinance adjusted OHLC", "requested_period": PERIOD,
                  "common_start": pd.Timestamp(dates[0]).date().isoformat(), "common_end": pd.Timestamp(dates[-1]).date().isoformat(),
                  "common_sessions": len(dates), "universe": UNIVERSE, "survivorship_bias": True,
                  "pead": pead_availability(None)}
    (out / "data_audit.json").write_text(json.dumps(data_audit, indent=2), encoding="utf-8")
    ranking = summaries.merge(oos[["Strategy", "Return %", "Sharpe"]].rename(
        columns={"Return %": "OOS Return %", "Sharpe": "OOS Sharpe"}), on="Strategy")
    ranking["Risk/OOS Rank"] = ranking[["Sharpe", "OOS Sharpe"]].rank(ascending=False).mean(axis=1)
    ranking.sort_values("Risk/OOS Rank").to_csv(out / "ranking.csv", index=False, float_format="%.6f")
    print(summaries.to_string(index=False))
    print("\nChronological OOS\n", oos.to_string(index=False))
    print(f"\nArtifacts: {out}")


if __name__ == "__main__":
    main()
