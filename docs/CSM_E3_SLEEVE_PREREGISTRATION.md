# Cross-Sectional Momentum + F1/E3 allocation experiment

Specification fixed on 2026-10-26, before running the combination study.

## Hypothesis and predeclared comparisons

The two different entry mechanisms may diversify daily returns and reduce portfolio drawdowns. The primary test is 50% Cross-Sectional Momentum (CSM) / 50% F1+E3. Sensitivities are 25% CSM / 75% E3 and 75% CSM / 25% E3. Pure CSM, pure E3, SPY buy-and-hold and fixed-universe equal-weight buy-and-hold are comparators. No allocation is selected from historical results.

## Capital and execution

- Initial total capital: $10,000. Fixed *initial* cash budgets in independent sleeves; all profits, losses and idle cash stay in their original sleeve. Weights drift as sleeve equity changes. There are no transfers, sleeve rebalancing or performance-based switches.
- Original universe: AAPL MSFT NVDA AMZN GOOGL META AVGO JPM V WMT. Use only the cached original five-year adjusted OHLC snapshot; stop at 2026-10-23. No new observations are silently added.
- Use the existing CSM and E3 engines at the actual allocated dollar capital. Commission: 0.10% per fill; adverse slippage: 0.05% per fill. Fractional shares; no leverage; cash interest zero. Mark open holdings at the final close without fictitious liquidation. Adjusted prices are synthetic historical units, not raw quoted fills.
- CSM: original 20-session ranking and rebalance schedule, stock > MA200 and SPY > MA200 at signal close, top two eligible names; next-session-open fills. The existing engine can invest the entire sleeve in one eligible stock.
- E3: close below BB(20,2), close > stock MA200, no SPY entry filter, no MA20 exit, time exit after ten holding-session closes at the next open. Maximum two positions in this sleeve, each new allocation up to half of its sleeve equity, subject to cash. Ties: ticker ascending.
- Each sleeve has its own limits. The combination may hold up to four distinct stocks versus two in each standalone strategy. Overlapping names are aggregated for concentration reporting, but fills are charged independently with no artificial cross-sleeve netting. No additional portfolio-level position cap is introduced.

## Evaluation and accounting

- Align every equity observation and fill to one common calendar. Sum cash and marked positions, not average Sharpe ratios or cumulative returns. Check NAV against a reconstruction from actual fills and compare allocated sleeve curves with scaled standalone curves.
- Preserve the original start (including 200-session warmup in cash). Therefore headline historical comparisons include a warmup disadvantage relative to buy-and-hold; this is disclosed, not removed after seeing results.
- Correct the split by assigning return dates strictly before 2025-04-28 to research and return dates on/after that date to chronological OOS. The previous close anchors each segment, so the boundary return is counted exactly once. Full return must compound from the two disjoint segments.
- Report CAGR, total return, Sharpe, Sortino, maximum drawdown, two-way turnover, actual fill count, realized sell-fill FIFO win rate, exposure, cumulative excess-return percentage points versus both benchmarks, yearly performance, prior-close SPY regime performance, sleeve correlation, weight drift and name concentration. Alpha here means cumulative excess return, not regression alpha.
- Risk-free rate and Sortino minimum acceptable return are zero. Sharpe uses population standard deviation; Sortino uses root-mean-square downside over **all** sessions. This corrects the old negative-days-only standard deviation convention; old Sortino values are not directly comparable.
- All variants and the original date range have already been examined. This is historical sensitivity evidence, not untouched OOS or forward evidence. No statistical winner or future diversification benefit is assumed from one short chronological segment.

## Forward milestone

E3's new-data assessment must freeze rules and record each actual signal availability time, next tradable open, portfolio cash/positions and data snapshot. Only observations genuinely unseen when the freeze is recorded count as forward data. The cached last bar on 2026-10-23 does not by itself prove that subsequent dates are untouched. This experiment does not start an automated paper runner or place orders.
