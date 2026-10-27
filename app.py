"""Read-only Streamlit dashboard for independent Frozen V12 and E3 accounts."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.ai_analysis import (
    compact_ai_provider,
    generate_compact_summary,
    has_compact_ai_key,
)
from src.config import get_secret
from src.market_intelligence import market_payload, valid_symbol
from src.v3_dashboard import render_v3_dashboard
from src.e3_dashboard import dashboard_view, render_e3_dashboard
from src.e3_dashboard_snapshot import E3DisplayError
from src.strategy_overview import render_strategy_overview
from src.strategy_pages import render_market_context, render_paired_page
from src.dashboard_cloud_snapshot import (
    DashboardSnapshotError,
    load_signed_snapshot,
    load_supabase_snapshot,
)
from src.dashboard_read_model import (
    DEFAULT_LEDGER_PATH,
    build_dashboard_snapshot,
)
from src.dashboard_ui import (
    header as _header,
    inject_style as _inject_style,
    money as _money,
    number as _number,
    paper_banner as _paper_banner,
    pct as _pct,
)


APP_TITLE = "V12 + E3 Dashboard"
COLORS = {"V12": "#39D98A", "SPY": "#D4D4D8", "QQQ": "#818CF8"}


st.set_page_config(
    page_title=APP_TITLE,
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="auto",
)


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
            "health_label": "Sync Error",
            "trading_blocked": True,
            "integrity_error": str(exc),
            "warnings": ["The cloud Dashboard snapshot could not be verified"],
        })
        return state


@st.cache_data(ttl=120, show_spinner=False)
def _market_payload(symbol: str) -> dict[str, Any]:
    return market_payload(symbol)


def _chart_layout(*, height: int) -> dict[str, Any]:
    return {
        "height": height,
        "margin": {"l": 8, "r": 8, "t": 12, "b": 8},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "#0d0d10",
        "font": {"color": "#a1a1aa", "family": "Inter, Segoe UI, sans-serif"},
        "hovermode": "x unified",
        "hoverlabel": {"bgcolor": "#16161a", "bordercolor": "#27272a"},
        "xaxis": {"gridcolor": "rgba(255,255,255,.055)", "zeroline": False},
        "yaxis": {
            "gridcolor": "rgba(255,255,255,.055)",
            "zeroline": False,
        },
        "legend": {"orientation": "h", "y": 1.08},
    }


def _rebalance_change_summary(trades: list[dict[str, Any]]) -> str:
    exited = [row["ticker"] for row in trades if row["action"] == "SELL" and not row.get("is_trim")]
    trimmed = [
        f'{row["ticker"]} to {float(row.get("target_weight") or 0.0):.0%}'
        for row in trades if row.get("is_trim")
    ]
    opened = [
        f'{row["ticker"]} at {float(row.get("target_weight") or 0.0):.0%}'
        for row in trades
        if row["action"] == "BUY" and float(row.get("before_shares") or 0.0) <= 1e-9
    ]
    topped_up = [
        f'{row["ticker"]} toward {float(row.get("target_weight") or 0.0):.0%}'
        for row in trades
        if row["action"] == "BUY" and float(row.get("before_shares") or 0.0) > 1e-9
    ]
    changes = []
    if exited:
        changes.append(f'exited {", ".join(exited)}')
    if trimmed:
        changes.append(f'trimmed {", ".join(trimmed)}')
    if opened:
        changes.append(f'opened {", ".join(opened)}')
    if topped_up:
        changes.append(f'topped up {", ".join(topped_up)}')
    return "V12 " + "; ".join(changes) + "." if changes else "No allocation changes were required."


def _e3_view():
    try:
        return dashboard_view()
    except E3DisplayError:
        return None


def render_overview() -> None:
    _header("Paper Trading", "V12 + E3 Overview", "Matching details for both independent paper strategies.")
    _paper_banner()
    state, e3 = _dashboard_state(), _e3_view()
    render_strategy_overview(state, e3)
    render_paired_page("overview", state, e3)


def render_activity() -> None:
    _header("Execution", "V12 + E3 Trading Activity", "Compare saved plans, paper fills, costs, signals and ledger events side by side.")
    _paper_banner()
    render_paired_page("activity", _dashboard_state(), _e3_view())


def render_market() -> None:
    _header("Market Intelligence", "Market Intelligence", "Prices, earnings, material news, and company filings in one concise view.")
    render_market_context(_dashboard_state(), _e3_view())
    search, action = st.columns([5, 1])
    with search:
        symbol = st.text_input("Ticker", value=st.session_state.get("market_symbol", ""), placeholder="For example: AAPL or NVDA", label_visibility="collapsed").strip().upper()
    with action:
        clicked = st.button("Search", type="primary", width="stretch")
    if clicked:
        if not valid_symbol(symbol):
            st.warning("Enter a valid ticker, for example NVDA, AAPL or BRK-B.")
            return
        st.session_state["market_symbol"] = symbol
    symbol = st.session_state.get("market_symbol", "")
    if not symbol:
        st.info("Enter a ticker and select Search. Opening this page does not automatically call external data or AI APIs.")
        return

    with st.spinner(f"Loading market data for {symbol}…"):
        payload = _market_payload(symbol)
    prices = payload["prices"]
    if prices.empty:
        st.warning("Prices are temporarily unavailable. Other available company information is shown below.")
    overview = payload["overview"] or {}
    current = float(prices["close"].iloc[-1]) if not prices.empty else None
    previous = float(prices["close"].iloc[-2]) if len(prices) > 1 else current
    daily_change = current / previous - 1 if current is not None and previous else None
    company = overview.get("公司名稱") or symbol
    st.markdown(f"### {html.escape(symbol)} · {html.escape(str(company))}")
    price_col, meta_col = st.columns([1, 2])
    price_col.metric("Latest Close", _money(current), f"{daily_change:+.2%}" if daily_change is not None else None)
    meta_col.caption(f"Price source: {payload['source']} · As of {prices['date'].iloc[-1] if not prices.empty else 'Unavailable'} · Daily close, not live")
    if not prices.empty:
        meta_col.caption("Provider daily Close, not a total-return series. Historical split conventions may differ between providers.")
        if (pd.Timestamp.now(tz='America/New_York').date() - pd.Timestamp(prices['date'].iloc[-1]).date()).days > 4:
            st.warning("The latest available price is more than four calendar days old. Check the source status before relying on it.")
    st.caption(f"Fundamentals: {payload['fundamentals_source']} · News: {payload['news_source']} · Fetched: {payload['fetched_at']}")
    issues = [row for row in payload['provider_status'] if row['Status'] not in {'Available','No data'}]
    if issues:
        st.caption("Some data sources are unavailable. Available backup results are shown; see Data coverage & providers for details.")
    cache_rows = payload.get('cache_status', [])
    if any('Stale' in row.get('Status', '') for row in cache_rows):
        st.warning("Some research data uses a previous successful download because refresh failed. Check retrieval times below; this is not live data.")
    with st.expander("Data coverage & providers"):
        st.dataframe(
            pd.DataFrame(payload["provider_status"]),
            width="stretch",
            hide_index=True,
        )
        st.caption("Unavailable sections only limit this research view. They do not alter Frozen V12 or E3.")
        if cache_rows:
            st.dataframe(pd.DataFrame(cache_rows), width="stretch", hide_index=True)

    if not prices.empty:
        figure = go.Figure(go.Scatter(
            x=pd.to_datetime(prices["date"]), y=prices["close"], mode="lines",
            line={"color": COLORS["V12"], "width": 2.5}, fill="tozeroy", fillcolor="rgba(57,217,138,.045)",
            hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>",
        ))
        layout = _chart_layout(height=330)
        layout["yaxis"].update({"tickprefix": "$"})
        figure.update_layout(**layout)
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False})

    st.markdown("### Earnings & Fundamentals")
    metrics = st.columns(5)
    reported = {row['Metric']: row for row in payload.get('reported_financials', [])}
    has_valuation = any(overview.get(key) is not None for key in ('市值', '本益比', '每股盈餘', '毛利率', '營業利益率'))
    if not has_valuation and reported:
        st.caption("SEC reported figures are shown instead of unavailable valuation metrics. These are not TTM values; each card identifies its reporting period.")
        for column, label in zip(metrics, ('Revenue', 'Net income', 'Diluted EPS', 'Assets', 'Liabilities')):
            row = reported.get(label, {})
            column.metric(label, _number(row.get('Value'), currency=True),
                          help="SEC reported USD per share" if label == 'Diluted EPS' else "SEC reported USD")
            if row:
                start = row.get('Period start', 'Instant')
                period = row.get('Period end', 'Unknown')
                column.caption(f"{start} → {period}" if start != 'Instant' else f"As of {period}")
        with st.expander("Why are Market Cap, P/E and TTM margins unavailable?"):
            st.caption("The valuation provider did not return these metrics. SEC statements are not a substitute for current market capitalization or TTM P/E. No estimates are invented.")
    else:
        metrics[0].metric("Market Cap", _number(overview.get("市值"), currency=True))
        metrics[1].metric("P/E", _number(overview.get("本益比")))
        metrics[2].metric("EPS (provider TTM)", _number(overview.get("每股盈餘"), currency=True))
        metrics[3].metric("Gross Margin", "—" if overview.get("毛利率") is None else f"{overview['毛利率']:.2f}%")
        try:
            operating_margin = float(overview["營業利益率"])
        except (KeyError, TypeError, ValueError):
            operating_margin = None
        metrics[4].metric("Operating Margin", _pct(operating_margin))
        if not has_valuation:
            st.info("Neither valuation metrics nor SEC financial figures are available. Missing values are not zero; see provider status above.")
    if payload["earnings"]:
        with st.expander("Recent / Scheduled Earnings", expanded=True):
            st.dataframe(pd.DataFrame(payload["earnings"]).rename(columns={"date": "Date", "estimate": "EPS Estimate", "reported": "Reported EPS", "surprise": "Surprise"}), width="stretch", hide_index=True)
    else:
        st.caption("No earnings-date rows were returned. This does not mean the company has no earnings reports.")
    if not overview:
        st.warning("Fundamentals are unavailable from the current providers; missing values are not zero.")
    if payload.get('reported_financials'):
        st.markdown("#### SEC Reported Financials")
        st.caption("Latest reported period for each metric, not TTM or a forecast. Periods can differ; compare the period and filing date before using these figures. USD/shares means dollars per share.")
        st.dataframe(pd.DataFrame(payload['reported_financials']), width="stretch", hide_index=True,
                     column_config={'Source': st.column_config.LinkColumn('SEC filing')})

    news_col, filing_col = st.columns(2)
    with news_col:
        st.markdown("### Latest News")
        st.caption("Only dated headlines from the last 7 days explicitly matching the company or ticker are shown. Identifiable quote, option-contract, search and shopping pages are excluded. This checks headline relevance, not full-text accuracy or materiality; open the source to confirm.")
        if payload["news"]:
            for item in payload["news"][:5]:
                title = html.escape(str(item.get("title") or "Untitled"))
                url = html.escape(str(item.get("url") or ""), quote=True)
                link = f'<a href="{url}" target="_blank">{title}</a>' if url else title
                meta = " · ".join(filter(None, [str(item.get("source") or ""), str(item.get("time_published") or ""), str(item.get("relevance_reason") or "")]))
                st.markdown(f'<div class="event-card">{link}<div class="event-meta">{html.escape(meta)}</div></div>', unsafe_allow_html=True)
        else:
            st.info("No sufficiently matched recent headlines are available. Uncertain matches are hidden. Check Data coverage & providers for source issues.")
    with filing_col:
        st.markdown("### SEC / Company Filings")
        if payload["filings"]:
            for item in payload["filings"][:5]:
                title = f"{item['type']} · {item['title']}"
                url = html.escape(item.get("url", ""), quote=True)
                link = f'<a href="{url}" target="_blank">{html.escape(title)}</a>' if url else html.escape(title)
                st.markdown(f'<div class="event-card">{link}<div class="event-meta">{html.escape(item["date"])}</div></div>', unsafe_allow_html=True)
        else:
            st.info("No company filings are available from the current sources. Check SEC configuration and provider status above.")

    st.markdown("### AI Key Takeaways")
    st.caption("AI summarizes only the displayed prices, fundamentals, and news. It does not provide price targets or trading instructions.")
    provider = compact_ai_provider()
    if provider:
        st.caption(f"Summary provider: {provider}")
    summary_key = f"compact_summary_{symbol}"
    if summary_key in st.session_state:
        st.markdown(st.session_state[summary_key])
    if st.button("Generate 3–5 Takeaways", key=f"summary_button_{symbol}"):
        if not has_compact_ai_key():
            st.warning("GEMINI_API_KEY or ANTHROPIC_API_KEY is not configured, so an AI summary cannot be generated.")
        else:
            try:
                with st.spinner("Preparing key takeaways…"):
                    summary = generate_compact_summary(symbol, prices, payload["news"], overview)
                st.session_state[summary_key] = summary
                st.rerun()
            except Exception as exc:
                st.error(f"AI summary is temporarily unavailable: {exc}")


def render_strategy_health() -> None:
    _header("Strategy Health", "V12 + E3 Strategy Health", "The same system checks and evidence panels for each frozen strategy.")
    _paper_banner()
    render_paired_page("health", _dashboard_state(), _e3_view())


def render_accounting() -> None:
    _header("Accounting", "V12 + E3 Accounting", "Cash, positions, costs and dividends for each independent account.")
    _paper_banner()
    render_paired_page("accounting", _dashboard_state(), _e3_view())


def main() -> None:
    _inject_style()
    with st.sidebar:
        st.markdown(
            '<div class="brand-kicker">FORWARD RESEARCH</div>'
            '<div class="brand-title">V12 + E3 Dashboard</div>'
            '<div class="brand-meta">V12 + E3 paper accounts<br>Read-only interface</div>',
            unsafe_allow_html=True,
        )
        st.divider()
    navigation = st.navigation({"V12 + E3": [
        st.Page(render_overview, title="Overview", default=True),
        st.Page(render_activity, title="Activity"),
        st.Page(render_market, title="Market Intelligence"),
        st.Page(render_strategy_health, title="Strategy Health"),
        st.Page(render_accounting, title="Accounting", url_path="accounting"),
    ], "Research reference": [
        st.Page(render_v3_dashboard, title="V3 Accounting"),
        st.Page(render_e3_dashboard, title="E3 Forward Paper", url_path="e3-forward-paper"),
    ]})
    navigation.run()
    st.markdown('<div class="footer-note">For education and research only. Paper trading is not a real execution, and past performance does not predict future results.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
