"""A single next-session-open execution engine shared by every strategy."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    commission_rate: float = 0.001
    slippage_rate: float = 0.0005


REQUIRED_COLUMNS = {"date", "open", "close", "entry_signal", "exit_signal"}


def run_backtest(
    data: pd.DataFrame,
    symbol: str,
    strategy_name: str,
    config: BacktestConfig | None = None,
) -> dict:
    config = config or BacktestConfig()
    missing = REQUIRED_COLUMNS.difference(data.columns)
    if missing:
        raise ValueError(f"Missing backtest columns: {sorted(missing)}")

    df = data.sort_values("date").reset_index(drop=True).copy()
    cash = config.initial_capital
    shares = 0.0
    trades: list[dict] = []
    equity_rows: list[dict] = []
    pending: dict | None = None
    exposed_days = 0

    for i, row in df.iterrows():
        if pending is not None and pd.notna(row["open"]):
            action = pending["action"]
            if action == "BUY" and shares == 0:
                actual_price = float(row["open"]) * (1 + config.slippage_rate)
                shares = cash / (actual_price * (1 + config.commission_rate))
                notional = shares * actual_price
                commission = notional * config.commission_rate
                cash -= notional + commission
                if abs(cash) < 1e-8:
                    cash = 0.0
                trades.append({
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "action": "BUY",
                    "signal_date": pending["signal_date"],
                    "execution_date": row["date"],
                    "execution_price": actual_price,
                    "shares": shares,
                    "transaction_cost": commission,
                    "reason": pending["reason"],
                })
            elif action == "SELL" and shares > 0:
                actual_price = float(row["open"]) * (1 - config.slippage_rate)
                notional = shares * actual_price
                commission = notional * config.commission_rate
                cash += notional - commission
                trades.append({
                    "symbol": symbol,
                    "strategy": strategy_name,
                    "action": "SELL",
                    "signal_date": pending["signal_date"],
                    "execution_date": row["date"],
                    "execution_price": actual_price,
                    "shares": shares,
                    "transaction_cost": commission,
                    "reason": pending["reason"],
                })
                shares = 0.0
            pending = None

        if shares > 0:
            exposed_days += 1

        equity_rows.append({
            "date": row["date"],
            "equity": cash + shares * float(row["close"]),
            "cash": cash,
            "shares": shares,
        })

        # Signals observed at today's close can only execute on the next row's open.
        if i < len(df) - 1:
            if shares == 0 and bool(row["entry_signal"]):
                pending = {
                    "action": "BUY",
                    "signal_date": row["date"],
                    "reason": row.get("entry_reason", "Entry signal"),
                }
            elif shares > 0 and bool(row["exit_signal"]):
                pending = {
                    "action": "SELL",
                    "signal_date": row["date"],
                    "reason": row.get("exit_reason", "Exit signal"),
                }

    equity_curve = pd.DataFrame(equity_rows)
    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "initial_capital": config.initial_capital,
        "final_value": float(equity_curve["equity"].iloc[-1]),
        "trades": trades,
        "equity_curve": equity_curve,
        "open_position": shares > 0,
        "open_shares": shares,
        "exposure_pct": 100 * exposed_days / len(df) if len(df) else 0.0,
    }


def run_buy_and_hold(
    data: pd.DataFrame,
    symbol: str,
    config: BacktestConfig | None = None,
) -> dict:
    df = data.sort_values("date").reset_index(drop=True).copy()
    df["entry_signal"] = False
    df["exit_signal"] = False
    if len(df) > 1:
        df.loc[0, "entry_signal"] = True
        df.loc[0, "entry_reason"] = "Buy-and-hold baseline"
    return run_backtest(df, symbol, "Buy & Hold", config)
