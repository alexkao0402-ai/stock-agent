# CSM + E3 fixed initial allocation experiment

Run date: 2026-10-26. Original snapshot: 2021-10-27 to 2026-10-23. No new forward observations.

Primary hypothesis: 50/50 separate starting cash budgets. Sensitivities: 25/75 and 75/25 CSM/E3. All sleeves retain their own cash and PnL; weights drift. These are not constant-weight rebalanced portfolios. Rules were fixed in docs/CSM_E3_SLEEVE_PREREGISTRATION.md before this study.

## Full

| Strategy | Return % | CAGR % | Sharpe | Sortino | Max Drawdown % | Exposure % | Excess vs SPY pp | Excess vs Equal Weight pp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CSM 100% | 165.401 | 21.612 | 0.952 | 1.471 | -20.166 | 71.326 | 87.268 | -51.704 |
| E3 100% | 125.295 | 17.683 | 1.426 | 2.414 | -15.518 | 29.396 | 47.162 | -91.810 |
| CSM 50% / E3 50% | 145.348 | 19.712 | 1.226 | 1.933 | -17.164 | 53.647 | 67.215 | -71.757 |
| CSM 25% / E3 75% | 135.321 | 18.715 | 1.448 | 2.350 | -16.021 | 42.591 | 57.189 | -81.784 |
| CSM 75% / E3 25% | 155.374 | 20.677 | 1.057 | 1.643 | -18.159 | 63.105 | 77.242 | -61.730 |
| SPY buy-and-hold | 78.132 | 12.270 | 0.763 | 1.109 | -24.496 | 100.000 | 0.000 | -138.972 |
| Equal-Weight Universe | 217.105 | 26.030 | 1.027 | 1.519 | -34.937 | 100.000 | 138.972 | 0.000 |

## Research

| Strategy | Return % | CAGR % | Sharpe | Sortino | Max Drawdown % | Exposure % | Excess vs SPY pp | Excess vs Equal Weight pp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CSM 100% | 103.537 | 22.560 | 0.976 | 1.521 | -20.124 | 61.644 | 76.576 | 1.274 |
| E3 100% | 69.029 | 16.212 | 1.400 | 2.325 | -15.518 | 26.787 | 42.068 | -33.234 |
| CSM 50% / E3 50% | 86.283 | 19.491 | 1.218 | 1.922 | -17.164 | 47.033 | 59.322 | -15.980 |
| CSM 25% / E3 75% | 77.656 | 17.880 | 1.435 | 2.299 | -16.021 | 37.840 | 50.695 | -24.607 |
| CSM 75% / E3 25% | 94.910 | 21.050 | 1.065 | 1.667 | -18.159 | 54.861 | 67.949 | -7.353 |
| SPY buy-and-hold | 26.961 | 7.072 | 0.458 | 0.659 | -24.496 | 100.000 | 0.000 | -75.302 |
| Equal-Weight Universe | 102.263 | 22.340 | 0.869 | 1.278 | -34.937 | 100.000 | 75.302 | 0.000 |

## Explored OOS

| Strategy | Return % | CAGR % | Sharpe | Sortino | Max Drawdown % | Exposure % | Excess vs SPY pp | Excess vs Equal Weight pp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CSM 100% | 30.395 | 19.427 | 0.894 | 1.353 | -20.166 | 93.883 | -9.911 | -26.384 |
| E3 100% | 33.288 | 21.193 | 1.493 | 2.610 | -6.718 | 35.473 | -7.017 | -23.491 |
| CSM 50% / E3 50% | 31.707 | 20.230 | 1.244 | 1.958 | -11.305 | 69.057 | -8.598 | -25.071 |
| CSM 25% / E3 75% | 32.459 | 20.689 | 1.481 | 2.464 | -8.080 | 53.660 | -7.846 | -24.319 |
| CSM 75% / E3 25% | 31.022 | 19.811 | 1.036 | 1.586 | -15.300 | 82.314 | -9.283 | -25.757 |
| SPY buy-and-hold | 40.305 | 25.425 | 1.907 | 2.927 | -8.885 | 100.000 | 0.000 | -16.473 |
| Equal-Weight Universe | 56.778 | 35.095 | 1.552 | 2.343 | -16.078 | 100.000 | 16.473 | 0.000 |

