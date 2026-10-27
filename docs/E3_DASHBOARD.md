# E3 on the existing V12 website

E3 appears beside V12 on the existing Streamlit app's shared tracking pages. The redundant standalone **E3 Forward Paper** navigation page and its overview link have been retired. This removes duplicate navigation only; the isolated F1 + E3 study, daily collection and separate signed display publication continue unchanged.

The primary **Overview, Activity, Strategy Health and Accounting** pages use the same components for V12 on the left and E3 on the right. Matching sections stack vertically on small screens. Both accounts get performance metrics, their own equity charts, holdings/signal/execution status, selection explanations, P/L and position tables, latest fills, timelines, audit details, signal evidence, event filters, operational checks and frozen rules. Duplicate overview summary cards are removed. Overview opens with performance and equity charts; matching supporting sections remain in a collapsed **More strategy detail** expander. Startup E3 returns remain `Waiting`; unavailable verified data remains unavailable. Different inception dates are explicitly labeled and no winner or combined portfolio is inferred.

**Market Intelligence** has an equal stock selector for each account, leading into one shared company-research view. Opening the page does not request external quotes or AI analysis. The redundant **Research reference / V3 Accounting** navigation section is removed from this two-strategy website. V3 source, ledgers and operations remain untouched and are not renamed or replayed as E3. The E3 comparison-account balance table remains in Overview's supporting details; its freeze/start dates and session/fill counts are in Strategy Health. No display detail depends on the retired standalone pages.

## Detailed projection

The local display exporter adds a versioned `details` block to the signed E3 object, without changing the trading runner or freeze. It copies saved entry checklists, plans, timing and journal metadata; projects every E3 paper fill; and reconstructs display cost basis from recorded fills and split actions. Current marks come only from the checksum-verified input snapshot used by the latest saved close. Average cost includes buy commission, realized P/L includes both sides' commission, and slippage is reported separately without subtracting it twice. Shares, marked value and total P/L must reconcile with the frozen runner's account or publication fails closed.

The display includes all E3 fills and recorded valuation history, the latest 120 signal checks and latest 250 E3/control journal events. It is a published window, not a complete copy of the private journal. Existing V12 transport is unchanged and continues to publish its latest rebalance and event window; the UI labels that scope. No older trades are invented to make archive coverage look identical.

E3 uses its already-recorded SPY/equal-weight/CSM comparison accounts. QQQ, V7/V8 agreement, historical-reference Sharpe and T+2 simulation are explicitly not collected or not applicable. Drawdown includes the initial cash high; 12-month Sharpe waits for 253 recorded closing values (252 close-to-close returns). No startup cash chart is fabricated. E3's frozen runner accrues dividends as nonspendable receivables and does not record dividend-payment cash; the accounting page explains this.

## Data flow

1. The unchanged frozen E3 runner records its prospective plans, simulated fills and closes locally.
2. `python scripts/publish_e3_dashboard.py --upload` verifies the existing freeze, source snapshots and append-only journal. It exports only display fields.
3. The exporter signs a domain-separated `E3_FORWARD_PAPER_DISPLAY_V1` envelope and writes the separate private Supabase object `v12-dashboard/e3_forward_dashboard.json`.
4. Streamlit authenticates and displays that E3 object. It does not load the E3 SQLite database or import the local runner. It cannot create a decision, order, fill or ledger event.

The exporter does not write `v12_dashboard.json` or any durable V12 state object. The browser never receives server credentials. The E3 signing domain and schema prevent the existing V12 envelope from being replayed as E3 data.

## Configuration

Use the existing server-side `SUPABASE_URL`, `SUPABASE_SECRET_KEY` (or legacy service-role key), and `V12_DASHBOARD_SYNC_SECRET`. If both ends explicitly configure `E3_DASHBOARD_SYNC_SECRET`, it takes precedence. No new credential or access policy is required. The current deployment uses the existing private `v12-dashboard` bucket.

Run the exporter in the same local runtime as the frozen runner; it uses the installed research dependency directory so the frozen dependency check remains valid. The website runs independently in its own Streamlit environment.

## Scheduled publication

After a successful daily paper cycle, publish the new E3 display with `python scripts/publish_e3_dashboard.py --upload`. A waiting or already-processed cycle may republish the same verified state, but the page still checks whether the last collected market session is current. A fresh publication timestamp cannot hide a missing forward session.

A collection or integrity failure must be reported without fabricating substitute data or modifying the frozen source. A display-publication failure is separate from the already-saved paper journal; it is not grounds to rerun or reset trades.

## Presentation safeguards

- Startup cash is shown as capital, with **zero forward sessions and fills**. No historical curve or hypothetical return is substituted.
- First eligible signal and first possible next-open fill dates are shown, with the eligibility condition.
- The page shows frozen entry/exit rules, two-position limits, costs, universe, E3 holdings, pending actions, paper fills and separate comparison accounts.
- The curve uses recorded forward closes only. Short samples are not labeled proof of an edge.
- Missing, malformed or unauthenticated data fails closed with an E3-specific error, rather than borrowing V12 or local simulated data.
- The page warns when an expected completed market session is missing or the publication is old. Reload or reopen the page to retrieve an updated snapshot.

Source and display changes do not alter any file listed in the E3 freeze manifest. The V12 execution engine, ledger, cloud state and signed transport remain unchanged.
