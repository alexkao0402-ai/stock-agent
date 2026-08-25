# AI Stock Research

A modular research system focused on large-cap equities. It preserves the existing AI analysis, news, fundamentals, and prediction tracking while comparing three distinct trading ideas through one execution engine.

## Research focus

Fixed current large-cap universe: **AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, V, WMT**.

This fixed present-day universe is for research convenience. It is not point-in-time historical index membership and therefore has **survivorship bias**. The UI still supports manually entered tickers.

## Strategies

1. **Trend Following** — Close > MA200 and MA50 > MA200; exit when Close < MA200.
2. **Momentum + Relative Strength** — positive six-month momentum, above MA200, outperforming SPY, while SPY is above its MA200; exit below MA200 or when relative strength is lost.
3. **Mean Reversion** — above MA200 with RSI14 < 30; exit at RSI14 > 50, Close > MA20, or 20 holding days.

Benchmark: **SPY**. Buy & Hold is included as a passive comparison.

## Execution and costs

- Signal generated using Day T close and earlier data only.
- Trade executed at Day T+1 open.
- Commission: **0.1%** per transaction.
- Slippage: **0.05%** adverse adjustment per transaction.
- Open positions at the end are marked to the final close but are not recorded as completed sell trades.
- No intraday High/Low assumptions are used by the active strategies.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

Run validation:

```powershell
python -m unittest discover -s tests -v
```

## Known limitations

- Fixed current large-cap universe and survivorship bias.
- yfinance adjustments, missing data, and vendor-quality limitations.
- Results depend on simplified open-price liquidity and slippage assumptions.
- Taxes, borrow constraints, partial fills, market impact, and corporate-action edge cases are not modeled.
- Historical backtests do not guarantee future performance.
- The archived V1 research contains older BTC and OHLC-based experiments and is not part of the active application path.

For education and research only; not financial advice.
