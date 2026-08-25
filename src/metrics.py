"""Performance and risk metrics for backtest results."""

from __future__ import annotations

import pandas as pd


def calculate_max_drawdown(equity_df):
    equity = equity_df["portfolio_value"].astype(float)
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max * 100
    min_index = drawdown.idxmin()
    peak_index = equity.loc[:min_index].idxmax()
    return {
        "max_drawdown_pct": round(float(drawdown.loc[min_index]), 2),
        "peak_date": equity_df.loc[peak_index, "date"],
        "trough_date": equity_df.loc[min_index, "date"],
    }


def calculate_risk_metrics(equity_df):
    equity = equity_df["portfolio_value"].astype(float)
    daily_returns = equity.pct_change().dropna()
    if daily_returns.empty:
        return {
            "annualized_volatility_pct": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown_pct": None,
        }
    daily_volatility = daily_returns.std()
    annualized_volatility = daily_volatility * (252 ** 0.5)
    daily_mean_return = daily_returns.mean()
    sharpe_ratio = None
    if pd.notna(daily_volatility) and daily_volatility > 0:
        sharpe_ratio = daily_mean_return / daily_volatility * (252 ** 0.5)
    downside_returns = daily_returns[daily_returns < 0]
    sortino_ratio = None
    if not downside_returns.empty:
        downside_deviation = downside_returns.std()
        if pd.notna(downside_deviation) and downside_deviation > 0:
            sortino_ratio = daily_mean_return / downside_deviation * (252 ** 0.5)
    running_max = equity.cummax()
    max_drawdown = ((equity - running_max) / running_max).min()
    return {
        "annualized_volatility_pct": round(float(annualized_volatility * 100), 2),
        "sharpe_ratio": round(float(sharpe_ratio), 3) if sharpe_ratio is not None else None,
        "sortino_ratio": round(float(sortino_ratio), 3) if sortino_ratio is not None else None,
        "max_drawdown_pct": round(float(max_drawdown * 100), 2),
    }


def calculate_performance_metrics(trades, initial_capital, final_value, df):
    start_date = pd.to_datetime(df["date"].iloc[0])
    end_date = pd.to_datetime(df["date"].iloc[-1])
    years = (end_date - start_date).days / 365.25
    cagr_pct = None
    if years > 0 and initial_capital > 0 and final_value > 0:
        cagr_pct = ((final_value / initial_capital) ** (1 / years) - 1) * 100
    completed_trades = []
    buy_trade = None
    for trade in trades:
        if trade["action"] == "buy":
            buy_trade = trade
        elif trade["action"] == "sell" and buy_trade is not None:
            trade_return_pct = ((trade["execution_price"] - buy_trade["execution_price"]) / buy_trade["execution_price"] * 100)
            completed_trades.append({
                "entry_signal_date": buy_trade.get("signal_date"),
                "entry_date": buy_trade.get("execution_date", buy_trade.get("date")),
                "entry_price": buy_trade["execution_price"],
                "exit_date": trade.get("execution_date", trade.get("date")),
                "exit_price": trade["execution_price"],
                "return_pct": round(float(trade_return_pct), 2),
            })
            buy_trade = None
    if completed_trades:
        winning = [t for t in completed_trades if t["return_pct"] > 0]
        losing = [t for t in completed_trades if t["return_pct"] <= 0]
        win_rate_pct = len(winning) / len(completed_trades) * 100
        avg_win_pct = sum(t["return_pct"] for t in winning) / len(winning) if winning else 0
        avg_loss_pct = sum(t["return_pct"] for t in losing) / len(losing) if losing else 0
        total_gains = sum(t["return_pct"] for t in winning)
        total_losses = abs(sum(t["return_pct"] for t in losing))
        profit_factor = total_gains / total_losses if total_losses > 0 else None
    else:
        win_rate_pct = avg_win_pct = avg_loss_pct = profit_factor = None
    return {
        "cagr_pct": round(float(cagr_pct), 2) if cagr_pct is not None else None,
        "years_covered": round(float(years), 2),
        "win_rate_pct": round(float(win_rate_pct), 2) if win_rate_pct is not None else None,
        "avg_win_pct": round(float(avg_win_pct), 2) if avg_win_pct is not None else None,
        "avg_loss_pct": round(float(avg_loss_pct), 2) if avg_loss_pct is not None else None,
        "profit_factor": round(float(profit_factor), 2) if profit_factor is not None else None,
        "number_of_completed_trades": len(completed_trades),
        "completed_trades": completed_trades,
    }


def build_trade_diagnostics(df, completed_trades):
    diagnostics = []
    for trade in completed_trades:
        entry_date = trade["entry_date"]
        exit_date = trade["exit_date"]
        entry_price = trade["entry_price"]
        window = df[(df["date"] >= entry_date) & (df["date"] <= exit_date)]
        if window.empty:
            continue
        holding_days = (pd.to_datetime(exit_date) - pd.to_datetime(entry_date)).days
        market_return_pct = ((window["close"].iloc[-1] - window["close"].iloc[0]) / window["close"].iloc[0] * 100)
        mfe_pct = (window["high"].max() - entry_price) / entry_price * 100
        mae_pct = (window["low"].min() - entry_price) / entry_price * 100
        diagnostics.append({
            "entry_date": entry_date,
            "entry_price": round(float(entry_price), 2),
            "exit_date": exit_date,
            "exit_price": round(float(trade["exit_price"]), 2),
            "return_pct": trade["return_pct"],
            "holding_days": holding_days,
            "market_return_pct": round(float(market_return_pct), 2),
            "mfe_pct": round(float(mfe_pct), 2),
            "mae_pct": round(float(mae_pct), 2),
        })
    return diagnostics


def build_comparison_row(symbol, strategy_name, backtest_result, risk_metrics, performance_metrics):
    return {
        "Stock": symbol,
        "Strategy": strategy_name,
        "Return_pct": backtest_result.get("total_return_pct"),
        "CAGR_pct": performance_metrics.get("cagr_pct") if performance_metrics else None,
        "Volatility_pct": risk_metrics.get("annualized_volatility_pct") if risk_metrics else None,
        "Sharpe": risk_metrics.get("sharpe_ratio") if risk_metrics else None,
        "Sortino": risk_metrics.get("sortino_ratio") if risk_metrics else None,
        "MaxDD_pct": risk_metrics.get("max_drawdown_pct") if risk_metrics else None,
        "WinRate_pct": performance_metrics.get("win_rate_pct") if performance_metrics else None,
        "ProfitFactor": performance_metrics.get("profit_factor") if performance_metrics else None,
        "Trades": performance_metrics.get("number_of_completed_trades") if performance_metrics else backtest_result.get("number_of_trades", 0),
    }
