# Frozen V12 Forward Trading Roadmap

Last updated: 2026-08-29
Strategy: `V12-FROZEN-2026-08-28`

## Current decision

- The first legal V12 forward signal and its Internal Simulator lifecycle remain the immediate priority.
- IBKR integration is a later phase. Nothing in this roadmap authorizes an IBKR connection or broker order today.
- The Internal Forward Paper Trading engine remains the deterministic execution and audit baseline.
- The only future broker scope approved by this roadmap is **IBKR PAPER**.
- **IBKR LIVE is prohibited**. Moving to live capital requires a separate design, validation, approval and implementation project.
- V7 and V8 remain diagnostics. Frozen V12 is the only official forward portfolio.

## Target architecture

```text
Research Layer
    ↓
Frozen V12
    ↓
Point-in-Time Signal
    ↓
Risk Engine
    ↓
Target Portfolio
    ↓
Order Manager
    ↓
Broker Abstraction
    ├── Internal Simulator → Expected Fill / Position / P&L
    └── IBKR Paper        → Broker Fill / Position / P&L
                         ↓
                   Reconciliation
                         ↓
                  Portfolio Monitor
                         ↓
                     Streamlit
```

Frozen V12 must not know which broker is used. Streamlit is a monitoring surface, not a trading-state source.

## Phase sequence and gates

| Phase | Scope | Status | Exit gate |
| --- | --- | --- | --- |
| 1 | V12 Final Paper Readiness | **READY WITH CONDITIONS** | Satisfy the gates in `V12_FINAL_PAPER_READINESS_REPORT.md`. |
| 2 | First legal forward signal | **PENDING** | Create the first immutable, non-backfilled point-in-time signal only inside its legal post-close window. |
| 3 | Internal T+1 forward execution | **PENDING** | Verify one complete Signal → Order → Fill → Position → Portfolio → P&L lifecycle, including ledger and accounting reconciliation. |
| 4 | Broker abstraction layer | **NOT STARTED** | Strategy-independent interface and Internal Simulator adapter pass unit tests. Start only after Phase 3 passes. |
| 5 | Mock broker tests | **NOT STARTED** | All lifecycle, failure, idempotency and reconciliation tests pass without an IBKR connection. |
| 6 | IBKR Paper integration | **NOT STARTED** | Paper-only account guard, order lifecycle and recovery are verified. No live capability. |
| 7 | Internal vs IBKR reconciliation | **NOT STARTED** | Expected and broker execution differences are recorded without mutating either source of truth. |
| 8 | Streamlit monitoring dashboard | **NOT STARTED** | Read-only presentation of ledger, portfolio and reconciliation state; no trading state stored in Streamlit. |
| 9 | Forward track record | **NOT STARTED** | Accumulate auditable V12 forward observations before any later capital decision. |

Small-capital live validation is outside the approved roadmap. It may only be evaluated in a separate future phase after an explicit user decision.

## Phase 4 — broker abstraction TODO

Create an execution layer outside Frozen V12:

```text
Strategy → Risk Engine → Order Manager → BrokerInterface
```

The interface should define at least:

- `submit_order()`
- `cancel_order()`
- `get_order_status()`
- `get_positions()`
- `get_account()`
- `get_fills()`

Planned implementations:

- `InternalPaperBroker`
- `IBKRPaperBroker`

`IBKRLiveBroker` is not part of this roadmap.

## Phase 5 — mock broker activation tests

Tests must be independent of an IBKR connection and cover:

- accepted and filled orders;
- partial fills, rejected orders and cancelled orders;
- duplicate submission;
- timeout, connection loss and unknown broker state;
- position reconciliation;
- cash reconciliation;
- transactional recovery and safe retry.

No IBKR Paper connection is allowed until this test gate passes.

## Phase 6 — paper-only order lifecycle

Every signal must move through explicit states:

```text
Signal
→ Risk Decision
→ Order Intent
→ Broker Order
→ Acknowledgement
→ Fill / Partial Fill / Rejection
→ Position
→ Portfolio
→ Reconciliation
```

