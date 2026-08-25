"""Streamlit interface for AI-assisted large-cap equity research."""

import time

import pandas as pd
import streamlit as st

from src.ai_analysis import extract_structured_data, generate_report
from src.backtest_engine import BacktestConfig, run_backtest, run_buy_and_hold
from src.performance import calculate_metrics
from src.prediction_tracker import check_prediction_outcome, list_predictions, save_prediction
from src.regime_analysis import build_regime_series
from src.stock_data import (
    clean_stock_data,
    get_company_overview,
    get_daily_stock_data,
    get_long_history_stock_data,
    get_news_sentiment,
)
from src.strategies import (
    mean_reversion_signals,
    momentum_relative_strength_signals,
    trend_following_signals,
)


LARGE_CAP_UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(commission_rate=0.001, slippage_rate=0.0005)


st.set_page_config(page_title="AI Stock Research", page_icon="📈", layout="wide")
st.title("AI Stock Research")
st.caption("AI analysis · news · fundamentals · unbiased large-cap strategy comparison")

symbol = st.text_input("Ticker", value="AAPL").strip().upper()
analyze_clicked = st.button("Analyze", type="primary")
analysis_payload = st.session_state.get("analysis_payload")

if analyze_clicked:
    if not symbol:
        st.warning("Please enter a ticker.")
        st.stop()

    raw_data = get_daily_stock_data(symbol)
    if "Time Series (Daily)" not in raw_data:
        st.error("Price data could not be loaded. Check the ticker or API status.")
        st.stop()
    short_df = clean_stock_data(raw_data)

    with st.spinner("Loading news and fundamentals..."):
        news = get_news_sentiment(symbol, limit=20)
        time.sleep(15)
        overview = get_company_overview(symbol)

    current_price = float(short_df["close"].iloc[-1])
    with st.spinner("Generating AI research report..."):
        report = generate_report(symbol, short_df, news, overview)
        structured = extract_structured_data(symbol, current_price, report)
    saved_path = save_prediction(symbol, current_price, structured, report)

    analysis_payload = {
        "symbol": symbol,
        "short_df": short_df,
        "news": news,
        "overview": overview,
        "current_price": current_price,
        "report": report,
        "structured": structured,
        "saved_path": saved_path,
    }
    st.session_state["analysis_payload"] = analysis_payload

if analysis_payload:
    symbol = analysis_payload["symbol"]
    short_df = analysis_payload["short_df"]
    news = analysis_payload["news"]
    overview = analysis_payload["overview"]
    current_price = analysis_payload["current_price"]
    report = analysis_payload["report"]
    structured = analysis_payload["structured"]
    saved_path = analysis_payload["saved_path"]

    st.header(f"{symbol} · {overview.get('公司名稱', symbol) if overview else symbol}")
    st.metric("Latest close", f"${current_price:,.2f}")
    tab_overview, tab_strategy, tab_data = st.tabs(["Overview", "Large-Cap Strategy Research", "Research & Data"])

    with tab_overview:
        st.line_chart(short_df.set_index("date")[["close"]], height=340)
        st.subheader("AI Research Report")
        st.markdown(report)
        st.subheader("Recent News")
        for item in news[:5]:
            st.markdown(f"**{item['title']}**")
            st.caption(f"{item['time_published']} · {item['source']} · {item['overall_sentiment_label']}")

    with tab_strategy:
        st.subheader("Large-Cap Strategy Research")
        st.caption(
            "Fixed current large-cap universe for research purposes. This creates survivorship bias. "
            "All signals use Day T close and execute at Day T+1 open. Costs: 0.1% commission and 0.05% slippage."
        )
        if symbol not in LARGE_CAP_UNIVERSE:
            st.info("Manual tickers are supported, but the fixed research universe is: " + ", ".join(LARGE_CAP_UNIVERSE))

        stock_df = get_long_history_stock_data(symbol, period="5y")
        spy_df = get_long_history_stock_data("SPY", period="5y")
        if stock_df.empty or spy_df.empty or len(stock_df) < 201:
            st.warning("At least 201 trading days of stock and SPY data are required.")
        else:
            prepared = {
                "Trend Following": trend_following_signals(stock_df),
                "Momentum + Relative Strength": momentum_relative_strength_signals(stock_df, spy_df),
                "Mean Reversion": mean_reversion_signals(stock_df, max_holding_days=20),
            }
            results = []
            for name, frame in prepared.items():
                results.append(run_backtest(frame, symbol, name, CONFIG))
            results.append(run_buy_and_hold(stock_df, symbol, CONFIG))
            comparison = pd.DataFrame([calculate_metrics(result) for result in results])
            st.dataframe(comparison.round(2), use_container_width=True, hide_index=True)

            selected = st.selectbox("Chart strategy", list(prepared))
            chart_columns = ["close", "ma200"]
            if selected == "Trend Following":
                chart_columns.append("ma50")
            elif selected == "Mean Reversion":
                chart_columns.extend(["ma20", "rsi14"])
            chart = prepared[selected].set_index("date")[chart_columns]
            st.line_chart(chart, height=400)

            regime = build_regime_series(period="5y")
            latest_regime = regime.dropna(subset=["regime"]).iloc[-1]
            st.caption(f"Current SPY regime: {latest_regime['regime']} (SPY close vs SPY MA200)")

    with tab_data:
        left, right = st.columns(2)
        with left:
            st.subheader("Company Fundamentals")
            st.json(overview or {})
        with right:
            st.subheader("Structured AI Data")
            st.json(structured or {})
        st.caption(f"Prediction saved: {saved_path}")
        st.dataframe(short_df.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

        st.subheader("Prediction History")
        predictions = list_predictions()
        if predictions:
            index = st.selectbox(
                "Prediction",
                range(len(predictions)),
                format_func=lambda i: f"{predictions[i]['ticker']} — {predictions[i]['timestamp']}",
            )
            record = predictions[index]
            st.json(record)
            if not record.get("outcome_checked") and st.button("Verify current price"):
                latest_raw = get_daily_stock_data(record["ticker"])
                if "Time Series (Daily)" in latest_raw:
                    latest_price = float(clean_stock_data(latest_raw)["close"].iloc[-1])
                    check_prediction_outcome(record, latest_price)
                    st.success("Prediction outcome updated.")
                    st.rerun()
        else:
            st.info("No saved predictions yet.")

st.caption("For education and research only. Historical results do not guarantee future performance.")
