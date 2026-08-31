"""Read-only Streamlit dashboard for Frozen V12 forward paper trading."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

from src.ai_analysis import (
    compact_ai_provider,
    generate_compact_summary,
    has_compact_ai_key,
)
from src.config import get_secret
from src.dashboard_cloud_snapshot import (
    DashboardSnapshotError,
    load_signed_snapshot,
    load_supabase_snapshot,
)
from src.dashboard_read_model import DEFAULT_LEDGER_PATH, build_dashboard_snapshot
from src.stock_data import (
    clean_stock_data,
    get_company_overview,
    get_daily_stock_data,
    get_long_history_stock_data,
    get_news_sentiment,
    has_alpha_vantage_key,
)


APP_TITLE = "V12 Forward Dashboard"
COLORS = {"V12": "#39E5A5", "SPY": "#35C9FF", "QQQ": "#8A7CFF"}


st.set_page_config(
    page_title=APP_TITLE,
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="auto",
)


def _inject_style() -> None:
    st.markdown(
        """
        <style>
        :root { --panel:#111827; --line:#263247; --muted:#93a2b7; --cyan:#35c9ff; --green:#39e5a5; --amber:#f5c451; --red:#ff6b75; }
        header[data-testid="stHeader"] { background: rgba(6,10,18,.75); backdrop-filter: blur(14px); }
        .stApp { background: radial-gradient(circle at 78% 0%, rgba(53,201,255,.08), transparent 30%), #070b13; color:#f7f9fc; }
        .block-container { max-width:1240px; padding-top:4.5rem; padding-bottom:4rem; }
        section[data-testid="stSidebar"] { background:#090e18; border-right:1px solid #202b3d; }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] { padding-top:.5rem; }
        .eyebrow { color:var(--cyan); font-size:.78rem; font-weight:700; letter-spacing:.13em; text-transform:uppercase; }
        .page-title { font-size:clamp(1.8rem,4vw,2.7rem); font-weight:760; letter-spacing:-.04em; margin:.25rem 0 .2rem; }
        .page-subtitle { color:var(--muted); max-width:760px; margin-bottom:1.5rem; }
        .paper-banner { padding:.8rem 1rem; border:1px solid rgba(245,196,81,.48); border-radius:12px; color:var(--amber); background:rgba(245,196,81,.07); font-weight:750; letter-spacing:.08em; text-align:center; margin:.25rem 0 1.25rem; }
        .status-badge { display:inline-flex; align-items:center; gap:.55rem; padding:.48rem .8rem; border-radius:999px; font-weight:750; border:1px solid currentColor; }
        .status-normal { color:var(--green); background:rgba(57,229,165,.08); }
        .status-watch { color:var(--amber); background:rgba(245,196,81,.08); }
        .status-error { color:var(--red); background:rgba(255,107,117,.08); }
        .empty-state { padding:3rem 1.25rem; border:1px dashed #344157; border-radius:18px; text-align:center; background:rgba(17,24,39,.55); }
        .empty-state h3 { margin:0 0 .45rem; }
        .empty-state p { color:var(--muted); margin:0; }
        .overview-card-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; margin:.15rem 0 1.25rem; }
        .overview-card { min-width:0; min-height:230px; padding:1.35rem; border:1px solid var(--line); border-radius:16px; background:linear-gradient(145deg,rgba(17,24,39,.92),rgba(8,13,23,.96)); display:flex; flex-direction:column; box-sizing:border-box; }
        .overview-card-kicker { color:var(--cyan); font-size:.72rem; font-weight:750; letter-spacing:.12em; margin-bottom:.45rem; }
        .overview-card-title { color:#f7f9fc; font-size:1.2rem; font-weight:720; min-height:2rem; }
        .overview-card-value { color:#f7f9fc; font-size:1.7rem; font-weight:720; line-height:1.15; margin-top:1.4rem; }
        .overview-card-detail { color:var(--muted); font-size:.9rem; line-height:1.65; margin-top:auto; padding-top:1rem; }
        .read-only { color:#9aa9bd; font-size:.86rem; border-left:3px solid var(--cyan); padding:.45rem .75rem; margin:.6rem 0 1.2rem; }
        div[data-testid="stMetric"] { min-height:126px; border:1px solid var(--line); border-radius:16px; padding:1rem; background:linear-gradient(145deg,rgba(24,34,51,.94),rgba(12,18,30,.96)); box-shadow:inset 0 1px 0 rgba(255,255,255,.04),0 18px 42px rgba(0,0,0,.16); }
        div[data-testid="stMetricLabel"] { color:#aab5c5; }
        div[data-testid="stMetricValue"] { font-size:clamp(1.35rem,2.7vw,2.05rem); }
        div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow-x:auto; }
        div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line) !important; background:rgba(17,24,39,.55); }
        .event-card { border:1px solid var(--line); border-radius:14px; padding:1rem; background:rgba(17,24,39,.66); margin-bottom:.65rem; }
        .event-card a { color:var(--cyan); text-decoration:none; }
        .event-meta { color:var(--muted); font-size:.82rem; margin-top:.35rem; }
        .footer-note { color:#7f8da2; text-align:center; font-size:.82rem; margin-top:2.5rem; }
        @media (max-width:720px) {
          .block-container { padding:4.25rem .7rem 3rem; }
          .overview-card-grid { grid-template-columns:1fr; gap:.75rem; }
          .overview-card { min-height:190px; }
          div[data-testid="stMetric"] { min-height:104px; padding:.8rem; }
          div[data-testid="stMetricValue"] { font-size:1.35rem; overflow-wrap:anywhere; }
          .paper-banner { font-size:.78rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _header(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="page-title">{html.escape(title)}</div>'
        f'<div class="page-subtitle">{html.escape(subtitle)}</div>',
        unsafe_allow_html=True,
    )


def _paper_banner() -> None:
    st.markdown('<div class="paper-banner">FORWARD PAPER TRADING · NOT LIVE CAPITAL</div>', unsafe_allow_html=True)


def _status_badge(status: str, label: str) -> None:
    css = {"NORMAL": "normal", "WATCH": "watch", "ERROR": "error"}.get(status, "watch")
    st.markdown(f'<span class="status-badge status-{css}">● {html.escape(label)}</span>', unsafe_allow_html=True)


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _pct(value: float | None, *, points: bool = False) -> str:
    if value is None:
        return "—"
    suffix = " pp" if points else "%"
    return f"{value * 100:+.2f}{suffix}"


def _number(value: Any, *, currency: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(number) >= 1_000_000_000_000:
        result = f"{number / 1_000_000_000_000:.2f}T"
    elif abs(number) >= 1_000_000_000:
        result = f"{number / 1_000_000_000:.2f}B"
    elif abs(number) >= 1_000_000:
        result = f"{number / 1_000_000:.2f}M"
    else:
        result = f"{number:,.2f}"
    return f"${result}" if currency else result


def _ledger_path() -> Path:
    configured = get_secret("V12_LEDGER_PATH")
    return Path(configured) if configured else DEFAULT_LEDGER_PATH


def _dashboard_state() -> dict[str, Any]:
    supabase_url = get_secret("SUPABASE_URL")
    supabase_key = get_secret("SUPABASE_SECRET_KEY") or get_secret(
        "SUPABASE_SERVICE_ROLE_KEY"
    )
    remote_source = get_secret("V12_DASHBOARD_SNAPSHOT_URL") or get_secret(
        "V12_DASHBOARD_SNAPSHOT_PATH"
    )
    if not supabase_url and not supabase_key and not remote_source:
        return build_dashboard_snapshot(_ledger_path())
    try:
        if bool(supabase_url) != bool(supabase_key):
            raise DashboardSnapshotError("Supabase URL and secret key must both be configured")
        if supabase_url and supabase_key:
            return load_supabase_snapshot(
                supabase_url,
                supabase_key,
                get_secret("V12_DASHBOARD_SYNC_SECRET") or "",
                bucket=get_secret("V12_DASHBOARD_SUPABASE_BUCKET") or "v12-dashboard",
                object_path=get_secret("V12_DASHBOARD_SUPABASE_OBJECT")
                or "v12_dashboard.json",
            )
        return load_signed_snapshot(
            remote_source,
            get_secret("V12_DASHBOARD_SYNC_SECRET") or "",
        )
    except DashboardSnapshotError as exc:
        state = build_dashboard_snapshot(Path("__cloud_snapshot_unavailable__.sqlite3"))
        state.update({
            "health_status": "ERROR",
            "health_label": "同步異常",
            "trading_blocked": True,
            "integrity_error": str(exc),
            "warnings": ["雲端 Dashboard Snapshot 無法驗證"],
        })
        return state


def _yahoo_company_events(symbol: str) -> dict[str, list[dict[str, str]]]:
    earnings: list[dict[str, str]] = []
    filings: list[dict[str, str]] = []
    ticker = yf.Ticker(symbol)
    try:
        frame = ticker.get_earnings_dates(limit=4)
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            for index, row in frame.head(4).iterrows():
                earnings.append({
                    "date": pd.Timestamp(index).strftime("%Y-%m-%d"),
                    "estimate": _number(row.get("EPS Estimate")),
                    "reported": _number(row.get("Reported EPS")),
                    "surprise": _number(row.get("Surprise(%)")),
                })
    except Exception:
        pass
    try:
        raw_filings = getattr(ticker, "sec_filings", None)
        if callable(raw_filings):
            raw_filings = raw_filings()
        for item in (raw_filings or [])[:6]:
            if not isinstance(item, dict):
                continue
            filings.append({
                "date": str(item.get("date") or item.get("filingDate") or "")[:10],
                "type": str(item.get("type") or item.get("formType") or "SEC Filing"),
                "title": str(item.get("title") or item.get("description") or "公司申報"),
                "url": str(item.get("edgarUrl") or item.get("url") or ""),
            })
    except Exception:
        pass
    return {"earnings": earnings, "filings": filings}


@st.cache_data(ttl=1800, show_spinner=False)
def _market_payload(symbol: str) -> dict[str, Any]:
    raw = get_daily_stock_data(symbol)
    source = "Alpha Vantage"
    if "Time Series (Daily)" in raw:
        prices = clean_stock_data(raw)
    else:
        prices = get_long_history_stock_data(symbol, period="1y").tail(180).reset_index(drop=True)
        source = "Yahoo Finance"
    return {
        "prices": prices,
        "overview": get_company_overview(symbol),
        "news": get_news_sentiment(symbol, limit=10),
        "source": source,
        **_yahoo_company_events(symbol),
    }


def render_overview() -> None:
    _header("Portfolio", "總覽 / 模擬交易", "只呈現 Frozen V12 的正式 Forward 證據，不使用回測數字填補空白。")
    _paper_banner()
    state = _dashboard_state()
    if state["integrity_error"]:
        st.error(f"Dashboard 資料同步異常：{state['integrity_error']}")
    columns = st.columns(5)
    columns[0].metric("Portfolio Value", _money(state["portfolio_value"]))
    columns[1].metric("累積報酬", _pct(state["cumulative_return"]))
    columns[2].metric("vs SPY", _pct(state["excess_vs_spy"], points=True))
    columns[3].metric("vs QQQ", _pct(state["excess_vs_qqq"], points=True))
    columns[4].metric("MDD", _pct(state["max_drawdown"]))

    st.markdown("### V12 vs SPY vs QQQ")
    curve = state["curve"]
    if state["formal_forward_rows"] == 0 or curve.empty:
        st.markdown('<div class="empty-state"><h3>尚未產生第一筆正式 Forward Signal</h3><p>Dashboard 不會用歷史回測或示意數字假裝成 Forward 績效。</p></div>', unsafe_allow_html=True)
    else:
        figure = go.Figure()
        for name in ("V12", "SPY", "QQQ"):
            frame = curve[curve["series"].eq(name)].copy()
            if frame.empty:
                continue
            figure.add_trace(go.Scatter(
                x=pd.to_datetime(frame["date"]), y=frame["value"], name=name, mode="lines+markers",
                line={"color": COLORS[name], "width": 3 if name == "V12" else 2},
                hovertemplate=f"<b>{name}</b><br>%{{x|%Y-%m-%d}}<br>$%{{y:,.2f}}<extra></extra>",
            ))
        figure.update_layout(
            height=430, margin={"l": 8, "r": 8, "t": 12, "b": 8},
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(12,18,30,.68)",
            font={"color": "#dfe7f2"}, hovermode="x unified",
            xaxis={"gridcolor": "#202b3d"}, yaxis={"tickprefix": "$", "tickformat": ",.0f", "gridcolor": "#202b3d"},
            legend={"orientation": "h", "y": 1.08},
        )
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})

    if state["holdings"]:
        portfolio_value = f'{len(state["holdings"])} 檔持股'
        lines = []
        for position in state["holdings"]:
            weight = position.get("target_weight")
            weight_text = "—" if weight is None else f"{float(weight):.0%}"
            lines.append(f'{html.escape(str(position.get("ticker") or "—"))} · {weight_text}')
        portfolio_detail = f'{"<br>".join(lines)}<br>現金 · {_money(state["cash"])}'
    else:
        portfolio_value = "0 檔持股"
        portfolio_detail = "等待第一筆正式 Forward 配置<br>現金 · —"
    if state["latest_signal"] is None:
        signal_value = "尚未產生"
        signal_detail = "等待正式月末訊號<br>SPY Regime · —"
    else:
        signal_value = html.escape(state["signal_date"] or "—")
        selections = " · ".join(f"{ticker} {weight:.0%}" for ticker, weight in state["target_weights"].items()) or "—"
        signal_detail = f'SPY Regime · {html.escape(state["market_regime"] or "—")}<br>{html.escape(selections)}'
    execution_value = html.escape(state["execution_status"])
    execution_detail = f'預定執行日 · {html.escape(state["execution_date"] or "—")}<br>執行規則 · T+1 Open'
    st.markdown(
        f'''
        <div class="overview-card-grid">
          <section class="overview-card"><div class="overview-card-kicker">PORTFOLIO</div><div class="overview-card-title">目前持股與現金</div><div class="overview-card-value">{portfolio_value}</div><div class="overview-card-detail">{portfolio_detail}</div></section>
          <section class="overview-card"><div class="overview-card-kicker">LATEST SIGNAL</div><div class="overview-card-title">最新 V12 訊號</div><div class="overview-card-value">{signal_value}</div><div class="overview-card-detail">{signal_detail}</div></section>
          <section class="overview-card"><div class="overview-card-kicker">EXECUTION</div><div class="overview-card-title">T+1 執行</div><div class="overview-card-value">{execution_value}</div><div class="overview-card-detail">{execution_detail}</div></section>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    if state["events"]:
        with st.expander("查看不可回寫的事件紀錄"):
            rows = pd.DataFrame([{key: row.get(key) for key in ("sequence", "created_at", "portfolio_id", "event_type", "ticker", "action", "data_asof")} for row in reversed(state["events"][-100:])])
            st.dataframe(rows, width="stretch", hide_index=True)
    st.markdown('<div class="read-only">Read-only UI：此頁不會建立、更新或刪除 Signal、Order、Fill、Position 或 Ledger event。</div>', unsafe_allow_html=True)


def render_market() -> None:
    _header("Market Intelligence", "市場情報", "價格、財報、重大新聞與公司公告集中在同一頁；不恢復冗長情境報告。")
    search, action = st.columns([5, 1])
    with search:
        symbol = st.text_input("股票代號", value=st.session_state.get("market_symbol", ""), placeholder="例如 AAPL、NVDA", label_visibility="collapsed").strip().upper()
    with action:
        clicked = st.button("搜尋", type="primary", width="stretch")
    if clicked:
        st.session_state["market_symbol"] = symbol
    symbol = st.session_state.get("market_symbol", "")
    if not symbol:
        st.info("輸入股票代號並按「搜尋」開始查看；進入此頁不會自動呼叫外部資料或 AI API。")
        return

    with st.spinner(f"載入 {symbol} 市場資料…"):
        payload = _market_payload(symbol)
    prices = payload["prices"]
    if prices.empty:
        st.error("無法取得價格資料。請檢查股票代號或稍後再試。")
        return
    overview = payload["overview"] or {}
    current = float(prices["close"].iloc[-1])
    previous = float(prices["close"].iloc[-2]) if len(prices) > 1 else current
    daily_change = current / previous - 1 if previous else 0.0
    company = overview.get("公司名稱") or symbol
    st.markdown(f"### {html.escape(symbol)} · {html.escape(str(company))}")
    price_col, meta_col = st.columns([1, 2])
    price_col.metric("最新收盤", _money(current), f"{daily_change:+.2%}")
    meta_col.caption(f"資料來源：{payload['source']} · 截至 {prices['date'].iloc[-1]} · 非即時報價")

    figure = go.Figure(go.Scatter(
        x=pd.to_datetime(prices["date"]), y=prices["close"], mode="lines",
        line={"color": COLORS["V12"], "width": 2.5}, fill="tozeroy", fillcolor="rgba(57,229,165,.06)",
        hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>",
    ))
    figure.update_layout(
        height=330, margin={"l": 8, "r": 8, "t": 8, "b": 8}, paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(12,18,30,.68)", font={"color": "#dfe7f2"},
        xaxis={"gridcolor": "#202b3d"}, yaxis={"tickprefix": "$", "gridcolor": "#202b3d"},
    )
    st.plotly_chart(figure, width="stretch", config={"displaylogo": False})

    st.markdown("### 財報與基本面")
    metrics = st.columns(5)
    metrics[0].metric("市值", _number(overview.get("市值"), currency=True))
    metrics[1].metric("本益比", _number(overview.get("本益比")))
    metrics[2].metric("EPS", _number(overview.get("每股盈餘"), currency=True))
    metrics[3].metric("毛利率", "—" if overview.get("毛利率") is None else f"{overview['毛利率']:.2f}%")
    try:
        operating_margin = float(overview["營業利益率"])
    except (KeyError, TypeError, ValueError):
        operating_margin = None
    metrics[4].metric("營業利益率", _pct(operating_margin))
    if payload["earnings"]:
        with st.expander("近期 / 預定財報日期", expanded=True):
            st.dataframe(pd.DataFrame(payload["earnings"]).rename(columns={"date": "日期", "estimate": "EPS 預估", "reported": "EPS 實際", "surprise": "驚喜幅度"}), width="stretch", hide_index=True)
    elif not has_alpha_vantage_key():
        st.caption("尚未設定 Alpha Vantage；部分基本面與財報欄位可能無法顯示。")

    news_col, filing_col = st.columns(2)
    with news_col:
        st.markdown("### 重大新聞")
        if payload["news"]:
            for item in payload["news"][:5]:
                title = html.escape(str(item.get("title") or "Untitled"))
                url = html.escape(str(item.get("url") or ""), quote=True)
                link = f'<a href="{url}" target="_blank">{title}</a>' if url else title
                meta = " · ".join(filter(None, [str(item.get("source") or ""), str(item.get("time_published") or "")]))
                st.markdown(f'<div class="event-card">{link}<div class="event-meta">{html.escape(meta)}</div></div>', unsafe_allow_html=True)
        else:
            st.info("目前沒有可用新聞；設定 ALPHAVANTAGE_API_KEY 後可補充新聞資料。")
    with filing_col:
        st.markdown("### SEC / 公司公告")
        if payload["filings"]:
            for item in payload["filings"][:5]:
                title = f"{item['type']} · {item['title']}"
                url = html.escape(item.get("url", ""), quote=True)
                link = f'<a href="{url}" target="_blank">{html.escape(title)}</a>' if url else html.escape(title)
                st.markdown(f'<div class="event-card">{link}<div class="event-meta">{html.escape(item["date"])}</div></div>', unsafe_allow_html=True)
        else:
            st.info("Yahoo Finance 目前沒有回傳可用的 SEC / 公司公告。")

    st.markdown("### AI 重點摘要")
    st.caption("AI 僅整理已顯示的價格、基本面與新聞；不產生目標價或買賣指令。")
    provider = compact_ai_provider()
    if provider:
        st.caption(f"摘要服務：{provider}")
    summary_key = f"compact_summary_{symbol}"
    if summary_key in st.session_state:
        st.markdown(st.session_state[summary_key])
    if st.button("產生 3–5 點摘要", key=f"summary_button_{symbol}"):
        if not has_compact_ai_key():
            st.warning("尚未設定 GEMINI_API_KEY 或 ANTHROPIC_API_KEY，無法產生 AI 摘要。")
        else:
            try:
                with st.spinner("整理重點…"):
                    summary = generate_compact_summary(symbol, prices, payload["news"], overview)
                st.session_state[summary_key] = summary
                st.rerun()
            except Exception as exc:
                st.error(f"AI 摘要暫時無法使用：{exc}")


def render_strategy_health() -> None:
    _header("Strategy Health", "策略狀況", "固定規則監控策略與系統；只有資料或執行異常能阻止交易。")
    _paper_banner()
    state = _dashboard_state()
    _status_badge(state["health_status"], state["health_label"])
    if state["trading_blocked"]:
        st.error("交易已被系統層阻止：" + (state["integrity_error"] or state["execution_status"]))
    elif state["warnings"]:
        for warning in state["warnings"]:
            st.warning(warning)
    else:
        st.success("資料完整、執行狀態正常；Frozen V12 規則保持不變。")

    first = st.columns(5)
    first[0].metric("V12 狀態", "FROZEN")
    first[1].metric("SPY Regime", state["market_regime"] or "—")
    agreement = "—" if state["agreement_count"] is None else f"{state['agreement_count']} 檔重疊"
    first[2].metric("V7 / V8 agreement", agreement)
    first[3].metric("Drawdown", _pct(state["max_drawdown"]))
    first[4].metric("資料截至", state["last_data_asof"] or "—")

    second = st.columns(4)
    second[0].metric("12M Rolling Sharpe", "—" if state["rolling_sharpe"] is None else f"{state['rolling_sharpe']:.2f}")
    second[1].metric("Forward vs Backtest", "—" if state["sharpe_deviation"] is None else f"{state['sharpe_deviation']:+.2f} Sharpe")
    second[2].metric("T+1", _pct(state["t1_return"]))
    second[3].metric("T+2 / 差異", "—" if state["t2_return"] is None else f"{_pct(state['t2_return'])} / {_pct(state['t1_t2_spread'], points=True)}")

    st.markdown("### 固定狀態規則")
    operational, statistical = st.columns(2)
    with operational:
        with st.container(border=True):
            st.markdown("#### 🔴 系統異常 · 可阻止交易")
            st.write("- Ledger hash / schema / JSON 驗證失敗")
            st.write("- 訊號已存在但缺少訂單或 T+1 已逾期")
            st.write("- 資料不完整、時間錯誤或會計無法對帳")
    with statistical:
        with st.container(border=True):
            st.markdown("#### 🟡 績效觀察 · 不修改策略")
            st.write("- 少於 13 個月正式 snapshot：樣本不足")
            st.write("- Rolling Sharpe < 0：進入觀察")
            st.write("- Forward drawdown ≤ −20%：啟動研究檢查")
    st.info("短期績效不好只能警告。Dashboard 不會調整 lookback、權重、股票池、執行日或任何 Frozen V12 規則。")
    st.markdown('<div class="read-only">資料流：Frozen V12 → Forward Engine → SQLite / Evidence → Read-only UI → Streamlit。</div>', unsafe_allow_html=True)


def main() -> None:
    _inject_style()
    with st.sidebar:
        st.markdown("## ◈ V12")
        st.caption("Forward Research System")
        st.divider()
        st.caption("Frozen strategy · Read-only dashboard")
    navigation = st.navigation([
        st.Page(render_overview, title="總覽 / 模擬交易", icon="📊", default=True),
        st.Page(render_market, title="市場情報", icon="📰"),
        st.Page(render_strategy_health, title="策略狀況", icon="🛡️"),
    ])
    navigation.run()
    st.markdown('<div class="footer-note">僅供教育與研究使用。Paper trading 不代表真實成交；歷史績效不代表未來表現。</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