Submitting an order never implies that it was filled. Supported order states must include:

- `PENDING`
- `SUBMITTED`
- `PARTIALLY_FILLED`
- `FILLED`
- `CANCELLED`
- `REJECTED`

Every transition must be append-only and timestamped.

Each IBKR Paper order record must include at least:

- `strategy_version`, `run_id`, `signal_id`, `order_intent_id`;
- `ticker`, `action`, `quantity`, `target_weight`, `expected_price`;
- `broker`, `broker_account_type`, `broker_order_id`, `order_status`;
- `submitted_at`, `filled_at`, `average_fill_price`, `commission`;
- `execution_rule`, `error_message`.

`broker_account_type` must be `PAPER`. Paper and any future live records must never share an identity or ledger namespace.

## Idempotency and failure policy

Before submitting any broker order:

```text
Check order_intent_id
→ Check the append-only local ledger
→ Check broker state where possible
→ Submit only when the result is unambiguous
```

If order status is unknown, the system must **fail closed** and recover or reconcile state before another submission. A scheduled job or script retry must never duplicate a broker order.

The design must explicitly handle:

- IBKR unavailable, timeout, authentication failure or connection loss;
- rejection, partial fill, cancellation or duplicate order;
- unknown or stale broker state;
- position or cash mismatch;
- closed market, invalid ticker or insufficient paper buying power.

## Source-of-truth boundaries

| Domain | Source of truth |
| --- | --- |
| Research | Frozen V12 plus immutable point-in-time snapshot |
| Expected execution | Internal Simulator |
| Broker execution | IBKR Paper account and broker events |
| Monitoring | Streamlit read-only views |

IBKR state must never overwrite the immutable signal or Internal Simulator ledger. Reconciliation records differences; it does not rewrite history.

## Reconciliation requirements

Compare Internal Simulator and IBKR Paper for:

- expected fill vs broker fill;
- expected position vs broker position;
- expected cash vs broker cash;
- expected portfolio value vs broker account value.

At minimum record:

- fill difference;
- execution difference percentage;
- position difference;
- cash difference;
- portfolio-value difference;
- `MATCH` or `RECONCILIATION WARNING` status.

A mismatch must not be hidden by changing the Internal Simulator ledger.

## T+1 and T+2 isolation

- T+1 remains the Official V12 portfolio.
- T+2 remains the Challenger and its performance must stay separate.
- If both are ever connected to IBKR Paper, they require separate portfolio/accounting identities.
- If one IBKR Paper account cannot isolate them cleanly, only T+1 may use IBKR Paper; T+2 stays in the Internal Simulator.

## Future Streamlit monitoring scope

The future page may display:

- portfolio value, cash, positions, daily and cumulative P&L, and maximum drawdown;
- SPY and QQQ benchmarks;
- signal date and target weights;
- Internal expected fill and IBKR Paper fill;
- execution difference, order status and reconciliation status.

It must clearly display:

- `FORWARD PAPER TRADING`
- `IBKR PAPER`
- `NOT LIVE CAPITAL`

UI work starts only after the underlying broker and reconciliation states are reliable.

## Live-trading boundary

No live-order path is authorized. A future live project would require, at minimum:

- an explicit enable flag and account whitelist;
- independent confirmation and deployment guards;
- maximum order size and portfolio exposure;
- daily loss guard and duplicate-order protection;
- an emergency kill switch.

These controls are listed only to define the future boundary; they are **not implementation TODOs for the current phases**.

## Non-regression rules

This roadmap must not:

- modify Frozen V12;
- delay or backfill the first legal forward signal;
- remove the Internal Simulator;
- put IBKR logic inside strategy code;
- merge T+1 and T+2 performance;
- rewrite already validated infrastructure;
- enable IBKR Live;
- trigger a GitHub push.

The next executable milestone remains Phase 2, followed by verification of the Phase 3 Internal Simulator lifecycle. IBKR work begins only after that gate is explicitly confirmed.
