# Market Intelligence research sources

This display-only layer is not a signal, pricing, accounting, or readiness input
for Frozen V12 or V3. It does not modify those engines or enable scheduling.

Daily prices and optional valuation/earnings-date data still use the pinned
Yahoo Finance dependency. Alpha Vantage remains an optional last-resort source
for fundamentals/news, with zero immediate retries. Missing numeric values are
not converted to zero, and raw provider exceptions/API keys are not displayed.
Free services are best-effort and may rate-limit cloud hosts. Respect provider
terms; this view is not a licensed redistribution feed. The price date, not the
page fetch time, identifies its freshness.

## Daily-price fallback and summary cards

Market Intelligence uses a separate daily-price reader, not the strategy's
adjusted history cache. Yahoo `history(auto_adjust=False, raise_errors=True)`
preserves explicit failure status. If it fails, the existing Alpha Vantage key
can request `TIME_SERIES_DAILY` with compact output (up to 100 rows) and zero
immediate retries. Response symbols are checked. Access still depends on the
key's entitlements and quota; neither source is guaranteed available on Cloud.
Successful Yahoo daily data is cached one hour, Alpha daily data six hours to
conserve quota. A fresh alternate source is preferred over a stale success.

The view conservatively excludes today's daily bar until 16:15 New York time;
this is intended for US-market securities, not global exchange session handling.
Invalid/nonpositive/nonfinite closes and future dates are rejected. These are
provider Close series, not total returns or approved Forward inputs. Yahoo and
Alpha may use different historical split conventions, so series are never
spliced together. A stale backup remains labeled with its real date; a price more
than four calendar days old also triggers a warning (not an exchange-calendar
assertion).

When all valuation metrics are unavailable but SEC figures exist, the summary
cards show Revenue, Net income, Diluted EPS, Assets and Liabilities with their
reporting periods. They do not masquerade as market capitalization, P/E, margins,
or TTM EPS. The detailed SEC financial table remains available underneath.

## Configuration

Set `SEC_USER_AGENT` in Streamlit Community Cloud Secrets (append to existing
secrets, do not replace them) or the process environment:

```toml
SEC_USER_AGENT = "stock-agent/1.0 your-contact-email@example.com"
```

Replace the example email with your own contact address. Example addresses are
rejected. Local `.streamlit/secrets.toml` is Git-ignored. No SEC API key is needed.
This local setting is **not** automatically uploaded to Community Cloud.

## Financials and filings

Resolve the ticker through the SEC directory and verify the returned CIK and
submission ticker before showing financials or filings. Direct SEC filings are
preferred; Yahoo filings remain a fallback. Standard USD US-GAAP revenue, net
income, diluted EPS, assets, and liabilities are supported. Non-USD/IFRS/custom
concepts may remain unavailable in this version.

Each fact keeps its period start/end, filing date, form, and original SEC filing
link. At the latest period end, the shortest available duration is preferred;
if only YTD or annual data is available, its actual dates remain visible.
Dates after today and nonfinite values are excluded. Instant balances are not
treated as quarterly flows. These are reported figures, **not TTM estimates**.
Different rows may have different periods. No margins or valuations are invented.
This latest-disclosure view is not a historical point-in-time backtest dataset.

## News relevance

All news providers pass through the same conservative headline filter. A result
needs a safe HTTP(S) link, a valid date within the last seven days, and an explicit
company-name alias or bounded ticker match. Ambiguous words such as Apple require
financial/product context; common-word tickers need explicit ticker notation.
Publisher suffixes are excluded from matching. Duplicate headlines, unknown
dates, future dates, and uncertain matches are hidden. Each result shows the
matching basis, publisher, and time. Precision is prioritized over completeness.

Plain tickers are accepted only for a small explicit unambiguous allowlist;
other symbols need company-name matching or explicit ticker notation.
Headline matching does **not** verify article truth, full-text relevance, or
materiality. Broad market articles without an explicit match are intentionally
omitted. Google RSS links may be Google redirect links, not direct publisher URLs.

## Availability and cache

Successful research responses are cached separately under Git-ignored
`cache/market_research_v1`. News/Yahoo/Alpha responses use 15 minutes; SEC directory
uses 24 hours, filings 1 hour, financials 6 hours. A failed refresh may reuse a
success up to seven days old with a prominent stale warning and retrieval time.
News still must pass the seven-day publication-date filter. Provider failures use
a two-minute cooldown; no immediate retry loops. The page-level cache is two
minutes. Cache retrieval time is not publication time or the financial period.

SEC requests are bounded by a timeout and moderated to two/second per process.
The SEC's limit is per user across all machines: multiple deployments must still
coordinate aggregate traffic. Cached success is not proof an upstream source is
currently healthy. Read-only/corrupt cache failures must not crash the page.

Technical provider status is collapsed under Data coverage & providers. Missing
prices must not hide available financials, news, or filings.

References: [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
and [SEC fair access](https://www.sec.gov/about/developer-resources).

## Validation history

The previous 2026-10-08 baseline had 226 passing repository tests, with live
NVDA coverage from Yahoo and Google RSS. That older run is not evidence of
current provider availability. The earlier mobile/Community Cloud browser
verification remained pending. Local source/test changes do not deploy to Cloud.
