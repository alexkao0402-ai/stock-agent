# Market Intelligence sources

Market Intelligence is research context only. It is not a signal input for
Frozen V12 or the isolated V3 accounting engine.

The primary key-free source is Yahoo Finance via the already pinned yfinance
dependency: delayed prices, company fundamentals, earnings dates and SEC filings.
Yahoo news is normalized across nested and older flat response formats. If news
is empty or fails, Google News RSS search supplies up to ten recent search matches.
These are not verified material events, investment advice or sentiment scores.
Links preserve the original publisher/aggregator destination and publication date.

Alpha Vantage is an optional last-resort source for missing fundamentals/news,
not a prerequisite. Missing free data triggers at most one attempt per section;
paid-access denial and rate limits are not blindly retried. Raw provider errors
and API keys are never shown. No additional dependency or secret is required.

The page displays actual providers, fetch time, delayed price date and individual
coverage status (available, no data, paid access required, rate limited, invalid
key, connection failed or provider unavailable). Missing prices no longer hide
news/fundamentals/filings. Missing numeric fields are not converted to zero.
Fetch time does not imply that each underlying financial metric is current.
The page-level cache lasts 30 minutes; price disk cache may last 20 hours.

Free providers are best-effort, may rate-limit cloud hosts, and do not guarantee
complete coverage. Respect their terms; this is not a licensed redistribution feed.
Search matches can be unrelated and must be checked against the publisher.

Validation on 2026-10-08: NVDA returned 180 price rows, Yahoo fundamentals,
10 Google News matches, six filings and four earnings-date rows without using
Alpha Vantage premium endpoints. Tests cover partial/complete provider failure,
paid denial, RSS parsing, schema normalization, missing values, unsafe links,
invalid ticker rejection and UI rendering when prices are missing.

Full repository regression: 226 tests passed. Frozen V3 dependency inspection
still passed with the original one-event journal unchanged. Browser automation
timed out, so actual mobile/Community Cloud visual verification remains pending.
