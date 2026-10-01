# V12 Cloud Dashboard Sync Contract

## Purpose

Streamlit Cloud is a read-only monitoring surface.  The append-only SQLite
ledger remains the source of truth and is never uploaded to Streamlit Cloud.
For the ephemeral GitHub runner, an authenticated copy of the complete ignored
Forward state is stored in private Supabase Storage and restored before every
run. Streamlit does not load or write that private state object.

## Data flow

```text
Frozen V12 / Forward Engine
        ↓
Append-only SQLite ledger
        ↓
Verified display projection
        ↓
HMAC-signed JSON snapshot
        ↓
Private Supabase Storage object
        ↓
Streamlit Cloud (read-only)
```

The trusted runner has a separate durable-state path:

```text
Private signed Forward-state bundle in Supabase
        ↓ restore + verify before any work
GitHub Actions runner / append-only SQLite ledger
        ↓ capture, execution, valuation
Verify ledger + reject divergence
        ↓ persist after every mutating phase
Private signed Forward-state bundle in Supabase
```

The exported JSON contains only fields used by the Dashboard.  Raw event
payloads, content hashes and the complete accounting ledger are excluded.

## Security rules

- `V12_DASHBOARD_SYNC_SECRET` signs and verifies every snapshot.
- A signature mismatch, payload hash mismatch, missing secret, unsupported
  schema or non-HTTPS remote URL fails closed.
- A ledger integrity error prevents snapshot export.
- Streamlit never writes a signal, order, fill, position or ledger event.
- The durable-state bundle is HMAC authenticated, private, path-allowlisted and
  contains only the ledger plus immutable Forward evidence directories.
- A cloud ledger that is newer than or divergent from the runner ledger cannot
  be overwritten.
- GitHub Actions uses a single concurrency group so two scheduled runs cannot
  operate simultaneously.
- The signing secret must exist only in the trusted runner and Streamlit
  Secrets.  It must never be committed.

## Commands and configuration

The trusted runner creates a derived local snapshot with:

```bash
python scripts/export_v12_dashboard_snapshot.py
```

For the selected private Supabase bucket, both the trusted runner and Streamlit
need server-side configuration.  The key must remain in `.env`, GitHub Actions
Secrets or Streamlit Secrets and must never be committed:

```toml
SUPABASE_URL = "https://your-project-ref.supabase.co"
SUPABASE_SECRET_KEY = "your-server-side-secret-key"
V12_DASHBOARD_SUPABASE_BUCKET = "v12-dashboard"
V12_DASHBOARD_SUPABASE_OBJECT = "v12_dashboard.json"
V12_FORWARD_STATE_SUPABASE_OBJECT = "forward_state/v12_forward_state.json"
V12_DASHBOARD_SYNC_SECRET = "same-long-random-secret-as-the-runner"
```

The trusted runner explicitly exports and uploads with:

```bash
python scripts/export_v12_dashboard_snapshot.py --upload-supabase
```

Without `--upload-supabase`, the command only creates the ignored local JSON
file.  Streamlit performs authenticated reads only; it never uploads or changes
the object.  `SUPABASE_SERVICE_ROLE_KEY` is accepted as a legacy fallback, but
`SUPABASE_SECRET_KEY` is the preferred configuration name.

## Durable-state bootstrap

After the automation code is committed, bootstrap the existing verified local
ledger exactly once:

```bash
python scripts/sync_v12_forward_state.py upload --bootstrap
```

Future runs restore the object first and refuse to create a new blank ledger.
The object may also be restored manually with:

```bash
python scripts/sync_v12_forward_state.py download
```

## Automation boundary

The first legal Signal → Order → Fill → Position → Portfolio lifecycle passed
under supervision. The scheduler is active and its first unattended post-close
valuation loop completed successfully for the 2026-09-03 US session. An
operational failure must notify and stop; it must never retry an unknown order
by guessing. The scheduler runs at 23:30 UTC on weekdays, safely after the
regular NYSE close in both EST and EDT. It performs:

1. authenticated Forward-state restore;
2. month-end capture only on the final NYSE session;
3. any due T+1/T+2 executions;
4. daily close valuations of V12, SPY and QQQ paper portfolios;
5. ledger verification and durable-state persistence;
6. signed read-only Dashboard publication.

Corporate actions still fail closed for explicit review. IBKR Paper is a later
phase and IBKR Live remains prohibited.

GitHub runs scheduled workflows only from the repository's default branch.
Without merging `main`, the production dashboard branch containing this
workflow is the default branch: `refactor/large-cap-strategies`.
