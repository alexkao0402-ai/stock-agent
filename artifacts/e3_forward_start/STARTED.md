# F1 + E3 paper study — startup receipt

Actual freeze: **2026-10-26 23:26:06 America/Los_Angeles**, equivalent to **2026-10-27T06:26:06.108647+00:00**. This receipt records initialization, not an executed forward trade or performance result.

| Item | Verified startup state |
|---|---|
| Experiment version | F1-E3-PAPER-V1 |
| Primary | Mean Reversion F1 + E3 |
| Paper cash | $10,000.00 |
| Positions | None |
| Primary fills | 0 |
| Counted forward sessions | 0 |
| State | ARMED_WAITING_FIRST_FORWARD_CLOSE |
| First eligible signal session | 2026-10-27 close |
| First possible modeled fill | 2026-10-28 open, conditional on a signal |
| Independent comparators | CSM, SPY and equal-weight universe; $10,000 each |
| Ledger integrity | PASS |
| Runtime events at startup | INITIALIZE and BASELINE_CAPTURED only |
| Warmup session | Through 2026-10-26, excluded from forward evidence |
| Market-data connection | Successfully fetched and validated all ten stocks and SPY |
| First real cycle | WAIT_COMPLETED_DAILY_BAR; no forward data or fills added |
| Recurring task | F1 + E3 forward-paper daily |
| Automation ID | f1-e3-forward-paper-daily |
| Automation status | ACTIVE, verified by app view and saved configuration |
| Schedule | Weekdays at 13:30 America/Los_Angeles; exchange holidays checked by runner |

The first primary fill may occur later than October 28 if there is no eligible E3 entry. Simulated next-open fills are recorded after that execution session closes, using decisions already saved before its open. This does not claim actual exchange execution.

## Frozen evidence

- Source implementation commit: `190cb115b70c92432e864b00f3bd0ee15a95a8d4`.
- Freeze manifest SHA256: `4d14c413d3a351c44a8e9ea70b80e2c133d1f7e38f6e2b13ffe3f02ec9e4fdd2`.
- Captured warmup snapshot SHA256: `b801072e8ee62da7202366c31870b8a127d1da4ccd25981718425a93440f2ec1`.
- Frozen runtime: Python 3.11.5, pandas 3.1.0, NumPy 2.4.6, yfinance 1.7.0.
- Implementation hashes normalize Windows line endings and are checked on each invocation. Runtime dependency versions and the rule manifest are checked too.
- The actual journal and source snapshots are retained in `paper_ledger/e3_forward/`, excluded from Git. Preserve that directory; this sanitized receipt does not replace or back up the runtime database.

## Executed verification

`python -m unittest tests.test_e3_forward tests.test_candidate_strategies tests.test_sleeve_portfolio tests.test_backtest_engine tests.test_trading_calendar tests.test_paper_ledger tests.test_cross_sectional_analytics tests.test_strategy_lab`

48 tests ran and passed in the production dependency environment. Checks cover prospective T+1 fills, ten-session exits, no forward trades at initialization, idempotent retries, no past/future bar substitution, missing-session rejection, no warmup performance, split/dividend bookkeeping, changed snapshot detection, changed freeze detection and append-only database protection.

Actual commands `python scripts/run_e3_forward.py init`, `baseline`, and `cycle` all completed successfully. The baseline network check emitted upstream package deprecation warnings but returned validated data and no exception. No frozen code was changed after the actual freeze.

## Operation

See [the operating protocol](../../docs/E3_FORWARD_PAPER.md). Notifications are limited to the first new forward observation, primary scheduled actions or fills, failures and required review. Ordinary no-action sessions remain quiet.

This is a local scheduled task. The computer must be on, the desktop app running, and the checkout available. A missed required session stops the experiment for review without inventing signals or fills. Frozen V12, IBKR, real orders and main-branch deployment are outside this paper runner.
