# Candidate Strategy Pre-registration

These rules were fixed before running the candidate comparison.

- Universe: AAPL, MSFT, NVDA, AMZN, GOOGL, META, AVGO, JPM, V, WMT.
- Data window: the common trading sessions in the requested five-year adjusted-OHLC history.
- Capital and friction: $10,000; 0.10% commission and 0.05% adverse slippage per transaction.
- Timing: signals use information through the T close; all entries and signal exits execute at the T+1 open.
- Comparable allocation: no more than two concurrent stocks; a new position receives no more than 50% of portfolio equity. If more candidates exist, the strongest rule-specific breakout/deviation score wins. Unused capital remains cash.
- Bollinger Band Mean Reversion: enter when the close is below the 20-session mean minus two population standard deviations; exit when close reaches the 20-session mean or after 10 sessions.
- Donchian Breakout: enter when close exceeds the highest high of the prior 55 sessions; exit when close falls below the lowest low of the prior 20 sessions.
- Volatility Contraction Breakout: contraction means the 20-session average true range divided by close is at or below its trailing 126-session 20th percentile. Enter only when close also exceeds the prior 20-session high. Exit below EMA20 or after 40 sessions.
- Cross-Sectional Momentum: existing baseline; every 20 sessions rank trailing 20-session return, require stock close above MA200 and SPY close above MA200, hold the top 20% (two stocks) equally, execute next open.
- PEAD: not eligible for a numeric backtest unless each event has the historical release timestamp, reported EPS, point-in-time consensus EPS, source, and the time the record became available. Release timing must decide whether the first tradable price is the same day's after-hours/next open or the following session. No substitute event dates are allowed.

The final 30% of common sessions is reported as a chronological holdout. It is not a true untouched experiment because these generic strategy families are known in advance. The present-day fixed universe has survivorship and selection bias.
