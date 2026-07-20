"""Drawdown-Constrained Convexity Protection engine (production port).

Productionized from the research notebooks in scripts/utils/ (source of
record: final_guaranteed_floor_project.ipynb). Each tranche shorts TSLL,
buys a long TSLL call and optionally sells a same-expiry OTM TSLL put (a
collar). Per-tranche worst-case loss is an exact algebraic reservation,
continuous in time via model-free no-arbitrage bounds; the portfolio's
maximum drawdown is capped by the closed-form master equation

    MaxDD <= (d + g) / (1 + g)

where l = per-cycle loss budget, d = drawdown limit, g = gain trigger and
q = deployment cost gate (see config.py for the notation rationale).

Modules:
    config      parameters and notation
    data        market data loading (spot, chains, borrow)
    selection   contract selection (anchor, top-up, put leg)
    marks       no-arbitrage banded mark-to-market
    portfolio_engine   the tranche/portfolio simulation
    stats       performance metrics and analytic bounds
    verify      floor and drawdown-bound verification
    plots       final figures
    reproduce_results  reproduces every published result (CLI entry point)

Reproduce all results:  venv/bin/python3 scripts/strategies/floor_engine/reproduce_results.py
Full write-up:          latex/tsla_tsll_hedging_report.tex
Documentation:          docs/strategies/04_floor_engine.md
"""
