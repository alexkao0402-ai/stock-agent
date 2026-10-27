"""Matching read-only components for V12 and E3 on every tracking page."""
import html
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard_read_model import HISTORICAL_SHARPE
from src.dashboard_ui import money, pct, selection_cards, signed_money, timeline, trade_activity_rows
from src.strategy_page_model import e3_model, v12_model


def _metrics(items):
    for offset in range(0, len(items), 2):
        columns = st.columns(2)
        for column, (label, value) in zip(columns, items[offset:offset + 2]):
            column.metric(label, value)


def _data(rows, empty="No recorded rows yet."):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info(empty)


def _performance(m):
    _metrics([("Portfolio Value", money(m.get("portfolio_value"))),
              ("Cumulative Return", "Waiting" if m.get("cumulative_return") is None else pct(m["cumulative_return"])),
              ("vs SPY", pct(m.get("excess_vs_spy"), points=True)),
              (f"vs {m['benchmark']}", pct(m.get("excess_vs_qqq"), points=True)),
              ("Max Drawdown", pct(m.get("max_drawdown"))),
              ("Cash", money(m.get("cash")))])
    st.caption(f"Latest recorded close: {m.get('valuation_date') or 'Waiting'} · Display updated: {m.get('publication') or 'Unavailable'}")
    if m.get("delayed"):
        st.warning(m["freshness_message"])
    if m["name"] == "E3":
        st.caption("EW = equal-weight ten stocks. QQQ is not collected by the frozen E3 experiment.")


def _chart(m):
    curve = m["curve"]
    with st.container(height=380, border=False):
        if curve.empty or not m.get("formal_forward_rows"):
            st.info("Waiting for recorded forward closes. Initial cash is not a performance chart.")
            return
        figure = go.Figure()
        colors = {"V12": "#39d98a", "E3": "#818cf8", "SPY": "#d4d4d8", "QQQ": "#818cf8", "EW": "#e8b84b", "CSM": "#60a5fa"}
        for series in m["benchmarks"]:
            frame = curve[curve["series"].eq(series)]
            if frame.empty:
                continue
            figure.add_scatter(x=pd.to_datetime(frame["date"]), y=frame["value"], name=series, mode="lines",
                               line={"color": colors[series], "width": 3 if series == m["name"] else 2},
                               hovertemplate=f"{series}<br>%{{x|%Y-%m-%d}}<br>$%{{y:,.2f}}<extra></extra>")
        figure.update_layout(height=350, margin={"l": 8, "r": 8, "t": 35, "b": 8}, template="plotly_dark",
                             paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0d0d10", hovermode="x unified",
                             yaxis={"tickprefix": "$"}, legend={"orientation": "h", "y": 1.15})
        st.plotly_chart(figure, width="stretch", key=f"{m['name']}_equity", config={"displaylogo": False})
    if m["name"] == "E3":
        st.caption("CSM is E3's separate Cross-Sectional Momentum comparison account; it is not Frozen V12.")


def _posture(m):
    _metrics([("Stocks held", str(len(m["positions"]))),
              ("Latest signal", m.get("signal_date") or "Not generated"),
              ("Next-open plan", m.get("execution_status") or "Waiting"),
              ("Execution date", m.get("execution_date") or m.get("next_execution_date") or "Waiting")])
    st.write("**Saved decision:** " + m["signal_summary"])
    if m["name"] == "E3":
        st.caption("At most two stocks. New entries use up to 50% each, subject to cash; existing weights drift with prices.")
        st.caption("Open-price model fills are recorded after the close using a decision saved before that open.")
    else:
        st.caption("Market regime: " + (m.get("market_regime") or "Waiting"))


def _reasons(m):
    if m["selections"]:
        selection_cards(m["selections"])
        st.caption("E3 percentages are current weights; V12 percentages are saved target weights." if m["name"] == "E3" else "Saved V7 / V8 selections explain the target weights. AI does not choose the allocation.")
    else:
        st.info("Position reasons are unavailable in this older publication." if m["positions"] else "No stocks held or selected yet. Cash is a valid state.")
    if m["name"] == "E3":
        history = m["history"]
        if history:
            _signal_table(history[-1])
        else:
            st.caption("The ten-stock entry checklist will appear after the first recorded close. No current signal is inferred from research data.")


