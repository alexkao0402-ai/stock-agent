"""Plain-language overview of two independent, read-only paper accounts."""
from html import escape

from src.dashboard_ui import latest_curve_date, money, pct
from src.e3_dashboard import dashboard_view, freshness
from src.e3_dashboard_snapshot import E3DisplayError


def account_cards(v12, e3=None):
    """Project display fields only; never align returns from different start dates."""
    valid_v12 = not v12.get("integrity_error") and bool(v12.get("formal_forward_rows"))
    holdings = ", ".join(str(row["ticker"]) for row in v12.get("holdings", []))
    v12_next = "Waiting for the next official signal."
    if v12.get("execution_status") != "Executed" and v12.get("execution_date"):
        v12_next = f"Planned execution: {v12['execution_date']} market open. Check Activity for status."
    elif v12.get("next_signal_date"):
        v12_next = f"Next scheduled signal: {v12['next_signal_date']} close."
    cards = [{
        "name": "V12", "role": "Existing frozen strategy", "style": "v12",
        "idea": "Combines two frozen stock rankings to choose monthly holdings. A market trend filter can move the account to cash.",
        "value": money(v12.get("portfolio_value")) if valid_v12 else "Unavailable",
        "return": pct(v12.get("cumulative_return")) if valid_v12 else "Unavailable",
        "cash": money(v12.get("cash")) if valid_v12 else "Unavailable",
        "status": "Needs attention" if v12.get("trading_blocked") else ("Tracking forward" if valid_v12 else "Waiting for data"),
        "holdings": (holdings or "Cash only") if valid_v12 else "Unavailable",
        "asof": latest_curve_date(v12) if valid_v12 else "Unavailable",
        "published": v12.get("snapshot_generated_at") or v12.get("last_event_created_at") or "Unavailable",
        "next": v12_next if valid_v12 else "Open Strategy Health to check the data.",
    }]
    card = {
        "name": "E3", "role": "New forward-paper candidate · F1 + E3", "style": "e3",
        "idea": "Looks for a short-term price dip in a stock with a long-term uptrend. Holds for 10 trading sessions, then exits at the following open.",
        "value": "Unavailable", "return": "Unavailable", "cash": "Unavailable",
        "status": "Data unavailable", "holdings": "Unavailable", "asof": "Unavailable",
        "published": "Unavailable", "next": "Open E3 Forward Paper to check the data.",
    }
    if e3 is not None:
        account = e3["accounts"]["E3"]
        sessions = e3["forward_sessions"]
        pending = e3.get("pending") or {}
        plan = pending.get("plans", {}).get("E3", {})
        actions = []
        for key, label in (("entries", "Buy"), ("exits", "Sell")):
            if plan.get(key):
                actions.append(f"{label} {', '.join(plan[key])}")
        if actions:
            next_action = f"Planned for {pending['execution_date']} open: {'; '.join(actions)}."
        elif not sessions:
            next_action = (f"First signal check: {e3['first_signal_session']} close. "
                           f"Earliest possible buy: {e3['first_possible_fill_session']} open, only if a stock qualifies.")
        else:
            next_action = "No buys or sells planned. Check again after the next recorded market close."
        card.update({
            "value": money(account["equity"]), "cash": money(account["cash"]),
            "return": "Waiting" if not sessions or account.get("return_pct") is None else f"{account['return_pct']:+.2f}%",
            "status": f"Tracking forward · {sessions} sessions" if sessions else "Waiting for first signal check",
            "holdings": ", ".join(account["positions"]) or "Cash only · no stocks held",
            "asof": e3.get("last_close") or "No forward close yet",
            "published": e3["published_at"], "next": next_action,
        })
    cards.append(card)
    return cards


def render_strategy_overview(v12):
    import streamlit as st

    try:
        e3 = dashboard_view()
    except E3DisplayError:
        e3 = None
    st.subheader("Your two paper strategies")
    st.caption("Two separate accounts, shown together. Each keeps its own cash, holdings and results.")
    sections = []
    for card in account_cards(v12, e3):
        c = {key: escape(str(value or "Unavailable")) for key, value in card.items()}
        sections.append(
            f'<section class="strategy-summary {c["style"]}" aria-label="{c["name"]} paper account">'
            f'<div class="strategy-role">{c["role"]}</div><h3>{c["name"]}</h3>'
            f'<p class="strategy-idea">{c["idea"]}</p><div class="strategy-state">{c["status"]}</div>'
            f'<div class="strategy-numbers"><div><span>Paper value</span><strong>{c["value"]}</strong></div>'
            f'<div><span>Return since its start</span><strong>{c["return"]}</strong></div>'
            f'<div><span>Cash available</span><strong>{c["cash"]}</strong></div></div>'
            f'<p><b>Holding now</b><br>{c["holdings"]}</p>'
            f'<p><b>What happens next</b><br>{c["next"]}</p>'
            f'<div class="strategy-asof">Latest recorded close: {c["asof"]}<br>Display updated: {c["published"]}</div></section>'
        )
    st.markdown('<div class="strategy-pair">' + "".join(sections) + '</div>', unsafe_allow_html=True)
    if e3 is None:
        st.warning("E3 data could not be verified. Its balance and return are unavailable; V12 remains visible.")
    else:
        warning = freshness(e3)
        if warning:
            st.warning("E3: " + warning)
    st.info("Too early to name a winner. V12 and E3 started at different times. These returns cover each account's own history; a fair comparison needs the same dates and enough new observations.")
    with st.expander("How to read this"):
        st.markdown(
            "- **Paper value:** the simulated value of cash and investments, including any dividend receivables.\n"
            "- **Return since its start:** the change since that account began. E3 shows **Waiting** until a forward close is recorded.\n"
            "- **Holding now:** stocks already held. A planned buy is not a completed trade.\n"
            "- **What happens next:** the saved plan or next check, not a promise to trade. Signals use the close; fills use a later market open.\n"
            "- **E3 limits:** at most 2 stocks, up to 50% per new position, subject to available cash. Costs are 0.10% commission + 0.05% adverse slippage per fill."
        )
    st.markdown("[E3 rules, holdings and paper trades](/e3-forward-paper)")
