# Backtest Engine V2 — Correctness Refactor

## What changed

- Strategy V1 factor rules are unchanged.
- Signal generated on day T executes only at day T+1 open.
- Trades now store both `signal_date` and `execution_date`.
- V1, TP25, and Trailing20 use one unified accounting engine.
- TP and trailing versions now produce daily equity curves.
- Trailing stop uses only the highest price known before today's intraday path.
- Today's new high cannot retroactively raise today's stop.
- Buy & Hold now includes the same transaction-cost and slippage assumptions.
- Metrics were moved into `src/metrics.py`.
- The unified engine lives in `src/backtest_engine.py`.

## Important research consequence

Previous TP25 and Trailing20 results should be rerun. The old trailing implementation could use the same day's high to raise a stop and then use the same day's low to trigger that newly raised stop. Daily OHLC data does not establish that ordering.

Strategy V1 factor definitions were not changed, but Buy & Hold comparisons may move slightly because the benchmark now includes trading friction.

## Tests

Run:

```bash
python -m unittest discover -s tests -v
```
