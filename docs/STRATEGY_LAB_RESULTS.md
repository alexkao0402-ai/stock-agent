# Strategy Lab Results
Data through: **2026-08-26**  
Universe: AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, V, WMT.  
Regime: Bull when SPY close > trailing SPY MA200; Bear otherwise. Signals use close information and execute at the next open. Costs: 0.10% commission + 0.05% slippage.
## Recent chronological OOS summary
| Strategy | Market Regime | Stocks | Median_Alpha_vs_BH | Median_Alpha_vs_SPY | Median_Sharpe | Median_MDD | Total_Trades | Median_Sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pullback Mean Reversion | Bear | 10 | -4.92 | -4.23 | 0.0 | 0.0 | 1 | 12.0 |
| Pullback Mean Reversion | Bull | 10 | -24.8 | -27.87 | 0.0 | 0.0 | 4 | 305.0 |
| Short-Term Momentum | Bear | 10 | -6.18 | -4.23 | 0.0 | 0.0 | 0 | 12.0 |
| Short-Term Momentum | Bull | 10 | -20.05 | -25.1 | 0.22 | -16.81 | 149 | 305.0 |

## Best tested strategy by stock and regime (Recent OOS)
| Market Regime | Stock | Strategy | Alpha vs B&H % | Alpha vs SPY % | Trades | Sample Size |
| --- | --- | --- | --- | --- | --- | --- |
| Bear | AAPL | Pullback Mean Reversion | -4.4 | -4.23 | 0 | 12 |
| Bear | AMZN | Pullback Mean Reversion | -7.73 | -4.23 | 0 | 12 |
| Bear | AVGO | Short-Term Momentum | -13.16 | -4.23 | 0 | 12 |
| Bear | GOOGL | Pullback Mean Reversion | 3.43 | 4.62 | 1 | 12 |
| Bear | JPM | Pullback Mean Reversion | -8.02 | -4.23 | 0 | 12 |
| Bear | META | Short-Term Momentum | -3.16 | -4.23 | 0 | 12 |
| Bear | MSFT | Pullback Mean Reversion | 1.97 | -4.23 | 0 | 12 |
| Bear | NVDA | Pullback Mean Reversion | -5.43 | -4.23 | 0 | 12 |
| Bear | V | Pullback Mean Reversion | -2.43 | -4.23 | 0 | 12 |
| Bear | WMT | Short-Term Momentum | -6.92 | -4.23 | 0 | 12 |
| Bull | AAPL | Short-Term Momentum | -46.0 | -24.59 | 15 | 305 |
| Bull | AMZN | Short-Term Momentum | -18.39 | -26.14 | 15 | 305 |
| Bull | AVGO | Pullback Mean Reversion | -38.11 | -27.87 | 0 | 305 |
| Bull | GOOGL | Short-Term Momentum | -26.98 | 38.39 | 17 | 305 |
| Bull | JPM | Short-Term Momentum | -18.79 | -17.2 | 17 | 305 |
| Bull | META | Pullback Mean Reversion | 11.76 | -27.87 | 0 | 305 |
| Bull | MSFT | Short-Term Momentum | 3.07 | -11.81 | 8 | 305 |
| Bull | NVDA | Short-Term Momentum | -29.79 | -6.58 | 20 | 305 |
| Bull | V | Pullback Mean Reversion | -5.62 | -27.87 | 0 | 305 |
| Bull | WMT | Pullback Mean Reversion | 1.77 | -23.82 | 1 | 305 |

## Cross-Sectional Momentum (portfolio level)
| Time Period | Market Regime | Return % | Alpha vs B&H % | Alpha vs SPY % | Sharpe | Sortino | Max Drawdown % | Trades | Exposure % | Sample Size |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full History | Bull | 201.32 | 8.31 | 132.55 | 1.33 | 2.09 | -20.38 | 70 | 100.0 | 849 |
| Full History | Bear | 18.66 | -28.61 | -9.58 | 1.38 | 1.35 | -9.76 | 0 | 100.0 | 205 |
| Recent OOS | Bull | 49.28 | 17.13 | 21.41 | 1.5 | 2.42 | -20.38 | 26 | 100.0 | 305 |
| Recent OOS | Bear | 5.43 | -1.6 | 1.2 | 3.12 | 7.12 | -7.73 | 0 | 100.0 | 12 |

## Interpretation limits
- This is a fixed present-day universe, so survivorship bias remains.
- Recent OOS is a chronological holdout, not a separately designed live-forward test.
- Sample Size counts regime trading days; Trades counts completed round trips by entry signal regime.
- Rows with very few trades cannot support a strong claim even when daily Sample Size is large.
- Cross-Sectional Momentum is portfolio-level and is not falsely duplicated into stock-level rows.
