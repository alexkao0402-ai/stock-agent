# V3 source review status

Checked: 2026-10-08 (America/Los_Angeles).
Status: NOT APPROVED. This document is an audit note, not a signed input bundle.

## Local evidence

The mirror's V3 quarantine contains one NVDA historical CLOSE capture for
2026-10-06, captured on 2026-10-07 UTC. Its draft remains PENDING_REVIEW,
approved=false and forward_eligible=false. At the initial audit no real SPY or
QQQ bundle was found. Subsequent capture results are recorded below.
The repository packaging did not copy mirror runtime data.

The intake tool's default issuer allowlist currently contains only NVIDIA and
SEC hosts. It will reject State Street and Invesco issuer URLs by default.
Do not remove host validation or silently approve redirected third-party sites.

## Official source discovery (not archived evidence)

- SPY identity: https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy
  The page identifies USD, SPY, NYSE Arca, CUSIP 78462F103 and ISIN US78462F1030.
- SPY distributions: https://www.ssga.com/us/en/individual/resources/documents/etf-dividend-distributions
  Official page links a distribution schedule PDF and historical distribution XLSX.
  Its unpopulated HTML table is NOT evidence of no distributions.
- QQQ issuer: https://www.invesco.com/qqq-etf/en/home.html
- QQQ details: https://www.invesco.com/qqq-etf/en/about.html
  These confirm an ETF tracking Nasdaq-100 but do not constitute a complete
  identity/distribution audit. Some dynamic fields did not load. The direct
  product-detail request also failed in this inspection.

No original issuer bytes or signed review were generated from these web-tool
results. A URL or search excerpt cannot substitute for a hash-bound original.

## Subsequent original capture (2026-10-08)

Using the existing intake function with explicit per-call issuer hosts (without
changing its default allowlist), original bytes were saved in the repository's
ignored `shadow_forward/V3_ACCOUNTING/quarantine/` directory.

- SPY capture `c71b3a396397e8f9d6c075e0332aed5c5e05ad6aa00b13ef1114bc925a69dfc0`:
  Yahoo chart JSON, State Street product HTML, historical distribution XLSX,
  and distribution schedule PDF. All four SHA-256 hashes match their manifest.
  XLSX ZIP signature and PDF signature checked; spreadsheet rows are not yet
  reviewed. A file-format signature alone does not prove valid economic data.
- QQQ capture `52ec24d70a7e0b5008acd857a2c4dfd4d53459a46b16cb93b9741ef17b82b5d0`:
  Yahoo chart JSON, Invesco full product HTML, and Invesco about-page HTML.
  All three SHA-256 hashes match their manifest. The product HTML includes
  CUSIP 46090E103 and ISIN US46090E1038; the capture's provisional ticker-based
  ID is not approved or promoted to a fixed account identity.

Both price observations refer to 2026-10-07 CLOSE and were collected later;
they remain historical_retrieval=true, approved=false, identity_verified=false,
forward_eligible=false and scheduler_enabled=false. No Alpha Vantage key was
used; its absence is recorded rather than concealed. No signed review or market
bundle was created. QQQ complete distribution/action evidence is still missing.

Initial sandbox network failures generated two zero-source drafts. These remain
as failed-attempt evidence; they must not be confused with successful captures.

## Distribution inspection follow-up (2026-10-08)

Read-only inspection of State Street's saved workbook (`dividend` sheet):
136 SPY rows, ex-dates 1993-03-19 through 2026-09-18.
Basic CUSIP, positive amount, date ordering and duplicate-key checks found no
issues. These checks do not establish full corporate-action coverage or resolve
blank capital-gain fields.

2026 source rows:

| Fund | Ex-date | Issuer payment date | USD/share | Source |
| --- | --- | --- | --- | --- |
| SPY | 2026-03-20 | 2026-04-30 | 1.796999 | Workbook row 9131 |
| SPY | 2026-06-18 | 2026-07-31 | 1.903516 | Workbook row 9130 |
| SPY | 2026-09-18 | 2026-10-30 | 1.888834 | Workbook row 9129 |
| QQQ | 2026-03-23 | 2026-03-27 | 0.73282 | Issuer JSON |
| QQQ | 2026-06-22 | 2026-07-10 | 0.81349 | Issuer JSON |
| QQQ | 2026-09-21 | 2026-10-08 | 0.75143 | Issuer JSON |

QQQ distribution API was discovered in the saved US issuer HTML, including its
locale=en_US, CUSIP=46090E103, idType=cusip and productType=ETF parameters.
Source: https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/distribution?idType=cusip&productType=ETF
Original saved at `quarantine/qqq-distributions-8cac48440d684d73a51016d1b98323b2ffd85a378bd82f987c43c807f0ae1aa2/sources/invesco_distributions.json`.
SHA-256: `8cac48440d684d73a51016d1b98323b2ffd85a378bd82f987c43c807f0ae1aa2`.
89 returned rows; basic date ordering, positive finite amounts and duplicate
ex-date checks found no issues. CurrencyCode=USD and CUSIP match the product HTML.
The 2026 ordinary-income fields equal the total per-share distributions. Null
component fields and older rows with other income classification still require
review; absence of splits or other actions is not proven by this dividend API.
Hong Kong listing announcements were not substituted for US ex-dates.

Existing V3 payment policy check (not a credited event):
- QQQ 2026-10-08 issuer payment -> 2026-10-09 13:30 UTC session OPEN.
- SPY 2026-10-30 issuer payment -> 2026-11-02 14:30 UTC session OPEN.

Only an entitled holding from before the applicable ex-date can earn the dividend.
All captures remain unapproved and are not a signed market bundle. No journal,
account, cloud head, scheduler or official V12 state was changed.

## Remaining approval gates

1. Save original issuer identity documents with capture timestamps and SHA-256.
2. Review each fixed security ID, currency, instrument type and identity source.
3. Obtain complete distribution/action records for the exact required interval.
4. Validate amount, ex-date, issuer payment date and distribution classification.
5. Check splits and other actions; empty provider event lists do not prove coverage.
6. Confirm raw price basis; do not add dividends to dividend-adjusted prices.
7. Bind exact coverage boundaries, marks and every original in market/review files.
8. Sign only after factual review, then validate without publishing or trading.

Historical captures may support rehearsal but must not be relabeled as genuine
point-in-time Forward captures. Scheduled operation, initialization and cloud head
publication remain separate gates. Frozen V12 and existing ledgers are untouched.
