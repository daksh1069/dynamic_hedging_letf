# Master Results Index

Every published number, where it came from, and how to reproduce it. All
windows are 2022-08-12 to 2026-06-10 unless stated otherwise; the common
cross-strategy window (2022-11-08 to 2026-06-08) is shorter because of the
delta-arbitrage warm-up.

## Final engine (Strategy 4, the deliverable)

Reproduce all of the below with one command:

```bash
venv/bin/python3 scripts/strategies/floor_engine/reproduce_results.py
```

| Result | Value | Table/CSV | Figure |
|---|---|---|---|
| Collar, frictionless | +15.69% CAGR, -12.29% MaxDD, Calmar 1.277 | `results/floor_engine/summary.csv` | `observations/strategies/final/final_equity_floor_deployment.png` |
| Collar, realized (borrow) | +10.41% CAGR, -15.21% MaxDD | same | same |
| Call-only, frictionless | +14.00% CAGR, -11.29% MaxDD, Calmar 1.240 | same | same |
| Call-only, realized (borrow) | +13.42% CAGR, -15.44% MaxDD, Calmar 0.869 | same | same |
| Guarantee verification | 0 leak-adjusted floor violations, all variants | `results/floor_engine/verification.csv` | n/a |
| Holdout halves | collar H1 +33.16%/H2 -2.08%; call H1 +30.84%/H2 +0.49%; 0 violations | `results/floor_engine/holdout.csv` | n/a |
| Risk dial (x = l = d = g) | frontier peaks near x = 10% | `results/floor_engine/risk_dial.csv` | `observations/strategies/final/final_risk_dial.png` |
| Strategy lineage | static +19.42% reproduced exactly | `results/floor_engine/lineage.csv` | `observations/strategies/final/final_lineage_equity_curves.png` |
| Per-tranche log (collar) | 20 tranches, 18 with put leg | `results/floor_engine/tranche_log_collar.csv` | n/a |

Research record for the same numbers: the notebook archive in
`scripts/utils/sandbox/prod_experiments/` (kept local, gitignored; the
production package is the tracked source of record). Report:
`latex/tsla_tsll_hedging_report.tex`.

## Earlier strategies (historical record; scripts frozen)

| Result | Source script | Outputs |
|---|---|---|
| Naked short: -81.1% MaxDD (common window) | `scripts/strategies/double_short.py` | `observations/strategies/double_short/`, `results/double_short/equity.csv` |
| Delta-arb: Sharpe 2.69 on paper, rejected for look-ahead bias | `scripts/strategies/delta_arb.py` | `observations/strategies/delta_arb/`, `results/delta_arb/equity.csv` |
| Convexity CBA: A-20% OTM best at fixed spend (+17.4%, -61.2%) | `scripts/backtest/cba_backtest.py` | `observations/strategies/cba/`, `results/cba/` |
| Cross-strategy table | `scripts/strategies/compare_all.py` | `observations/strategies/results.txt`, `comparison.png` |
| Static guaranteed floor: +19.42%, -19.70%, Calmar 0.986 | `scripts/strategies/static_guaranteed_floor.py` (port of `guaranteed_floor_hybrid_sandbox.ipynb`) | `observations/strategies/static_guaranteed_floor/`, `results/static_guaranteed_floor/equity.csv` |
| Grid search / sensitivity sweeps | `scripts/backtest/grid_search.py` | `observations/strategies/grid_search/` |

## Reading the numbers

Frictionless results exclude bid-ask spreads (unavailable in this dataset by
scope), commissions, and borrow; realized results add the approximate borrow
series only. The guaranteed MaxDD bounds are theorems given the stated
assumptions; every CAGR is a single 3.8-year history and the returns of the
final engine are crash-regime concentrated by design.
