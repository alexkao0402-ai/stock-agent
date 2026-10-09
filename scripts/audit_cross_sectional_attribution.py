"""Verify that stock-level P&L attribution reconciles to portfolio equity."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest_engine import BacktestConfig
from src.cross_sectional import cross_sectional_momentum_backtest
from src.cross_sectional_analytics import stock_contribution
from src.stock_data import get_long_history_stock_data


UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]


def main() -> None:
    prices = {symbol: get_long_history_stock_data(symbol, "5y") for symbol in UNIVERSE}
    spy = get_long_history_stock_data("SPY", "5y")
    result = cross_sectional_momentum_backtest(prices, spy, BacktestConfig())
    contribution = stock_contribution(result, prices)
    final_gain = result["final_value"] - result["initial_capital"]
    attributed = contribution["Total Contribution"].sum()
    difference = final_gain - attributed
    print(f"final_gain={final_gain:.6f}")
    print(f"attributed={attributed:.6f}")
    print(f"difference={difference:.9f}")
    if abs(difference) > 0.01:
        raise SystemExit("P&L attribution does not reconcile")


if __name__ == "__main__":
    main()
