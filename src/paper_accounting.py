"""Deterministic accounting for the Frozen V12 paper portfolios.

Signals are not calculated here.  This module only translates frozen target
weights into simulated orders and reconciles cash, positions, costs and P&L.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any


COMMISSION_RATE = 0.001
SLIPPAGE_RATE = 0.0005
TOLERANCE = 1e-9


@dataclass(frozen=True)
class Position:
    shares: float
    average_cost: float


@dataclass(frozen=True)
class PortfolioState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    dividends: float = 0.0
    transaction_costs: float = 0.0

    def equity(self, marks: dict[str, float]) -> float:
        missing = sorted(set(self.positions) - set(marks))
        if missing:
            raise ValueError(f"missing marks for: {', '.join(missing)}")
        return self.cash + sum(
            position.shares * float(marks[ticker])
            for ticker, position in self.positions.items()
        )

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        missing = sorted(set(self.positions) - set(marks))
        if missing:
            raise ValueError(f"missing marks for: {', '.join(missing)}")
        return sum(
            position.shares * (float(marks[ticker]) - position.average_cost)
            for ticker, position in self.positions.items()
        )


@dataclass(frozen=True)
class PaperOrder:
    sequence: int
    ticker: str
    side: str
    shares: float
    expected_price: float
    estimated_fill_price: float
    estimated_notional: float
    estimated_commission: float
    estimated_slippage_cost: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrderPlan:
    pretrade_equity: float
    starting_cash: float
    estimated_ending_cash: float
    target_weights: dict[str, float]
    estimated_final_shares: dict[str, float]
    orders: tuple[PaperOrder, ...]


def _validate_prices(required: set[str], prices: dict[str, float]) -> None:
    missing = sorted(required - set(prices))
    if missing:
        raise ValueError(f"missing execution prices for: {', '.join(missing)}")
    invalid = sorted(
        ticker
        for ticker in required
        if not math.isfinite(float(prices[ticker])) or float(prices[ticker]) <= 0
    )
    if invalid:
        raise ValueError(f"invalid execution prices for: {', '.join(invalid)}")


def build_order_plan(
    state: PortfolioState,
    raw_open_prices: dict[str, float],
    target_weights: dict[str, float],
    *,
    commission_rate: float = COMMISSION_RATE,
    slippage_rate: float = SLIPPAGE_RATE,
    fractional_shares: bool = True,
) -> OrderPlan:
    """Create a sell-first, cash-safe rebalance plan from frozen target weights."""
    if state.cash < -TOLERANCE:
        raise ValueError("cash cannot be negative")
    if commission_rate < 0 or slippage_rate < 0:
        raise ValueError("commission and slippage cannot be negative")
    weights = {str(k): float(v) for k, v in target_weights.items() if float(v) > TOLERANCE}
    if any(value < 0 for value in target_weights.values()):
        raise ValueError("target weights cannot be negative")
    if sum(weights.values()) > 1.0 + TOLERANCE:
        raise ValueError("target weights cannot exceed 100%")
    holdings = {
        ticker: float(position.shares)
        for ticker, position in state.positions.items()
        if position.shares > TOLERANCE
    }
    required = set(holdings) | set(weights)
    _validate_prices(required, raw_open_prices)
    opens = {ticker: float(raw_open_prices[ticker]) for ticker in required}
    equity = state.cash + sum(holdings[ticker] * opens[ticker] for ticker in holdings)
    target_shares = {
        ticker: equity * weight / opens[ticker] for ticker, weight in weights.items()
    }
    if not fractional_shares:
        target_shares = {ticker: float(math.floor(value)) for ticker, value in target_shares.items()}

    orders: list[PaperOrder] = []
    cash = float(state.cash)
    sequence = 1

    for ticker in sorted(holdings):
        current = holdings[ticker]
        desired = target_shares.get(ticker, 0.0)
        shares = max(current - desired, 0.0)
        if shares <= TOLERANCE:
            continue
        fill = opens[ticker] * (1.0 - slippage_rate)
        notional = shares * fill
        commission = notional * commission_rate
        cash += notional - commission
        holdings[ticker] = current - shares
        orders.append(
            PaperOrder(
                sequence, ticker, "SELL", shares, opens[ticker], fill,
                notional, commission, shares * opens[ticker] * slippage_rate,
                "Frozen V12 monthly rebalance",
            )
        )
        sequence += 1

    for ticker in sorted(weights):
        current = holdings.get(ticker, 0.0)
        desired = max(target_shares[ticker] - current, 0.0)
        if desired <= TOLERANCE:
            continue
        fill = opens[ticker] * (1.0 + slippage_rate)
        affordable = cash / (fill * (1.0 + commission_rate))
        shares = min(desired, affordable)
        if not fractional_shares:
            shares = float(math.floor(shares))
        if shares <= TOLERANCE:
            continue
        notional = shares * fill
        commission = notional * commission_rate
        cash -= notional + commission
        holdings[ticker] = current + shares
        orders.append(
            PaperOrder(
                sequence, ticker, "BUY", shares, opens[ticker], fill,
                notional, commission, shares * opens[ticker] * slippage_rate,
                "Frozen V12 monthly rebalance",
            )
        )
        sequence += 1

    holdings = {ticker: shares for ticker, shares in holdings.items() if shares > TOLERANCE}
    if cash < -1e-6:
        raise AssertionError("order plan produced negative cash")
    return OrderPlan(
        pretrade_equity=equity,
        starting_cash=state.cash,
        estimated_ending_cash=max(cash, 0.0),
        target_weights=weights,
        estimated_final_shares=holdings,
        orders=tuple(orders),
    )


def apply_fills(state: PortfolioState, orders: tuple[PaperOrder, ...]) -> PortfolioState:
    """Apply a complete fill batch and return a reconciled immutable state."""
    cash = float(state.cash)
    positions = dict(state.positions)
    realized = float(state.realized_pnl)
    costs = float(state.transaction_costs)
    for order in orders:
        if order.shares <= TOLERANCE or order.estimated_fill_price <= 0:
            raise ValueError("fill quantity and price must be positive")
        ticker = order.ticker
        position = positions.get(ticker, Position(0.0, 0.0))
        if order.side == "BUY":
            total_cost = order.estimated_notional + order.estimated_commission
            new_shares = position.shares + order.shares
            average_cost = (
                position.shares * position.average_cost + total_cost
            ) / new_shares
            cash -= total_cost
            positions[ticker] = Position(new_shares, average_cost)
        elif order.side == "SELL":
            if order.shares > position.shares + TOLERANCE:
                raise ValueError(f"sell exceeds position for {ticker}")
            net_proceeds = order.estimated_notional - order.estimated_commission
            realized += net_proceeds - order.shares * position.average_cost
            cash += net_proceeds
            remaining = position.shares - order.shares
            if remaining <= TOLERANCE:
                positions.pop(ticker, None)
            else:
                positions[ticker] = Position(remaining, position.average_cost)
        else:
            raise ValueError(f"unsupported side: {order.side}")
        costs += order.estimated_commission + order.estimated_slippage_cost
    if cash < -1e-6:
        raise AssertionError("fills produced negative cash")
    expected_cash = state.cash + sum(
        (order.estimated_notional - order.estimated_commission)
        if order.side == "SELL"
        else -(order.estimated_notional + order.estimated_commission)
        for order in orders
    )
    if not math.isclose(cash, expected_cash, abs_tol=1e-7):
        raise AssertionError("cash reconciliation failed")
    return PortfolioState(max(cash, 0.0), positions, realized, state.dividends, costs)


def apply_split(state: PortfolioState, ticker: str, ratio: float) -> PortfolioState:
    """Adjust shares and unit cost without creating profit or loss."""
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("split ratio must be positive")
    if ticker not in state.positions:
        return state
    positions = dict(state.positions)
    position = positions[ticker]
    positions[ticker] = Position(position.shares * ratio, position.average_cost / ratio)
    return PortfolioState(state.cash, positions, state.realized_pnl, state.dividends, state.transaction_costs)


def apply_dividend(state: PortfolioState, ticker: str, amount_per_share: float) -> PortfolioState:
    if amount_per_share < 0 or not math.isfinite(amount_per_share):
        raise ValueError("dividend must be finite and non-negative")
    shares = state.positions.get(ticker, Position(0.0, 0.0)).shares
    cash_amount = shares * amount_per_share
    return PortfolioState(
        state.cash + cash_amount,
        state.positions,
        state.realized_pnl,
        state.dividends + cash_amount,
        state.transaction_costs,
    )


def apply_ticker_change(state: PortfolioState, old: str, new: str) -> PortfolioState:
    if old not in state.positions:
        return state
    if new in state.positions:
        raise ValueError("ticker change would collide with an existing position")
    positions = dict(state.positions)
    positions[new] = positions.pop(old)
    return PortfolioState(state.cash, positions, state.realized_pnl, state.dividends, state.transaction_costs)
