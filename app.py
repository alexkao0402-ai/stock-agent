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
from src.dashboard_read_model import (
    DEFAULT_LEDGER_PATH,
    HISTORICAL_SHARPE,
    build_dashboard_snapshot,
)
from src.dashboard_ui import (
    header as _header,
    inject_style as _inject_style,
    latest_curve_date,
    money as _money,
    number as _number,
    paper_banner as _paper_banner,
    pct as _pct,
    selection_cards,
    selection_rows,
    signed_money as _signed_money,
    status_badge as _status_badge,
    timeline,
)
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
                "title": str(item.get("title") or item.get("description") or "Company filing"),
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
    overview = get_company_overview(symbol)
    news = get_news_sentiment(symbol, limit=10)
    events = _yahoo_company_events(symbol)
    return {
        "prices": prices,
        "overview": overview,
        "news": news,
        "source": source,
        "provider_status": [
            {"Data": "Prices", "Provider": source, "Status": "Available" if not prices.empty else "Unavailable"},
            {"Data": "Fundamentals", "Provider": "Alpha Vantage", "Status": "Available" if overview else "Unavailable"},
            {"Data": "News", "Provider": "Alpha Vantage", "Status": "Available" if news else "Unavailable"},
            {"Data": "Earnings / Filings", "Provider": "Yahoo Finance", "Status": "Available" if events["earnings"] or events["filings"] else "Unavailable"},
        ],
        **events,
    }


