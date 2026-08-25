"""Streamlit interface for AI-assisted large-cap equity research."""

import base64
import html
import re
from pathlib import Path
import pandas as pd
import streamlit as st

from src.ai_analysis import extract_structured_data, generate_report
from src.backtest_engine import BacktestConfig, run_backtest, run_buy_and_hold
from src.performance import calculate_metrics
from src.prediction_tracker import (
    check_prediction_outcome,
    get_recent_prediction,
    list_predictions,
    save_prediction,
)
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


def asset_data_uri(filename):
    """Embed a local visual asset so it also works when Streamlit is deployed."""
    path = Path(__file__).parent / "assets" / filename
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def format_price_range(low, high):
    """Use one currency marker so Streamlit does not parse the range as LaTeX."""
    if low is None or high is None:
        return "—"
    return f"${low:,.2f}–{high:,.2f}"


def extract_scenario_report(report_text, scenario):
    """Return only the selected Bull/Base/Bear section from the AI report."""
    normalized = str(report_text).replace("\\n", "\n")
    labels = {
        "中性": r"Base Case|中性情境",
        "樂觀": r"Bull Case|樂觀情境",
        "悲觀": r"Bear Case|悲觀情境",
    }
    pattern = rf"(?ims)^###\s*(?:{labels[scenario]})[^\n]*\n(.*?)(?=^###\s|^##\s|\Z)"
    match = re.search(pattern, normalized)
    return match.group(1).strip() if match else "這份報告沒有可分離的情境段落，請查看完整 AI 分析。"


st.set_page_config(page_title="AI Stock Research", page_icon="📈", layout="wide")
background_uri = asset_data_uri("metal-dashboard-background.png")
st.markdown(
    f"""
    <style>
    header[data-testid="stHeader"] {{display: none;}}
    .stApp {{background: linear-gradient(180deg, rgba(5,8,12,.76), rgba(5,8,12,.94)), url("{background_uri}") center top / cover fixed;}}
    .block-container {{max-width: 1180px; padding: 2rem 2rem 4rem; background: rgba(7,10,15,.84); border-left: 1px solid rgba(190,203,220,.14); border-right: 1px solid rgba(190,203,220,.14); box-shadow: 0 0 60px rgba(0,0,0,.42); backdrop-filter: blur(16px);}}
    .hero {{padding: 1.2rem 0 1.5rem;}}
    .hero h1 {{font-size: 2rem; margin: 0; letter-spacing: -.03em; color: #f4f7fb;}}
    .hero p {{color: #aeb8c8; margin: .35rem 0 0;}}
    div[data-testid="stMetric"] {{border: 1px solid rgba(190,203,220,.22); border-radius: 14px; padding: 1rem; background: linear-gradient(145deg, rgba(37,43,53,.78), rgba(12,16,23,.9)); box-shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 12px 30px rgba(0,0,0,.2);}}
    div[data-testid="stMetricValue"] {{font-size: clamp(1.4rem, 3vw, 2.2rem);}}
    div[data-testid="stTabs"] button {{font-weight: 600;}}
    div[data-testid="stDataFrame"] {{border: 1px solid rgba(128,128,128,.18); border-radius: 10px; overflow: hidden;}}
    .section-note {{color: #8b95a7; font-size: .9rem; margin-top: -.5rem;}}
    .quote-strip {{display: flex; align-items: center; justify-content: space-between; gap: 1.5rem; padding: 1.35rem 1.5rem; margin: .75rem 0 1.25rem; border: 1px solid rgba(205,216,230,.28); border-radius: 16px; background: linear-gradient(110deg, rgba(43,50,61,.88), rgba(11,15,22,.94) 58%, rgba(29,38,49,.86)); box-shadow: inset 0 1px 0 rgba(255,255,255,.09), 0 18px 40px rgba(0,0,0,.28);}}
    .quote-company {{font-size: 1.5rem; font-weight: 700; color: #f5f7fa;}}
    .quote-industry {{margin-top: .25rem; color: #9da9ba; font-size: .84rem; letter-spacing: .08em; text-transform: uppercase;}}
    .quote-market {{display: flex; align-items: center; gap: 1.25rem; white-space: nowrap;}}
    .quote-label {{font-size: .75rem; color: #95a1b2; letter-spacing: .08em;}}
    .quote-price {{font-size: 2rem; font-weight: 650; line-height: 1.15; color: #f5f7fa;}}
    .quote-change {{padding: .45rem .75rem; border-radius: 999px; font-weight: 650;}}
    .quote-up {{color: #72e6a4; background: rgba(26,121,76,.28);}}
    .quote-down {{color: #ff8d91; background: rgba(154,48,55,.28);}}
    .stButton > button[kind="primary"] {{background: linear-gradient(135deg, #d8dee7, #788596) !important; color: #090c11 !important; border: 1px solid rgba(255,255,255,.42) !important; font-weight: 700; box-shadow: inset 0 1px 0 rgba(255,255,255,.45), 0 8px 24px rgba(0,0,0,.28);}}
    @media (max-width: 720px) {{.block-container {{padding: 1rem 1rem 3rem;}} .quote-strip {{align-items: flex-start; flex-direction: column; gap: 1rem;}} .quote-market {{width: 100%; justify-content: space-between;}} .quote-price {{font-size: 1.75rem;}}}}
    </style>
    <div class="hero">
      <h1>AI Stock Research</h1>
      <p>快速看懂公司、AI 情境與量化策略表現</p>
    </div>
    """,
    unsafe_allow_html=True,
)

