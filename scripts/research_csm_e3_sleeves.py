"""Offline, preregistered fixed-initial-budget CSM/E3 sleeve experiment."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.backtest_engine import BacktestConfig, run_buy_and_hold
from src.candidate_strategies import bollinger_mean_reversion_variant
from src.cross_sectional import cross_sectional_momentum_backtest, equal_weight_buy_and_hold
from src.portfolio_backtest import run_signal_portfolio
from src.sleeve_portfolio import combine_sleeves, disjoint_periods, normalized_curve, period_metrics, replay_fills

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "WMT"]
CONFIG = BacktestConfig(10000, 0.001, 0.0005)
BOUNDARY = "2025-04-28"
ALLOCATIONS = (0.5, 0.25, 0.75)
OUT = ROOT / "artifacts" / "csm_e3_sleeves"


def load_snapshot():
    audit = json.loads((ROOT / "artifacts" / "candidate_strategy_comparison" / "data_audit.json").read_text(encoding="utf-8"))
    frames, source_rows = {}, []
    for symbol in [*UNIVERSE, "SPY"]:
        path = ROOT / "cache" / f"{symbol}_long_history_5y_adjusted_v1.json"
        blob = json.loads(path.read_text(encoding="utf-8"))
        frame = pd.DataFrame(blob["data"])
        frame["date"] = pd.to_datetime(frame["date"])
        if frame["date"].duplicated().any():
            raise ValueError(f"Duplicate dates in {symbol}")
        frame = frame[frame["date"].between(audit["common_start"], audit["common_end"])].sort_values("date").reset_index(drop=True)
        numbers = frame[["open", "high", "low", "close"]].to_numpy(float)
        if frame.empty or not np.isfinite(numbers).all() or (numbers <= 0).any():
            raise ValueError(f"Invalid price data in {symbol}")
        if (frame["low"] > frame[["open", "close"]].min(axis=1) + 1e-6).any() or (frame["high"] < frame[["open", "close"]].max(axis=1) - 1e-6).any():
            raise ValueError(f"Inconsistent OHLC in {symbol}")
        frames[symbol] = frame
        source_rows.append({"symbol": symbol, "cached_at": blob["cached_at"], "sessions": len(frame),
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    calendar = frames["SPY"]["date"]
    if len(calendar) != audit["common_sessions"]:
        raise ValueError("Original common session count has changed")
    if any(not frame["date"].equals(calendar) for frame in frames.values()):
        raise ValueError("Missing stock observations; silent intersection is prohibited")
    return {s: frames[s] for s in UNIVERSE}, frames["SPY"], source_rows


def e3_result(prepared, capital):
    return run_signal_portfolio(prepared, "F1 + E3", replace(CONFIG, initial_capital=capital), 2, 10)


def benchmark_results(prices, spy):
    equal_weight = equal_weight_buy_and_hold(prices, CONFIG)
    curve = equal_weight["equity_curve"]
    curve.loc[0, "cash"] = CONFIG.initial_capital
    fills = []
    date = prices[UNIVERSE[0]]["date"].iloc[1]
    for symbol, frame in prices.items():
        execution = float(frame["open"].iloc[1]) * (1 + CONFIG.slippage_pct)
        qty = (CONFIG.initial_capital / len(prices)) / (execution * (1 + CONFIG.transaction_cost_pct))
        notional = qty * execution
        fills.append({"signal_date": frame["date"].iloc[0], "execution_date": date, "symbol": symbol, "action": "BUY",
                      "execution_price": execution, "shares": qty, "notional": notional,
                      "transaction_cost": notional * CONFIG.transaction_cost_pct, "reason": "initial_equal_weight"})
    equal_weight["trades"] = fills
    spy_result = run_buy_and_hold(spy, "SPY", CONFIG)
    spy_result["strategy"] = "SPY buy-and-hold"
    return spy_result, equal_weight


def table(frame):
    formatted = frame.copy()
    for column in formatted:
        if pd.api.types.is_numeric_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda value: f"{value:.3f}" if pd.notna(value) else "—")
    return "\n".join(["| " + " | ".join(formatted.columns) + " |", "| " + " | ".join("---" for _ in formatted.columns) + " |",
                      *("| " + " | ".join(map(str, row)) + " |" for row in formatted.itertuples(index=False, name=None))])


def main():
    prices, spy_df, sources = load_snapshot()
    prepared = {s: bollinger_mean_reversion_variant(frame, spy_df, False, True, False) for s, frame in prices.items()}
    csm = cross_sectional_momentum_backtest(prices, spy_df, CONFIG)
    e3 = e3_result(prepared, 10000)
    spy, ew = benchmark_results(prices, spy_df)
    csm["strategy"] = "CSM 100%"
    e3["strategy"] = "E3 100%"
    results = {"CSM 100%": csm, "E3 100%": e3}
    funding_checks = []
    for weight in ALLOCATIONS:
        csm_sleeve = cross_sectional_momentum_backtest(prices, spy_df, replace(CONFIG, initial_capital=10000 * weight))
        e3_sleeve = e3_result(prepared, 10000 * (1 - weight))
        for key, funded, reference, ratio in (("CSM", csm_sleeve, csm, weight), ("E3", e3_sleeve, e3, 1 - weight)):
            actual = normalized_curve(funded)["equity"]
            expected = normalized_curve(reference)["equity"] * ratio
            error = float(np.max(np.abs(actual - expected)))
            if error > 1e-5:
                raise ValueError("Allocated run is not cash-scale invariant")
            funding_checks.append({"CSM_initial_weight": weight, "sleeve": key, "max_scale_error_dollars": error})
        label = f"CSM {weight:.0%} / E3 {1 - weight:.0%}"
        results[label] = combine_sleeves({"CSM": csm_sleeve, "E3": e3_sleeve}, label)
    results[spy["strategy"]], results[ew["strategy"]] = spy, ew
    OUT.mkdir(parents=True, exist_ok=True)
    replayed, concentrations = {}, []
    for label, result in results.items():
        indexed_prices = {symbol: frame.set_index("date") for symbol, frame in {**prices, "SPY": spy_df}.items()}
        for fill in result["trades"]:
            raw_open = float(indexed_prices[fill["symbol"]].loc[pd.Timestamp(fill["execution_date"]), "open"])
            adverse = 1 + CONFIG.slippage_pct if str(fill["action"]).upper() == "BUY" else 1 - CONFIG.slippage_pct
            if not np.isclose(fill["execution_price"], raw_open * adverse, rtol=1e-10, atol=1e-8):
                raise ValueError("Fill is not the next-open adverse execution price")
            if not np.isclose(fill["transaction_cost"], fill["shares"] * fill["execution_price"] * CONFIG.transaction_cost_pct, rtol=1e-9, atol=1e-8):
                raise ValueError("Commission does not reconcile")
        replay, positions = replay_fills(result, {**prices, "SPY": spy_df})
        replayed[label] = replay
        if "CSM_weight" in result["equity_curve"]:
            weights = result["equity_curve"]["CSM_weight"]
            concentrations.append({"Strategy": label, "Initial CSM Weight %": float(weights.iloc[0] * 100),
                                   "Final CSM Weight %": float(weights.iloc[-1] * 100), "Min CSM Weight %": float(weights.min() * 100),
                                   "Max CSM Weight %": float(weights.max() * 100), "Peak Unique Stocks": int(replay["holdings"].max()),
                                   "Peak Single Name %": float(replay["max_name_weight"].max() * 100)})
        safe = label.lower().replace(" / ", "_").replace(" ", "_").replace("%", "pct").replace("-", "_")
        pd.DataFrame(result["trades"]).to_csv(OUT / f"trades_{safe}.csv", index=False)
        positions.to_csv(OUT / f"positions_{safe}.csv", index=False)
        result["equity_curve"]["holdings"] = replay["holdings"]
        result["equity_curve"]["max_name_weight"] = replay["max_name_weight"]
        result["equity_curve"].to_csv(OUT / f"daily_{safe}.csv", index=False, float_format="%.10f")
    periods = disjoint_periods(csm["equity_curve"]["date"], BOUNDARY)
    assert not len(periods["Research"].intersection(periods["Explored OOS"]))
    rows, yearly, regimes = [], [], []
    regime = spy_df.copy()
    average = regime["close"].rolling(200, min_periods=200).mean()
    regime["regime"] = np.where(regime["close"] > average, "Bull", "Bear")
    regime.loc[average.isna(), "regime"] = "Unknown warmup"
    prior_regime = regime.set_index("date")["regime"].shift(1)
    for label, result in results.items():
        for period, dates in periods.items():
            rows.append({"Period": period, **period_metrics(result, dates, spy, ew)})
        dates = periods["Full"]
        for year in sorted(set(dates.year)):
            yearly.append({"Year": year, **period_metrics(result, dates[dates.year == year], spy, ew)})
        for period in ("Full", "Explored OOS"):
            for state in ("Bull", "Bear", "Unknown warmup"):
                subset = periods[period][prior_regime.reindex(periods[period]).to_numpy() == state]
                if len(subset):
                    metrics = period_metrics(result, subset, spy, ew)
                    # Conditional days are concatenated; calendar CAGR is not meaningful.
                    metrics.pop("CAGR %")
                    metrics.pop("Annualized Turnover x")
                    regimes.append({"Period": period, "Prior Close Regime": state, **metrics})
        stats = {row["Period"]: row for row in rows if row["Strategy"] == label}
        assert np.isclose((1 + stats["Research"]["Return %"] / 100) * (1 + stats["Explored OOS"]["Return %"] / 100),
                          1 + stats["Full"]["Return %"] / 100)
    metrics = pd.DataFrame(rows)
    metrics.to_csv(OUT / "comparison.csv", index=False, float_format="%.8f")
    pd.DataFrame(yearly).to_csv(OUT / "calendar_years.csv", index=False, float_format="%.8f")
    pd.DataFrame(regimes).to_csv(OUT / "portfolio_regimes.csv", index=False, float_format="%.8f")
    pd.DataFrame(concentrations).to_csv(OUT / "concentration_and_weight_drift.csv", index=False, float_format="%.8f")
    correlation = []
    csm_r = normalized_curve(csm).set_index("date")["equity"].pct_change()
    e3_r = normalized_curve(e3).set_index("date")["equity"].pct_change()
    for period, dates in periods.items():
        correlation.append({"Period": period, "Sessions": len(dates), "Daily Return Correlation": float(csm_r.loc[dates].corr(e3_r.loc[dates]))})
    pd.DataFrame(correlation).to_csv(OUT / "sleeve_correlation.csv", index=False, float_format="%.8f")
    audit = {"sources": sources, "original_sample_end": str(spy_df["date"].iloc[-1].date()), "new_forward_observations": 0,
             "split": {k: {"first": str(v[0].date()), "last": str(v[-1].date()), "returns": len(v)} for k, v in periods.items()},
             "overlapping_research_oos_return_dates": 0, "scale_checks": funding_checks,
             "checks": ["OHLC finite and positive", "identical price calendars", "all fills T+1", "all prices match adverse next open", "commission reconciles", "NAV reconstructed from fills",
                        "no negative cash", "all segment returns compound to full return", "each return assigned to exactly one split"],
             "sortino_definition": "mean daily return / RMS of min(return,0) over all sessions * sqrt(252)",
             "limits": ["present-day selected universe", "historically adjusted OHLC, not PIT raw quotes", "explored OOS",
                        "200-session warmup counted in headline sample", "combination may have four distinct names",
                        "no statistical confidence claim", "independent sleeve fills charged without netting"]}
    (OUT / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    write_report(metrics, correlation, concentrations)
    print(metrics[["Period", "Strategy", "Return %", "CAGR %", "Sharpe", "Max Drawdown %", "Exposure %", "Excess vs SPY pp", "Excess vs Equal Weight pp"]].to_string(index=False))
    print("Correlation", correlation)
    print("Concentration", concentrations)


def write_report(metrics, correlation, concentrations):
    cols = ["Strategy", "Return %", "CAGR %", "Sharpe", "Sortino", "Max Drawdown %", "Exposure %", "Excess vs SPY pp", "Excess vs Equal Weight pp"]
    lines = ["# CSM + E3 fixed initial allocation experiment", "", "Run date: 2026-10-26. Original snapshot: 2021-10-27 to 2026-10-23. No new forward observations.", "",
             "Primary hypothesis: 50/50 separate starting cash budgets. Sensitivities: 25/75 and 75/25 CSM/E3. All sleeves retain their own cash and PnL; weights drift. These are not constant-weight rebalanced portfolios. Rules were fixed in docs/CSM_E3_SLEEVE_PREREGISTRATION.md before this study.", ""]
    for period in ("Full", "Research", "Explored OOS"):
        lines += [f"## {period}", "", table(metrics[metrics["Period"] == period][cols]), ""]
    full = metrics[metrics["Period"] == "Full"].set_index("Strategy")
    oos = metrics[metrics["Period"] == "Explored OOS"].set_index("Strategy")
    primary, pure_csm, pure_e3 = "CSM 50% / E3 50%", "CSM 100%", "E3 100%"
    lines += ["## Primary result", "",
        f"The 50/50 blend's full Sharpe is {full.loc[primary, 'Sharpe']:.3f}, versus CSM {full.loc[pure_csm, 'Sharpe']:.3f} and E3 {full.loc[pure_e3, 'Sharpe']:.3f}. Full drawdowns are {full.loc[primary, 'Max Drawdown %']:.2f}%, {full.loc[pure_csm, 'Max Drawdown %']:.2f}% and {full.loc[pure_e3, 'Max Drawdown %']:.2f}% respectively.", "",
        f"Explored-OOS blend Sharpe is {oos.loc[primary, 'Sharpe']:.3f}, versus CSM {oos.loc[pure_csm, 'Sharpe']:.3f} and E3 {oos.loc[pure_e3, 'Sharpe']:.3f}. Blend OOS return is {oos.loc[primary, 'Return %']:.2f}%; excess versus SPY {oos.loc[primary, 'Excess vs SPY pp']:.2f} points and versus equal-weight universe {oos.loc[primary, 'Excess vs Equal Weight pp']:.2f} points.", "",
        "The primary blend improves neither Sharpe nor drawdown relative to standalone E3 in this sample, although it reduces drawdown relative to standalone CSM. Its exposure lies between the two sleeves, so a lower drawdown than CSM does not by itself separate diversification from reduced market exposure. Do not select a weight from the sensitivity rows or infer a reliable future winner from them.", "",
        "## Correlation and capacity", "", table(pd.DataFrame(correlation)), "", table(pd.DataFrame(concentrations)), "",
        "## Corrected accounting", "",
        "Research return dates end 2025-04-25; explored OOS return dates begin 2025-04-28. Each return appears once, with the prior close providing the starting equity. Full return compounds exactly from these disjoint segments. Prior reports shared one boundary return; use this study's corrected segment metrics for CSM and E3.", "",
        "Sortino now uses RMS downside over all return days, with a zero target. Previous reports used standard deviation restricted to negative days; those Sortino values are not comparable. Sharpe uses a zero risk-free rate and population standard deviation. Alpha columns are cumulative return differences in percentage points, not regression alpha.", "",
        "Win rate is the percentage of realized SELL fills with positive FIFO PnL, including prorated entry and exit commission. It is not a comparable independent-trade sample count because CSM can rebalance partially. Fill count includes buys and sells. Turnover is two-way traded notional divided by average NAV. Exposure is invested dollars / NAV, not the fraction of days with any position.", "",
        "## Evidence boundary and next milestone", "",
        "All these dates have already been explored. The fixed universe retains survivorship and selection bias. Adjusted OHLC is not a point-in-time event dataset. Headline comparisons include the original indicator warmup in cash. Blends may hold four names and overlapping stocks can increase concentration; standalone strategies allow two. Therefore this is not a two-position-constrained diversification test.", "",
        "E3 remains a forward-study candidate. Freeze the strategy, source and availability timestamps, execution convention, initial cash and evaluation schedule before collecting genuinely unseen data. This study neither creates a live or paper automation nor places orders. Zero observations here count as new forward evidence.", "",
        "## Reproducibility", "", "Run: python -m unittest tests.test_sleeve_portfolio tests.test_candidate_strategies tests.test_backtest_engine tests.test_cross_sectional_analytics tests.test_strategy_lab", "", "Then: python scripts/research_csm_e3_sleeves.py (offline original cache required). Input hashes and reconciliation checks are in audit.json. Daily curves, actual fills, aggregated name positions, calendar-year and prior-close-regime tables are included in this directory."]
    (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
