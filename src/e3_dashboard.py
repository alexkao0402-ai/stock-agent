"""Read-only E3 display; deliberately does not import the frozen paper runner."""
from datetime import datetime, timedelta, timezone

from src.e3_dashboard_snapshot import E3DisplayError, load_display


def freshness(view, now=None):
    from src.trading_calendar import NEW_YORK, is_session, previous_session, session_close
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(NEW_YORK).date()
    if not is_session(day) or now < session_close(day) + timedelta(minutes=20):
        day = previous_session(day)
    expected = day.isoformat()
    if expected >= view["first_signal_session"] and (not view.get("last_close") or view["last_close"] < expected):
        return "A completed market session has not reached this display yet. Check the local collector and publication task."
    published = datetime.fromisoformat(view["published_at"].replace("Z", "+00:00"))
    if now - published > timedelta(hours=48):
        return "This display snapshot is more than 48 hours old. Check the local publication task."
    return None


def render_e3_dashboard():
    import pandas as pd
    import plotly.graph_objects as go
    import streamlit as st
    from src.config import get_secret
    from src.dashboard_ui import header, money, paper_banner

    header("INDEPENDENT FORWARD STUDY", "E3 Forward Paper", "Mean Reversion F1 + E3 · primary challenger · separate from Frozen V12")
    paper_banner()
    st.caption("Read-only paper account. This page cannot create signals, execute trades, or change either strategy's ledger.")
    try:
        view = load_display(get_secret("SUPABASE_URL"), get_secret("SUPABASE_SECRET_KEY") or get_secret("SUPABASE_SERVICE_ROLE_KEY"),
                            get_secret("E3_DASHBOARD_SYNC_SECRET") or get_secret("V12_DASHBOARD_SYNC_SECRET"))
    except E3DisplayError as exc:
        st.error(str(exc))
        return
    warning = freshness(view)
    if warning:
        st.warning(warning)
    e3 = view["accounts"]["E3"]
    if view["forward_sessions"] == 0:
        st.info("Armed — waiting for the first eligible forward close. No forward trades or performance have been recorded.")
    else:
        st.success(f"{view['forward_sessions']} recorded forward sessions · {view['primary_fill_count']} E3 fills")
    columns = st.columns(4)
    columns[0].metric("E3 paper cash", money(e3["cash"]))
    columns[1].metric("Paper value", money(e3["equity"]))
    columns[2].metric("Forward sessions", str(view["forward_sessions"]))
    columns[3].metric("E3 fills", str(view["primary_fill_count"]))
    dates = st.columns(2)
    dates[0].metric("First eligible signal close", view["first_signal_session"])
    dates[1].metric("First possible next-open fill", view["first_possible_fill_session"])
    st.caption("First possible fill is conditional on an eligible signal. Open-price paper fills are recorded after that session closes, from instructions saved before its open.")
    st.caption(f"Frozen at {view['frozen_at']} · Last forward close: {view.get('last_close') or 'None yet'} · Signed display updated: {view['published_at']}")
    with st.expander("Frozen F1 + E3 rules", expanded=True):
        st.markdown("- Buy when the stock closes **above MA200** and **below the lower Bollinger Band (20, 2)**.\n"
                    "- No SPY entry filter, MA20 exit or stop-loss.\n"
                    "- Execute at the **next session's open**. Hold for **10 trading sessions**, then exit at the following open.\n"
                    "- Maximum **2 positions**; each new position receives up to **50%** of portfolio equity, subject to cash.\n"
                    "- Rank simultaneous entries by normalized distance below the lower band; ticker breaks ties.\n"
                    "- **0.10% commission + 0.05% adverse slippage** per fill. Idle cash earns zero.")
        st.caption("Universe: " + " · ".join(view["rules"]["universe"]))
    st.subheader("E3 holdings and next-open plan")
    holdings = [{"Stock": name, "Shares": position["shares"], "Entry session": position["entry_session"],
                 "Held sessions": position["held_sessions"]} for name, position in e3["positions"].items()]
    if holdings:
        st.dataframe(pd.DataFrame(holdings), hide_index=True, width="stretch")
    else:
        st.write("No E3 positions. Paper capital is held in cash.")
    pending = view.get("pending")
    plan = pending.get("plans", {}).get("E3", {}) if pending else {}
    if plan.get("entries") or plan.get("exits"):
        st.write({"Execution session": pending["execution_date"], "Buy": plan.get("entries", []), "Sell": plan.get("exits", [])})
    else:
        st.write("No E3 next-open entries or exits are currently planned.")
    st.subheader("Independent forward comparison accounts")
    labels = {"E3": "F1 + E3 (primary)", "CSM": "Cross-Sectional Momentum", "SPY": "SPY buy-and-hold", "EW": "Equal-weight ten stocks"}
    rows = [{"Account": labels[name], "Paper value": money(account["equity"]), "Cash": money(account["cash"]),
             "Net return": "Waiting for forward data" if account["return_pct"] is None else f"{account['return_pct']:+.2f}%"}
            for name, account in view["accounts"].items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if view["curve"]:
        chart = go.Figure()
        for name in ("E3", "CSM", "SPY", "EW"):
            items = [row for row in view["curve"] if row["series"] == name]
            chart.add_scatter(x=[row["date"] for row in items], y=[row["value"] for row in items], name=labels[name], mode="lines+markers")
        chart.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis_title="Paper account value ($)", xaxis_title="Forward close", height=360)
        st.plotly_chart(chart, width="stretch")
    else:
        st.write("The forward equity chart will appear after the first recorded session. Initial cash is not investment performance.")
    st.subheader("E3 paper transaction log")
    if view["trades"]:
        st.dataframe(pd.DataFrame(view["trades"]).iloc[::-1], hide_index=True, width="stretch")
    else:
        st.write("No E3 paper fills yet.")
    st.caption("Short samples cannot establish an edge. Dividend receivables remain separate from spendable cash. V12's official curve and results do not include these accounts.")
    st.caption(f"Ledger verified · {view['ledger_events']} events · Freeze {view['freeze_sha256'][:12]} · Source {(view.get('source_commit') or 'unavailable')[:8]}")