search_col, button_col = st.columns([5, 1])
with search_col:
    symbol = st.text_input("股票代號", value="AAPL", placeholder="例如：AAPL、NVDA", label_visibility="collapsed").strip().upper()
with button_col:
    analyze_clicked = st.button("開始分析", type="primary", use_container_width=True)
analysis_payload = st.session_state.get("analysis_payload")
analysis_cache = st.session_state.setdefault("analysis_cache", {})

if analyze_clicked:
    if not symbol:
        st.warning("Please enter a ticker.")
        st.stop()

    if symbol in analysis_cache:
        analysis_payload = analysis_cache[symbol]
        st.toast("已載入本次工作階段的分析快取")
    else:
        with st.status(f"正在分析 {symbol}", expanded=True) as status:
            st.write("取得股價資料…")
            raw_data = get_daily_stock_data(symbol)
            if "Time Series (Daily)" not in raw_data:
                status.update(label="股價資料載入失敗", state="error")
                st.error("Price data could not be loaded. Check the ticker or API status.")
                st.stop()
            short_df = clean_stock_data(raw_data)

            st.write("取得新聞與基本面…")
            news = get_news_sentiment(symbol, limit=20)
            overview = get_company_overview(symbol)

            current_price = float(short_df["close"].iloc[-1])
            recent_prediction = get_recent_prediction(symbol, max_age_hours=12)
            if recent_prediction:
                st.write("載入 12 小時內的 AI 分析快取…")
                report = recent_prediction["full_report_text"]
                structured_keys = (
                    "current_price", "bull_low", "bull_high", "base_low", "base_high",
                    "bear_low", "bear_high", "entry_zone_low", "entry_zone_high",
                    "take_profit_low", "take_profit_high", "invalidation_down", "invalidation_up",
                )
                structured = {key: recent_prediction.get(key) for key in structured_keys}
                saved_path = recent_prediction["_filepath"]
            else:
                st.write("產生 AI 情境分析…")
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
            analysis_cache[symbol] = analysis_payload
            status.update(label="分析完成", state="complete", expanded=False)
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

    structured = structured or {}
    company_name = overview.get("公司名稱", symbol) if overview else symbol
    previous_close = float(short_df["close"].iloc[-2]) if len(short_df) > 1 else current_price
    daily_change = current_price / previous_close - 1 if previous_close else 0.0
    industry = overview.get("產業別", "大型股研究") if overview else "大型股研究"
    change_class = "quote-up" if daily_change >= 0 else "quote-down"
    change_arrow = "↑" if daily_change >= 0 else "↓"
    st.markdown(
        f"""
        <div class="quote-strip">
          <div>
            <div class="quote-company">{html.escape(symbol)} · {html.escape(str(company_name))}</div>
            <div class="quote-industry">{html.escape(str(industry))}</div>
          </div>
          <div class="quote-market">
            <div>
              <div class="quote-label">最新收盤</div>
              <div class="quote-price">${current_price:,.2f}</div>
            </div>
            <div class="quote-change {change_class}">{change_arrow} {abs(daily_change):.2%}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    tab_overview, tab_strategy, tab_data = st.tabs(["投資摘要", "策略回測", "公司資料"])

    with tab_overview:
        st.line_chart(short_df.set_index("date")[["close"]], height=380)

        entry, target, risk = st.columns(3)
        entry.metric("參考進場", format_price_range(structured.get("entry_zone_low"), structured.get("entry_zone_high")))
        target.metric("參考停利", format_price_range(structured.get("take_profit_low"), structured.get("take_profit_high")))
        risk.metric("風險失效價", f"${structured.get('invalidation_down', '—')}")

        st.markdown("#### AI 情境")
        scenario = st.segmented_control(
            "選擇情境",
            ["中性", "樂觀", "悲觀"],
            default="中性",
            label_visibility="collapsed",
        )
        scenario_fields = {
            "中性": ("base_low", "base_high"),
            "樂觀": ("bull_low", "bull_high"),
            "悲觀": ("bear_low", "bear_high"),
        }
        selected_scenario = scenario or "中性"
        low_key, high_key = scenario_fields[selected_scenario]
        st.metric(
            f"{selected_scenario}情境可能區間",
            format_price_range(structured.get(low_key), structured.get(high_key)),
        )
        with st.container(border=True):
            st.markdown(extract_scenario_report(report, selected_scenario))

        with st.expander("完整 AI 分析"):
            st.markdown(str(report).replace("\\n", "\n"))

        with st.expander(f"近期新聞（{min(len(news), 5)}）"):
            for item in news[:5]:
                st.markdown(f"**{item['title']}**")
                st.caption(f"{item['time_published']} · {item['source']} · {item['overall_sentiment_label']}")

    with tab_strategy:
        st.subheader("大型股策略比較")
        st.caption(
            "三種策略使用相同資料、成本與隔日開盤成交規則，方便公平比較。"
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

            selected = st.selectbox("查看策略圖表", list(prepared))
            chart_columns = ["close", "ma200"]
            if selected == "Trend Following":
                chart_columns.append("ma50")
            elif selected == "Mean Reversion":
                chart_columns.extend(["ma20", "rsi14"])
            chart = prepared[selected].set_index("date")[chart_columns]
            st.line_chart(chart, height=400)

            regime = build_regime_series(period="5y")
            latest_regime = regime.dropna(subset=["regime"]).iloc[-1]
            st.info(f"目前大盤狀態：{latest_regime['regime']}（SPY 收盤價相對 MA200）")

    with tab_data:
        st.subheader("公司基本面")
        fundamentals = overview or {}
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("市值", fundamentals.get("市值", "—"))
        f2.metric("本益比", fundamentals.get("本益比", "—"))
        f3.metric("每股盈餘", fundamentals.get("每股盈餘", "—"))
        f4.metric("產業", fundamentals.get("產業別", "—"))
        if fundamentals.get("公司簡介"):
            st.write(fundamentals["公司簡介"])

        with st.expander("查看原始股價資料"):
            st.dataframe(short_df.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

        st.subheader("歷史預測")
        predictions = list_predictions()
        if predictions:
            index = st.selectbox(
                "選擇預測紀錄",
                range(len(predictions)),
                format_func=lambda i: f"{predictions[i]['ticker']} — {predictions[i]['timestamp']}",
            )
            record = predictions[index]
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("預測時股價", f"${record.get('current_price_at_prediction', '—')}")
            h2.metric("樂觀區間", format_price_range(record.get("bull_low"), record.get("bull_high")))
            h3.metric("中性區間", format_price_range(record.get("base_low"), record.get("base_high")))
            h4.metric("悲觀區間", format_price_range(record.get("bear_low"), record.get("bear_high")))
            if record.get("outcome_checked"):
                st.success(
                    f"已驗證：實際報酬 {record.get('actual_return_pct', '—')}% · "
                    f"落在 {str(record.get('which_scenario_occurred', '—')).upper()} 情境"
                )
            if not record.get("outcome_checked") and st.button("驗證目前股價"):
                latest_raw = get_daily_stock_data(record["ticker"])
                if "Time Series (Daily)" in latest_raw:
                    latest_price = float(clean_stock_data(latest_raw)["close"].iloc[-1])
                    check_prediction_outcome(record, latest_price)
                    st.success("預測結果已更新。")
                    st.rerun()
        else:
            st.info("目前沒有歷史預測。")

st.caption("僅供教育與研究使用，歷史績效不代表未來表現。")
