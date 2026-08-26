# app.py — UI V2
# 簡潔、高級感、少分頁版本

import time
import pandas as pd
import streamlit as st

from src.stock_data import (
    get_daily_stock_data,
    clean_stock_data,
    get_news_sentiment,
    get_company_overview,
    get_long_history_stock_data,
    get_crypto_daily_data,
    clean_crypto_data,
)
from src.ai_analysis import generate_report, extract_structured_data
from src.prediction_tracker import save_prediction, list_predictions, check_prediction_outcome
from src.strategy_v1 import (
    add_trend_filter,
    add_momentum,
    add_relative_strength,
    add_entry_exit_signals,
    run_backtest_v1,
    run_backtest_v1_with_equity_curve,
    run_backtest_v1_with_takeprofit_v2,
    run_backtest_v1_with_trailing_exit,
    calculate_buy_and_hold,
    calculate_performance_metrics,
    calculate_risk_metrics,
    build_comparison_row,
    build_trade_diagnostics,
)
from src.regime_analysis import build_regime_series


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="AI Stock Research",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# LIGHT UI POLISH — 不改功能，只讓介面更乾淨
# ============================================================

st.markdown(
    """
    <style>
        .block-container {
            max-width: 1380px;
            padding-top: 2.2rem;
            padding-bottom: 4rem;
        }

        [data-testid="stMetric"] {
            background: rgba(255,255,255,0.025);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
            padding: 14px 16px;
        }

        [data-testid="stMetricLabel"] {
            opacity: 0.72;
        }

        div[data-testid="stTabs"] button {
            font-size: 0.98rem;
        }

        .section-title {
            font-size: 1.35rem;
            font-weight: 650;
            margin-top: 0.5rem;
            margin-bottom: 0.25rem;
        }

        .muted {
            color: rgba(255,255,255,0.58);
            font-size: 0.9rem;
        }

        .hero-symbol {
            font-size: 2.25rem;
            font-weight: 750;
            letter-spacing: -0.04em;
            margin-bottom: 0;
        }

        .hero-company {
            color: rgba(255,255,255,0.60);
            margin-top: -0.25rem;
        }

        .disclaimer {
            color: rgba(255,255,255,0.42);
            font-size: 0.78rem;
            margin-top: 1.5rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# HEADER
# ============================================================

st.markdown('<div class="hero-symbol">AI Stock Research</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-company">Systematic research · AI analysis · quantitative backtesting</div>',
    unsafe_allow_html=True,
)
st.markdown("")


# ============================================================
# SEARCH
# ============================================================

with st.container(border=True):
    c1, c2 = st.columns([5, 1])
    with c1:
        symbol_input = st.text_input(
            "Ticker",
            placeholder="Enter a ticker, e.g. NVDA",
            label_visibility="collapsed",
        )
    with c2:
        analyze_clicked = st.button(
            "Analyze",
            use_container_width=True,
            type="primary",
        )


# ============================================================
# ANALYSIS FLOW
# ============================================================

if analyze_clicked:
    if not symbol_input.strip():
        st.warning("請先輸入股票代號。")
        st.stop()

    symbol = symbol_input.strip().upper()

    with st.spinner(f"Loading {symbol} price data..."):
        raw_data = get_daily_stock_data(symbol)

    if "Time Series (Daily)" not in raw_data:
        st.error("抓取股價資料失敗，請確認股票代號是否正確，或稍後再試。")
        st.stop()

    df = clean_stock_data(raw_data)

    with st.spinner("Loading related news..."):
        time.sleep(15)
        news_list = get_news_sentiment(symbol, limit=20)

    with st.spinner("Loading company fundamentals..."):
        time.sleep(15)
        overview = get_company_overview(symbol)

    current_price = df["close"].iloc[-1]

    with st.spinner("AI is analyzing the company..."):
        report = generate_report(symbol, df, news_list, overview)

    with st.spinner("Structuring the analysis..."):
        structured = extract_structured_data(symbol, current_price, report)

    saved_path = save_prediction(symbol, current_price, structured, report)

    # ========================================================
    # COMPANY HERO
    # ========================================================

    company_name = overview.get("公司名稱", symbol) if overview else symbol
    industry = overview.get("產業別", "") if overview else ""

    st.markdown("---")

    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown(f'<div class="hero-symbol">{symbol}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="hero-company">{company_name} · {industry}</div>', unsafe_allow_html=True)
    with h2:
        st.metric("Latest Close", f"${current_price:,.2f}")

    # ========================================================
    # KPI STRIP
    # ========================================================

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Market Cap", overview.get("市值", "N/A") if overview else "N/A")
    k2.metric("P / E", overview.get("本益比", "N/A") if overview else "N/A")
    k3.metric("EPS", overview.get("每股盈餘", "N/A") if overview else "N/A")
    k4.metric("52W High", overview.get("52週最高價", "N/A") if overview else "N/A")
    k5.metric("52W Low", overview.get("52週最低價", "N/A") if overview else "N/A")

    st.caption(
        f"Data: {len(df):,} price records · {len(news_list):,} news items · "
        f"Saved prediction: {saved_path}"
    )

    # ========================================================
    # ONLY 3 MAIN AREAS
    # ========================================================

    tab_overview, tab_strategy, tab_research = st.tabs(
        ["Overview", "Quant Strategy", "Research & Data"]
    )

    # ========================================================
    # TAB 1 — OVERVIEW
    # ========================================================

    with tab_overview:
        left, right = st.columns([1.55, 1])

        with left:
            st.markdown('<div class="section-title">Price & AI View</div>', unsafe_allow_html=True)
            chart_data = df.set_index("date")[["close"]]
            st.line_chart(chart_data, height=360)

            with st.container(border=True):
                st.markdown("#### AI Research Report")
                st.markdown(report)

        with right:
            st.markdown('<div class="section-title">Recent News</div>', unsafe_allow_html=True)
            st.caption("Showing the latest 5 items")

            if news_list:
                for n in news_list[:5]:
                    with st.container(border=True):
                        st.markdown(f"**{n['title']}**")
                        st.caption(
                            f"{n['time_published']} · {n['source']} · "
                            f"{n['overall_sentiment_label']}"
                        )
            else:
                st.info("目前沒有新聞資料。")

            with st.expander("View all news"):
                for n in news_list:
                    st.markdown(f"**{n['title']}**")
                    st.caption(
                        f"{n['time_published']} · {n['source']} · "
                        f"{n['overall_sentiment_label']}"
                    )

    # ========================================================
    # TAB 2 — QUANT STRATEGY
    # ========================================================

    with tab_strategy:
        st.markdown('<div class="section-title">Strategy V1</div>', unsafe_allow_html=True)
        st.caption(
            "MA200 trend filter + 6-month momentum + relative strength vs BTC. "
            "Signals execute at the next day's open."
        )

        with st.spinner("Running quantitative backtest..."):
            v1_stock_df = get_long_history_stock_data(symbol, period="2y")

        if v1_stock_df.empty or len(v1_stock_df) < 200:
            st.warning("歷史資料不足 200 天，無法計算 MA200。")
        else:
            crypto_df = clean_crypto_data(get_crypto_daily_data("BTC", "USD"))

            v1_stock_df = add_trend_filter(v1_stock_df)
            v1_stock_df = add_momentum(v1_stock_df)
            v1_stock_df = add_relative_strength(v1_stock_df, crypto_df)
            v1_stock_df = add_entry_exit_signals(v1_stock_df)

            v1_result = run_backtest_v1(v1_stock_df)
            bh_result = calculate_buy_and_hold(v1_stock_df)
            v1_metrics = calculate_performance_metrics(
                v1_result["trades"],
                v1_result["initial_capital"],
                v1_result["final_value"],
                v1_stock_df,
            )

            # ------------------------
            # Performance cards
            # ------------------------
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Strategy Return", f"{v1_result['total_return_pct']}%")
            p2.metric("Buy & Hold", f"{bh_result['total_return_pct']}%")
            p3.metric("CAGR", f"{v1_metrics['cagr_pct']}%")
            p4.metric("Win Rate", f"{v1_metrics['win_rate_pct']}%")

            # ------------------------
            # Main chart
            # ------------------------
            chart_df = v1_stock_df.set_index("date")[["close", "ma200"]]
            st.line_chart(chart_df, height=420)

            # ------------------------
            # Signals / diagnostics
            # ------------------------
            with st.expander("Trade signals & diagnostics"):
                signal_points = v1_stock_df[
                    v1_stock_df["signal"].notna()
                ][["date", "close", "signal", "execution_price"]]

                if len(signal_points) > 0:
                    st.dataframe(signal_points, use_container_width=True, hide_index=True)
                else:
                    st.info("這段期間沒有觸發訊號。")

                if v1_metrics["completed_trades"]:
                    diagnostics = build_trade_diagnostics(
                        v1_stock_df,
                        v1_metrics["completed_trades"],
                    )
                    diag_df = pd.DataFrame(diagnostics)
                    st.dataframe(diag_df, use_container_width=True, hide_index=True)

            # ------------------------
            # Strategy versions
            # ------------------------
            st.markdown('<div class="section-title">Strategy Versions</div>', unsafe_allow_html=True)
            st.caption("V1 vs fixed take-profit vs trailing exit vs Buy & Hold")

            with st.spinner("Comparing strategy versions..."):
                v1_eq_result = run_backtest_v1_with_equity_curve(v1_stock_df)
                v1_eq_risk = calculate_risk_metrics(v1_eq_result["equity_curve"])
                v1_eq_perf = calculate_performance_metrics(
                    v1_eq_result["trades"],
                    v1_eq_result["initial_capital"],
                    v1_eq_result["final_value"],
                    v1_stock_df,
                )
                row_v1 = build_comparison_row(
                    symbol, "V1", v1_eq_result, v1_eq_risk, v1_eq_perf
                )

                tp_result = run_backtest_v1_with_takeprofit_v2(
                    v1_stock_df,
                    take_profit_pct=25.0,
                )
                tp_perf = calculate_performance_metrics(
                    tp_result["trades"],
                    tp_result["initial_capital"],
                    tp_result["final_value"],
                    v1_stock_df,
                )
                row_tp = build_comparison_row(
                    symbol, "V1+TakeProfit25", tp_result, None, tp_perf
                )

                trail_result = run_backtest_v1_with_trailing_exit(
                    v1_stock_df,
                    trailing_pct=20.0,
                )
                trail_perf = calculate_performance_metrics(
                    trail_result["trades"],
                    trail_result["initial_capital"],
                    trail_result["final_value"],
                    v1_stock_df,
                )
                row_trail = build_comparison_row(
                    symbol, "V1+Trailing20", trail_result, None, trail_perf
                )

                row_bh = build_comparison_row(
                    symbol, "Buy&Hold", bh_result, None, None
                )

            comparison_df = pd.DataFrame(
                [row_v1, row_tp, row_trail, row_bh]
            )

            def color_return(val):
                if pd.isna(val):
                    return ""
                color = "#00D9A0" if val > 0 else "#FF4B4B"
                return f"color: {color}; font-weight: bold"

            styled_df = comparison_df.style.map(
                color_return,
                subset=["Return_pct", "CAGR_pct"],
            )
            st.dataframe(styled_df, use_container_width=True, hide_index=True)

            # ------------------------
            # Market regime
            # ------------------------
            with st.expander("Market regime"):
                st.caption(
                    "SPY + BTC 200-day trend → Risk-On / Risk-Off / Mixed"
                )
                with st.spinner("Analyzing market regime..."):
                    regime_df = build_regime_series(period="2y")

                regime_counts = regime_df["regime"].value_counts()
                r1, r2, r3 = st.columns(3)
                r1.metric("Risk-On", regime_counts.get("Risk-On", 0))
                r2.metric("Risk-Off", regime_counts.get("Risk-Off", 0))
                r3.metric("Mixed", regime_counts.get("Mixed", 0))

            st.caption(
                "⚠️ 回測僅供研究用途。過去績效不代表未來績效。"
            )

    # ========================================================
    # TAB 3 — RESEARCH & DATA
    # ========================================================

    with tab_research:
        left, right = st.columns(2)

        with left:
            with st.expander("Company fundamentals", expanded=True):
                if overview:
                    for key, value in overview.items():
                        if key == "公司簡介":
                            st.markdown(f"**{key}**")
                            st.write(value)
                        else:
                            st.markdown(f"**{key}**：{value}")
                else:
                    st.write("未取得公司基本面資料。")

        with right:
            with st.expander("Structured AI data", expanded=True):
                if structured:
                    st.json(structured)
                else:
                    st.warning("未能解析結構化數據。")

        with st.expander("Raw price data"):
            st.dataframe(
                df.sort_values("date", ascending=False),
                use_container_width=True,
                hide_index=True,
            )

        # ----------------------------------------------------
        # Historical predictions
        # ----------------------------------------------------
        st.markdown('<div class="section-title">Prediction History</div>', unsafe_allow_html=True)
        st.caption("查看過去 AI 預測，並在之後驗證結果。")

        all_predictions = list_predictions()

        if not all_predictions:
            st.info("目前還沒有任何預測紀錄。")
        else:
            options = [
                f"{r['ticker']} — {r['timestamp']}"
                for r in all_predictions
            ]
            selected_index = st.selectbox(
                "Prediction",
                range(len(options)),
                format_func=lambda i: options[i],
                label_visibility="collapsed",
            )

            selected_record = all_predictions[selected_index]

            a1, a2, a3, a4 = st.columns(4)
            a1.metric(
                "Price at Prediction",
                f"${selected_record.get('current_price_at_prediction', 'N/A')}"
            )
            a2.metric(
                "Bull",
                f"{selected_record.get('bull_low', 'N/A')} ~ {selected_record.get('bull_high', 'N/A')}"
            )
            a3.metric(
                "Base",
                f"{selected_record.get('base_low', 'N/A')} ~ {selected_record.get('base_high', 'N/A')}"
            )
            a4.metric(
                "Bear",
                f"{selected_record.get('bear_low', 'N/A')} ~ {selected_record.get('bear_high', 'N/A')}"
            )

            if selected_record.get("outcome_checked"):
                st.success("這筆預測已經驗證過結果")
                st.write(
                    f"驗證時間：{selected_record.get('checked_at')} · "
                    f"實際報酬率：{selected_record.get('actual_return_pct')}% · "
                    f"情境：{selected_record.get('which_scenario_occurred')}"
                )
            else:
                st.info("這筆預測尚未驗證結果")
                if st.button("Verify current price", type="secondary"):
                    with st.spinner("Checking latest price..."):
                        raw = get_daily_stock_data(selected_record["ticker"])
                        if "Time Series (Daily)" in raw:
                            latest_df = clean_stock_data(raw)
                            actual_price = latest_df["close"].iloc[-1]
                            updated = check_prediction_outcome(
                                selected_record,
                                actual_price,
                            )
                            st.success(
                                f"驗證完成：${actual_price} · "
                                f"{updated['which_scenario_occurred']}"
                            )
                            st.rerun()
                        else:
                            st.error("查詢目前股價失敗，請稍後再試。")

    st.markdown(
        '<div class="disclaimer">For education and research only. Not financial advice.</div>',
        unsafe_allow_html=True,
    )
