"""Display-only accounting from saved E3 evidence, never from fresh quotes."""
from pathlib import Path
import hashlib
import json
import math
import statistics


def _snapshot(home, payload):
    path = Path(home) / "inputs" / payload["session"] / f"{payload['snapshot_sha256']}.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if hashlib.sha256(canonical.encode()).hexdigest() != payload["snapshot_sha256"]:
        raise ValueError("E3 display source checksum mismatch")
    return snapshot


def build_details(home, events, info):
    """Replay cost basis for display; reconcile against the unchanged paper runner."""
    closes = [e for e in events if e["event_type"] == "CLOSE_PROCESSED"]
    fills = [e["payload"] for e in events if e["portfolio_id"] == "E3" and e["event_type"] == "PAPER_FILL"]
    positions, transactions, history, valuations = {}, [], [], []
    realized = commissions = slippage = 0.0
    for event in closes:
        payload = event["payload"]
        day = payload["session"]
        # Captured actions occurred before the session's model fills.
        for action in payload["actions"]:
            if action["account"] == "E3" and action["action"] == "SPLIT":
                positions[action["symbol"]]["shares"] *= action["ratio"]
        for fill in (f for f in fills if f["execution_date"] == day):
            symbol, qty, fee = fill["symbol"], fill["shares"], fill["commission"]
            price = fill["execution_price"]
            notional = fill["notional"]
            cost = abs(price - fill["raw_open"]) * qty
            commissions += fee
            slippage += cost
            before = positions.get(symbol, {}).get("shares", 0.0)
            pnl = None
            if fill["action"] == "BUY":
                position = positions.setdefault(symbol, {"shares": 0.0, "basis": 0.0, "signal_date": fill["signal_date"]})
                position["shares"] += qty
                position["basis"] += notional + fee
            else:
                position = positions[symbol]
                basis_sold = position["basis"] * qty / position["shares"]
                pnl = notional - fee - basis_sold
                realized += pnl
                position["shares"] -= qty
                position["basis"] -= basis_sold
                if position["shares"] < 1e-8:
                    del positions[symbol]
            transactions.append(dict(fill, ticker=symbol, fill_price=price, trade_value=notional,
                                     fee=fee, slippage_cost=cost, transaction_cost=fee + cost,
                                     realized_pnl=pnl, before_shares=before,
                                     after_shares=positions.get(symbol, {}).get("shares", 0.0),
                                     reason="Price dip in a long-term uptrend" if fill["action"] == "BUY" else "10-session holding period completed"))
        history.append({"signal_date": day, "recorded_at": payload["decision_recorded_at"],
                        "execution_date": payload["state"]["pending"]["execution_date"],
                        "plan": payload["state"]["pending"]["plans"]["E3"],
                        "stocks": payload["signal_details"]})
        valuations.append({"date": day, **payload["valuations"]["E3"]})
    holdings = []
    if closes:
        latest_snapshot = _snapshot(home, closes[-1]["payload"])
        account = info["accounts"]["E3"]
        if set(positions) != set(account["positions"]):
            raise ValueError("E3 display positions do not reconcile")
        for symbol, pos in positions.items():
            saved = account["positions"][symbol]
            if not math.isclose(pos["shares"], saved["shares"], rel_tol=1e-9, abs_tol=1e-7):
                raise ValueError("E3 display share quantities do not reconcile")
            bars = [bar for bar in latest_snapshot["prices"][symbol] if bar["date"] == info["last_close"]]
            if len(bars) != 1:
                raise ValueError("E3 captured closing mark missing")
            mark = float(bars[0]["close"])
            market_value = saved["shares"] * mark
            holdings.append({"ticker": symbol, **saved, "average_cost": pos["basis"] / pos["shares"],
                             "mark": mark, "market_value": market_value,
                             "current_weight": market_value / valuations[-1]["equity"],
                             "target_weight": None, "unrealized_pnl": market_value - pos["basis"],
                             "signal_date": pos["signal_date"],
                             "reason": "Entered after a close above MA200 and below the lower Bollinger Band; scheduled 10-session hold."})
        marked = sum(h["market_value"] for h in holdings)
        if not math.isclose(marked, valuations[-1]["position_value"], abs_tol=1e-6):
            raise ValueError("E3 captured valuation does not reconcile")
    unrealized = sum(h["unrealized_pnl"] for h in holdings)
    equity = valuations[-1]["equity"] if valuations else 10000.0
    receivable = info["accounts"]["E3"]["dividend_receivable"]
    if not math.isclose(equity, 10000 + realized + unrealized + receivable, abs_tol=1e-5):
        raise ValueError("E3 display profit and loss does not reconcile")
    peak = 10000.0
    drawdown = 0.0
    for valuation in valuations:
        peak = max(peak, valuation["equity"])
        drawdown = min(drawdown, valuation["equity"] / peak - 1)
    values = [v["equity"] for v in valuations]
    sharpe = None
    if len(values) >= 253:
        returns = [b / a - 1 for a, b in zip(values[-253:-1], values[-252:])]
        deviation = statistics.stdev(returns)
        if deviation > 0:
            sharpe = statistics.mean(returns) / deviation * math.sqrt(252)
    sales = [t for t in transactions if t["action"] == "SELL"]
    return {"version": 1, "holdings": holdings, "transactions": transactions,
            "realized_pnl": realized, "unrealized_pnl": unrealized,
            "commissions": commissions, "slippage_cost": slippage,
            "transaction_costs": commissions + slippage, "dividends_received": 0.0,
            "max_drawdown": drawdown if valuations else None, "rolling_sharpe": sharpe,
            "exposure": valuations[-1]["exposure_pct"] / 100 if valuations else None,
            "win_rate": sum(t["realized_pnl"] > 0 for t in sales) / len(sales) if sales else None,
            "closed_trades": len(sales), "signal_history": history[-120:],
            "valuations": valuations,
            "events": [{key: event.get(key) for key in ("event_id", "created_at", "portfolio_id", "event_type", "ticker", "action", "data_asof", "signal_timestamp")}
                       for event in events if event["portfolio_id"] in ("E3", "E3_FORWARD_CONTROL")][-250:]}
