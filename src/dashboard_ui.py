"""Reusable presentation helpers for the read-only V12 Streamlit dashboard."""
from __future__ import annotations

import html
from datetime import datetime, time, timedelta, timezone
from typing import Any

import streamlit as st
from src.trading_calendar import is_session, previous_session


def inject_style() -> None:
    st.markdown(
        """
        <style>
        :root {
          --bg:#09090b; --bg-secondary:#0d0d10; --surface:#111114;
          --surface-raised:#16161a; --line:rgba(255,255,255,.09);
          --line-soft:rgba(255,255,255,.055); --text:#f4f4f5;
          --text-secondary:#a1a1aa; --muted:#71717a; --accent:#39d98a;
          --amber:#e8b84b; --red:#ef6b73;
        }
        html { color-scheme:dark; }
        body, .stApp, [class*="css"] {
          font-family:Inter,Geist,"SF Pro Display","Segoe UI",sans-serif;
        }
        header[data-testid="stHeader"] {
          background:rgba(9,9,11,.92); border-bottom:1px solid var(--line-soft);
          backdrop-filter:blur(12px);
        }
        .stApp { background:var(--bg); color:var(--text); }
        .block-container { max-width:1180px; padding-top:4.2rem; padding-bottom:4rem; }
        section[data-testid="stSidebar"] {
          background:var(--bg-secondary); border-right:1px solid var(--line);
        }
        section[data-testid="stSidebar"] [data-testid="stSidebarNav"] { padding-top:.35rem; }
        section[data-testid="stSidebar"] a {
          border-radius:8px; transition:background-color 180ms ease,color 180ms ease;
        }
        section[data-testid="stSidebar"] a:hover { background:rgba(255,255,255,.045); }
        section[data-testid="stSidebar"] a[aria-current="page"] {
          color:var(--text); background:rgba(57,217,138,.075);
          box-shadow:inset 2px 0 0 var(--accent);
        }
        .brand-kicker { color:var(--accent); font-size:.68rem; font-weight:760; letter-spacing:.16em; }
        .brand-title { color:var(--text); font-size:1.15rem; font-weight:720; letter-spacing:-.02em; margin:.25rem 0; }
        .brand-meta { color:var(--muted); font-size:.78rem; line-height:1.55; }
        .eyebrow { color:var(--accent); font-size:.72rem; font-weight:730; letter-spacing:.14em; text-transform:uppercase; }
        .page-title { color:var(--text); font-size:clamp(1.85rem,4vw,2.65rem); font-weight:720; letter-spacing:-.045em; margin:.3rem 0 .3rem; line-height:1.1; }
        .page-subtitle { color:var(--text-secondary); max-width:740px; margin-bottom:1.45rem; line-height:1.55; }
        .paper-banner { padding:.72rem 1rem; border:1px solid rgba(232,184,75,.34); border-radius:10px; color:var(--amber); background:rgba(232,184,75,.045); font-size:.78rem; font-weight:720; letter-spacing:.11em; text-align:center; margin:.25rem 0 1.4rem; }
        .status-badge { display:inline-flex; align-items:center; gap:.5rem; padding:.44rem .7rem; border-radius:8px; font-size:.83rem; font-weight:700; border:1px solid currentColor; }
        .status-normal { color:var(--accent); background:rgba(57,217,138,.055); }
        .status-watch { color:var(--amber); background:rgba(232,184,75,.055); }
        .status-error { color:var(--red); background:rgba(239,107,115,.055); }
        .empty-state { padding:2.75rem 1.25rem; border:1px dashed rgba(255,255,255,.15); border-radius:12px; text-align:center; background:var(--bg-secondary); }
        .empty-state h3 { margin:0 0 .45rem; }
        .empty-state p { color:var(--text-secondary); margin:0; }
        .overview-card-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1rem; margin:.15rem 0 1.25rem; }
        .overview-card { min-width:0; min-height:218px; padding:1.25rem; border:1px solid var(--line); border-radius:12px; background:var(--surface); display:flex; flex-direction:column; box-sizing:border-box; transition:border-color 180ms ease,background-color 180ms ease; }
        .overview-card:hover { border-color:rgba(255,255,255,.15); background:var(--surface-raised); }
        .overview-card-kicker { color:var(--accent); font-size:.68rem; font-weight:740; letter-spacing:.13em; margin-bottom:.55rem; }
        .overview-card-title { color:var(--text-secondary); font-size:.9rem; font-weight:610; min-height:1.5rem; }
        .overview-card-value { color:var(--text); font-size:1.65rem; font-weight:690; line-height:1.15; margin-top:1.25rem; font-variant-numeric:tabular-nums; }
        .overview-card-detail { color:var(--text-secondary); font-size:.85rem; line-height:1.6; margin-top:auto; padding-top:1rem; }
        .selection-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.8rem; margin:.5rem 0 1.25rem; }
        .selection-card { min-width:0; padding:1rem; border:1px solid var(--line); border-radius:12px; background:var(--surface); transition:border-color 180ms ease; }
        .selection-card:hover { border-color:rgba(57,217,138,.28); }
        .selection-top { display:flex; align-items:baseline; justify-content:space-between; gap:.75rem; }
        .selection-ticker { font-size:1.15rem; font-weight:700; }
        .selection-weight { color:var(--accent); font-size:1rem; font-weight:680; font-variant-numeric:tabular-nums; }
        .selection-support { color:var(--text-secondary); font-size:.72rem; font-weight:700; letter-spacing:.08em; margin:.55rem 0 .35rem; }
        .selection-reason { color:var(--muted); font-size:.83rem; line-height:1.55; }
        .timeline { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.7rem; margin:.5rem 0 1.25rem; }
        .timeline-step { min-width:0; padding:.9rem; border:1px solid var(--line-soft); border-left:2px solid var(--accent); border-radius:0 9px 9px 0; background:var(--surface); }
        .timeline-label { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.08em; }
        .timeline-value { margin-top:.35rem; font-weight:650; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
        .health-strip { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); border:1px solid var(--line); border-radius:12px; overflow:hidden; background:var(--surface); margin:.4rem 0 1.4rem; }
        .health-cell { min-width:0; padding:1.15rem; border-right:1px solid var(--line); }
        .health-cell:last-child { border-right:0; }
        .health-label { color:var(--muted); font-size:.7rem; font-weight:720; letter-spacing:.1em; text-transform:uppercase; }
        .health-value { color:var(--text); font-size:1.25rem; font-weight:680; margin:.55rem 0 .4rem; font-variant-numeric:tabular-nums; }
        .health-copy { color:var(--text-secondary); font-size:.82rem; line-height:1.5; }
        .section-note { color:var(--text-secondary); font-size:.82rem; margin-top:-.35rem; margin-bottom:.8rem; }
        .footer-note { color:var(--muted); text-align:center; font-size:.78rem; margin-top:2.8rem; }
        h1,h2,h3,h4 { color:var(--text); letter-spacing:-.025em; }
        h3 { margin-top:1.65rem !important; }
        div[data-testid="stMetric"] { min-height:116px; border:1px solid var(--line); border-radius:12px; padding:.95rem; background:var(--surface); box-shadow:none; transition:border-color 180ms ease; }
        div[data-testid="stMetric"]:hover { border-color:rgba(255,255,255,.15); }
        div[data-testid="stMetricLabel"] { color:var(--text-secondary); }
        div[data-testid="stMetricValue"] { color:var(--text); font-size:clamp(1.3rem,2.6vw,1.95rem); font-variant-numeric:tabular-nums; }
        div[data-testid="stMetricDelta"] { font-variant-numeric:tabular-nums; }
        div[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:10px; overflow-x:auto; }
        div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--line) !important; background:var(--surface); border-radius:12px !important; }
        div[data-testid="stExpander"] { border-color:var(--line) !important; border-radius:10px !important; background:var(--surface); }
        .event-card { border:1px solid var(--line); border-radius:10px; padding:.9rem; background:var(--surface); margin-bottom:.6rem; transition:border-color 180ms ease; }
        .event-card:hover { border-color:rgba(255,255,255,.15); }
        .event-card a { color:var(--text); text-decoration:none; }
        .event-card a:hover { color:var(--accent); }
        .event-meta { color:var(--muted); font-size:.78rem; margin-top:.35rem; }
        .stButton > button { border-radius:9px; border:1px solid var(--line); transition:all 180ms ease; }
        .stButton > button[kind="primary"] { background:var(--accent); color:#07130d; border-color:var(--accent); font-weight:700; }
        .stButton > button[kind="primary"]:hover { background:#4be49a; border-color:#4be49a; }
        [data-testid="stAlert"] { border-radius:10px; border:1px solid var(--line-soft); }
        code, pre, [data-testid="stDataFrame"] { font-variant-numeric:tabular-nums; }
        @media (max-width:720px) {
          .block-container { padding:4rem .75rem 3rem; }
          .overview-card-grid, .selection-grid { grid-template-columns:1fr; gap:.7rem; }
          .timeline { grid-template-columns:repeat(2,minmax(0,1fr)); gap:.55rem; }
          .health-strip { grid-template-columns:1fr; }
          .health-cell { border-right:0; border-bottom:1px solid var(--line); }
          .health-cell:last-child { border-bottom:0; }
          .overview-card { min-height:178px; }
          div[data-testid="stMetric"] { min-height:98px; padding:.75rem; }
          div[data-testid="stMetricValue"] { font-size:1.28rem; overflow-wrap:anywhere; }
          .paper-banner { font-size:.7rem; letter-spacing:.075em; }
          .page-subtitle { font-size:.9rem; }
          [data-testid="stHorizontalBlock"] { gap:.55rem; }
          div[data-testid="stDataFrame"] { max-width:calc(100vw - 1.5rem); }
        }
        @media (max-width:440px) {
          .timeline { grid-template-columns:1fr; }
          .overview-card-value { font-size:1.45rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def header(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="page-title">{html.escape(title)}</div>'
        f'<div class="page-subtitle">{html.escape(subtitle)}</div>',
        unsafe_allow_html=True,
    )


def paper_banner() -> None:
    st.markdown(
        '<div class="paper-banner">FORWARD PAPER TRADING · NOT LIVE CAPITAL</div>',
        unsafe_allow_html=True,
    )


def status_badge(status: str, label: str) -> None:
    css = {"NORMAL": "normal", "WATCH": "watch", "ERROR": "error"}.get(
        status, "watch"
    )
    st.markdown(
        f'<span class="status-badge status-{css}"><span aria-hidden="true">●</span> {html.escape(label)}</span>',
        unsafe_allow_html=True,
    )


def money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def signed_money(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else "−"
    return f"{sign}${abs(value):,.2f}"


def pct(value: float | None, *, points: bool = False) -> str:
    if value is None:
        return "—"
    suffix = " pp" if points else "%"
    return f"{value * 100:+.2f}{suffix}"


def number(value: Any, *, currency: bool = False) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(parsed) >= 1_000_000_000_000:
        result = f"{parsed / 1_000_000_000_000:.2f}T"
    elif abs(parsed) >= 1_000_000_000:
        result = f"{parsed / 1_000_000_000:.2f}B"
    elif abs(parsed) >= 1_000_000:
        result = f"{parsed / 1_000_000:.2f}M"
    else:
        result = f"{parsed:,.2f}"
    return f"${result}" if currency else result


def selection_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return saved explanations, with a display-only fallback for old snapshots."""
    existing = state.get("selection_explanations") or []
    if existing:
        return list(existing)

    weights = state.get("target_weights") or {}
    v7 = set(state.get("v7_selected") or [])
    v8 = set(state.get("v8_selected") or [])
    rows: list[dict[str, Any]] = []
    for ticker, raw_weight in sorted(
        weights.items(), key=lambda item: (-float(item[1]), str(item[0]))
    ):
        in_v7 = ticker in v7
        in_v8 = ticker in v8
        if in_v7 and in_v8:
            support = "V7 + V8"
            reason = (
                "Selected by both frozen momentum components; consensus receives "
                "the larger allocation."
            )
        elif in_v7:
            support = "V7"
            reason = "Selected by the frozen 12–1 momentum component."
        elif in_v8:
            support = "V8"
            reason = (
                "Selected by the frozen 3–1 / 6–1 / 12–1 composite momentum "
                "component."
            )
        else:
            support = "Frozen V12"
            reason = "Saved in the official immutable target allocation."
        rows.append(
            {
                "ticker": str(ticker),
                "target_weight": float(raw_weight),
                "support": support,
                "reason": reason,
            }
        )
    return rows


def latest_curve_date(state: dict[str, Any]) -> str | None:
    """Use the explicit valuation date or the latest immutable curve observation."""
    explicit = state.get("latest_valuation_date")
    if explicit:
        return str(explicit)
    curve = state.get("curve")
    if curve is None or getattr(curve, "empty", True) or "date" not in curve:
        return None
    dates = curve["date"].dropna()
    if dates.empty:
        return None
    latest = dates.max()
    try:
        return latest.strftime("%Y-%m-%d")
    except AttributeError:
        return str(latest)[:10]


def selection_cards(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    cards = []
    for row in rows:
        cards.append(
            '<section class="selection-card">'
            '<div class="selection-top">'
            f'<div class="selection-ticker">{html.escape(str(row.get("ticker") or "—"))}</div>'
            f'<div class="selection-weight">{float(row.get("target_weight") or 0.0):.0%}</div>'
            '</div>'
            f'<div class="selection-support">{html.escape(str(row.get("support") or "—"))}</div>'
            f'<div class="selection-reason">{html.escape(str(row.get("reason") or ""))}</div>'
            '</section>'
        )
    st.markdown(
        '<div class="selection-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def timeline(steps: list[tuple[str, str]]) -> None:
    cards = "".join(
        '<section class="timeline-step">'
        f'<div class="timeline-label">{html.escape(label)}</div>'
        f'<div class="timeline-value">{html.escape(value)}</div>'
        '</section>'
        for label, value in steps
    )
    st.markdown(f'<div class="timeline">{cards}</div>', unsafe_allow_html=True)


def activity_event_rows(state: dict[str, Any]) -> list[dict[str, str]]:
    """Return a compact, newest-first projection of immutable ledger events."""
    rows: list[dict[str, str]] = []
    for event in reversed(list(state.get("events") or [])):
        rows.append({
            "Time": str(event.get("created_at") or "—"),
            "Portfolio": str(event.get("portfolio_id") or "—"),
            "Event": str(event.get("event_type") or "—"),
            "Ticker": str(event.get("ticker") or "—"),
            "Action": str(event.get("action") or "—"),
            "Data As Of": str(event.get("data_asof") or "—"),
        })
    return rows


def freshness_status(state: dict[str, Any], *, now: datetime | None = None) -> tuple[str, str]:
    """Allow 90 minutes after the scheduled 23:30 UTC publication cycle."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current = current.astimezone(timezone.utc)
    candidate = current.date() - timedelta(days=1)
    if current.time() < time(1):
        candidate -= timedelta(days=1)
    if not is_session(candidate):
        candidate = previous_session(candidate)
    raw = latest_curve_date(state)
    if not raw:
        return "UNAVAILABLE", "Valuation date unavailable. Check dashboard synchronization."
    try:
        valuation = datetime.fromisoformat(raw[:10]).date()
    except ValueError:
        return "UNAVAILABLE", "Valuation date is invalid. Check dashboard synchronization."
    if valuation < candidate:
        return "DELAYED", f"Data update delayed: expected prices through {candidate}; currently {valuation}. Check the latest automation run."
    if valuation > current.date():
        return "UNAVAILABLE", "Valuation date is in the future. Check dashboard synchronization."
    return "CURRENT", f"Data is current for the publication schedule (latest required session: {candidate})."


def trade_activity_rows(trades: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Format execution rows without changing the signed trade evidence."""
    rows: list[dict[str, str]] = []
    for trade in trades:
        action = str(trade.get("action") or "—")
        if trade.get("is_trim"):
            action = "SELL · TRIM"
        target = trade.get("target_weight")
        reason = str(trade.get("reason") or "Monthly rebalance")
        if state is not None:
            ticker = trade.get("ticker")
            v7 = ticker in (state.get("v7_selected") or [])
            v8 = ticker in (state.get("v8_selected") or [])
            if v7 or v8:
                support = "V7 + V8 consensus" if v7 and v8 else "V7 12–1 momentum" if v7 else "V8 composite momentum"
                reason += f" · Selected by {support} in the saved {state.get('signal_date') or 'official'} signal."
            elif state.get("market_regime") and state.get("market_regime") != "BULL":
                reason += " · Saved market regime requires cash."
            elif state.get("v7_selected") is not None and state.get("v8_selected") is not None:
                reason += " · Not selected by either component in the saved signal."
            else:
                reason += " · Component evidence unavailable in this snapshot."
        rows.append({
            "Action": action,
            "Ticker": str(trade.get("ticker") or "—"),
            "Shares": f'{float(trade.get("shares") or 0.0):,.4f}',
            "Fill Price": money(trade.get("fill_price")),
            "Trade Value": money(trade.get("trade_value")),
            "Realized P/L": signed_money(trade.get("realized_pnl")),
            "Target": "—" if target is None else f"{float(target):.0%}",
            "Reason": reason,
        })
    return rows
