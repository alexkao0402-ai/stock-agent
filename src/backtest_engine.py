"""Unified long-only backtest engine with explicit T+1 execution."""
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

ExitMode = Literal["signal_only", "take_profit", "trailing"]


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10000.0
    transaction_cost_pct: float = 0.001
    slippage_pct: float = 0.0005
    exit_mode: ExitMode = "signal_only"
    take_profit_pct: float = 25.0
    trailing_pct: float = 20.0


def _buy(cash, open_price, cfg):
    execution_price = open_price * (1 + cfg.slippage_pct)
    shares = cash / (execution_price * (1 + cfg.transaction_cost_pct))
    transaction_cost = shares * execution_price * cfg.transaction_cost_pct
    return shares, execution_price, transaction_cost


def _sell(shares, raw_price, cfg):
    execution_price = raw_price * (1 - cfg.slippage_pct)
    gross = shares * execution_price
    transaction_cost = gross * cfg.transaction_cost_pct
    cash = gross - transaction_cost
    return cash, execution_price, transaction_cost


def run_backtest(df: pd.DataFrame, *args, config: Optional[BacktestConfig] = None):
    """Run one long-only strategy through the shared T+1 execution engine.

    Supports the V2 form ``run_backtest(df, config)`` and the research form
    ``run_backtest(df, symbol, strategy_name, config)``.
    """
    symbol = None
    strategy_name = "Strategy"
    if args and isinstance(args[0], str):
        symbol = args[0]
        strategy_name = args[1] if len(args) > 1 else strategy_name
        cfg = args[2] if len(args) > 2 else (config or BacktestConfig())
    else:
        cfg = args[0] if args else (config or BacktestConfig())
    df = df.copy()
    if "signal" not in df.columns and {"entry_signal", "exit_signal"}.issubset(df.columns):
        df["signal"] = None
        df.loc[df["entry_signal"].astype(bool), "signal"] = "buy"
        df.loc[df["exit_signal"].astype(bool), "signal"] = "sell"
    required = {"date", "open", "high", "low", "close", "signal"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    data = df.copy().reset_index(drop=True)
    if data.empty:
        raise ValueError("Backtest data is empty.")

    data["date_dt"] = pd.to_datetime(data["date"])
    data = data.sort_values("date_dt").drop(columns="date_dt").reset_index(drop=True)

    cash = float(cfg.initial_capital)
    shares = 0.0
    entry_price = None
    highest_known = None
    entry_signal_date = None
    trades, equity_rows = [], []

    for i in range(len(data)):
        row = data.iloc[i]
        current_date = row["date"]
        current_open = float(row["open"])
        current_high = float(row["high"])
        current_low = float(row["low"])
        current_close = float(row["close"])

        # Signals observed at T close may execute only at T+1 open.
        if i > 0:
            prev = data.iloc[i - 1]
            if prev["signal"] == "sell" and shares > 0:
                cash, px, transaction_cost = _sell(shares, current_open, cfg)
                trades.append({
                    "signal_date": prev["date"],
                    "execution_date": current_date,
                    "date": current_date,
                    "action": "sell",
                    "execution_price": px,
                    "shares": shares,
                    "transaction_cost": transaction_cost,
                    "reason": "strategy_signal",
                })
                shares, entry_price, highest_known, entry_signal_date = 0.0, None, None, None
            elif prev["signal"] == "buy" and cash > 0:
                shares, px, transaction_cost = _buy(cash, current_open, cfg)
                cash, entry_price, highest_known, entry_signal_date = 0.0, px, px, prev["date"]
                trades.append({
                    "signal_date": prev["date"],
                    "execution_date": current_date,
                    "date": current_date,
                    "action": "buy",
                    "execution_price": px,
                    "shares": shares,
                    "transaction_cost": transaction_cost,
                    "reason": "strategy_signal",
                })

        if shares > 0 and entry_price is not None:
            if cfg.exit_mode == "take_profit":
                target = entry_price * (1 + cfg.take_profit_pct / 100)
                # Gap-up: assume the open is available; otherwise execute at target when high reaches it.
                if current_open >= target:
                    raw_exit = current_open
                elif current_high >= target:
                    raw_exit = target
                else:
                    raw_exit = None

                if raw_exit is not None:
                    cash, px, transaction_cost = _sell(shares, raw_exit, cfg)
                    trades.append({
                        "signal_date": entry_signal_date,
                        "execution_date": current_date,
                        "date": current_date,
                        "action": "sell",
                        "execution_price": px,
                        "shares": shares,
                        "transaction_cost": transaction_cost,
                        "reason": f"take_profit_{cfg.take_profit_pct:g}pct",
                    })
                    shares, entry_price, highest_known, entry_signal_date = 0.0, None, None, None

            elif cfg.exit_mode == "trailing":
                # Stop is based only on information known before today's intraday path.
                stop = highest_known * (1 - cfg.trailing_pct / 100)

                # Gap-down through the stop must execute at the open, not at an unavailable stop price.
                if current_open <= stop:
                    raw_exit = current_open
                elif current_low <= stop:
                    raw_exit = stop
                else:
                    raw_exit = None

                if raw_exit is not None:
                    cash, px, transaction_cost = _sell(shares, raw_exit, cfg)
                    trades.append({
                        "signal_date": entry_signal_date,
                        "execution_date": current_date,
                        "date": current_date,
                        "action": "sell",
                        "execution_price": px,
                        "shares": shares,
                        "transaction_cost": transaction_cost,
                        "reason": f"trailing_{cfg.trailing_pct:g}pct",
                    })
                    shares, entry_price, highest_known, entry_signal_date = 0.0, None, None, None
                else:
                    highest_known = max(highest_known, current_high)

        position_value = shares * current_close
        equity_rows.append({
            "date": current_date,
            "close": current_close,
            "cash": cash,
            "shares": shares,
            "position_value": position_value,
            "portfolio_value": cash + position_value,
            "position": int(shares > 0),
        })

    equity_curve = pd.DataFrame(equity_rows)
    equity_curve["equity"] = equity_curve["portfolio_value"]
    final_value = float(equity_curve["portfolio_value"].iloc[-1])
    result = {
        "symbol": symbol,
        "strategy": strategy_name,
        "initial_capital": cfg.initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round((final_value / cfg.initial_capital - 1) * 100, 2),
        "number_of_trades": len(trades),
        "transaction_cost_pct": cfg.transaction_cost_pct,
        "slippage_pct": cfg.slippage_pct,
        "trades": trades,
        "still_holding_shares": shares > 0,
        "open_position": shares > 0,
        "open_shares": shares,
        "equity_curve": equity_curve,
        "exit_mode": cfg.exit_mode,
        "exposure_pct": float(equity_curve["position"].mean() * 100),
    }
    for trade in result["trades"]:
        trade.setdefault("symbol", symbol)
        trade.setdefault("strategy", strategy_name)
    return result


def run_buy_and_hold(df, symbol, config: Optional[BacktestConfig] = None):
    """Buy at the first available next-session open and hold through the end."""
    data = df.copy().sort_values("date").reset_index(drop=True)
    data["signal"] = None
    if len(data) > 1:
        data.loc[0, "signal"] = "buy"
    return run_backtest(data, symbol, "Buy & Hold", config or BacktestConfig())


def calculate_buy_and_hold(
    df,
    initial_capital=10000,
    transaction_cost_pct=0.001,
    slippage_pct=0.0005,
):
    if df.empty:
        raise ValueError("Buy & Hold data is empty.")

    data = df.copy()
    data["date_dt"] = pd.to_datetime(data["date"])
    data = data.sort_values("date_dt").reset_index(drop=True)

    first_open = float(data["open"].iloc[0])
    final_close = float(data["close"].iloc[-1])
    buy_price = first_open * (1 + slippage_pct)
    shares = initial_capital * (1 - transaction_cost_pct) / buy_price
    sell_price = final_close * (1 - slippage_pct)
    final_value = shares * sell_price * (1 - transaction_cost_pct)

    return {
        "initial_capital": initial_capital,
        "final_value": round(final_value, 2),
        "total_return_pct": round((final_value / initial_capital - 1) * 100, 2),
        "start_date": data["date"].iloc[0],
        "end_date": data["date"].iloc[-1],
        "start_price": first_open,
        "end_price": final_close,
        "transaction_cost_pct": transaction_cost_pct,
        "slippage_pct": slippage_pct,
    }
