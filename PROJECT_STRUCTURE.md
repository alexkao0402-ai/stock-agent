# Project Structure

```text
stock-agent/
├── app.py
├── main.py
├── src/
│   ├── indicators.py
│   ├── backtest_engine.py
│   ├── performance.py
│   ├── regime_analysis.py
│   ├── stock_data.py
│   ├── ai_analysis.py
│   ├── prediction_tracker.py
│   ├── cache_utils.py
│   └── strategies/
│       ├── trend.py
│       ├── momentum.py
│       └── mean_reversion.py
├── tests/
│   └── test_research_system.py
├── docs/
│   └── RESEARCH_FINDINGS.md
└── legacy/
    ├── ablation_study.py
    ├── strategy.py
    └── strategy_v1.py
```

Active strategies produce close-based signals only. `backtest_engine.py` exclusively owns execution, costs, trade records, cash, shares, and equity curves. `performance.py` exclusively owns metric definitions. Archived V1 material is not imported by the Streamlit application.
