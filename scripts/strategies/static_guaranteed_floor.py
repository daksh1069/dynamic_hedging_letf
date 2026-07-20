"""Convexity Protection, final static implementation: the guaranteed floor.

Short a FIXED share count of TSLL forever and buy exactly share-matched TSLL
call contracts each cycle, held to expiry (three-tier fill: strict TSLL ATM
60-110 DTE; relaxed TSLL 45-120 DTE with a TSLA delta supplement; TSLA only).
Share-matching on the same instrument makes each cycle's worst case an
algebraic identity, the premium paid, rather than a backtest observation.

This is the production port of the research notebook
scripts/utils/sandbox/prod_experiments/guaranteed_floor_hybrid_sandbox.ipynb and the "prior best"
reference row of every later comparison. Published result (2022-08-12 to
2026-06-10): CAGR +19.42%, Sharpe 0.928, max drawdown -19.70%, Calmar 0.986.
A reproduction check asserts the published CAGR at the end of the run.

No deleveraging, no risk budget, no ceiling, no gate, no cash interest, no
borrow costs: those are the extensions that became the drawdown-constrained
engine in scripts/strategies/floor_engine/ (see docs/strategies/04).

Risk metrics are printed to the console; the equity-curve figure is saved to
observations/strategies/static_guaranteed_floor/ and the equity series to
results/static_guaranteed_floor/equity.csv.

Usage (from the project root):
    venv/bin/python3 scripts/strategies/static_guaranteed_floor.py
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "strategies" / "floor_engine"))

from data import load_market_data, load_lineage_extras      # noqa: E402
from stats import quick_stats, static_hybrid_equity          # noqa: E402

OBS_DIR = ROOT / "observations" / "strategies" / "static_guaranteed_floor"
RES_DIR = ROOT / "results" / "static_guaranteed_floor"

PUBLISHED_CAGR = 0.1942


def main() -> None:
    OBS_DIR.mkdir(parents=True, exist_ok=True)
    RES_DIR.mkdir(parents=True, exist_ok=True)

    md = load_lineage_extras(load_market_data())
    print(f"Data loaded. Sim: {md.sim_dates[0].date()} -> {md.sim_dates[-1].date()} "
          f"({len(md.sim_dates)} days)")

    print("Running static guaranteed floor (fixed share count, cycles to expiry) ...")
    equity = static_hybrid_equity(md)
    st = quick_stats(equity, "Static Convexity Protection (full notional)")

    print("\n=== Risk metrics ===")
    for k in ("CAGR", "Sharpe", "MaxDD", "Calmar"):
        print(f"{k:>8}: {st[k]:.4f}")

    equity.rename("equity").to_csv(RES_DIR / "equity.csv")

    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(13, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [2, 1]})
    ax0.plot(equity.index, equity, color="steelblue", lw=1.5)
    ax0.axhline(1.0, color="black", lw=0.5)
    ax0.set_ylabel("Equity (notional = 1)")
    ax0.set_title("Static Convexity Protection (guaranteed floor, full notional)\n"
                  f"CAGR {st['CAGR']:+.2%}  Sharpe {st['Sharpe']:.3f}  "
                  f"MaxDD {st['MaxDD']:.2%}  Calmar {st['Calmar']:.3f}")
    dd = equity / equity.cummax() - 1.0
    ax1.fill_between(dd.index, dd * 100, color="indianred", alpha=0.35)
    ax1.plot(dd.index, dd * 100, color="indianred", lw=0.9)
    ax1.set_ylabel("Drawdown (%)")
    ax1.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    fig.savefig(OBS_DIR / "equity_drawdown.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    print(f"\nEquity CSV -> {RES_DIR / 'equity.csv'}")
    print(f"Figure     -> {OBS_DIR / 'equity_drawdown.png'}")

    if abs(st["CAGR"] - PUBLISHED_CAGR) > 0.002:
        raise SystemExit(f"REPRODUCTION FAILED: CAGR {st['CAGR']:.2%} does not "
                         f"match the published {PUBLISHED_CAGR:+.2%}.")
    print("Reproduction check passed (matches published +19.42% CAGR).")


if __name__ == "__main__":
    main()