def _holdings(m):
    _metrics([("Realized P/L", signed_money(m.get("realized_pnl"))),
              ("Unrealized P/L", signed_money(m.get("unrealized_pnl"))),
              ("Cumulative Trading Costs", money(m.get("cumulative_transaction_costs"))),
              ("Latest Valuation", m.get("valuation_date") or "Waiting")])
    rows = [{"Ticker": p["ticker"], "Shares": p.get("shares"), "Average Cost": p.get("average_cost"),
             "Latest Price": p.get("mark"), "Current Weight": p.get("current_weight"),
             "Target Weight": p.get("target_weight"), "Market Value": p.get("market_value"),
             "Unrealized P/L": p.get("unrealized_pnl"),
             **({"Entry Session": p.get("entry_session"), "Held Sessions": p.get("held_sessions")} if m["name"] == "E3" else {})}
            for p in m["positions"]]
    _data(rows, "No positions. Paper capital is held in cash.")
    if m["name"] == "E3":
        st.caption("Average cost includes buy commission. Target weight is not applicable to E3's fixed holding rule. Marks come from captured raw closing prices, not a fresh quote.")
    st.caption(f"Dividends received: {money(m.get('dividends_received'))} · Receivable: {money(m.get('dividends_receivable'))}. Receivables count toward value but cannot fund buys.")
    if not m.get("details_available"):
        st.warning("This older E3 display lacks position and accounting details. A new verified publication is required; missing fields are not estimated.")


def _latest_execution(m):
    trades = m["latest_trades"]
    if not trades:
        st.info("No recorded paper fills yet." if m["name"] == "E3" else "No trades in the latest published allocation.")
        return
    st.caption(f"Latest fill session: {trades[0].get('execution_date') or 'Unavailable'} · T+1 market open")
    buys = sum(t.get("trade_value", 0) for t in trades if t["action"] == "BUY")
    sells = sum(t.get("trade_value", 0) for t in trades if t["action"] == "SELL")
    costs = sum((t.get("fee") or 0) + (t.get("slippage_cost") or 0) for t in trades)
    _metrics([("Bought", money(buys)), ("Sold", money(sells)), ("Trading Costs", money(costs)),
              ("Portfolio Changed", pct(m.get("latest_turnover")) if m["name"] == "V12" else "Not published")])
    st.write("; ".join(f"{t['action']} {t.get('ticker') or t.get('symbol')}" for t in trades))
    st.caption("Activity contains quantities, fills, costs and the execution audit.")


def _timeline(m):
    timeline([("Latest signal", m.get("signal_date") or "Not generated"),
              ("T+1 execution", f"{m.get('execution_status') or 'Waiting'} · {m.get('execution_date') or 'Waiting'}"),
              ("Latest valuation", m.get("valuation_date") or "Waiting"),
              ("Next check", (m.get("next_signal_date") or "After next market close") + " close" if m.get("next_signal_date") else "After next market close")])
    if m["name"] == "V12" and m.get("next_execution_date"):
        st.caption(f"Next expected fill session: {m['next_execution_date']}")
    if m["name"] == "E3" and not m.get("formal_forward_rows"):
        st.caption(f"First possible next-open fill: {m.get('next_execution_date') or 'Waiting'}, only if a stock qualifies.")


def _plan(m):
    if m["name"] == "E3":
        _data(m["next_plan"], "No E3 next-open buys or sells are currently planned.")
    else:
        st.write("**Saved targets:** " + m["signal_summary"])
        st.write(f"**Execution:** {m.get('execution_status') or 'Waiting'} · {m.get('execution_date') or 'Waiting'}")
    st.caption("A saved plan is not a completed trade. Both strategies use close-time decisions and a later market open.")


