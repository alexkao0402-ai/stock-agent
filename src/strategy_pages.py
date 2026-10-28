"""Matching read-only components for V12 and E3 on every tracking page."""
import html
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard_read_model import HISTORICAL_SHARPE
from src.dashboard_ui import display_timestamp, money, pct, selection_cards, signed_money, timeline, trade_activity_rows
from src.strategy_page_model import e3_model, v12_model


def _metrics(items):
    for offset in range(0, len(items), 2):
        columns = st.columns(2)
        for column, (label, value) in zip(columns, items[offset:offset + 2]):
            column.metric(label, value)


def _data(rows, empty="No recorded rows yet."):
    if rows:
        frame = pd.DataFrame(rows)
        currency = {"Average Cost", "Latest Price", "Market Value", "Unrealized P/L", "Fill Price", "Trade Value", "Commission", "Slippage", "Realized P/L"}
        config = {name: st.column_config.NumberColumn(format="$%.2f") for name in currency & set(frame.columns)
                  if pd.api.types.is_numeric_dtype(frame[name])}
        if "Shares" in frame and pd.api.types.is_numeric_dtype(frame["Shares"]):
            config["Shares"] = st.column_config.NumberColumn(format="%.4f")
        for name in ("Current Weight", "Target Weight"):
            if name in frame and pd.api.types.is_numeric_dtype(frame[name]):
                frame[name] = frame[name].map(lambda v: "—" if pd.isna(v) else f"{v:.1%}")
        st.dataframe(frame, hide_index=True, width="stretch", column_config=config)
    else:
        st.info(empty)


def _performance(m):
    st.metric("Portfolio Value", money(m.get("portfolio_value")))
    _metrics([("Cumulative Return", "Waiting" if m.get("cumulative_return") is None else pct(m["cumulative_return"])),
              ("Max Drawdown", pct(m.get("max_drawdown"))),
              ("vs SPY", pct(m.get("excess_vs_spy"), points=True)),
              (f"vs {m['benchmark']}", pct(m.get("excess_vs_qqq"), points=True))])
    st.caption(f"Prices as of {m.get('valuation_date') or 'Waiting'} · Published {display_timestamp(m.get('publication'))}")
    if m.get("delayed"):
        st.warning(m["freshness_message"])
    if m["name"] == "E3":
        st.caption("EW = equal-weight ten stocks. QQQ is not collected by the frozen E3 experiment.")


def _chart(m):
    curve = m["curve"]
    with st.container(border=False):
        if curve.empty or not m.get("formal_forward_rows"):
            st.info("Waiting for recorded forward closes. Initial cash is not a performance chart.")
            return
        observations = curve.loc[curve["series"].eq(m["name"]), "date"].nunique()
        if observations < 2:
            st.info("First close recorded. The equity chart will appear after two recorded sessions.")
            st.caption(f"Recorded sessions: {observations} · Paper fills: {m.get('primary_fill_count') or 0}. One observation cannot show a performance trend.")
            return
        figure = go.Figure()
        colors = {"V12": "#39d98a", "E3": "#818cf8", "SPY": "#d4d4d8", "QQQ": "#818cf8", "EW": "#e8b84b", "CSM": "#60a5fa"}
        for series in m["benchmarks"]:
            frame = curve[curve["series"].eq(series)]
            if frame.empty:
                continue
            figure.add_scatter(x=pd.to_datetime(frame["date"]), y=frame["value"], name=series, mode="lines+markers" if len(frame) == 1 else "lines",
                               line={"color": colors[series], "width": 3 if series == m["name"] else 2},
                               hovertemplate=f"{series}<br>%{{x|%Y-%m-%d}}<br>$%{{y:,.2f}}<extra></extra>")
        figure.update_layout(height=350, margin={"l": 8, "r": 8, "t": 35, "b": 8}, template="plotly_dark",
                             paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0d0d10", hovermode="x unified",
                             xaxis={"tickformat": "%b %d", "type": "date"},
                             yaxis={"tickprefix": "$"}, legend={"orientation": "h", "y": 1.15})
        st.plotly_chart(figure, width="stretch", key=f"{m['name']}_equity", config={"displaylogo": False})
    if m["name"] == "E3":
        st.caption("CSM is E3's separate Cross-Sectional Momentum comparison account; it is not Frozen V12.")


