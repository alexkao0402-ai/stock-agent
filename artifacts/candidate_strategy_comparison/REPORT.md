# Large-cap candidate strategy comparison

Run date: 2026-10-26. Common adjusted-OHLC sample: 2021-10-27 through 2026-10-23 (1,253 sessions). Initial capital: $10,000. Costs: 0.10% commission plus 0.05% adverse slippage per transaction. Every close-based signal executes at the next open. The fixed rules are in `docs/CANDIDATE_STRATEGY_PREREGISTRATION.md`.

| Strategy | CAGR | Total return | Sharpe | Sortino | Max DD | Turnover | Completed trades/periods | Win rate | Exposure | Alpha vs SPY | Alpha vs equal weight |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Cross-Sectional Momentum | 21.61% | 165.40% | 0.952 | 1.226 | -20.17% | 86.73x | 52 | 57.69% | 71.27% | 87.27% | -51.70% |
| Bollinger Band Mean Reversion | 16.72% | 116.21% | 0.841 | 0.956 | -32.74% | 137.63x | 132 | 66.67% | 41.92% | 38.08% | -100.90% |
| Volatility Contraction Breakout | 14.40% | 95.64% | 0.864 | 1.104 | -15.49% | 67.85x | 64 | 37.50% | 47.52% | 17.51% | -121.46% |
| Donchian Breakout | 12.00% | 75.96% | 0.674 | 0.863 | -25.42% | 34.91x | 34 | 50.00% | 70.93% | -2.17% | -141.14% |

For the Cross-Sectional strategy, “completed periods” and win rate refer to completed rebalance-to-rebalance portfolio periods because partial rebalancing transactions are not independent round trips. For the other strategies they refer to closed stock round trips.

## Chronological final-30% holdout

| Strategy | Return | Sharpe | Alpha vs SPY | Alpha vs equal weight | Sessions |
|---|---:|---:|---:|---:|---:|
| Bollinger Band Mean Reversion | 45.79% | 1.458 | 5.49% | -10.99% | 376 |
| Donchian Breakout | 35.92% | 1.038 | -4.39% | -20.86% | 376 |
| Cross-Sectional Momentum | 30.39% | 0.894 | -9.91% | -26.38% | 376 |
| Volatility Contraction Breakout | 15.05% | 0.683 | -25.26% | -41.73% | 376 |

## Verdict

There is no reliable overall winner. Cross-Sectional Momentum has the best full-period CAGR, Sharpe, and Sortino. Bollinger Mean Reversion has the best chronological holdout return and holdout Sharpe, but it also has the deepest drawdown and highest turnover. Volatility Contraction has the smallest full-period drawdown but weak holdout results. Every strategy underperformed the equal-weight fixed-universe benchmark in both the full sample and holdout.

PEAD is not ranked. No point-in-time event dataset containing historical release timestamps, historical consensus EPS, reported EPS, source provenance, and data-availability timestamps was available. Substituting current or date-only earnings data would make the test look-ahead prone.

## Bias and evidence limits

- The fixed present-day ten-stock universe has survivorship and selection bias. Results cannot establish an investable large-cap universe edge.
- Yahoo adjusted OHLC is suitable for this price-rule comparison but is not point-in-time constituent data and cannot support PEAD.
- The final 30% is chronological, but these are well-known strategy families rather than hypotheses invented without knowledge of market history. It is weaker than live-forward evidence.
- Bull/bear and calendar-year returns are in `calendar_and_regime.csv`; trade-level evidence is in the four `trades_*.csv` files.
- The high turnover of Bollinger Mean Reversion makes its result particularly sensitive to market-impact assumptions beyond the fixed commission and slippage model.
