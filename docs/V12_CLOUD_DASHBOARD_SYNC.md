# V12 Cloud Dashboard Sync Contract

## Purpose

Streamlit Cloud is a read-only monitoring surface.  The append-only SQLite
ledger remains in a trusted persistent execution environment and is never
uploaded to Streamlit Cloud as the trading source of truth.

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

The exported JSON contains only fields used by the Dashboard.  Raw event
payloads, content hashes and the complete accounting ledger are excluded.

## Security rules

- `V12_DASHBOARD_SYNC_SECRET` signs and verifies every snapshot.
- A signature mismatch, payload hash mismatch, missing secret, unsupported
  schema or non-HTTPS remote URL fails closed.
- A ledger integrity error prevents snapshot export.
- Streamlit never writes a signal, order, fill, position or ledger event.
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

## Automation boundary

The first legal Forward lifecycle remains manual and supervised.  Only after
Signal → Order → Fill → Position → Portfolio reconciliation passes may a
scheduler run capture, execution, snapshot export and upload automatically.
Operational failure must notify and stop; it must never retry an unknown order
by guessing.  IBKR Paper is a later phase and IBKR Live remains prohibited.