## Primary result

The 50/50 blend's full Sharpe is 1.226, versus CSM 0.952 and E3 1.426. Full drawdowns are -17.16%, -20.17% and -15.52% respectively.

Explored-OOS blend Sharpe is 1.244, versus CSM 0.894 and E3 1.493. Blend OOS return is 31.71%; excess versus SPY -8.60 points and versus equal-weight universe -25.07 points.

The primary blend improves neither Sharpe nor drawdown relative to standalone E3 in this sample, although it reduces drawdown relative to standalone CSM. Its exposure lies between the two sleeves, so a lower drawdown than CSM does not by itself separate diversification from reduced market exposure. Do not select a weight from the sensitivity rows or infer a reliable future winner from them.

## Correlation and capacity

| Period | Sessions | Daily Return Correlation |
| --- | --- | --- |
| Full | 1252.000 | 0.267 |
| Research | 876.000 | 0.244 |
| Explored OOS | 376.000 | 0.319 |

| Strategy | Initial CSM Weight % | Final CSM Weight % | Min CSM Weight % | Max CSM Weight % | Peak Unique Stocks | Peak Single Name % |
| --- | --- | --- | --- | --- | --- | --- |
| CSM 50% / E3 50% | 50.000 | 54.087 | 48.568 | 65.822 | 4.000 | 51.600 |
| CSM 25% / E3 75% | 25.000 | 28.196 | 23.942 | 39.097 | 4.000 | 52.070 |
| CSM 75% / E3 25% | 75.000 | 77.945 | 73.911 | 85.246 | 4.000 | 51.459 |

## Corrected accounting

Research return dates end 2025-04-25; explored OOS return dates begin 2025-04-28. Each return appears once, with the prior close providing the starting equity. Full return compounds exactly from these disjoint segments. Prior reports shared one boundary return; use this study's corrected segment metrics for CSM and E3.

Sortino now uses RMS downside over all return days, with a zero target. Previous reports used standard deviation restricted to negative days; those Sortino values are not comparable. Sharpe uses a zero risk-free rate and population standard deviation. Alpha columns are cumulative return differences in percentage points, not regression alpha.

Win rate is the percentage of realized SELL fills with positive FIFO PnL, including prorated entry and exit commission. It is not a comparable independent-trade sample count because CSM can rebalance partially. Fill count includes buys and sells. Turnover is two-way traded notional divided by average NAV. Exposure is invested dollars / NAV, not the fraction of days with any position.

## Evidence boundary and next milestone

All these dates have already been explored. The fixed universe retains survivorship and selection bias. Adjusted OHLC is not a point-in-time event dataset. Headline comparisons include the original indicator warmup in cash. Blends may hold four names and overlapping stocks can increase concentration; standalone strategies allow two. Therefore this is not a two-position-constrained diversification test.

E3 remains a forward-study candidate. Freeze the strategy, source and availability timestamps, execution convention, initial cash and evaluation schedule before collecting genuinely unseen data. This study neither creates a live or paper automation nor places orders. Zero observations here count as new forward evidence.

## Reproducibility

Run: python -m unittest tests.test_sleeve_portfolio tests.test_candidate_strategies tests.test_backtest_engine tests.test_cross_sectional_analytics tests.test_strategy_lab

Then: python scripts/research_csm_e3_sleeves.py (offline original cache required). Input hashes and reconciliation checks are in audit.json. Daily curves, actual fills, aggregated name positions, calendar-year and prior-close-regime tables are included in this directory.