# Executed validation — 2026-10-26

- `python -m unittest tests.test_sleeve_portfolio tests.test_candidate_strategies tests.test_backtest_engine tests.test_cross_sectional_analytics tests.test_strategy_lab`: 27 tests ran, all passed.
- `python scripts/research_csm_e3_sleeves.py`: completed successfully against the offline original price cache.
- Every fill was checked against the original next common session, adverse adjusted-open execution price, and 0.10% commission. Cash and aggregated holdings independently reproduce every daily NAV for all seven portfolios. No negative cash or unfunded sells were found.
- Allocated-dollar CSM/E3 runs match proportionally scaled standalone NAVs to within $0.00001 on every date. This validates the independent sleeve accounting, rather than assuming a weighted average of daily returns.
- Research contains 876 return dates and explored OOS 376. The sets are disjoint and their compounded returns reconcile to all 1,252 full-sample returns for every portfolio.
- A direct synthetic smoke check of the corrected original variant generator confirmed one research return plus two OOS returns with exact full-period compounding.
- Causality testing changes future OHLC in both stock and SPY data and verifies that earlier E3/CSM portfolio equity remains unchanged.
- No network data refresh was used. Zero new forward observations were collected. The full repository suite was not rerun; this status covers the named research tests and reconciliation checks only.
