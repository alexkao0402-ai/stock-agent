# E3 on the existing V12 website

The existing Streamlit app has a separate **E3 Forward Paper** navigation page at `/e3-forward-paper`. It is a read-only view of the isolated F1 + E3 experiment; its results are not merged into V12's equity curve or ledger.

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