def _comparison_accounts(m):
    if m["name"] == "E3":
        labels = {"E3": "E3", "CSM": "Cross-Sectional Momentum", "SPY": "SPY", "EW": "Equal-weight ten stocks"}
        rows = [{"Account": labels[name], "Paper value": money(account["equity"]), "Cash": money(account["cash"]),
                 "Return": "Waiting" if account["return_pct"] is None else f"{account['return_pct']:+.2f}%"}
                for name, account in m.get("comparison_accounts", {}).items()]
        st.caption("Four separate accounts from the same E3 study start; their money is not pooled with V12.")
    else:
        rows = []
        curve = m["curve"]
        if not curve.empty:
            for name in m["benchmarks"]:
                values = curve[curve["series"].eq(name)].sort_values("date")
                if not values.empty:
                    rows.append({"Account": name, "Paper value": money(float(values["value"].iloc[-1])),
                                 "Latest close": str(values["date"].iloc[-1])[:10]})
        st.caption("Published V12, SPY and QQQ comparison histories use V12's own start date.")
    _data(rows, "No recorded comparison history yet.")


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
    if m["name"] == "E3" and rows:
        st.caption("Average cost includes buy commission. Target weight is not applicable to E3's fixed holding rule. Marks come from captured raw closing prices, not a fresh quote.")
    st.caption(f"Dividends received: {money(m.get('dividends_received'))} · Receivable: {money(m.get('dividends_receivable'))}. Receivables cannot fund buys.".replace("$", r"\$"))
    if not m.get("details_available"):
        st.warning("This older E3 display lacks position and accounting details. A new verified publication is required; missing fields are not estimated.")


def _latest_execution(m):
    trades = m["latest_trades"]
    if not trades:
        st.info("No recorded paper fills yet." if m["name"] == "E3" else "No trades in the latest published allocation.")
        return
    st.caption(f"Latest fill session: {trades[0].get('execution_date') or m.get('execution_date') or 'Unavailable'} · T+1 market open")
    buys = sum(t.get("trade_value", 0) for t in trades if t["action"] == "BUY")
    sells = sum(t.get("trade_value", 0) for t in trades if t["action"] == "SELL")
    costs = sum((t.get("fee") or 0) + (t.get("slippage_cost") or 0) for t in trades)
    _metrics([("Bought", money(buys)), ("Sold", money(sells)), ("Trading Costs", money(costs)),
              ("Portfolio Changed", pct(m.get("latest_turnover")) if m["name"] == "V12" else "Not published")])
    st.write("; ".join(f"{'TRIM' if t.get('is_trim') else t['action']} {t.get('ticker') or t.get('symbol')}" for t in trades))


def _plan(m):
    if m["name"] == "E3":
        st.caption(f"Saved after {m.get('signal_date') or 'Waiting'} close · eligible execution: {m.get('next_execution_date') or 'Waiting'} open")
        _data(m["next_plan"], "No E3 next-open buys or sells are currently planned.")
    else:
        if str(m.get("execution_status") or "").lower().startswith("executed"):
            st.info("No pending allocation is published. The latest saved allocation has already executed.")
            if m.get("next_signal_date"):
                st.caption(f"Next expected signal: {m['next_signal_date']} close · eligible execution: {m.get('next_execution_date') or 'Waiting'} open, conditional on a valid signal.")
        else:
            st.write("**Saved targets:** " + m["signal_summary"])
            st.write(f"**Execution:** {m.get('execution_status') or 'Waiting'} · {m.get('execution_date') or 'Waiting'}")


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
    st.caption(f"Saved {display_timestamp(record['recorded_at'])} · {record['signal_date']} close → {record['execution_date']} open.")


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
    if not blocked and not delayed:
        st.write("**Saved data is verified and current.** " +
                 ("Performance history is still too short to evaluate." if m.get("rolling_sharpe") is None else "A full rolling performance window is available for review."))
    _metrics([("System", "Check required" if delayed or blocked else "Verified"),
              ("Position", "Invested" if m["positions"] else "Cash")])
    if blocked:
        st.error(m.get("integrity_error") or m.get("execution_status") or "Check the underlying cycle.")
    elif delayed:
        st.warning(m["freshness_message"])
    st.caption("A verified display confirms its saved evidence; it does not prove the next collector run will succeed.")
    for warning in m.get("warnings", []):
        if str(warning) != "Insufficient Forward history to calculate 12-month Rolling Sharpe":
            st.warning(str(warning))


def _pipeline(m):
    timeline([("Data", m.get("valuation_date") or "Waiting"),
              ("Signal", m.get("signal_date") or "Not generated"),
              ("Execution", m.get("execution_status") or "Waiting"),
              ("Dashboard sync", display_timestamp(m.get("publication")))])


