# Large-Cap Short-Term Swing Strategy Research System

A research application for testing **3–20 trading-day swing hypotheses** on large-cap US equities. It is not a day-trading, crypto, penny-stock, long-term recommendation, brokerage, or live-execution system.

## Research flow

```text
SPY Market Regime
→ Large-Cap Stock
→ Three Different Swing Hypotheses
→ Historical / Out-of-Sample Validation
→ Risk and Strategy Comparison
→ AI Explanation
```

The quantitative engine owns signals, returns, alpha, risk statistics, and historical outperformance rates. AI may explain or contextualize those results, but it must not invent win probabilities.

## Fixed research universe

`AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, V, WMT`

This is a **fixed current large-cap universe for research purposes**. It is not point-in-time S&P membership and has survivorship bias. Cross-sectional Top 20% therefore means exactly **2 of 10 stocks**. The universe and threshold are not changed after viewing results.

## Fixed V1 swing rules

### A. Pullback Mean Reversion

- Entry at Day T close setup: `Close > MA200` and `RSI(14) < 30`.
- Entry execution: Day T+1 open.
- Exit signal: `RSI(14) > 50`, `Close >= MA20`, or 10 trading-day holding limit.
- Exit execution: Day T+1 open.
- MA200 is only a long-term trend filter, not the primary exit.

### B. Short-Term Momentum

- Entry at Day T close setup:
  - Stock `Close > MA200`.
  - SPY `Close > MA200`.
  - Stock 20D return > 0.
  - Stock 20D return > SPY 20D return.
- Entry execution: Day T+1 open.
- Exit signal: stock 20D relative strength no longer exceeds SPY, or 20 trading-day holding limit.
- Exit execution: Day T+1 open.

### C. Cross-Sectional Momentum

- Rank all 10 universe members by trailing 20D return using Day T close and earlier data only.
- Select Top 20%: 2 stocks.
- Ranking/rebalance schedule: every 20 common trading days.
- Execute the new target portfolio at Day T+1 open.
- SPY below MA200 moves the portfolio to cash.

Z-score, Bollinger Bands, ATR, alternative RSI thresholds, and alternative momentum windows are not part of the primary rules. They may remain isolated as future ablation experiments.

## Market regime

- SPY Close > SPY MA200 → `Favorable`.
- SPY Close <= SPY MA200 → `Unfavorable`.

BTC and crypto are absent from the active data, regime, strategy, UI, and validation paths. Archived legacy notes may still mention earlier BTC experiments.

## Shared execution and accounting

- Initial capital: **$10,000**.
- Commission: **0.10% of traded notional**.
- Slippage: **0.05% adverse adjustment**.
- Day T close signal → Day T+1 open execution.
- A last-day signal with no next open is not executed.
- Trades record `signal_date`, `execution_date`, `execution_price`, `shares`, `transaction_cost`, and `reason`.
- Open positions are marked to the final close and are not counted as completed round trips.

## Price-data treatment

Long-history research uses yfinance with `auto_adjust=True`, so OHLC prices are adjusted consistently for corporate actions using the vendor adjustment process. The engine does not maintain a separate cash-dividend ledger. Cached files use a versioned adjusted-price key so older unadjusted data is not silently reused.

## Validation

- Each new prediction stores the signal, reason, market regime, cross-sectional rank, and indicator values known at prediction time.
- Original snapshots are immutable; old records are never recalculated with future data.
- Matured outcomes are evaluated after 5, 10, and 20 trading days.
- `Alpha = Stock Return - SPY Return`.
- Historical outperformance rates include sample size and only count saved `BUY` snapshots with matured outcomes.
- The UI labels this as signal outperformance rather than realized strategy P&L, because fixed-horizon stock returns do not reproduce each strategy's exit rules.

## Daily signal snapshots

Run the point-in-time universe capture after the US market close:

```bash
python -m scripts.capture_daily_signals
```

The command writes one immutable, schema-versioned file per market date under
`signal_snapshots/`. Re-running the same date never overwrites the original
signals. The runtime directory is excluded from Git.

## App loading behavior

The main research areas use a single page selector rather than eagerly computed
tabs. The five-year universe backtest loads only when the user opens the strategy
research page; the investment summary and company history do not trigger it.
- Full-history results are supplemented with a chronological 70% research / 30% out-of-sample holdout. No random time-series split is used.
- Fixed rules are not optimized on either segment; the split is a stability check, not parameter selection.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
streamlit run app.py
```

Run all correctness tests:

```powershell
python -m unittest discover -s tests -v
```

## Known limitations

- Fixed present-day universe creates survivorship bias.
- No point-in-time index membership or delisted-security database.
- Vendor adjustments, missing data, and data-quality issues can affect results.
- Simplified next-open fills do not model partial fills, liquidity limits, taxes, or market impact.
- Cross-sectional accounting shares the same costs and timing assumptions but uses a dedicated multi-asset portfolio loop.
- The 70/30 holdout is not a full train-select-test walk-forward optimization.
- Historical backtests and observed signal frequencies do not guarantee future performance.

For education and research only; not financial advice.
