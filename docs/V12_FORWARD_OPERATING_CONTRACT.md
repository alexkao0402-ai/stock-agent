# Frozen V12 Forward Paper Operating Contract

The phased path after the first legal Internal Simulator lifecycle is defined in `V12_ROADMAP.md`. This operating contract remains authoritative for the current forward run; the roadmap does not activate IBKR or alter Frozen V12.

## Classification

- Strategy: `V12-FROZEN-2026-08-28`
- Official execution portfolio: `T+1_OPEN`
- Challenger execution portfolio: `T+2_OPEN`
- Every official package must say `FORWARD`, `NOT_BACKTEST`, and `NOT_BACKFILLED`.
- V7 and V8 are selection diagnostics only. They are not separate paper portfolios.

## Time and session definition

- Calendar timezone: `America/New_York`.
- Signal: close of the final valid NYSE session of the month.
- T+1: next valid NYSE session.
- T+2: second valid NYSE session.
- A recurring NYSE holiday calendar, early-close times, weekends, and DST are explicit in code.
- Exceptional exchange closures are an operational calendar update. Affected runs must fail closed until the calendar is updated and reviewed.

## Return definition

- V12 signal indicators use adjusted/total-return close history.
- The paper portfolio uses raw USD shares and raw USD marks. Cash dividends are credited and stock splits adjust both shares and unit cost; therefore the intended portfolio return is total return.
- SPY and QQQ paper benchmarks start with the same capital, use their corresponding T+1 or T+2 opening session, and use the same commission/slippage assumptions on simulated purchases. Dividends and splits use the same accounting functions as V12.
- `Strategy Return - Benchmark Return` is named **Excess Return vs SPY** or **Excess Return vs QQQ**. It is not called Alpha without a separate regression estimate.

## Costs and share policy

- Commission: 0.10% of simulated notional.
- Adverse slippage: 0.05% from the raw opening price.
- Frozen paper policy: fractional shares are allowed, matching the historical portfolio's continuous-weight accounting. Whole-share mode is separately tested for diagnostics but is not the official forward account.
- Sells are processed before buys and purchases cannot create negative cash.

## Accounting identity

Every portfolio snapshot must reconcile:

`Portfolio Equity = Cash + Market Value of Positions`

Realized P&L is net sale proceeds, after sell commission, minus the sold shares' average cost basis. Average cost includes buy commission. Unrealized P&L is marked value minus remaining average cost basis. Dividends are tracked separately and also increase cash.

## Corporate actions

- Supported accounting: cash dividends, stock splits, and one-to-one ticker changes.
- Merger and delisting handling is **not automated** in the first paper version. An affected portfolio must fail closed until explicit cash/stock terms and an auditable event are supplied.
- Yahoo action data is captured in the immutable price snapshot, but automated daily action ingestion is part of P2 monitoring and is not yet complete.

## Append-only state and retry rules

- The SQLite event log rejects updates and deletes with database triggers.
- Signal, order, fill, corporate-action and snapshot records use deterministic IDs.
- Identical retries return `ALREADY_PROCESSED`/skip.
- The same ID with different content is a corruption error.
- Signal and pending-order creation is one database transaction.
- Fill events and the post-fill portfolio snapshot are one database transaction.
- A crash inside either transaction rolls back the entire batch. A crash after commit can be retried without duplicate events.
- Daily close valuation events are deterministic and append-only. They do not
  create signals, orders or fills and do not change the Frozen V12 definition.
- The cloud runner restores an HMAC-authenticated private state bundle and
  rejects any ledger that is newer than or divergent from its verified chain.

## Health policy

Operational failures can block a run: missing/stale data, partial universe, invalid trading date/time, failed hash, duplicate-content collision, missing portfolio initialization, or accounting reconciliation failure.

Statistical weakness can only warn and trigger investigation. It cannot modify or stop Frozen V12 unless a separate stop rule is researched, backtested, and validated out of sample before adoption.
