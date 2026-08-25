"""Cross-sectional large-cap portfolio research with next-open rebalancing."""

from __future__ import annotations

import math

import pandas as pd

from src.backtest_engine import BacktestConfig
from src.indicators import add_momentum, add_moving_averages


def _prepare_panel(price_data: dict[str, pd.DataFrame], spy_df: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for symbol, raw in price_data.items():
        frame = add_momentum(add_moving_averages(raw))
        frames.append(frame.assign(symbol=symbol))
    panel = pd.concat(frames, ignore_index=True)
    spy = add_moving_averages(spy_df)[["date", "close", "ma200"]].rename(
        columns={"close": "spy_close", "ma200": "spy_ma200"}
    )
    return panel.merge(spy, on="date", how="inner", validate="many_to_one")


def cross_sectional_momentum_backtest(
    price_data: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    config: BacktestConfig | None = None,
    top_fraction: float = 0.2,
) -> dict:
    """Hold the strongest large caps, ranked at month-end and traded next open."""
    config = config or BacktestConfig()
    if not price_data:
        raise ValueError("price_data cannot be empty")
    panel = _prepare_panel(price_data, spy_df)
    coverage = panel.groupby("date")["symbol"].nunique()
    dates = sorted(coverage[coverage == len(price_data)].index)
    panel = panel[panel["date"].isin(dates)]
    cash = config.initial_capital
    shares: dict[str, float] = {}
    pending_targets: list[str] | None = None
    equity_rows = []
    trades = []

    for date_i, date in enumerate(dates):
        day = panel[panel["date"] == date].set_index("symbol")
        available = [symbol for symbol in price_data if symbol in day.index and pd.notna(day.loc[symbol, "open"])]

        if pending_targets is not None:
            targets = [symbol for symbol in pending_targets if symbol in available]
            pretrade_value = cash + sum(
                quantity * float(day.loc[symbol, "open"])
                for symbol, quantity in shares.items()
                if symbol in day.index
            )
            target_value = pretrade_value / len(targets) if targets else 0.0

            for symbol, quantity in list(shares.items()):
                raw_open = float(day.loc[symbol, "open"])
                desired_quantity = target_value / raw_open if symbol in targets else 0.0
                sell_quantity = max(quantity - desired_quantity, 0.0)
                if sell_quantity > 1e-10:
                    execution_price = raw_open * (1 - config.slippage_rate)
                    notional = sell_quantity * execution_price
                    commission = notional * config.commission_rate
                    cash += notional - commission
                    shares[symbol] = quantity - sell_quantity
                    trades.append({"date": date, "symbol": symbol, "action": "SELL", "notional": notional, "cost": commission})

            for symbol in targets:
                raw_open = float(day.loc[symbol, "open"])
                current_value = shares.get(symbol, 0.0) * raw_open
                desired_notional = max(target_value - current_value, 0.0)
                execution_price = raw_open * (1 + config.slippage_rate)
                affordable = cash / (execution_price * (1 + config.commission_rate))
                buy_quantity = min(desired_notional / execution_price, affordable)
                if buy_quantity > 1e-10:
                    notional = buy_quantity * execution_price
                    commission = notional * config.commission_rate
                    cash -= notional + commission
                    shares[symbol] = shares.get(symbol, 0.0) + buy_quantity
                    trades.append({"date": date, "symbol": symbol, "action": "BUY", "notional": notional, "cost": commission})
            shares = {symbol: quantity for symbol, quantity in shares.items() if quantity > 1e-10}
            pending_targets = None

        close_value = cash + sum(
            quantity * float(day.loc[symbol, "close"])
            for symbol, quantity in shares.items()
            if symbol in day.index
        )
        equity_rows.append({"date": date, "equity": close_value, "cash": cash, "holdings": len(shares)})

        if date_i < len(dates) - 1:
            current_month = pd.Timestamp(date).to_period("M")
            next_month = pd.Timestamp(dates[date_i + 1]).to_period("M")
            if current_month != next_month:
                spy_bull = bool(day["spy_close"].iloc[0] > day["spy_ma200"].iloc[0]) if pd.notna(day["spy_ma200"].iloc[0]) else False
                eligible = day[
                    day[["momentum_6m", "ma200"]].notna().all(axis=1)
                    & (day["close"] > day["ma200"])
                ]
                count = max(1, math.ceil(len(price_data) * top_fraction))
                pending_targets = eligible.nlargest(count, "momentum_6m").index.tolist() if spy_bull else []

    curve = pd.DataFrame(equity_rows)
    return {
        "symbol": "LARGE_CAP_UNIVERSE",
        "strategy": "Cross-Sectional Momentum",
        "initial_capital": config.initial_capital,
        "final_value": float(curve["equity"].iloc[-1]),
        "equity_curve": curve,
        "trades": trades,
        "open_position": bool(shares),
        "open_holdings": sorted(shares),
        "exposure_pct": 100 * float((curve["holdings"] > 0).mean()),
    }


def latest_cross_sectional_ranking(
    price_data: dict[str, pd.DataFrame],
    spy_df: pd.DataFrame,
    top_fraction: float = 0.2,
) -> pd.DataFrame:
    """Return the latest point-in-time ranking and selected portfolio members."""
    panel = _prepare_panel(price_data, spy_df)
    coverage = panel.groupby("date")["symbol"].nunique()
    common_dates = coverage[coverage == len(price_data)].index
    if len(common_dates) == 0:
        return pd.DataFrame()
    day = panel[panel["date"] == common_dates[-1]].copy()
    spy_bull = bool(day["spy_close"].iloc[0] > day["spy_ma200"].iloc[0]) if pd.notna(day["spy_ma200"].iloc[0]) else False
    day["eligible"] = day[["momentum_6m", "ma200"]].notna().all(axis=1) & (day["close"] > day["ma200"])
    day = day.sort_values("momentum_6m", ascending=False).reset_index(drop=True)
    day["rank"] = range(1, len(day) + 1)
    count = max(1, math.ceil(len(price_data) * top_fraction))
    selected = day.loc[day["eligible"], "symbol"].head(count).tolist() if spy_bull else []
    day["selected"] = day["symbol"].isin(selected)
    day["market_regime"] = "Bull" if spy_bull else "Defensive"
    return day[["date", "rank", "symbol", "momentum_6m", "eligible", "selected", "market_regime"]]


def equal_weight_buy_and_hold(
    price_data: dict[str, pd.DataFrame],
    config: BacktestConfig | None = None,
) -> dict:
    """Invest equally across the same fixed universe on the first common next open."""
    config = config or BacktestConfig()
    common_dates = None
    indexed = {}
    for symbol, frame in price_data.items():
        item = frame.copy().set_index("date").sort_index()
        indexed[symbol] = item
        dates = set(item.index)
        common_dates = dates if common_dates is None else common_dates & dates
    dates = sorted(common_dates or [])
    if len(dates) < 2:
        raise ValueError("At least two common dates are required")
    execution_date = dates[1]
    allocation = config.initial_capital / len(indexed)
    shares = {}
    for symbol, frame in indexed.items():
        price = float(frame.loc[execution_date, "open"]) * (1 + config.slippage_rate)
        shares[symbol] = allocation / (price * (1 + config.commission_rate))
    equity_rows = []
    for date in dates:
        value = config.initial_capital if date < execution_date else sum(
            quantity * float(indexed[symbol].loc[date, "close"])
            for symbol, quantity in shares.items()
        )
        equity_rows.append({"date": date, "equity": value, "cash": 0.0, "holdings": len(shares)})
    curve = pd.DataFrame(equity_rows)
    return {
        "symbol": "LARGE_CAP_UNIVERSE",
        "strategy": "Equal-Weight Universe",
        "initial_capital": config.initial_capital,
        "final_value": float(curve["equity"].iloc[-1]),
        "equity_curve": curve,
        "trades": [],
        "open_position": True,
        "open_holdings": sorted(shares),
        "exposure_pct": 100.0,
    }
