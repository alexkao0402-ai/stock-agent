# AI Stock Research

A research-focused Python project combining market data, AI-assisted company analysis, prediction tracking, quantitative backtesting, market-regime analysis, and rolling robustness checks.

> For education and research only. This project does not execute trades or connect to brokerage accounts.

## Project layout

- `app.py` — Streamlit user interface
- `main.py` — command-line AI research flow
- `src/` — application and research modules
- `experiments/` — isolated research experiments
- `docs/` — research findings
- `legacy/` — superseded code kept for reference

See `PROJECT_STRUCTURE.md` for details.

## Setup

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Add your own API keys to `.env`, then run:

```powershell
streamlit run app.py
```

Or use the command-line entry point:

```powershell
python main.py
```

## Research integrity

Strategy V1 remains a baseline implementation. Signals are designed around next-session execution to reduce same-day execution bias. Existing research limitations, including OHLC path ambiguity and the distinction between rolling robustness checks and true train/test walk-forward optimization, are documented for future work.
