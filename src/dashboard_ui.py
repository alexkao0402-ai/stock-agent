"""Reusable presentation helpers for the read-only V12 Streamlit dashboard."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st


def inject_style() -> None:
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
        .selection-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:.8rem; margin:.5rem 0 1.25rem; }
        .selection-card { min-width:0; padding:1rem; border:1px solid var(--line); border-radius:14px; background:rgba(17,24,39,.66); }
        .selection-top { display:flex; align-items:baseline; justify-content:space-between; gap:.75rem; }
        .selection-ticker { font-size:1.2rem; font-weight:750; }
        .selection-weight { color:var(--green); font-size:1.05rem; font-weight:700; }
        .selection-support { color:var(--cyan); font-size:.78rem; font-weight:700; letter-spacing:.07em; margin:.55rem 0 .35rem; }
        .selection-reason { color:var(--muted); font-size:.86rem; line-height:1.55; }
        .timeline { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.7rem; margin:.5rem 0 1.25rem; }
        .timeline-step { min-width:0; padding:.9rem; border-left:3px solid var(--cyan); background:rgba(17,24,39,.55); }
        .timeline-label { color:var(--muted); font-size:.76rem; text-transform:uppercase; letter-spacing:.08em; }
        .timeline-value { margin-top:.35rem; font-weight:700; overflow-wrap:anywhere; }
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
          .overview-card-grid, .selection-grid, .timeline { grid-template-columns:1fr; gap:.75rem; }
          .overview-card { min-height:190px; }
          div[data-testid="stMetric"] { min-height:104px; padding:.8rem; }
          div[data-testid="stMetricValue"] { font-size:1.35rem; overflow-wrap:anywhere; }
          .paper-banner { font-size:.78rem; }
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
        f'<span class="status-badge status-{css}">● {html.escape(label)}</span>',
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