def _safety(m):
    _metrics([("Strategy status", "FROZEN"), ("Ledger", "Verified" if m.get("ledger_verified") else "Unavailable"),
              ("T+1 execution", m.get("execution_status") or "Waiting"),
              ("Cloud Snapshot", "Verified" if m.get("publication") else "Local read")])
    st.caption(f"{m.get('ledger_event_count') or 0} verified ledger events · Source {(m.get('source_commit') or 'local checkout')[:8]}")
    if m["name"] == "E3":
        st.caption("Freeze receipt: " + m.get("freeze_sha256", "Unavailable"))
        st.caption(f"Frozen at {m.get('frozen_at') or 'Unavailable'} · First eligible signal: {m.get('first_signal_session') or 'Unavailable'} · First possible fill: {m.get('first_possible_fill_session') or 'Unavailable'} (conditional on a qualifying signal).")
        st.caption(f"Recorded forward sessions: {m.get('formal_forward_rows') or 0} · E3 paper fills: {m.get('primary_fill_count') or 0}")
    with st.expander("What would stop a cycle?"):
        st.write("- Ledger, source, schema or signature verification failure\n- Missing prices or a missed session\n- Invalid decision timing or accounting reconciliation")
        if m["name"] == "E3":
            st.write("E3 halts on a missing forward session. It does not invent signals or backfill trades.")


def _evidence(m):
    is_e3 = m["name"] == "E3"
    if is_e3:
        _metrics([("Forward Drawdown", pct(m.get("max_drawdown"))),
                  ("Recorded close sessions", str(m.get("formal_forward_rows") or 0)),
                  ("12M Rolling Sharpe", "Waiting" if m.get("rolling_sharpe") is None else f"{m['rolling_sharpe']:.2f}"),
                  ("Exposure", pct(m.get("exposure"))),
                  ("Completed trades", str(m.get("closed_trades") or 0)),
                  ("Win rate", "Waiting" if m.get("win_rate") is None else pct(m["win_rate"]))])
        st.caption("E3 evaluates stock pullbacks independently. V7/V8 agreement and T+2 comparison belong to V12.")
        return
    _metrics([("SPY regime", m.get("market_regime") or "Waiting"),
              ("V7 / V8 agreement", "Waiting" if m.get("agreement_count") is None else str(m["agreement_count"])),
              ("Forward Drawdown", pct(m.get("max_drawdown"))),
              ("Official Allocation Batches", str(m.get("formal_forward_rows") or 0)),
              ("12M Rolling Sharpe", "Waiting" if m.get("rolling_sharpe") is None else f"{m['rolling_sharpe']:.2f}"),
              ("Forward vs Backtest", "Waiting" if m.get("sharpe_deviation") is None else f"{m['sharpe_deviation']:+.2f} Sharpe"),
              ("T+1 Return", pct(m.get("t1_return"))),
              ("T+2 / Difference", "Waiting" if m.get("t2_return") is None else f"{pct(m['t2_return'])} / {pct(m.get('t1_t2_spread'), points=True)}")])
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
    if m["name"] == "E3":
        st.write("The frozen E3 runner accrues captured dividends as receivables. It has no dividend-payment-date cash process; no cash payment is invented here.")
    else:
        st.write("Reviewed pay dates credit cash separately from dividend entitlement. The existing V12 publication provides aggregate totals on this page.")


SECTIONS = {
    "overview": [("Performance", _performance), ("Recorded equity curves", _chart),
                 ("Current holdings", _holdings), ("Comparison accounts", _comparison_accounts)],
    "activity": [("Upcoming plans", _plan), ("Last completed execution", _latest_execution), ("Paper fills and execution audit", _trades),
                 ("Saved signal evidence", _signals), ("Recent system events", _events)],
    "health": [("Current interpretation", _health), ("Automation pipeline", _pipeline),
               ("System safety checks", _safety), ("Strategy evidence", _evidence), ("Frozen rules", _rules)],
    "accounting": [("Account reconciliation", _balances), ("Position accounting", _holdings),
                   ("Dividend accounting", _dividends)],
}


def render_paired_page(page, v12, e3):
    """Use the same section and component for each independent strategy."""
    models = (v12_model(v12), e3_model(e3))
    def paired_section(heading, render):
        st.subheader(heading)
        columns = st.columns(2, gap="large")
        for column, model in zip(columns, models):
            with column, st.container(border=True):
                st.markdown(f'<div class="paired-label {model["name"].lower()}">{html.escape(model["name"])}</div>', unsafe_allow_html=True)
                st.caption("Monthly momentum · Official portfolio" if model["name"] == "V12" else "Pullback · Independent experiment")
                if not model["available"]:
                    st.error(f"{model['name']} data unavailable. No substitute balance or performance is shown.")
                else:
                    render(model)

    sections = SECTIONS[page]
    for heading, render in sections:
        if heading in {"Comparison accounts", "Automation pipeline", "System safety checks", "Frozen rules", "Saved signal evidence", "Recent system events"}:
            with st.expander(heading, expanded=False):
                paired_section(heading, render)
        else:
            paired_section(heading, render)
