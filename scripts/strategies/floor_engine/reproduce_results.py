"""Reproduce every published result of the drawdown-constrained convexity
protection engine.

Usage (from the project root):
    venv/bin/python3 scripts/strategies/floor_engine/reproduce_results.py

Outputs:
    observations/strategies/final/*.png    figures (mirrored to latex/figures/)
    results/floor_engine/*.csv             equity curves and result tables
    console                                summary tables and verification

This is the production port of scripts/utils/final_guaranteed_floor_project
.ipynb; numbers must match that notebook exactly (the static hybrid must
reproduce +19.42% CAGR / -19.70% MaxDD, and every variant must verify with
zero leak-adjusted floor violations).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import (LOSS_BUDGET, DD_LIMIT, GAIN_TRIGGER, COST_GATE,            # noqa: E402
                    RISK_DIAL_LADDER, master_bound, dial_bound)
from data import load_market_data, load_lineage_extras                          # noqa: E402
from portfolio_engine import simulate                                                     # noqa: E402
from stats import quick_stats, naked_short_equity, static_hybrid_equity         # noqa: E402
from verify import verify, print_report                                         # noqa: E402
import plots                                                                    # noqa: E402

ROOT    = Path(__file__).resolve().parents[3]
RES_DIR = ROOT / "results" / "floor_engine"


def main() -> None:
    RES_DIR.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 160)

    md = load_market_data()
    print(f"Data loaded. Sim: {md.sim_dates[0].date()} -> {md.sim_dates[-1].date()} "
          f"({len(md.sim_dates)} days)")
    print(f"Config: loss budget l={LOSS_BUDGET:.0%}, drawdown limit d={DD_LIMIT:.1%}, "
          f"gain trigger g={GAIN_TRIGGER:.0%}, cost gate q={COST_GATE:.0%} "
          f"-> guaranteed MaxDD bound = {master_bound():.1%}\n")

    # ---- Main runs: collar and call-only, frictionless and with borrow ----
    runs = {}
    for name, up, ub in [("Collar (frictionless)", True, False),
                         ("Collar with borrow (realized)", True, True),
                         ("Call-only (frictionless)", False, False),
                         ("Call-only with borrow (realized)", False, True)]:
        print(f"Running: {name} ...")
        runs[name] = simulate(md, use_puts=up, use_borrow=ub)

    summary = pd.DataFrame([quick_stats(r.equity, n) for n, r in runs.items()]
                            ).set_index("Strategy")
    summary.loc["Prior best (static hybrid, frictionless ref)"] = \
        [0.1942, 0.928, -0.1970, 0.986]
    print("\n=== Headline results (guaranteed bound "
          f"{master_bound():.1%} frictionless) ===")
    print(summary.round(4).to_string(), "\n")
    summary.to_csv(RES_DIR / "summary.csv")

    slug = {"Collar (frictionless)": "collar_frictionless",
            "Collar with borrow (realized)": "collar_borrow",
            "Call-only (frictionless)": "call_frictionless",
            "Call-only with borrow (realized)": "call_borrow"}
    for name, r in runs.items():
        r.equity.rename("equity").to_csv(RES_DIR / f"equity_{slug[name]}.csv")
    runs["Collar (frictionless)"].log.to_csv(RES_DIR / "tranche_log_collar.csv",
                                              index=False)

    # ---- Verification (floor + bound, leak-adjusted where borrow applies) ----
    print("=== Verification ===")
    checks = [verify(r, label=n) for n, r in runs.items()]
    for v in checks:
        print_report(v)
    pd.DataFrame(checks).set_index("label").to_csv(RES_DIR / "verification.csv")
    n_bad = sum(v["floor_violations"] for v in checks)
    n_out = sum(not v["within_bound"] for v in checks)
    if n_bad or n_out:
        raise SystemExit(f"GUARANTEE FAILED: {n_bad} floor violations, "
                         f"{n_out} bound breaches -- investigate before publishing.")

    # ---- Holdout halves (frictionless, fixed pre-registered config) ----
    split = md.sim_dates[len(md.sim_dates) // 2]
    halves = {"H1": md.sim_dates[md.sim_dates <= split],
              "H2": md.sim_dates[md.sim_dates > split]}
    hold_rows = []
    for variant, up in [("collar", True), ("call-only", False)]:
        for hname, dts in halves.items():
            r = simulate(md, sim_dates=dts, use_puts=up)
            st = quick_stats(r.equity, f"{variant} {hname}")
            st["FloorViol"] = verify(r, label="")["floor_violations"]
            hold_rows.append(st)
    hold = pd.DataFrame(hold_rows).set_index("Strategy")
    print("=== Holdout halves (frictionless) ===")
    print(hold.round(4).to_string(), "\n")
    hold.to_csv(RES_DIR / "holdout.csv")

    # ---- Risk dial (collar, frictionless): x = l = d = g ----
    dial_rows = []
    for x in RISK_DIAL_LADDER:
        r = simulate(md, loss_budget=x, dd_limit=x, gain_trigger=x, use_puts=True)
        st = quick_stats(r.equity, f"{x:.0%}")
        dial_rows.append({"x": f"{x:.0%}", "Bound": dial_bound(x),
                          "CAGR": st["CAGR"], "Sharpe": st["Sharpe"],
                          "MaxDD": st["MaxDD"], "Calmar": st["Calmar"],
                          "FloorViol": verify(r, loss_budget=x, dd_limit=x,
                                              gain_trigger=x, label="")["floor_violations"]})
    dial = pd.DataFrame(dial_rows).set_index("x")
    print("=== Risk dial (collar, frictionless) ===")
    print(dial.round(4).to_string(), "\n")
    dial.to_csv(RES_DIR / "risk_dial.csv")

    # ---- Strategy lineage (needs TSLA side for the static hybrid) ----
    print("Running: static hybrid reproduction (lineage) ...")
    load_lineage_extras(md)
    eq_static = static_hybrid_equity(md)
    eq_naked  = naked_short_equity(md)
    lineage = pd.DataFrame([
        quick_stats(eq_naked,  "Naked Short TSLL"),
        quick_stats(eq_static, "Static Convexity Protection (full notional)"),
        quick_stats(runs["Call-only (frictionless)"].equity,
                    "Drawdown-Constrained Convexity Protection (Call)"),
        quick_stats(runs["Collar (frictionless)"].equity,
                    "Drawdown-Constrained Convexity Protection (Collar)"),
    ]).set_index("Strategy")
    print("=== Strategy lineage (frictionless) ===")
    print(lineage.round(4).to_string(), "\n")
    lineage.to_csv(RES_DIR / "lineage.csv")
    static_stats = quick_stats(eq_static, "static")
    if abs(static_stats["CAGR"] - 0.1942) > 0.002:
        raise SystemExit("REPRODUCTION FAILED: static hybrid CAGR "
                         f"{static_stats['CAGR']:.2%} != published +19.42%.")

    # ---- Figures ----
    plots.plot_equity_floor_deployment(runs["Collar (frictionless)"],
                                       runs["Collar with borrow (realized)"],
                                       runs["Call-only (frictionless)"])
    plots.plot_risk_dial(dial)
    plots.plot_lineage(eq_naked, eq_static,
                       runs["Call-only (frictionless)"].equity,
                       runs["Collar (frictionless)"].equity)
    print(f"Figures -> observations/strategies/final/  |  tables -> {RES_DIR}")
    print("All guarantees verified; reproduction checks passed.")


if __name__ == "__main__":
    main()
