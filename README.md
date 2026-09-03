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

## Frozen V12 free live inputs

The forward paper test does not require a paid market-data key. After the US
regular session closes, capture the current company-level top-ten universe and
the raw/adjusted price history with:

```bash
python -m scripts.capture_v12_live_inputs
```

The capture combines Yahoo Finance market-cap and price data with Nasdaq's
current non-ETF symbol directories and SEC CIK/incorporation records. If SEC
blocks a shared/cloud IP, an explicitly recorded Yahoo company-profile fallback
provides the company ID and domicile instead. Multiple share classes such as
GOOG/GOOGL are consolidated by company ID. Non-US incorporated
issuers are excluded so the live definition stays aligned with the frozen CRSP
US-common-stock universe.

Each date is written once under `live_forward_inputs/YYYY-MM-DD/` with separate
universe and price CSV files plus a SHA-256 manifest. An existing date is never
overwritten. If source coverage is incomplete, the command fails closed instead
of falling back to the old fixed universe. The command also refuses to create an
official record before the final business day of the month. Its frozen V12
decision is written separately to `live_forward_signals/YYYY-MM-DD/v12_signal.json`.
V12 still executes at T+1 open, while T+2 remains the forward challenger; the
signal file remains in an awaiting-execution state until those future opens exist.
The same command also creates an immutable evidence package and pending
V12/SPY/QQQ paper-account events. It refuses official evidence if any critical
forward file is uncommitted. After an execution session closes, record exact raw
open fills with:

```bash
python -m scripts.process_v12_paper_open --execution-date YYYY-MM-DD
```

See `docs/V12_FORWARD_OPERATING_CONTRACT.md` for accounting, calendar,
corporate-action and retry definitions.

The supervised first T+1/T+2 lifecycle is complete. The fail-closed workflow in
`.github/workflows/v12-forward-paper.yml` can restore the private durable state,
run month-end capture, process due T+1/T+2 accounts, append daily close
valuations, verify the ledger and publish the signed Dashboard. Activation and
the one-time state bootstrap are documented in
`docs/V12_CLOUD_DASHBOARD_SYNC.md`. Frozen V12 is unchanged.

The future paper-trading architecture and gated IBKR Paper phases are documented
in `docs/V12_ROADMAP.md`. IBKR is not active, and the roadmap does not authorize
live trading or change the first legal Frozen V12 forward signal.

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

## Streamlit Community Cloud

- Repository: `alexkao0402-ai/stock-agent`
- Branch: `refactor/large-cap-strategies`
- Main file: `app.py`
- Recommended Python version: `3.11`

Add these values in the app's **Settings → Secrets** page. Never commit the
real values to Git:

```toml
ALPHAVANTAGE_API_KEY = "your_alpha_vantage_key"
GEMINI_API_KEY = "your_gemini_key"
ANTHROPIC_API_KEY = "your_anthropic_key"
```

Both Streamlit `st.secrets` and local environment variables are supported.
Without Alpha Vantage, the app falls back to yfinance prices and clearly marks
news/fundamentals as unavailable. Compact dashboard summaries prefer Google's
current Gemini Flash-Lite alias and fall back to Anthropic only when
`GEMINI_API_KEY` is absent.
Without either AI key, price and quantitative research still load while the AI
summary is disabled. `OPENAI_API_KEY` is not used by this application.

The local `cache/`, `predictions/`, and `signal_snapshots/` directories are
ephemeral on Community Cloud. Use an external database before relying on
historical prediction records as durable multi-user storage.

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
