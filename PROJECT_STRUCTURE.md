# Project Structure

```text
AI_Stock_Research_clean/
├── app.py
├── main.py
├── README.md
├── PROJECT_STRUCTURE.md
├── requirements.txt
├── .gitignore
├── .env.example
├── src/
│   ├── __init__.py
│   ├── stock_data.py
│   ├── ai_analysis.py
│   ├── cache_utils.py
│   ├── prediction_tracker.py
│   ├── strategy_v1.py
│   ├── regime_analysis.py
│   └── walk_forward.py
├── experiments/
│   └── ablation_study.py
├── docs/
│   └── RESEARCH_FINDINGS.md
└── legacy/
    └── strategy.py
```

## Directory roles

- `src/`: active application and Strategy V1 modules.
- `experiments/`: research-only experiments that are not production entry points.
- `docs/`: durable research notes and findings.
- `legacy/`: superseded implementations retained for comparison; do not use them in the formal research pipeline.
- `cache/` and `predictions/`: runtime output directories, intentionally excluded from Git.
