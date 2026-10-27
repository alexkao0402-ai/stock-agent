"""Shared next-open portfolio engine for independently signalled stocks."""
from __future__ import annotations

import pandas as pd

from src.backtest_engine import BacktestConfig


def run_signal_portfolio(
    prepared: dict[str, pd.DataFrame],
    strategy: str,
    config: BacktestConfig,
    max_positions: int = 2,
    max_holding_days: int | None = None,
) -> dict:
    """Run signals with at most two positions and a 50% entry allocation cap."""
    if not prepared:
        raise ValueError("prepared data cannot be empty")
    frames = {}
    common = None
    for symbol, raw in prepared.items():
        frame = raw.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").drop_duplicates("date").set_index("date")
        frames[symbol] = frame
        common = set(frame.index) if common is None else common.intersection(frame.index)
    dates = sorted(common or [])
    if len(dates) < 2:
        raise ValueError("At least two common sessions are required")

    cash = float(config.initial_capital)
    positions: dict[str, dict] = {}
    pending: dict | None = None
    trades, equity_rows = [], []

    for date in dates:
        if pending:
            # Exits are processed first, using only the prior close's decisions.
            for symbol in pending["exits"]:
                if symbol not in positions:
                    continue
                qty = positions[symbol]["shares"]
                raw_open = float(frames[symbol].loc[date, "open"])
                price = raw_open * (1 - config.slippage_pct)
                notional = qty * price
                fee = notional * config.transaction_cost_pct
                cash += notional - fee
                trades.append({"signal_date": pending["signal_date"], "execution_date": date, "date": date,
                               "symbol": symbol, "strategy": strategy, "action": "SELL",
                               "execution_price": price, "shares": qty, "notional": notional,
                               "transaction_cost": fee, "reason": pending["exit_reasons"][symbol]})
                del positions[symbol]

            equity_at_open = cash + sum(
                pos["shares"] * float(frames[symbol].loc[date, "open"])
                for symbol, pos in positions.items()
            )
            allocation_cap = equity_at_open / max_positions
            for symbol in pending["entries"]:
                if symbol in positions or len(positions) >= max_positions:
                    continue
                raw_open = float(frames[symbol].loc[date, "open"])
                price = raw_open * (1 + config.slippage_pct)
                budget = min(allocation_cap, cash / (1 + config.transaction_cost_pct))
                qty = budget / price
                notional = qty * price
                fee = notional * config.transaction_cost_pct
                if qty <= 0:
                    continue
                cash -= notional + fee
                positions[symbol] = {"shares": qty, "entry_date": date, "sessions": 0}
                trades.append({"signal_date": pending["signal_date"], "execution_date": date, "date": date,
                               "symbol": symbol, "strategy": strategy, "action": "BUY",
                               "execution_price": price, "shares": qty, "notional": notional,
                               "transaction_cost": fee, "reason": "pre_registered_entry"})
            pending = None

        close_value = cash + sum(
            pos["shares"] * float(frames[symbol].loc[date, "close"])
            for symbol, pos in positions.items()
        )
        invested = sum(
            pos["shares"] * float(frames[symbol].loc[date, "close"])
            for symbol, pos in positions.items()
        )
        equity_rows.append({"date": date, "equity": close_value, "portfolio_value": close_value,
                            "cash": cash, "holdings": len(positions), "invested_value": invested})

        if date == dates[-1]:
            continue
        exits, reasons = [], {}
        for symbol, pos in positions.items():
            pos["sessions"] += 1
            row = frames[symbol].loc[date]
            timed = max_holding_days is not None and pos["sessions"] >= max_holding_days
            if bool(row.get("exit_signal", False)) or timed:
                exits.append(symbol)
                reasons[symbol] = "max_holding_days" if timed else "pre_registered_exit"
        slots = max_positions - (len(positions) - len(exits))
        candidates = []
        for symbol, frame in frames.items():
            if symbol in positions and symbol not in exits:
                continue
            row = frame.loc[date]
            if bool(row.get("entry_signal", False)):
                score = float(row.get("score", 0.0)) if pd.notna(row.get("score", 0.0)) else 0.0
                candidates.append((score, symbol))
        candidates.sort(reverse=True)
        pending = {"signal_date": date, "exits": exits, "exit_reasons": reasons,
                   "entries": [symbol for _, symbol in candidates[:max(0, slots)]]}

    curve = pd.DataFrame(equity_rows)
    return {"symbol": "LARGE_CAP_UNIVERSE", "strategy": strategy,
            "initial_capital": config.initial_capital, "final_value": float(curve["equity"].iloc[-1]),
            "equity_curve": curve, "trades": trades, "open_position": bool(positions),
            "open_holdings": sorted(positions),
            "exposure_pct": float((curve["invested_value"] / curve["equity"]).mean() * 100)}
