# Bollinger Mean Reversion variant study

Run date: 2026-10-26. Common sample: 2021-10-27 through 2026-10-23. The first 70% of sessions is the research period; the final 30% begins 2025-04-28. All variants use the same ten stocks, $10,000 initial capital, maximum two equal-weight positions, 0.10% commission, 0.05% adverse slippage, and T-close signal/T+1-open execution.

## Stage A: entry filters

| Variant | Research Sharpe | Research return | OOS Sharpe | OOS return | Full max drawdown | Trades |
|---|---:|---:|---:|---:|---:|---:|
| F0: SPY + stock MA200 | 0.950 | 35.22% | 0.806 | 14.44% | -13.88% | 69 |
| F1: stock MA200 only | **1.202** | **52.16%** | 1.031 | 19.65% | -15.34% | 76 |
| F2: SPY MA200 only | 1.175 | 51.05% | 1.210 | 33.35% | -17.72% | 88 |
| F3: no filters | 0.622 | 48.30% | **1.458** | **45.79%** | -32.74% | 132 |

The pre-declared research selection rule chooses F1: highest research Sharpe, then Sortino, then shallower drawdown. F3's strong OOS return comes with more trades, 137.63x turnover, and more than twice F1's full-period drawdown. The SPY entry filter did not consistently improve results: F1 beat F0 in research, while F2 beat F1 in OOS.

## Stage B: maximum holding period under F1

| Maximum | Research Sharpe | OOS Sharpe | OOS return | Full max drawdown |
|---|---:|---:|---:|---:|
| 5 days | 0.976 | 0.637 | 10.07% | -11.98% |
| 10 days | 1.202 | 1.031 | 19.65% | -15.34% |
| 15 days | 1.283 | 1.053 | 19.30% | -13.42% |
| 20 days | **1.404** | **1.081** | **20.18%** | -13.99% |

Five days appears too short. Fifteen and twenty days improve research performance, but their OOS improvement over ten days is small.

## Stage C: exit mechanism under F1

| Exit | Full CAGR | Research Sharpe | OOS Sharpe | OOS return | OOS max drawdown |
|---|---:|---:|---:|---:|---:|
| MA20 or 10D | 12.77% | 1.202 | 1.031 | 19.65% | -7.26% |
| MA20 or 5D | 9.19% | 0.976 | 0.637 | 10.07% | -7.92% |
| MA20 or 20D | 14.58% | 1.404 | 1.081 | 20.18% | -7.08% |
| Time only 10D | 17.69% | 1.399 | **1.493** | **33.29%** | **-6.72%** |
| Time only 20D | **25.14%** | **2.019** | 0.797 | 18.65% | -9.24% |

E4 has the strongest full/research result but a large OOS deterioration, so it should not be declared the winner. E3 is the most stable tested exit: research/OOS Sharpes are 1.399/1.493, with 73 completed trades, 65.75% win rate, 2.68 profit factor, 2.05% median trade return, and 29.37% exposure. However, E3's OOS return still trails SPY by 7.02 percentage points and the equal-weight universe by 23.49 points.

Cross-Sectional Momentum returned 30.39% in OOS with a 0.894 Sharpe and -20.17% full-period maximum drawdown. E3 returned slightly more with materially lower OOS drawdown, but the difference is based on one short holdout and is not enough to establish superiority.

## Verdict

No robust winner is established. E3 (F1 entry filter, no MA20 exit, fixed 10-session exit) is the best candidate for further forward testing because it is comparatively stable across research and OOS—not because it has proven an edge. E4 shows a likely parameter/regime cliff, and F3 demonstrates that removing filters raises opportunity and risk together.

Because every variant's OOS result was inspected in this requested “test all” run, the holdout is now an explored multiple-comparison sample. It must not be reused as untouched confirmation. The next valid step is a later walk-forward window or frozen forward-paper test. The present-day universe also retains survivorship and selection bias.

Detailed outputs:

- `all_variants.csv`: all full, research, OOS, cost, turnover, trade, and benchmark metrics.
- `research_ranking.csv`: research-period ranking.
- `entry_regime.csv`: completed trade outcomes grouped by the SPY regime at entry.
- `portfolio_regime.csv`: actual daily portfolio performance grouped by the previously known SPY regime.
- `trades_*.csv`: transaction-level evidence for every unique experiment.
