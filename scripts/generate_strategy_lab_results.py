"""Generate the reproducible Strategy Lab regime research artifacts."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest_engine import BacktestConfig
from src.stock_data import get_long_history_stock_data
from src.strategy_lab import build_cross_sectional_regime_matrix, build_regime_matrix


UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(initial_capital=10_000, transaction_cost_pct=0.001, slippage_pct=0.0005)


def markdown_table(frame) -> str:
    values = frame.fillna("—").astype(str)
    header = "| " + " | ".join(values.columns) + " |"
    divider = "| " + " | ".join(["---"] * len(values.columns)) + " |"
    rows = ["| " + " | ".join(row) + " |" for row in values.itertuples(index=False, name=None)]
    return "\n".join([header, divider, *rows])


def main() -> None:
    spy = get_long_history_stock_data("SPY", period="5y")
    prices = {symbol: get_long_history_stock_data(symbol, period="5y") for symbol in UNIVERSE}
    missing = [symbol for symbol, frame in prices.items() if frame.empty]
    if spy.empty or missing:
        raise RuntimeError(f"Missing market data: SPY={spy.empty}, stocks={missing}")

    results = build_regime_matrix(prices, spy, CONFIG)
    portfolio_results = build_cross_sectional_regime_matrix(prices, spy, CONFIG)
    output_dir = Path("docs")
    output_dir.mkdir(exist_ok=True)
    results.to_csv(output_dir / "STRATEGY_LAB_RESULTS.csv", index=False, float_format="%.6f")
    portfolio_results.to_csv(output_dir / "STRATEGY_LAB_PORTFOLIO_RESULTS.csv", index=False, float_format="%.6f")

    recent = results[results["Time Period"] == "Recent OOS"]
    summary = (
        recent.groupby(["Strategy", "Market Regime"], as_index=False)
        .agg(
            Stocks=("Stock", "nunique"),
            Median_Alpha_vs_BH=("Alpha vs B&H %", "median"),
            Median_Alpha_vs_SPY=("Alpha vs SPY %", "median"),
            Median_Sharpe=("Sharpe", "median"),
            Median_MDD=("Max Drawdown %", "median"),
            Total_Trades=("Trades", "sum"),
            Median_Sample=("Sample Size", "median"),
        )
    )
    winners = recent.sort_values("Alpha vs B&H %", ascending=False).groupby(
        ["Market Regime", "Stock"], as_index=False
    ).first()
    as_of = results["End"].max()
    markdown = [
        "# Strategy Lab Results\n",
        f"Data through: **{as_of}**  \n",
        "Universe: AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, V, WMT.  \n",
        "Regime: Bull when SPY close > trailing SPY MA200; Bear otherwise. ",
        "Signals use close information and execute at the next open. Costs: 0.10% commission + 0.05% slippage.\n",
        "## Recent chronological OOS summary\n",
        markdown_table(summary.round(2)),
        "\n\n## Best tested strategy by stock and regime (Recent OOS)\n",
        markdown_table(winners[["Market Regime", "Stock", "Strategy", "Alpha vs B&H %", "Alpha vs SPY %", "Trades", "Sample Size"]].round(2)),
        "\n\n## Cross-Sectional Momentum (portfolio level)\n",
        markdown_table(portfolio_results[["Time Period", "Market Regime", "Return %", "Alpha vs B&H %", "Alpha vs SPY %", "Sharpe", "Sortino", "Max Drawdown %", "Trades", "Exposure %", "Sample Size"]].round(2)),
        "\n\n## Interpretation limits\n",
        "- This is a fixed present-day universe, so survivorship bias remains.\n",
        "- Recent OOS is a chronological holdout, not a separately designed live-forward test.\n",
        "- Sample Size counts regime trading days; Trades counts completed round trips by entry signal regime.\n",
        "- Rows with very few trades cannot support a strong claim even when daily Sample Size is large.\n",
        "- Cross-Sectional Momentum is portfolio-level and is not falsely duplicated into stock-level rows.\n",
    ]
    (output_dir / "STRATEGY_LAB_RESULTS.md").write_text("".join(markdown), encoding="utf-8")


if __name__ == "__main__":
    main()
