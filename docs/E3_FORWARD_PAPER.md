# F1 + E3 forward-paper operating protocol

This is a simulated paper study with no broker connection. E3 is primary; CSM, SPY and the ten-stock equal-weight universe are independent comparison accounts. Each starts with $10,000. They do not share money or select among strategies using recent performance.

## Frozen strategy

E3 buys when a stock's adjusted close is above its trailing MA200 and below the lower Bollinger Band (20 sessions, 2 population standard deviations). It has no SPY entry filter, MA20 exit or stop loss. It holds at most two names, with new positions receiving up to 50% of available portfolio equity. Simultaneous signals rank by `(lower_band - close) / lower_band`, highest first; ticker ascending breaks ties. Nonselected signals expire at that close.

Entry is at the following session's modeled open. Count the entry session as holding session one. After the tenth holding-session close, schedule a full exit for the next open. A fresh eligible signal may re-enter after an exit, with both sets of costs charged, matching the research implementation.

The unchanged universe is AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, V, WMT. Commission is 0.10% of each fill and adverse slippage is 0.05%. Fractional shares are allowed. There is no leverage, idle cash earns zero, and final open positions are marked rather than fictitiously sold.

## Start and evidence boundary

`python scripts/run_e3_forward.py init` records the actual UTC freeze time, rule digest and implementation SHA256 hashes. The first eligible signal session must open strictly after that timestamp. Pre-start history is warmup only; it cannot create a paper fill or increase the forward-session count. Initialization cannot be rerun to reset performance.

At the first eligible close, record E3's signal and the comparator decisions. Their first possible fills are the following session's opens, subject to eligibility. The benchmark accounts buy at that same first possible open. CSM ranks on the first forward close and then each 20th observed close, applying the original SPY and individual MA200 filters.

Every new close is an observed forward sample, including days when E3 stays in cash. New evidence starts from the actual freeze, not the last historical backtest bar. Future decisions must use only snapshots capped at the signal date, captured after the close and before the intended next open.

## Daily cycle

Run `python scripts/run_e3_forward.py cycle` each trading weekday at 13:30 America/Los_Angeles. The program independently verifies exchange sessions and waits at least twenty minutes after the regular or early close. It performs these steps:

1. Verify the immutable rule/code freeze and append-only ledger chain.
2. Fetch complete raw daily OHLC, observed adjusted closes, dividends and splits for all ten stocks and SPY. Require the exact current session and at least 200 complete exchange sessions per stock.
3. Execute only the previous close's already-recorded plan at the current session's modeled open. Quantities use available open-time cash and marks; no same-day close is used to size these fills. Record the modeled fills after the close with their true later recording timestamp.
4. Mark actual paper shares at the raw close, then create and persist the next-open plan before its deadline.
5. Save source observations, signal details, decisions, modeled fills, costs, cash, positions, corporate actions and NAV. Identical retries must not add trades or duplicate observations.
6. The separate display exporter may publish the verified E3-only snapshot to its own object for the existing V12 website: `python scripts/publish_e3_dashboard.py --upload`. See [E3 dashboard publication](E3_DASHBOARD.md). This external read-only projection does not change the frozen runner, its journal, or V12 state.

If a required session was missed, the runner stops and reports the gap. Do not run a retrospective signal, choose a better later price, silently substitute stale prices, erase an event, reset the account or alter the frozen strategy. Missing current data may be retried before the next-open deadline; a missed deadline requires review.

## Prices and corporate actions

Indicators use adjusted history exactly as captured at the decision time. Actual paper quantities and fills use raw current-session prices. Each stored source snapshot has a hash, observation timestamp and source name. Later provider revisions cannot rewrite prior decisions or fills.

Splits on existing holdings adjust shares before that session's paper fills, retaining a ledger record. Captured ex-dividend distributions accrue to prior holders as dividend receivables, not spendable cash. Without a verified payment-date source they remain receivables rather than fabricated cash payments. Simultaneous split/dividend events halt for review. A split or distribution observed later is not grounds to rewrite an earlier source snapshot.

This forward cash/receivable accounting is not exactly the historical adjusted-price reinvestment approximation; disclose the difference in performance comparisons.

## Isolation, retention and notifications

The separate runtime directory is `paper_ledger/e3_forward/`, already excluded from Git. The isolated event database uses existing append-only database triggers and chained hashes. No V12 ledger, signals, orders, dashboard, cloud state or IBKR connection are read or changed by this runner. Rule and source changes fail the frozen-hash check instead of silently changing the study.

Retain the runtime directory and source snapshots. Git tracks the source, tests, protocol and sanitized startup receipt; it does not back up the private runtime database. Keep a separate filesystem backup of runtime data when operationally available.

Notify on the first captured forward session, a primary E3 scheduled entry/exit or fill, a source/integrity/session-gap failure, or required review. Stay quiet for ordinary no-change days. Do not optimize or swap candidates during scheduled runs. Monthly evidence reviews should report forward-session/trade counts, net returns, drawdowns, exposure, costs, benchmark differences and operational gaps; short samples cannot establish superiority.

## Operations and verified references

Use `python scripts/run_e3_forward.py status` to inspect the actual ledger and counts. Initialization, cycle and status require no brokerage credentials.

The [NYSE calendar and hours](https://www.nyse.com/trade/hours-calendars) supply the exchange-time convention. The existing recurring-holiday calendar is used; unexpected exchange closures require an operational calendar review.

The recurring local task requires the computer to be on, the desktop app running and the project folder accessible, as described in [OpenAI's scheduled-task documentation](https://learn.chatgpt.com/docs/automations?surface=app). A scheduler marked ACTIVE does not prove that a future collection or fill occurred; inspect the actual journal.
