# Isolated V3 challenger accounting

This package is NOT Frozen V12 and is not imported by the current dashboard.
No broker orders, scheduler, account initialization, source approval, or cloud
publication occurs on import or status inspection.

## Entry points, from repository root

```text
python -m src.v3_accounting.runner status
python -m unittest discover -s tests/v3 -t .
```

Formal store: `shadow_forward/V3_ACCOUNTING/integration/` (ignored by Git).
Existing mirror runtime files have NOT been copied here. Old snapshots with
different pinned hashes must fail validation; do not edit freezes to bypass this.

`signal.py` is a V3-local packaging adaptation of the verified V2 algorithm.
Original V2 and official V12 files remain unchanged. Rules and all signal function
ASTs are regression-checked against the original, normalizing only the calendar
pathname. Default storage is V3-only. Provenance is recorded next to the module.

## Three-account contract

- V3, SPY and QQQ commit in one append-only SQLite batch.
- All start with $10,000 at the same first legal T+1 OPEN, with equal cost rates.
- SPY/QQQ are 100% buy-and-hold after entry costs; dividends remain cash.
  They are not exposure-matched 95% controls.
- Raw prices plus explicit actions only: do not double-count adjusted-price dividends.
- Dividend receivables are unspendable until the first session OPEN after the
  issuer payment date. This is paper policy, not evidence of broker cash receipt.
- A failure in any account rolls back the complete batch; exact retry is idempotent.

## Reviewed input

Each bundle requires `market.json`, a HMAC-signed `review.json`, and bound originals
under its own `sources/` directory. This is not the ChatGPT project reference folder.
The signed file map must bind raw prices, action announcements and fixed ETF
identity originals. HMAC proves possession of the review key, not factual accuracy.

`market.json` needs schema_version=1, date, OPEN/CLOSE kind, RAW price_basis,
data_asof, captured_at, price_source_sha256, marks, coverage, actions, benchmarks.
Coverage must join the previous recorded boundary exactly and include all holdings,
new targets, unpaid entitlements and both benchmark IDs.

`benchmarks` must have exactly SPY and QQQ, each with security_id,
instrument_type=ETF, currency=USD, identity_source_sha256. Identities and identity
source hashes remain fixed after entry; actual identity changes require review.
All relevant action sources must be checked, not inferred from an empty API list.
Only reviewed USD ordinary cash distributions and simple splits are supported.
Special distributions, withholding, due-bill, merger and corrections fail closed.

Intake is quarantine-only. ETF capture requires explicit `--instrument-type ETF`
and SPY/QQQ. It cannot generate approvals, formal signals or performance.

## Cloud writer

`cloud_writer.sql` was applied to the approved project; do not rerun this
non-idempotent migration. RLS and backend-only RPC permissions were checked.
Two independent connections, server expiry, fencing, precise retries, stale
revision/owner rejection and public-role denial were verified separately.
The authoritative archive head is still empty. The runtime is not scheduled.

`cloud_cycle.run_cloud_cycle` explicitly restores the authoritative signed head
to a new isolated directory, calculates via a supplied reviewed Runner operation,
checks ledger extension, verifies immutable upload and finally publishes by CAS.
A locally calculated candidate is not official until publish succeeds.
The coordinator refuses empty-head auto-bootstrap.

## Secrets (values never belong in Git)

- V3_REVIEW_HMAC_KEY: independently generated, 32+ characters.
- V3_BACKUP_HMAC_KEY: independent of the review key, 32+ characters.
- SUPABASE_URL / SUPABASE_SECRET_KEY: backend only.
- ALPHAVANTAGE_API_KEY: optional source capture, not approval.

Do not expose the service key in browser code. Merely importing this package
does not read `.env`; explicit capture tools accept a chosen env file.

## Packaging verification (2026-10-07)

- Full repository discovery: 210 tests passed.
- Separately executed original signal fixtures: 8 tests passed.
- Package compilation and Git whitespace checks passed.
- Status remains NOT_INITIALIZED with scheduler_enabled=false.
- The restricted Windows environment denied access to its default temporary
  directory. Tests were rerun with Python's temporary directory redirected to
  ignored `cache/v3-test-temp`; no production engine change was needed.

## Authorized local initialization (2026-10-08)

The user authorized freezing the current V3 and creating an isolated local journal.
Frozen at 2026-10-08T23:24:08.574018+00:00 (16:24 PDT).
The journal contains exactly one INITIALIZE record, $10,000 cash, zero positions,
zero receivables, no processed trading/action events and no valuation boundary.
SPY/QQQ benchmark entry remains deferred until the first legal OPEN; no benchmark
fill or performance was manufactured by initialization.

- freeze.json SHA-256: b471b2c9589fa02fe37c1b6948b38ce57b3384b78724626028d2a0757d2cda17
- integration_freeze.json SHA-256: d63ee9627718488ac26372ae7a00d3462d011fb8ccf00592fcb114628c4ef1a5
- Repeated initialization leaves the validated journal state and freeze hashes unchanged.
- Status: LOCAL_ONLY; scheduler, cloud connection and broker connection are false.
- Initialization-related regression checks: 15 tests passed before initialization.
- Full repository regression after initialization: 210 tests passed (56.174 seconds).
- Read-only journal inspection confirmed only INITIALIZE and both no_update/no_delete triggers.
- Status-isolation test now uses a unique non-production path, rather than assuming
  the real store must remain uninitialized forever. No strategy/accounting code changed.

