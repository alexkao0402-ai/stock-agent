"""Capture all fixed-universe signals after the US market close."""

from __future__ import annotations

from src.backtest_engine import BacktestConfig, run_backtest
from src.cross_sectional import latest_cross_sectional_ranking
from src.signal_snapshot import save_daily_signal_snapshot
from src.stock_data import get_long_history_stock_data
from src.strategies import mean_reversion_signals, momentum_relative_strength_signals
from src.strategy_validation import current_signal


UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(initial_capital=10_000, transaction_cost_pct=0.001, slippage_pct=0.0005)


def capture() -> str:
    spy = get_long_history_stock_data("SPY", period="5y")
    prices = {ticker: get_long_history_stock_data(ticker, period="5y") for ticker in UNIVERSE}
    if spy.empty or any(frame.empty for frame in prices.values()):
        raise RuntimeError("Daily snapshot aborted because one or more required price series are unavailable.")

    ranking = latest_cross_sectional_ranking(prices, spy)
    rank_lookup = ranking.set_index("symbol").to_dict("index") if not ranking.empty else {}
    as_of_date = min(frame["date"].max() for frame in [spy, *prices.values()]).strftime("%Y-%m-%d")
    spy_signals = momentum_relative_strength_signals(prices[UNIVERSE[0]], spy, max_holding_days=20)
    favorable = bool(spy_signals.iloc[-1]["benchmark_close"] > spy_signals.iloc[-1]["spy_ma200"])
    rows = []

    for ticker, frame in prices.items():
        prepared = {
            "Pullback Mean Reversion": mean_reversion_signals(frame, max_holding_days=10),
            "Short-Term Momentum": momentum_relative_strength_signals(frame, spy, max_holding_days=20),
        }
        for name, prepared_frame in prepared.items():
            result = run_backtest(prepared_frame, ticker, name, CONFIG)
            rows.append({"ticker": ticker, **current_signal(name, prepared_frame, result)})

        ranked = rank_lookup.get(ticker)
        if ranked:
            rows.append({
                "ticker": ticker,
                "strategy": "Cross-Sectional Momentum",
                "signal": "BUY" if bool(ranked["selected"]) else "WAIT",
                "reason": f"20D return ranked #{int(ranked['rank'])} of {len(ranking)}",
                "rank": int(ranked["rank"]),
            })

    path = save_daily_signal_snapshot(
        as_of_date,
        rows,
        "Favorable" if favorable else "Unfavorable",
    )
    return str(path)


if __name__ == "__main__":
    print(capture())