def _trades(m):
    trades = m["trades"]
    st.caption(m["trade_scope"])
    if not trades:
        st.info("Trade details are unavailable in this older publication." if not m.get("details_available") else "No recorded paper fills yet.")
        return
    filters = st.columns(2)
    side = filters[0].selectbox("Action", ["All actions"] + sorted({t["action"] for t in trades}), key=f"{m['name']}_side")
    ticker = filters[1].selectbox("Ticker", ["All tickers"] + sorted({t["ticker"] for t in trades}), key=f"{m['name']}_ticker")
    chosen = [t for t in reversed(trades) if (side == "All actions" or t["action"] == side) and (ticker == "All tickers" or t["ticker"] == ticker)]
    if m["name"] == "V12":
        rows = trade_activity_rows(chosen, m)
    else:
        rows = [{"Signal": t["signal_date"], "Fill Session": t["execution_date"], "Action": t["action"],
                 "Ticker": t["ticker"], "Shares": t["shares"], "Fill Price": t["fill_price"],
                 "Trade Value": t["trade_value"], "Commission": t["fee"], "Slippage": t["slippage_cost"],
                 "Realized P/L": t.get("realized_pnl"), "Reason": t["reason"]} for t in chosen]
    _data(rows)
    with st.expander("Execution audit details"):
        _data([{"Signal": t.get("signal_date") or m.get("signal_date"), "Execution": t.get("execution_date"),
                "Side": "SELL · TRIM" if t.get("is_trim") else t["action"], "Ticker": t["ticker"],
                "Before": t.get("before_shares"), "Change": t["shares"] if t["action"] == "BUY" else -t["shares"],
                "After": t.get("after_shares"), "Fill Price": t["fill_price"], "Trade Value": t["trade_value"],
                "Commission": t.get("fee"), "Slippage": t.get("slippage_cost"),
                "Decision Saved": t.get("decision_recorded_at")} for t in chosen])
        st.caption("SELL · TRIM means a selected position was reduced to its target weight. E3 has no target-weight rebalance.")
    st.download_button("Download published fills", pd.DataFrame(trades).to_csv(index=False),
                       file_name=f"{m['name'].lower()}-published-fills.csv", mime="text/csv", key=f"{m['name']}_fills_csv")


def _signal_table(record):
    entries = record["plan"].get("entries", [])
    rows = [{"Ticker": s["symbol"], "Signal Close (adjusted)": s["adjusted_close"], "MA200": s["ma200"],
             "Lower BB": s["lower_band"], "Entry Eligible": s["entry_signal"], "Rank Score": s["score"],
             "Next-open Decision": "BUY" if s["symbol"] in entries else ("SELL" if s["symbol"] in record["plan"].get("exits", []) else "No new order")}
            for s in sorted(record["stocks"], key=lambda s: (-s["score"], s["symbol"]))]
    _data(rows)
    st.caption(f"Saved {record['recorded_at']} after {record['signal_date']} close · eligible execution: {record['execution_date']} open. These are saved signals, not fresh recalculations.")


def _signals(m):
    if m["name"] == "E3":
        if not m["history"]:
            st.info("No recorded forward signal checks yet.")
            return
        dates = [r["signal_date"] for r in reversed(m["history"])]
        date = st.selectbox("Signal session", dates, key="E3_signal_session")
        _signal_table(next(r for r in m["history"] if r["signal_date"] == date))
        st.caption("Latest 120 saved close checks are included in the display; the full append-only journal remains local.")
    else:
        _reasons(m)
        st.caption("The current V12 signed display publishes the latest allocation, rather than a complete historical signal archive.")


def _events(m):
    events = m["event_rows"]
    if not events:
        st.info("No verified events are available in this publication.")
        return
    event_type = st.selectbox("Event type", ["All events"] + sorted({r["Event"] for r in events}), key=f"{m['name']}_events")
    _data([r for r in events if event_type == "All events" or r["Event"] == event_type])
    st.caption("Newest first. Published events are a read-only window into the append-only journal, not an editable record.")


def _health(m):
    delayed = m.get("delayed")
    blocked = bool(m.get("trading_blocked")) or not m.get("ledger_verified")
    _metrics([("System", "Needs attention" if delayed or blocked else "Verified display"),
              ("Strategy", "Invested" if m["positions"] else "Cash / waiting"),
              ("Evidence", "Building sample" if m.get("rolling_sharpe") is None else "252-session window available"),
              ("Ledger", "Verified" if m.get("ledger_verified") else "Unavailable")])
    if blocked:
        st.error(m.get("integrity_error") or m.get("execution_status") or "Check the underlying cycle.")
    elif delayed:
        st.warning(m["freshness_message"])
    else:
        st.info(m["freshness_message"])
    st.caption("A verified display confirms its saved evidence; it does not prove the next collector run will succeed.")
    for warning in m.get("warnings", []):
        st.warning(str(warning))


