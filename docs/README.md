# Documentation Index

Strategy research documentation for the TSLA/TSLL workstream of "Optimal
Hedging Strategy of a Leveraged ETF Position". Each document states what the
strategy is, where its code lives, how to reproduce its results, and what its
results were, including the strategies that failed and why.

## Strategies (chronological)

| Doc | Strategy | Status |
|---|---|---|
| [01_naked_short.md](strategies/01_naked_short.md) | Naked short TSLL (Double-Short baseline) | Benchmark, catastrophic drawdown |
| [02_delta_arbitrage.md](strategies/02_delta_arbitrage.md) | Delta-Adjusted Arbitrage (long TSLA vs short TSLL) | Rejected: look-ahead bias and cost fragility |
| [03_convexity_protection.md](strategies/03_convexity_protection.md) | Convexity Protection: static guaranteed floor (share-matched hybrid) | Best static approach; extended by the floor engine |
| [04_floor_engine.md](strategies/04_floor_engine.md) | Drawdown-Constrained Convexity Protection (final) | Final deliverable |

## Results

[results.md](results.md) is the master results index: every published number,
the file that produced it, and the command that reproduces it.

## Where things live

- Production engine: `scripts/strategies/floor_engine/`
  (`reproduce_results.py` reproduces all final results); the static
  convexity protection port is `scripts/strategies/static_guaranteed_floor.py`
- Earlier strategy scripts: `scripts/strategies/` and `scripts/backtest/`
  (frozen; the historical record)
- Research notebooks: `scripts/utils/sandbox/` (exploration record; the
  engine's own notebooks live in `sandbox/prod_experiments/`, kept local and
  gitignored; the production package reproduces every published number)
- Figures: `observations/` by topic; result tables/CSVs: `results/`
- Report: `latex/tsla_tsll_hedging_report.tex` (complete, self-contained:
  literature review, all four strategies, and the engine). An earlier main
  report is maintained on Overleaf; only its build artifacts are in the repo.
- Data pipeline and schemas: repository `README.md`, Sections 6 and 7
