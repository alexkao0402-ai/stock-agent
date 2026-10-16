# Reviewed cash-dividend accounting extension

This is an operational V12 accounting extension, not a new selection strategy.
Frozen signal rules, costs, order planning, `paper_accounting.py`, the trading
calendar and all V3 source files are unchanged. V12 and V3 remain separate.

## Policy

- Only explicitly reviewed ordinary USD cash dividends in
  `config/v12_reviewed_dividends.json` are accepted. A Yahoo observation alone
  does not approve an action. Reviews include issuer CIK, SEC URL, source SHA-256,
  review timestamp, amount, ex/record/pay dates and rationale.
- Ex-date entitlement uses shares held **before** that day's open. Buying on
  ex-date does not earn the dividend; selling on ex-date or later retains the
  fixed entitlement. Separate T+1/T+2 accounts retain separate quantities.
- An immutable `DIVIDEND_ENTITLEMENT` adds a receivable, not spendable cash.
  `portfolio_equity = cash + market_value + dividends_receivable`.
- A separate `DIVIDEND_PAYMENT` converts the fixed receivable to gross simulated
  USD cash at the first processed accounting close on/after the reviewed pay
  date. It does not increase equity a second time and does not depend on the
  shares held at payment. This policy is not proof of actual broker receipt and
  does not model tax withholding, FX or automatic reinvestment.
  Internal-paper amounts retain fractional-cent precision; UI amounts may round
  to cents. Actual broker rounding belongs to separate IBKR reconciliation.
- Existing order-budget rules remain unchanged: unpaid receivables are never
  available to buy stocks. The read-only dashboard identifies receivables
  separately from available cash. Old legacy `DIVIDEND` events are not rewritten;
  overlaps with a newly reviewed entitlement require manual reconciliation.
- Unknown or mismatched dividends, nonfinite observations, splits and other
  unsupported actions still fail closed. A later registry edit conflicting with
  an immutable entitlement is rejected. Review after an event does not pretend
  it was known before the event: append timestamps record the actual recovery.

## Atomicity and recovery

All new dividend events and all account valuations for a day use one append-only
transaction. Deterministic IDs prevent duplicates; different contents under the
same ID are rejected. Earlier event rows and hash links are preserved.

The scheduled runner may recover at most five missing completed sessions within
14 calendar days, strictly chronologically. It must stop if a missed day crosses
a month-end or contains an unprocessed scheduled execution. It never fabricates
historical signals or fills. Each completed recovery day is persisted before
continuing; no new Dashboard is published until the cycle completes.

An existing valuation on/after ex-date without its required entitlement cannot
be silently repaired or ignored. It requires a separately reviewed append-only
restatement; old valuation rows must not be edited or deleted. Production recovery
must re-read cloud authority immediately beforehand. Use the existing GitHub
production concurrency group; do not run a second local publisher concurrently.

## MU case reviewed 2026-10-15

Ordinary dividend: USD 0.15/share, ex/record date 2026-10-14, pay date 2026-10-29.
The issuer announcement verifies amount, record and pay dates. The Yahoo ex-date
observation is corroborated against the ordinary-distribution T+1 date convention;
this is not a general automatic inference rule for other dividends.

- [Issuer SEC announcement](https://www.sec.gov/Archives/edgar/data/723125/000072312526000018/a2026q4ex991-pressrelease.htm)
- [FINRA T+1 notice](https://www.finra.org/sites/default/files/2024-02/Regulatory_Notice_24-04.pdf)

An isolated download-only rehearsal on the then-current signed 236-event cloud
ledger recovered 2026-10-14 and 2026-10-15 by appending 14 events in a temporary
copy. All original rows/hashes were unchanged and immediate retries added
nothing. MU receivables: V12_T1 0.7586059201215439 USD; V12_T2
0.7421538795350471 USD. No payment was created, no new signal/fill was created,
and no production cloud write was made. This rehearsal does not establish that
cloud authority is still at that same head later.

Download-only rehearsal:

```text
python -m scripts.rehearse_v12_dividend_recovery
```

The script restores authenticated state into a temporary directory, never the
repository's production ledger. It has no upload, execution or signal calls.