Runtime files stay ignored by Git. This is not cloud publication or deployment.
The exact freeze timestamp is the first required corporate-action coverage boundary;
it must not be backdated or replaced to fit available historical inputs.

## Next operational gates

### Read-only Dashboard integration (2026-10-08)

The additive `cloud_reader.sql` migration was applied to the approved Supabase
project. `v3_read_head()` returns only the stream, revision and published hashes;
it is a STABLE SELECT with no writer lease or state changes. Permission checks
confirmed anon/authenticated EXECUTE=false and service_role EXECUTE=true.
Do not reapply the one-time CREATE FUNCTION migration to an existing endpoint.

`src/v3_dashboard.py` reads this head, downloads the immutable private archive,
verifies its receipt/signature/frozen dependencies/ledger in a disposable copy,
then rechecks the head to reject concurrent publications. It never acquires,
renews or publishes a lease and never initializes/processes a trading store.
Failures display a sanitized error; there is no V12, local-ledger or demo fallback.

The independent **V3 Accounting** navigation page shows cash, holdings, paid and
receivable dividends, snapshot creation time and verification time. Initialization
is explicitly not Forward performance. It does not connect a broker or enable
scheduling. Snapshot creation time is not labeled as publication time or price time.

Server-side Secrets required: SUPABASE_URL, SUPABASE_SECRET_KEY (or the existing
SUPABASE_SERVICE_ROLE_KEY alias), V3_BACKUP_HMAC_KEY and V3_REVIEW_HMAC_KEY.
Use the existing independent V3 keys; do not generate replacements or expose them
to browser code. The new keys still need to be configured on Streamlit Cloud before
deployment. No credentials are included in source or this document.

Live signed-cloud read and Streamlit page testing verified revision 1, one INITIALIZE
event, $10,000 cash, zero holdings and zero dividends, with unchanged local ledger.
Full repository regression: 215 tests passed (74.297 seconds). Local Streamlit
startup succeeded on localhost port 8516. Restricted-sandbox startup did not
complete; localhost startup with approved network access succeeded instead.
This local UI integration is not a commit, push or Community Cloud deployment.

### Deployment source-byte portability

The initialized V3 snapshot pins LF bytes for V3 Python modules and CRLF bytes
for the two existing shared accounting/calendar files. Scoped `.gitattributes`
preserves these exact working-tree bytes on Windows and Linux checkouts. It does
not change strategy logic, relax hash validation, rewrite the freeze or migrate
the ledger. The shared files retain their existing canonical Git blob contents.

### Local signed backup rehearsal (2026-10-08)

The real initialization-only journal was backed up with the existing dedicated
V3 backup key and restored into a new isolated rehearsal directory. No key values
were printed or saved. Archive SHA-256:
`02e481d54b335077b2de50f2f64dc21dd42809b32abc8b4b07dee2003dc6f3b1`.
The external local receipt records one event and journal head
`214438bdb88c2fcfb1584e9bd597dd463e3672f850d0589851ce8924a0f448af`.
The 3,033-byte archive, receipt and verification record are under ignored
`shadow_forward/V3_ACCOUNTING/local_backups/` and `local_receipts/`.

Restored state, both freeze hashes and journal validation matched. Four negative
checks rejected a wrong receipt hash, wrong signing key, tampered archive bytes,
and an existing destination. The original state and freezes remain unchanged.
This verifies local transport of the initial state only, not real trade evidence,
future dependency migrations, private cloud upload or the restore/update/publish
loop. At this rehearsal stage no authoritative cloud head was published and no
UI connection was added; the later authorized publication is recorded below.

### Authorized private cloud initialization (2026-10-08)

Published at 2026-10-08T23:41:39.997175+00:00 (16:41 PDT), following explicit
user authorization. The publisher verified the signed local snapshot, acquired
the fenced writer lease and confirmed the authoritative cloud head was empty
(revision 0). It uploaded the immutable content-addressed archive to private
`v3-accounting`, downloaded it and verified exact bytes and signed restored state,
then published the initial head using revision compare-and-swap.

- Cloud revision: 1; archive and journal hashes match the local rehearsal above.
- Journal: one INITIALIZE event; $10,000 cash; no positions or trades.
- Local source state remained unchanged.
- Durable publication intent and successful receipt are in ignored `local_receipts/`.
- Five publisher safety tests passed: ordered success, existing-head refusal,
  mismatched-readback refusal, invalid-snapshot refusal and no ambiguous retry.
- Scheduler, broker connection and App UI connection remain disabled.

This establishes recoverable initial cloud state only. It does not verify a real
scheduled trading cycle, approve market/action inputs or create Forward performance.
The local runner's LOCAL_ONLY status is not a live cloud connectivity indicator;
publication is evidenced by the dedicated successful cloud receipt.

There is no approved real SPY/QQQ input bundle or official V3 performance.
The earlier NVDA historical capture is still pending review and is NOT an eligible
first Forward input. Complete real identity/action coverage review, rehearse the
new signed restore/update/publish loop from the initialized cloud head, and obtain
a genuine PIT month-end signal plus T+1 OPEN before scheduling.
No deployment or scheduling is implied by packaging or successful synthetic tests.
