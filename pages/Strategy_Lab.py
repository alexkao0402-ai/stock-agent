"""Streamlit Strategy Lab: Stock × Strategy × Time comparison."""
import pandas as pd
import streamlit as st

from src.backtest_engine import BacktestConfig
from src.stock_data import get_long_history_stock_data
from src.strategy_lab import build_strategy_stock_matrix, research_verdict, strategy_summary

LARGE_CAP_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(initial_capital=10_000, transaction_cost_pct=0.001, slippage_pct=0.0005)

st.set_page_config(
    page_title="Strategy Lab",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="auto",
)
st.markdown(
    """
    <style>
    div[data-testid="stDataFrame"] {max-width: 100%; overflow-x: auto;}
    @media (max-width: 720px) {
      .block-container {padding-left: .75rem; padding-right: .75rem;}
      div[data-testid="stMetric"] {min-width: 0;}
      div[data-testid="stMetricValue"] {font-size: 1.3rem; overflow-wrap: anywhere;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("Strategy Lab")
st.caption("Which strategy works, for which stock, and does it actually beat simply holding that same stock?")
st.warning("Fixed present-day large-cap universe. Historical comparisons contain survivorship bias. Research use only.")

@st.cache_data(ttl=3600, show_spinner=False)
def load_lab_data():
    spy = get_long_history_stock_data("SPY", period="5y")
    universe = {ticker: get_long_history_stock_data(ticker, period="5y") for ticker in LARGE_CAP_UNIVERSE}
    return universe, spy

with st.spinner("Running fixed-rule backtests across the large-cap universe…"):
    universe_prices, spy_df = load_lab_data()
    if spy_df.empty or not any(not frame.empty for frame in universe_prices.values()):
        matrix = pd.DataFrame()
    else:
        try:
            matrix = build_strategy_stock_matrix(universe_prices, spy_df, CONFIG)
        except (KeyError, ValueError, IndexError):
            matrix = pd.DataFrame()

if matrix.empty:
    st.error("No research matrix could be produced. Check historical price data availability.")
    st.stop()

summary = research_verdict(strategy_summary(matrix))

st.subheader("1 · Strategy × Stock Matrix")
criterion = st.selectbox(
    "Comparison metric",
    ["Alpha vs B&H %", "Alpha vs SPY %", "Total Return %", "Sharpe", "Max Drawdown %", "OOS Alpha vs B&H %"],
    index=0,
)
pivot = matrix.pivot(index="Stock", columns="Strategy", values=criterion).reindex(LARGE_CAP_UNIVERSE)
st.dataframe(pivot.round(2), width="stretch")
st.caption("Positive Alpha vs B&H means the strategy beat buying and holding the same stock over the tested period. This is stricter than merely beating SPY.")

st.subheader("2 · Strategy View")
strategy = st.selectbox("Choose strategy", sorted(matrix["Strategy"].unique()), key="strategy_view")
strategy_rows = matrix[matrix["Strategy"] == strategy].copy().sort_values("Alpha vs B&H %", ascending=False)
st.dataframe(
    strategy_rows[["Stock", "Total Return %", "Stock B&H %", "Alpha vs B&H %", "Alpha vs SPY %", "Sharpe", "Max Drawdown %", "OOS Alpha vs B&H %"]].round(2),
    width="stretch",
    hide_index=True,
)
strategy_summary_row = summary[summary["Strategy"] == strategy]
if not strategy_summary_row.empty:
    row = strategy_summary_row.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Beat B&H", f"{int(row['Beat B&H'])}/{int(row['Stocks Tested'])}")
    c2.metric("Median Alpha vs B&H", f"{row['Median Alpha vs B&H %']:.2f}%")
    c3.metric("Median OOS Alpha", "—" if pd.isna(row["Median OOS Alpha vs B&H %"]) else f"{row['Median OOS Alpha vs B&H %']:.2f}%")
    c4.metric("Research verdict", row["Research Verdict"])

st.subheader("3 · Stock View")
stock = st.selectbox("Choose stock", LARGE_CAP_UNIVERSE, key="stock_view")
stock_rows = matrix[matrix["Stock"] == stock].copy().sort_values("Alpha vs B&H %", ascending=False)
st.dataframe(
    stock_rows[["Strategy", "Total Return %", "Stock B&H %", "Alpha vs B&H %", "Alpha vs SPY %", "Sharpe", "Max Drawdown %", "OOS Return %", "OOS Alpha vs B&H %"]].round(2),
    width="stretch",
    hide_index=True,
)
if not stock_rows.empty:
    best = stock_rows.iloc[0]
    if best["Alpha vs B&H %"] <= 0:
        st.error(f"NONE: Neither tested single-stock strategy beat Buy & Hold for {stock} over the full test period.")
    else:
        st.success(f"Best tested full-history strategy for {stock}: {best['Strategy']} ({best['Alpha vs B&H %']:+.2f}% vs B&H).")

st.subheader("4 · Past vs Recent / Out-of-Sample")
st.caption("Rules are fixed. The recent chronological holdout is used as a stability check; it is not a random split and not parameter optimization.")
time_table = matrix[["Stock", "Strategy", "Alpha vs B&H %", "OOS Alpha vs B&H %"]].copy()
time_table["Direction Stable?"] = (
    (time_table["Alpha vs B&H %"] > 0) == (time_table["OOS Alpha vs B&H %"] > 0)
)
st.dataframe(time_table.round(2), width="stretch", hide_index=True)

st.subheader("Research Scorecard")
st.dataframe(summary.round(2), width="stretch", hide_index=True)
st.caption("KEEP is intentionally conservative: positive median alpha vs same-stock B&H, >50% of stocks beating B&H, and positive median OOS alpha. MORE EVIDENCE and KILL are research labels, not trading advice.")
