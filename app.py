import pandas as pd
import streamlit as st

from src.ai_analysis import extract_structured_data, generate_report
from src.prediction_tracker import check_prediction_outcome, list_predictions, save_prediction
from src.regime_analysis import build_regime_series
from src.stock_data import (
    clean_crypto_data,
    clean_stock_data,
    get_company_overview,
    get_crypto_daily_data,
    get_daily_stock_data,
    get_long_history_stock_data,
    get_news_sentiment,
)
from src.strategy_v1 import (
    add_entry_exit_signals,
    add_momentum,
    add_relative_strength,
    add_trend_filter,
    build_comparison_row,
    build_trade_diagnostics,
    calculate_buy_and_hold,
    calculate_performance_metrics,
    calculate_risk_metrics,
    run_backtest_v1,
    run_backtest_v1_with_equity_curve,
    run_backtest_v1_with_takeprofit_v2,
    run_backtest_v1_with_trailing_exit,
)

st.set_page_config(
    page_title="AI Stock Research",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
        .block-container { max-width: 1380px; padding-top: 2.2rem; padding-bottom: 4rem; }
        [data-testid="stMetric"] {
            background: rgba(255,255,255,0.025);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 14px;
            padding: 14px 16px;
        }
        [data-testid="stMetricLabel"] { opacity: 0.72; }
        div[data-testid="stTabs"] button { font-size: 0.98rem; }
        .section-title { font-size: 1.35rem; font-weight: 650; margin-top: .5rem; margin-bottom: .25rem; }
        .muted { color: rgba(255,255,255,0.58); font-size: .9rem; }
        .hero-symbol { font-size: 2.25rem; font-weight: 750; letter-spacing: -.04em; margin-bottom: 0; }
        .hero-company { color: rgba(255,255,255,0.60); margin-top: -.25rem; }
        .disclaimer { color: rgba(255,255,255,0.42); font-size: .78rem; margin-top: 1.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _fmt(value, prefix="", suffix=""):
    if value is None or value == "None" or value == "":
        return "N/A"
    return f"{prefix}{value}{suffix}"


def _scenario_text(structured, prefix):
    if not structured:
        return "N/A"
    low = structured.get(f"{prefix}_low")
    high = structured.get(f"{prefix}_high")
    if low is None or high is None:
        return "N/A"
    return f"${low} – ${high}"


def _build_quant_result(symbol):
    stock_df = get_long_history_stock_data(symbol, period="2y")
    if stock_df.empty or len(stock_df) < 200:
        return {"error": "歷史資料不足 200 天，無法計算 MA200。"}

    crypto_raw = get_crypto_daily_data("BTC", "USD")
    if "Time Series (Digital Currency Daily)" not in crypto_raw:
        return {"error": "BTC benchmark 資料暫時無法取得。"}

    crypto_df = clean_crypto_data(crypto_raw)
    stock_df = add_trend_filter(stock_df)
    stock_df = add_momentum(stock_df)
    stock_df = add_relative_strength(stock_df, crypto_df)
    stock_df = add_entry_exit_signals(stock_df)

    v1_result = run_backtest_v1(stock_df)
    bh_result = calculate_buy_and_hold(stock_df)
    v1_perf = calculate_performance_metrics(
        v1_result["trades"], v1_result["initial_capital"], v1_result["final_value"], stock_df
    )

    v1_eq = run_backtest_v1_with_equity_curve(stock_df)
    v1_risk = calculate_risk_metrics(v1_eq["equity_curve"])
    v1_eq_perf = calculate_performance_metrics(
        v1_eq["trades"], v1_eq["initial_capital"], v1_eq["final_value"], stock_df
    )

    tp = run_backtest_v1_with_takeprofit_v2(stock_df, take_profit_pct=25.0)
    tp_risk = calculate_risk_metrics(tp["equity_curve"])
    tp_perf = calculate_performance_metrics(
        tp["trades"], tp["initial_capital"], tp["final_value"], stock_df
    )

    trail = run_backtest_v1_with_trailing_exit(stock_df, trailing_pct=20.0)
    trail_risk = calculate_risk_metrics(trail["equity_curve"])
    trail_perf = calculate_performance_metrics(
        trail["trades"], trail["initial_capital"], trail["final_value"], stock_df
    )

    comparison = pd.DataFrame([
        build_comparison_row(symbol, "V1", v1_eq, v1_risk, v1_eq_perf),
        build_comparison_row(symbol, "V1+TakeProfit25", tp, tp_risk, tp_perf),
        build_comparison_row(symbol, "V1+Trailing20", trail, trail_risk, trail_perf),
        build_comparison_row(symbol, "Buy&Hold", bh_result, None, None),
    ])

    latest = stock_df.iloc[-1]
    latest_signal = latest.get("signal") or "hold"

    try:
        regime_df = build_regime_series(period="2y")
        regime_counts = regime_df["regime"].value_counts().to_dict()
        current_regime = regime_df.iloc[-1]["regime"] if not regime_df.empty else "N/A"
    except Exception:
        regime_counts = {}
        current_regime = "N/A"

    return {
        "stock_df": stock_df,
        "v1_result": v1_result,
        "bh_result": bh_result,
        "v1_perf": v1_perf,
        "comparison": comparison,
        "latest_signal": str(latest_signal).upper(),
        "current_regime": current_regime,
        "regime_counts": regime_counts,
    }


def run_analysis(symbol):
    with st.spinner(f"Loading {symbol} market data..."):
        raw_data = get_daily_stock_data(symbol)
    if "Time Series (Daily)" not in raw_data:
        raise ValueError("抓取股價資料失敗，請確認股票代號或 API 狀態。")

    df = clean_stock_data(raw_data)

    with st.spinner("Loading news and fundamentals..."):
        news_list = get_news_sentiment(symbol, limit=20)
        overview = get_company_overview(symbol)

    current_price = float(df["close"].iloc[-1])

    with st.spinner("AI is analyzing the company..."):
        report = generate_report(symbol, df, news_list, overview)
        structured = extract_structured_data(symbol, current_price, report)

    saved_path = save_prediction(symbol, current_price, structured, report)

    with st.spinner("Running quantitative validation..."):
        quant = _build_quant_result(symbol)

    return {
        "symbol": symbol,
        "df": df,
        "news_list": news_list,
        "overview": overview,
        "current_price": current_price,
        "report": report,
        "structured": structured,
        "saved_path": saved_path,
        "quant": quant,
    }


st.markdown('<div class="hero-symbol">AI Stock Research</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-company">Systematic research · AI analysis · quantitative validation</div>',
    unsafe_allow_html=True,
)
st.markdown("")

if "analysis" not in st.session_state:
    st.session_state.analysis = None

with st.container(border=True):
    c1, c2 = st.columns([5, 1])
    with c1:
        default_symbol = st.session_state.analysis["symbol"] if st.session_state.analysis else ""
        symbol_input = st.text_input(
            "Ticker",
            value=default_symbol,
            placeholder="Enter a ticker, e.g. NVDA",
            label_visibility="collapsed",
        )
    with c2:
        analyze_clicked = st.button("Analyze", use_container_width=True, type="primary")

if analyze_clicked:
    if not symbol_input.strip():
        st.warning("請先輸入股票代號。")
    else:
        try:
            st.session_state.analysis = run_analysis(symbol_input.strip().upper())
        except Exception as exc:
            st.error(f"分析失敗：{exc}")

analysis = st.session_state.analysis
if analysis:
    symbol = analysis["symbol"]
    df = analysis["df"]
    news_list = analysis["news_list"]
    overview = analysis["overview"]
    current_price = analysis["current_price"]
    report = analysis["report"]
    structured = analysis["structured"]
    quant = analysis["quant"]

    company_name = overview.get("公司名稱", symbol) if overview else symbol
    industry = overview.get("產業別", "") if overview else ""

    st.markdown("---")
    h1, h2 = st.columns([3, 1])
    with h1:
        st.markdown(f'<div class="hero-symbol">{symbol}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="hero-company">{company_name} · {industry}</div>', unsafe_allow_html=True)
    with h2:
        st.metric("Latest Close", f"${current_price:,.2f}")

    # Decision-first snapshot: concise information before raw research details.
    st.markdown('<div class="section-title">Research Snapshot</div>', unsafe_allow_html=True)
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Quant Signal", quant.get("latest_signal", "N/A") if "error" not in quant else "N/A")
    s2.metric("Market Regime", quant.get("current_regime", "N/A") if "error" not in quant else "N/A")
    s3.metric("Bull Range", _scenario_text(structured, "bull"))
    s4.metric("Base Range", _scenario_text(structured, "base"))
    s5.metric("Bear Range", _scenario_text(structured, "bear"))

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Market Cap", overview.get("市值", "N/A") if overview else "N/A")
    k2.metric("P / E", overview.get("本益比", "N/A") if overview else "N/A")
    k3.metric("EPS", overview.get("每股盈餘", "N/A") if overview else "N/A")
    k4.metric("Gross Margin", _fmt(overview.get("毛利率") if overview else None, suffix="%"))
    k5.metric("52W High", overview.get("52週最高價", "N/A") if overview else "N/A")

    st.caption(f"{len(df):,} price records · {len(news_list):,} news items")

    tab_overview, tab_strategy, tab_research = st.tabs(
        ["Overview", "Quant Strategy", "Research & Data"]
    )

    with tab_overview:
        left, right = st.columns([1.55, 1])
        with left:
            st.markdown('<div class="section-title">Price</div>', unsafe_allow_html=True)
            st.line_chart(df.set_index("date")[["close"]], height=360)

            st.markdown("#### AI Research")
            with st.expander("Read full AI report", expanded=False):
                st.markdown(report)

        with right:
            st.markdown('<div class="section-title">Recent News</div>', unsafe_allow_html=True)
            if news_list:
                for n in news_list[:5]:
                    with st.container(border=True):
                        st.markdown(f"**{n.get('title') or 'Untitled'}**")
                        st.caption(
                            f"{n.get('time_published') or 'N/A'} · {n.get('source') or 'N/A'} · "
                            f"{n.get('overall_sentiment_label') or 'N/A'}"
                        )
            else:
                st.info("目前沒有新聞資料。")

            with st.expander("View all news"):
                for n in news_list:
                    st.markdown(f"**{n.get('title') or 'Untitled'}**")
                    st.caption(
                        f"{n.get('time_published') or 'N/A'} · {n.get('source') or 'N/A'} · "
                        f"{n.get('overall_sentiment_label') or 'N/A'}"
                    )

    with tab_strategy:
        st.markdown('<div class="section-title">Strategy V1 Validation</div>', unsafe_allow_html=True)
        st.caption(
            "MA200 trend filter + 6-month momentum + relative strength vs BTC. "
            "Signals execute at the next session open."
        )

        if "error" in quant:
            st.warning(quant["error"])
        else:
            v1_result = quant["v1_result"]
            bh_result = quant["bh_result"]
            v1_perf = quant["v1_perf"]
            stock_df = quant["stock_df"]

            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Strategy Return", f"{v1_result['total_return_pct']}%")
            p2.metric("Buy & Hold", f"{bh_result['total_return_pct']}%")
            p3.metric("CAGR", _fmt(v1_perf.get("cagr_pct"), suffix="%"))
            p4.metric("Win Rate", _fmt(v1_perf.get("win_rate_pct"), suffix="%"))

            st.line_chart(stock_df.set_index("date")[["close", "ma200"]], height=420)

            st.markdown('<div class="section-title">Strategy Versions</div>', unsafe_allow_html=True)
            comparison_df = quant["comparison"]

            def color_return(val):
                if pd.isna(val):
                    return ""
                return "color: #00D9A0; font-weight: bold" if val > 0 else "color: #FF4B4B; font-weight: bold"

            styled = comparison_df.style.map(color_return, subset=["Return_pct", "CAGR_pct"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

            with st.expander("Trade signals & diagnostics"):
                signals = stock_df[stock_df["signal"].notna()][["date", "close", "signal", "execution_price"]]
                st.dataframe(signals, use_container_width=True, hide_index=True)
                if v1_perf.get("completed_trades"):
                    diagnostics = build_trade_diagnostics(stock_df, v1_perf["completed_trades"])
                    st.dataframe(pd.DataFrame(diagnostics), use_container_width=True, hide_index=True)

            with st.expander("Market regime"):
                counts = quant.get("regime_counts", {})
                r1, r2, r3 = st.columns(3)
                r1.metric("Risk-On", counts.get("Risk-On", 0))
                r2.metric("Risk-Off", counts.get("Risk-Off", 0))
                r3.metric("Mixed", counts.get("Mixed", 0))

            st.caption("⚠️ 回測僅供研究用途。過去績效不代表未來績效。")

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
                    st.info("未取得公司基本面資料。")

        with right:
            with st.expander("AI scenario data", expanded=True):
                if structured:
                    q1, q2, q3 = st.columns(3)
                    q1.metric("Bull", _scenario_text(structured, "bull"))
                    q2.metric("Base", _scenario_text(structured, "base"))
                    q3.metric("Bear", _scenario_text(structured, "bear"))
                    st.caption(
                        f"Entry: {_fmt(structured.get('entry_zone_low'))} – {_fmt(structured.get('entry_zone_high'))} · "
                        f"TP: {_fmt(structured.get('take_profit_low'))} – {_fmt(structured.get('take_profit_high'))}"
                    )
                else:
                    st.warning("未能解析結構化數據。")

        with st.expander("Advanced / Raw price data"):
            st.dataframe(df.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

        st.markdown('<div class="section-title">Prediction History</div>', unsafe_allow_html=True)
        st.caption("過去預測會保留原始數值；驗證只追加結果，不回寫預測。")
        all_predictions = list_predictions()

        if not all_predictions:
            st.info("目前還沒有任何預測紀錄。")
        else:
            options = [f"{r['ticker']} — {r['timestamp']}" for r in all_predictions]
            selected_index = st.selectbox(
                "Prediction",
                range(len(options)),
                format_func=lambda i: options[i],
                label_visibility="collapsed",
                key="prediction_selector",
            )
            selected = all_predictions[selected_index]

            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Price at Prediction", f"${selected.get('current_price_at_prediction', 'N/A')}")
            a2.metric("Bull", _scenario_text(selected, "bull"))
            a3.metric("Base", _scenario_text(selected, "base"))
            a4.metric("Bear", _scenario_text(selected, "bear"))

            if selected.get("outcome_checked"):
                st.success(
                    f"Verified {selected.get('checked_at')} · Return {selected.get('actual_return_pct')}% · "
                    f"{selected.get('which_scenario_occurred')}"
                )
            elif st.button("Verify current price", type="secondary"):
                raw = get_daily_stock_data(selected["ticker"])
                if "Time Series (Daily)" in raw:
                    latest_df = clean_stock_data(raw)
                    actual_price = float(latest_df["close"].iloc[-1])
                    updated = check_prediction_outcome(selected, actual_price)
                    st.success(f"驗證完成：${actual_price} · {updated['which_scenario_occurred']}")
                    st.rerun()
                else:
                    st.error("查詢目前股價失敗，請稍後再試。")

    st.markdown(
        '<div class="disclaimer">For education and research only. Not financial advice.</div>',
        unsafe_allow_html=True,
    )