def _pipeline(m):
    timeline([("Data", m.get("valuation_date") or "Waiting"),
              ("Signal", m.get("signal_date") or "Not generated"),
              ("Execution", m.get("execution_status") or "Waiting"),
              ("Dashboard sync", m.get("publication") or "Unavailable")])


def _safety(m):
    _metrics([("Strategy status", "FROZEN"), ("Ledger", "Verified" if m.get("ledger_verified") else "Unavailable"),
              ("T+1 execution", m.get("execution_status") or "Waiting"),
              ("Cloud Snapshot", "Verified" if m.get("publication") else "Local read")])
    st.caption(f"{m.get('ledger_event_count') or 0} verified ledger events · Source {(m.get('source_commit') or 'local checkout')[:8]}")
    if m["name"] == "E3":
        st.caption("Freeze receipt: " + m.get("freeze_sha256", "Unavailable"))
    with st.expander("What would stop a cycle?"):
        st.write("- Ledger, source, schema or signature verification failure\n- Missing prices or a missed session\n- Invalid decision timing or accounting reconciliation")
        if m["name"] == "E3":
            st.write("E3 halts on a missing forward session. It does not invent signals or backfill trades.")


def _evidence(m):
    is_e3 = m["name"] == "E3"
    _metrics([("SPY regime", "Not an entry filter" if is_e3 else m.get("market_regime") or "Waiting"),
              ("V7 / V8 agreement", "Not applicable" if is_e3 else ("Waiting" if m.get("agreement_count") is None else str(m["agreement_count"]))),
              ("Forward Drawdown", pct(m.get("max_drawdown"))),
              ("Recorded close sessions" if is_e3 else "Official Allocation Batches", str(m.get("formal_forward_rows") or 0)),
              ("12M Rolling Sharpe", "Waiting" if m.get("rolling_sharpe") is None else f"{m['rolling_sharpe']:.2f}"),
              ("Forward vs Backtest", "Not configured" if is_e3 else ("Waiting" if m.get("sharpe_deviation") is None else f"{m['sharpe_deviation']:+.2f} Sharpe")),
              ("T+1 Return", pct(m.get("cumulative_return") if is_e3 else m.get("t1_return"))),
              ("T+2 / Difference", "Not collected" if is_e3 else ("Waiting" if m.get("t2_return") is None else f"{pct(m['t2_return'])} / {pct(m.get('t1_t2_spread'), points=True)}"))])
    if is_e3:
        _metrics([("Exposure", pct(m.get("exposure"))), ("Completed trades", str(m.get("closed_trades") or 0)),
                  ("Win rate", "Waiting" if m.get("win_rate") is None else pct(m["win_rate"]))])
        st.caption("SPY filtering, V7/V8 agreement, a historical Sharpe reference and T+2 simulation are not part of the frozen E3 experiment.")
    else:
        st.caption(f"Historical reference only: Frozen V12 Sharpe {HISTORICAL_SHARPE:.2f}. At -20% drawdown, research review begins; the rule is not automatically altered.")
    st.info("Short forward samples cannot establish an edge. A waiting metric is not evidence of failure, and performance never changes these frozen rules automatically.")


def _rules(m):
    if m["name"] == "E3":
        st.markdown("**F1 + E3 — Mean Reversion**\n\n"
                    "- Entry: adjusted close above MA200 and below lower BB(20, 2; population standard deviation).\n"
                    "- No SPY entry filter, MA20 exit or stop-loss.\n"
                    "- Rank by normalized distance below the lower band; ticker breaks ties.\n"
                    "- Enter at the next open. Hold 10 trading-session closes, then exit at the following open.\n"
                    "- At most 2 stocks; up to 50% per new entry, subject to cash.\n"
                    "- Per fill: 0.10% commission + 0.05% adverse slippage. Idle cash earns zero.")
        st.caption("Universe: " + " · ".join(m.get("rules", {}).get("universe", [])))
    else:
        st.markdown("**Frozen V12 — Momentum**\n\n"
                    "- V7 uses 12–1 momentum; V8 uses 3–1 / 6–1 / 12–1 composite momentum.\n"
                    "- Their saved selections determine the monthly target allocation. Agreement receives a larger weight.\n"
                    "- The saved SPY market regime controls stock exposure or cash.\n"
                    "- Official signals execute at the next session's open; the dashboard cannot modify them.")
    with st.expander("How to read the evidence"):
        st.write("Drawdown measures the fall from the account's prior high. Rolling Sharpe requires 252 daily returns. Returns on Overview cover each strategy's own start date; a fair ranking needs a common period and enough observations.")