def render_overview() -> None:
    _header("Portfolio", "Overview / Paper Trading", "Current paper portfolio, performance, and latest monthly rebalance.")
    _paper_banner()
    state = _dashboard_state()
    latest_valuation = latest_curve_date(state)
    if state["integrity_error"]:
        st.error(f"Dashboard sync error: {state['integrity_error']}")
    columns = st.columns(5)
    columns[0].metric("Portfolio Value", _money(state["portfolio_value"]))
    columns[1].metric("Cumulative Return", _pct(state["cumulative_return"]))
    columns[2].metric("vs SPY", _pct(state["excess_vs_spy"], points=True))
    columns[3].metric("vs QQQ", _pct(state["excess_vs_qqq"], points=True))
    columns[4].metric("MDD", _pct(state["max_drawdown"]))

    st.markdown("### V12 vs SPY vs QQQ")
    curve = state["curve"]
    if state["formal_forward_rows"] == 0 or curve.empty:
        st.markdown('<div class="empty-state"><h3>The first official Forward Signal has not been generated</h3><p>The Dashboard never presents backtest or illustrative values as Forward performance.</p></div>', unsafe_allow_html=True)
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
        portfolio_value = f'{len(state["holdings"])} holdings'
        lines = []
        for position in state["holdings"]:
            weight = position.get("target_weight")
            weight_text = "—" if weight is None else f"{float(weight):.0%}"
            lines.append(f'{html.escape(str(position.get("ticker") or "—"))} · {weight_text}')
        portfolio_detail = f'{"<br>".join(lines)}<br>Cash · {_money(state["cash"])}'
    else:
        portfolio_value = "0 holdings"
        portfolio_detail = "Waiting for the first official Forward allocation<br>Cash · —"
    if state["latest_signal"] is None:
        signal_value = "Not generated"
        signal_detail = "Waiting for the official month-end signal<br>SPY Regime · —"
    else:
        signal_value = html.escape(state["signal_date"] or "—")
        selections = " · ".join(f"{ticker} {weight:.0%}" for ticker, weight in state["target_weights"].items()) or "—"
        signal_detail = f'SPY Regime · {html.escape(state["market_regime"] or "—")}<br>{html.escape(selections)}'
    execution_value = html.escape(state["execution_status"])
    execution_detail = f'Scheduled execution · {html.escape(state["execution_date"] or "—")}<br>Execution rule · T+1 Open'
    st.markdown(
        f'''
        <div class="overview-card-grid">
          <section class="overview-card"><div class="overview-card-kicker">PORTFOLIO</div><div class="overview-card-title">Current Holdings & Cash</div><div class="overview-card-value">{portfolio_value}</div><div class="overview-card-detail">{portfolio_detail}</div></section>
          <section class="overview-card"><div class="overview-card-kicker">LATEST SIGNAL</div><div class="overview-card-title">Latest V12 Signal</div><div class="overview-card-value">{signal_value}</div><div class="overview-card-detail">{signal_detail}</div></section>
          <section class="overview-card"><div class="overview-card-kicker">EXECUTION</div><div class="overview-card-title">T+1 Execution</div><div class="overview-card-value">{execution_value}</div><div class="overview-card-detail">{execution_detail}</div></section>
        </div>
        ''',
        unsafe_allow_html=True,
    )

    st.markdown("### Why V12 Holds These Stocks")
    st.caption(
        "These explanations come from the immutable V7/V8 selections saved with the official signal. AI does not decide the allocation."
    )
    selection_cards(selection_rows(state))

    if state.get("holdings"):
        st.markdown("### Portfolio P/L & Contribution")
        pnl_metrics = st.columns(4)
        pnl_metrics[0].metric("Realized P/L", _signed_money(state.get("realized_pnl")))
        pnl_metrics[1].metric("Unrealized P/L", _signed_money(state.get("unrealized_pnl")))
        pnl_metrics[2].metric(
            "Cumulative Trading Costs",
            _money(state.get("cumulative_transaction_costs")),
        )
        pnl_metrics[3].metric(
            "Latest Valuation",
            latest_valuation or "—",
        )
        if any(
            state.get(field) is None
            for field in (
                "realized_pnl",
                "unrealized_pnl",
                "cumulative_transaction_costs",
            )
        ):
            st.caption(
                "Detailed position P/L will populate after the next signed cloud "
                "valuation snapshot. Missing values are not estimated."
            )
        holding_rows = []
        for position in state["holdings"]:
            holding_rows.append({
                "Ticker": position["ticker"],
                "Current Weight": position.get("current_weight"),
                "Target Weight": position.get("target_weight"),
                "Market Value": position.get("market_value"),
                "Unrealized P/L": position.get("unrealized_pnl"),
            })
        st.dataframe(
            pd.DataFrame(holding_rows),
            width="stretch",
            hide_index=True,
            column_config={
                "Current Weight": st.column_config.ProgressColumn(
                    "Current Weight", min_value=0.0, max_value=1.0, format="percent"
                ),
                "Target Weight": st.column_config.NumberColumn(
                    "Target", format="percent"
                ),
                "Market Value": st.column_config.NumberColumn(
                    "Market Value", format="$%.2f"
                ),
                "Unrealized P/L": st.column_config.NumberColumn(
                    "Unrealized P/L", format="$%.2f"
                ),
            },
        )

    st.markdown("### Latest Rebalance")
    latest_trades = state.get("latest_trades") or []
    if latest_trades:
        execution_date = latest_trades[0].get("execution_date") or state.get("execution_date") or "—"
        st.caption(f"Executed {execution_date} · T+1 market open")
        exited = [row["ticker"] for row in latest_trades if row["action"] == "SELL" and not row.get("is_trim")]
        trimmed = [
            f'{row["ticker"]} to {float(row.get("target_weight") or 0.0):.0%}'
            for row in latest_trades if row.get("is_trim")
        ]
        opened = [
            f'{row["ticker"]} at {float(row.get("target_weight") or 0.0):.0%}'
            for row in latest_trades if row["action"] == "BUY" and float(row.get("before_shares") or 0.0) <= 1e-9
        ]
        topped_up = [
            f'{row["ticker"]} toward {float(row.get("target_weight") or 0.0):.0%}'
            for row in latest_trades if row["action"] == "BUY" and float(row.get("before_shares") or 0.0) > 1e-9
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
        if changes:
            st.info("V12 " + "; ".join(changes) + ".")

        trade_metrics = st.columns(4)
        trade_metrics[0].metric("Bought", _money(state.get("latest_buy_value")))
        trade_metrics[1].metric("Sold", _money(state.get("latest_sell_value")))
        costs = state.get("latest_transaction_costs")
        if costs is None:
            costs = state.get("latest_trade_fees")
        trade_metrics[2].metric("Trading Costs", _money(costs))
        turnover = state.get("latest_turnover")
        trade_metrics[3].metric("Portfolio Changed", "—" if turnover is None else f"{float(turnover):.1%}")
        rows = []
        for trade in latest_trades:
            side = trade["action"]
            if trade.get("is_trim"):
                side = "SELL · TRIM"
            rows.append({
                "Action": side,
                "Ticker": trade["ticker"],
                "Trade Value": _money(trade["trade_value"]),
                "Realized P/L": _signed_money(trade.get("realized_pnl")),
                "Target": "—" if trade.get("target_weight") is None else f'{float(trade["target_weight"]):.0%}',
                "Reason": trade.get("reason") or "Monthly rebalance",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        next_signal = state.get("next_signal_date")
        next_execution = state.get("next_execution_date")
        if next_signal and next_execution:
            st.caption(f"Next expected cycle · Signal after {next_signal} close → simulated execution at {next_execution} open")
        st.caption("Realized P/L is shown only for sales and includes commission. Portfolio Changed shows the larger of purchases or sales as a percentage of execution-day portfolio value.")
        with st.expander("Execution audit details"):
            audit_rows = [{
                "Side": "SELL · TRIM" if trade.get("is_trim") else trade["action"],
                "Ticker": trade["ticker"],
                "Before": f'{float(trade.get("before_shares") or 0.0):,.4f}',
                "Change": f'{float(trade["shares"]) if trade["action"] == "BUY" else -float(trade["shares"]):+,.4f}',
                "After": f'{float(trade.get("after_shares") or 0.0):,.4f}',
                "Shares": f'{trade["shares"]:,.4f}',
                "Fill Price": _money(trade["fill_price"]),
                "Trade Value": _money(trade["trade_value"]),
                "Commission": _money(trade["fee"]),
                "Slippage": _money(trade.get("slippage_cost")),
            } for trade in latest_trades]
            st.dataframe(pd.DataFrame(audit_rows), width="stretch", hide_index=True)
            st.caption("SELL · TRIM means the stock remained selected and only the excess above its target weight was sold.")
    elif state["latest_signal"] is not None and state["execution_status"] != "Executed":
        st.info("The latest signal is waiting for execution. Trade details will appear here after the T+1 open.")
    elif state["latest_signal"] is not None:
        st.info("No trades were required because the portfolio already matched the latest target weights.")

    st.markdown("### Automation Timeline")
    next_signal = state.get("next_signal_date") or "Waiting"
    next_execution = state.get("next_execution_date") or "Waiting"
    timeline([
        ("Latest signal", state.get("signal_date") or "Not generated"),
        (
            "T+1 execution",
            f'{state.get("execution_status") or "—"} · {state.get("execution_date") or "—"}',
        ),
        ("Latest valuation", latest_valuation or "Waiting"),
        ("Next cycle", f"{next_signal} close → {next_execution} open"),
    ])


def render_market() -> None:
    _header("Market Intelligence", "Market Intelligence", "Prices, earnings, material news, and company filings in one concise view.")
    search, action = st.columns([5, 1])
    with search:
        symbol = st.text_input("Ticker", value=st.session_state.get("market_symbol", ""), placeholder="For example: AAPL or NVDA", label_visibility="collapsed").strip().upper()
    with action:
        clicked = st.button("Search", type="primary", width="stretch")
    if clicked:
        st.session_state["market_symbol"] = symbol
    symbol = st.session_state.get("market_symbol", "")
    if not symbol:
        st.info("Enter a ticker and select Search. Opening this page does not automatically call external data or AI APIs.")
        return

    with st.spinner(f"Loading market data for {symbol}…"):
        payload = _market_payload(symbol)
    prices = payload["prices"]
    if prices.empty:
        st.error("Price data is unavailable. Check the ticker or try again later.")
        return
    overview = payload["overview"] or {}
    current = float(prices["close"].iloc[-1])
    previous = float(prices["close"].iloc[-2]) if len(prices) > 1 else current
    daily_change = current / previous - 1 if previous else 0.0
    company = overview.get("公司名稱") or symbol
    st.markdown(f"### {html.escape(symbol)} · {html.escape(str(company))}")
    price_col, meta_col = st.columns([1, 2])
    price_col.metric("Latest Close", _money(current), f"{daily_change:+.2%}")
    meta_col.caption(f"Source: {payload['source']} · As of {prices['date'].iloc[-1]} · Delayed data")
    with st.expander("Data coverage & providers"):
        st.dataframe(
            pd.DataFrame(payload["provider_status"]),
            width="stretch",
            hide_index=True,
        )
        st.caption("Unavailable sections do not affect Frozen V12. They only limit the Market Intelligence view.")

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

    st.markdown("### Earnings & Fundamentals")
    metrics = st.columns(5)
    metrics[0].metric("Market Cap", _number(overview.get("市值"), currency=True))
    metrics[1].metric("P/E", _number(overview.get("本益比")))
    metrics[2].metric("EPS", _number(overview.get("每股盈餘"), currency=True))
    metrics[3].metric("Gross Margin", "—" if overview.get("毛利率") is None else f"{overview['毛利率']:.2f}%")
    try:
        operating_margin = float(overview["營業利益率"])
    except (KeyError, TypeError, ValueError):
        operating_margin = None
    metrics[4].metric("Operating Margin", _pct(operating_margin))
    if payload["earnings"]:
        with st.expander("Recent / Scheduled Earnings", expanded=True):
            st.dataframe(pd.DataFrame(payload["earnings"]).rename(columns={"date": "Date", "estimate": "EPS Estimate", "reported": "Reported EPS", "surprise": "Surprise"}), width="stretch", hide_index=True)
    elif not has_alpha_vantage_key():
        st.caption("Alpha Vantage is not configured; some earnings and fundamental fields may be unavailable.")

    news_col, filing_col = st.columns(2)
    with news_col:
        st.markdown("### Material News")
        if payload["news"]:
            for item in payload["news"][:5]:
                title = html.escape(str(item.get("title") or "Untitled"))
                url = html.escape(str(item.get("url") or ""), quote=True)
                link = f'<a href="{url}" target="_blank">{title}</a>' if url else title
                meta = " · ".join(filter(None, [str(item.get("source") or ""), str(item.get("time_published") or "")]))
                st.markdown(f'<div class="event-card">{link}<div class="event-meta">{html.escape(meta)}</div></div>', unsafe_allow_html=True)
        else:
            st.info("No news is currently available. Configure ALPHAVANTAGE_API_KEY to add news coverage.")
    with filing_col:
        st.markdown("### SEC / Company Filings")
        if payload["filings"]:
            for item in payload["filings"][:5]:
                title = f"{item['type']} · {item['title']}"
                url = html.escape(item.get("url", ""), quote=True)
                link = f'<a href="{url}" target="_blank">{html.escape(title)}</a>' if url else html.escape(title)
                st.markdown(f'<div class="event-card">{link}<div class="event-meta">{html.escape(item["date"])}</div></div>', unsafe_allow_html=True)
        else:
            st.info("Yahoo Finance did not return any available SEC or company filings.")

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
    _header(
        "Strategy Health",
        "Strategy & System Health",
        "Understand whether automation is safe, what V12 is doing now, and whether Forward results are becoming unusual.",
    )
    _paper_banner()
    state = _dashboard_state()

    st.markdown("### What can you learn here?")
    summary = st.columns(3)
    with summary[0]:
        with st.container(border=True):
            st.markdown("#### Can the system continue?")
            st.metric("Operational status", "BLOCKED" if state["trading_blocked"] else "READY")
            st.caption("A blocked status means the ledger, data, synchronization, or T+1 execution needs attention before another trade.")
    with summary[1]:
        with st.container(border=True):
            st.markdown("#### What is V12 doing?")
            posture = "INVESTED" if state.get("market_regime") == "BULL" and state.get("target_weights") else "CASH / WAITING"
            st.metric("Current posture", posture)
            st.caption("SPY regime controls whether Frozen V12 may hold stocks. It does not predict tomorrow's market direction.")
    with summary[2]:
        with st.container(border=True):
            st.markdown("#### Can performance be judged?")
            maturity = "BUILDING SAMPLE" if state.get("rolling_sharpe") is None else state["health_label"].upper()
            st.metric("Forward evidence", maturity)
            st.caption("Until enough official daily observations exist, weak or strong short-term returns are not reliable evidence.")

    st.markdown("### Current interpretation")
    if state["trading_blocked"]:
        st.error("Trading is blocked by the system: " + (state["integrity_error"] or state["execution_status"]))
    else:
        allocation = " · ".join(
            f"{ticker} {float(weight):.0%}"
            for ticker, weight in (state.get("target_weights") or {}).items()
        ) or "Cash / no allocation"
        st.success(
            f"No operational action is required. Latest signal: {state.get('signal_date') or '—'}; "
            f"execution: {state.get('execution_status') or '—'}; allocation: {allocation}."
        )
    for warning in state.get("warnings") or []:
        st.warning(f"Research watch only — {warning}. This does not change or stop Frozen V12.")

    st.markdown("### Automation pipeline")
    sync_time = state.get("snapshot_generated_at") or state.get("last_event_created_at") or "—"
    timeline([
        ("Data", state.get("last_data_asof") or "Waiting"),
        ("Signal", state.get("signal_date") or "Not generated"),
        ("Execution", state.get("execution_status") or "—"),
        ("Dashboard sync", sync_time),
    ])

    st.markdown("### System safety checks")
    st.caption("These checks answer whether the displayed records and the next automated cycle can be trusted.")
    operational_metrics = st.columns(4)
    operational_metrics[0].metric("V12 Status", "FROZEN")
    operational_metrics[1].metric("Ledger", "Verified" if state.get("ledger_verified") else "Unavailable")
    operational_metrics[2].metric("T+1 Execution", state["execution_status"])
    operational_metrics[3].metric(
        "Cloud Snapshot",
        "Verified" if state.get("snapshot_generated_at") else "Local read",
    )
    source_commit = str(state.get("source_commit") or "")
    source_text = source_commit[:8] if source_commit else "local checkout"
    st.caption(
        f'Data as of {state.get("last_data_asof") or "—"} · '
        f'{int(state.get("ledger_event_count") or 0)} verified ledger events · '
        f'Source {source_text}'
    )

    with st.expander("What would block trading?"):
        st.write("- Ledger hash, schema, or signed snapshot verification failure")
        st.write("- A signal exists without orders, or its T+1 execution is overdue")
        st.write("- Incomplete prices, timestamp errors, or failed accounting reconciliation")

    st.markdown("### Strategy evidence")
    st.caption("This section asks whether live paper results still resemble the behavior expected from the frozen research. It never changes the strategy automatically.")
    evidence = st.columns(4)
    evidence[0].metric("SPY Regime", state["market_regime"] or "—")
    agreement = "—" if state["agreement_count"] is None else f"{state['agreement_count']} overlapping"
    evidence[1].metric("V7 / V8 agreement", agreement)
    evidence[2].metric("Forward Drawdown", _pct(state["max_drawdown"]))
    evidence[3].metric("Official Allocation Batches", str(state["formal_forward_rows"]))

    second = st.columns(4)
    second[0].metric("12M Rolling Sharpe", "Waiting" if state["rolling_sharpe"] is None else f"{state['rolling_sharpe']:.2f}")
    second[1].metric("Forward vs Backtest", "Waiting" if state["sharpe_deviation"] is None else f"{state['sharpe_deviation']:+.2f} Sharpe")
    second[2].metric("T+1 Return", _pct(state["t1_return"]))
    second[3].metric("T+2 / Difference", "—" if state["t2_return"] is None else f"{_pct(state['t2_return'])} / {_pct(state['t1_t2_spread'], points=True)}")

    with st.expander("How to read these strategy metrics", expanded=True):
        st.markdown(
            """
            - **SPY Regime:** `BULL` permits stock exposure; an unfavorable regime moves V12 to cash according to the frozen rule.
            - **V7 / V8 agreement:** shows whether the two frozen ranking components selected the same stocks. Agreement explains the final weights; it is not a probability of profit.
            - **Forward Drawdown:** the decline from the highest official paper value. At **−20%**, research review begins, but the strategy is not automatically altered.
            - **12M Rolling Sharpe:** return earned per unit of volatility over 252 official daily observations. `Waiting` means the sample is still too small—not that the strategy failed.
            - **Forward vs Backtest:** compares Forward Sharpe with the frozen historical reference only after enough Forward data exists.
            - **T+1 vs T+2:** shows how sensitive results are to executing one day later. A large persistent gap may reveal execution fragility.
            """
        )
    st.caption(f"Historical reference only · Frozen V12 Sharpe {HISTORICAL_SHARPE:.2f}. Backtest results are never mixed into official Forward returns.")
    st.info("Use this page to detect operational failures or persistent strategy deterioration—not to create discretionary buy/sell signals. Weak short-term performance can warn you, but it cannot modify Frozen V12.")


def main() -> None:
    _inject_style()
    with st.sidebar:
        st.markdown("## ◈ V12")
        st.caption("Forward Research System")
        st.divider()
        st.caption("Frozen strategy · Read-only dashboard")
    navigation = st.navigation([
        st.Page(render_overview, title="Overview / Paper Trading", icon="📊", default=True),
        st.Page(render_market, title="Market Intelligence", icon="📰"),
        st.Page(render_strategy_health, title="Strategy Health", icon="🛡️"),
    ])
    navigation.run()
    st.markdown('<div class="footer-note">For education and research only. Paper trading is not a real execution, and past performance does not predict future results.</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
