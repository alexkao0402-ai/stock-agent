# Point-in-Time Large-Cap Data Contract

Baseline V2 must never reconstruct a historical universe from today's tickers.
It requires two separately sourced tables joined by a permanent company/security
identifier.

## Membership intervals

Required columns:

- `permanent_id`: stable identifier across ticker/name changes.
- `ticker`: ticker valid during this membership interval.
- `member_from`: first effective membership date.
- `member_to`: exclusive removal date; blank while still active.
- `index_name`: initial implementation uses `S&P 500`.

## Market-cap observations

Required columns:

- `permanent_id`
- `as_of_date`: date measured.
- `available_date`: first date the backtest may use the observation.
- `market_cap_usd`: positive point-in-time market capitalization.

The backtest ranks only observations with both `as_of_date <= signal_date` and
`available_date <= signal_date`. It fails closed when fewer than ten active
members have valid market-cap data.

## Baseline V2 universe rule

At each month-end signal date:

1. Filter to S&P 500 members active on that date.
2. Use only market caps available by that date.
3. Select the largest ten companies.
4. Apply the existing Cross-Sectional Momentum rules to those ten.
5. Execute any resulting trades at the next trading day's open.

No fallback to the present-day fixed universe is permitted.

## Approved-quality source requirements

The source must include historical membership changes, delisted securities,
ticker changes, corporate actions, and stable identifiers. CRSP/WRDS, licensed
S&P constituent history, or an equivalently auditable dataset can satisfy the
contract. A current-constituent web page or current ticker list cannot.
