# Project Structure

```text
stock-agent/
├── app.py                          # Read-only Streamlit entry point
├── src/
│   ├── dashboard_ui.py             # Shared Dashboard presentation components
│   ├── dashboard_read_model.py     # Ledger-to-display projection
│   ├── dashboard_cloud_snapshot.py # Signed cloud display transport
│   ├── v12_live_signal.py          # Frozen V12 signal calculation
│   ├── forward_execution.py        # T+1/T+2 paper execution
│   ├── forward_valuation.py        # Daily portfolio valuation
│   ├── forward_evidence.py         # Immutable evidence preparation
│   ├── forward_state_cloud.py      # Authenticated durable state
│   ├── paper_ledger.py             # Append-only event ledger
│   ├── paper_accounting.py         # Cash, positions, costs and P/L
│   ├── live_large_cap_data.py      # Point-in-time live universe inputs
│   ├── stock_data.py               # Market Intelligence providers
│   └── ai_analysis.py              # Optional compact AI summaries
├── scripts/
│   ├── run_v12_forward_automation.py
│   ├── capture_v12_live_inputs.py
│   ├── process_v12_paper_open.py
│   └── export_v12_dashboard_snapshot.py
├── tests/                           # Unit and regression tests
├── docs/                            # Operating contract, readiness and roadmap
├── legacy/                          # Archived strategies; not used by V12
├── pages/                           # Historical research views; not in active navigation
└── .github/workflows/               # Tests and scheduled Forward cycle
```

## Production data flow

```text
Frozen V12
    ↓
Point-in-time signal and immutable evidence
    ↓
T+1 official / T+2 challenger paper accounts
    ↓
Append-only ledger and accounting reconciliation
    ↓
Authenticated private Supabase state
    ↓
Signed display-only projection
    ↓
Read-only Streamlit Dashboard
```

The Dashboard may format or explain saved records, but it cannot create signals,
orders, fills, positions, valuations or ledger events. Files under `legacy/` and
`pages/` are research references and are not part of the active V12 navigation.