def _balances(m):
    position_value = (sum(p["market_value"] for p in m["positions"])
                      if all(p.get("market_value") is not None for p in m["positions"]) else None)
    _metrics([("Account value", money(m.get("portfolio_value"))), ("Spendable cash", money(m.get("cash"))),
              ("Stocks at recorded close", money(position_value)),
              ("Dividends receivable", money(m.get("dividends_receivable"))),
              ("Dividends received", money(m.get("dividends_received"))),
              ("Trading costs", money(m.get("cumulative_transaction_costs")))])
    st.caption("Account value = cash + marked stocks + receivables. Costs are already reflected in cash/P&L; do not subtract them twice.")


def _dividends(m):
    _metrics([("Cash dividends received", money(m.get("dividends_received"))),
              ("Nonspendable receivable", money(m.get("dividends_receivable")))])
    if m["name"] == "E3":
        st.write("The frozen E3 runner accrues captured dividends as receivables. It has no dividend-payment-date cash process; no cash payment is invented here.")
    else:
        st.write("Reviewed pay dates credit cash separately from dividend entitlement. The existing V12 publication provides aggregate totals on this page.")


SECTIONS = {
    "overview": [("Performance", _performance), ("Recorded equity curves", _chart),
                 ("Holdings, signal and execution", _posture), ("Why these stocks", _reasons),
                 ("Portfolio P/L & Contribution", _holdings), ("Latest execution", _latest_execution),
                 ("Automation timeline", _timeline)],
    "activity": [("Next-open plans", _plan), ("Paper fills and execution audit", _trades),
                 ("Saved signal evidence", _signals), ("Recent system events", _events)],
    "health": [("Current interpretation", _health), ("Automation pipeline", _pipeline),
               ("System safety checks", _safety), ("Strategy evidence", _evidence), ("Frozen rules", _rules)],
    "accounting": [("Account reconciliation", _balances), ("Position accounting", _holdings),
                   ("Dividend accounting", _dividends)],
}


def render_paired_page(page, v12, e3):
    """Use the same section and component for each independent strategy."""
    models = (v12_model(v12), e3_model(e3))
    st.caption("V12 on the left · E3 on the right. On small screens, each matching section stacks vertically. Accounts and start dates remain separate.")
    for heading, render in SECTIONS[page]:
        st.subheader(heading)
        columns = st.columns(2, gap="large")
        for column, model in zip(columns, models):
            with column, st.container(border=True):
                st.markdown(f'<div class="paired-label {model["name"].lower()}">{html.escape(model["name"])}</div>', unsafe_allow_html=True)
                if not model["available"]:
                    st.error(f"{model['name']} data unavailable. No substitute balance or performance is shown.")
                else:
                    render(model)


def render_market_context(v12, e3):
    """One shared company-research page, with equal access from both accounts."""
    with st.expander("Research stocks from either strategy", expanded=True):
        for column, model in zip(st.columns(2), (v12_model(v12), e3_model(e3))):
            with column:
                st.markdown(f"**{model['name']}**")
                if not model["available"]:
                    st.caption("Strategy context is unavailable.")
                    continue
                stocks = [p["ticker"] for p in model["positions"]]
                st.caption("Holding: " + (", ".join(stocks) or "Cash only"))
                candidates = stocks or (model.get("rules", {}).get("universe", []) if model["name"] == "E3" else list((model.get("target_weights") or {})))
                selected = st.selectbox("Research ticker", ["Choose a stock"] + candidates, key=f"{model['name']}_research_stock")
                if st.button(f"Research {model['name']} stock", key=f"{model['name']}_research_button", disabled=selected == "Choose a stock"):
                    st.session_state["market_symbol"] = selected
        st.caption("Prices, earnings, news and filings below are shared company research. They do not create orders or change either frozen strategy.")
