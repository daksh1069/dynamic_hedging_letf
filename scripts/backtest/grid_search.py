"""
Grid search over TARGET_DTE x ROLL_DTE x moneyness bucket for the CBA
Ensemble strategy (short TSLL + delta-neutral long call, cheapest of TSLA vs
TSLL calls each roll -- see cba_backtest.py), with a stop-loss override: if a
held position's unrealized loss vs its own entry premium breaches
STOP_LOSS_PCT, every bucket/underlying combination is re-priced and the
position switches into the cheapest one available, but only if something is
genuinely cheaper than re-establishing the current position right now.

cba_backtest.py's TARGET_DTE=180 / ROLL_DTE=14 defaults were picked from a
single earlier comparison against TARGET_DTE=60 -- this grid checks whether
that's actually the optimum, or whether a different combination dominates
once both parameters and the moneyness bucket are free to vary together.
TARGET_DTE is capped at 180 (the project's established upper limit); going
past it isn't validated against liquid contracts and distorts drawdown
numbers (long-dated options barely mark day-to-day in this backtest).

The grid is run at FOUR transaction-cost scenarios (COST_SCENARIOS): a
frictionless "none" reference plus low/base/high assumed per-leg costs on
TSLA vs TSLL calls. We don't have bid/ask data (only px_last), so these are
stated assumptions, not measured spreads -- TSLA is a liquid single-name
market (1-4% round-trip assumed); TSLL is a sparse chain (3-12% round-trip
assumed, given the 29-63% fill rates documented elsewhere in this project).
The frictionless grid previously found its "best" cell by exploiting near-
free high-frequency rolling/switching; comparing all four scenarios side by
side is the point -- it shows whether a result survives realistic costs or
is just an artifact of assuming free trading.

Outputs (per scenario):
  - Per-bucket CAGR / Max DD / Sharpe matrices (rows=TARGET_DTE, cols=ROLL_DTE),
    printed + saved as CSV + heatmap PNG.
  - Four global cross-cut tables: best combo by bucket, by TARGET_DTE, by
    ROLL_DTE, and overall (by Sharpe, by CAGR, by smallest |Max DD|).
  - A final cross-scenario table showing how the best cell shifts as costs rise.

Figures -> observations/strategies/grid_search/
Results -> results/grid_search/

NOTE: this runs ~170 full daily-loop backtests per scenario x 4 scenarios =
~680 backtests total -- expect a long runtime (potentially 10+ minutes), not
a bug if it's slow.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from capture import capture_stdout
from data_loader import load_tsla_underlying, load_tsll, load_tsla_calls, load_tsll_calls
from metrics import summarize
from cba_backtest import simulate_ensemble, BUCKETS, VOL_WINDOW
from borrow_rates import load_borrow_rates

OUT_DIR = ROOT / "observations" / "strategies" / "grid_search"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "grid_search"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

START = pd.Timestamp("2022-08-12")
END   = pd.Timestamp("2026-06-10")

TARGET_DTE_GRID = [30, 45, 60, 90, 120, 150, 180]   # capped at 180 -- the project's established limit
ROLL_DTE_GRID   = [3, 5, 7, 10, 14, 21, 30, 45, 60]
MAX_DTE         = 200   # small buffer over the 180 cap, not a wide search beyond it
STOP_LOSS_PCT   = 0.5   # roll early if a position has lost 50% of its premium

# Per-leg transaction cost scenarios (round-trip = 2x these), since we lack bid/ask data.
# TSLA: liquid single-name market. TSLL: sparse chain (29-63% fill rates documented earlier).
# "none" is the pure frictionless reference: zero transaction cost AND zero borrow cost, so
# it stays a clean baseline. low/base/high all include the real TSLL borrow-rate series
# (borrow_rates.py) on top of their transaction-cost assumption -- borrow isn't a "scenario",
# it's a real cost that should be in every non-frictionless run.
COST_SCENARIOS = {
    "none": {"tsla_cost_pct": 0.000, "tsll_cost_pct": 0.000, "borrow": False},
    "low":  {"tsla_cost_pct": 0.005, "tsll_cost_pct": 0.015, "borrow": True},   # 1% / 3% round-trip
    "base": {"tsla_cost_pct": 0.010, "tsll_cost_pct": 0.030, "borrow": True},   # 2% / 6% round-trip
    "high": {"tsla_cost_pct": 0.020, "tsll_cost_pct": 0.060, "borrow": True},   # 4% / 12% round-trip
}


def _slug(bucket: str) -> str:
    return bucket.lower().replace(" ", "_").replace("%", "pct")


def load_data():
    tsll_df = load_tsll()
    r_tsll = tsll_df.set_index("Date")["Close"].pct_change().dropna()
    r_tsll = r_tsll[(r_tsll.index >= START) & (r_tsll.index <= END)]
    returns = r_tsll.rename("TSLL").to_frame()

    tsla_spot = (load_tsla_underlying()
                 .set_index("Date")["Close"]
                 .reindex(returns.index).ffill())
    tsll_spot = (tsll_df.set_index("Date")["Close"]
                 .reindex(returns.index).ffill())

    tsla_calls = load_tsla_calls()
    tsll_calls = load_tsll_calls()
    tsla_lookup = tsla_calls.set_index(["raw_id", "date"])["px_last"].to_dict()
    tsll_lookup = tsll_calls.set_index(["raw_id", "date"])["px_last"].to_dict()
    tsla_vol_lookup = tsla_calls.set_index(["raw_id", "date"])["px_volume"].to_dict()
    tsll_vol_lookup = tsll_calls.set_index(["raw_id", "date"])["px_volume"].to_dict()

    tsla_sigma = (tsla_spot.pct_change()
                  .rolling(VOL_WINDOW).std() * (252 ** 0.5)).ffill().bfill()
    tsll_sigma = (tsll_spot.pct_change()
                  .rolling(VOL_WINDOW).std() * (252 ** 0.5)).ffill().bfill()

    borrow_df = load_borrow_rates(returns.index)

    return (returns, tsla_calls, tsla_spot, tsla_lookup, tsla_vol_lookup, tsla_sigma,
            tsll_calls, tsll_spot, tsll_lookup, tsll_vol_lookup, tsll_sigma, borrow_df)


def run_grid(data, tsla_cost_pct, tsll_cost_pct, tsll_borrow_rate) -> pd.DataFrame:
    (returns, tsla_calls, tsla_spot, tsla_lookup, tsla_vol_lookup, tsla_sigma,
     tsll_calls, tsll_spot, tsll_lookup, tsll_vol_lookup, tsll_sigma, _borrow_df) = data

    combos = [(b, t, r) for b in BUCKETS for t in TARGET_DTE_GRID
              for r in ROLL_DTE_GRID if r < t]
    rows = []
    for i, (bucket, target_dte, roll_dte) in enumerate(combos, 1):
        print(f"  [{i}/{len(combos)}] {bucket}  target_dte={target_dte}  "
              f"roll_dte={roll_dte} ...", flush=True)
        eq, stats = simulate_ensemble(
            returns,
            tsla_calls, tsla_spot, tsla_lookup, tsla_vol_lookup, tsla_sigma,
            tsll_calls, tsll_spot, tsll_lookup, tsll_vol_lookup, tsll_sigma,
            bucket, target_dte, roll_dte, MAX_DTE, stop_loss_pct=STOP_LOSS_PCT,
            tsla_cost_pct=tsla_cost_pct, tsll_cost_pct=tsll_cost_pct,
            tsll_borrow_rate=tsll_borrow_rate)
        eq = eq / eq.iloc[0]
        eq_ret = eq.pct_change().dropna()
        row = summarize(eq, eq_ret, f"{bucket}/{target_dte}/{roll_dte}")
        row["bucket"] = bucket
        row["target_dte"] = target_dte
        row["roll_dte"] = roll_dte
        row["stop_loss_rolls"] = stats["stop_loss_rolls"]
        row["misses"] = stats["misses"]
        row["exit_misses"] = stats["exit_misses"]
        row["transaction_costs_paid"] = round(stats["transaction_costs_paid"], 4)
        row["borrow_paid"] = round(stats["borrow_paid"], 4)
        rows.append(row)

    return pd.DataFrame(rows)


def save_matrix(df: pd.DataFrame, bucket: str, metric: str, col: str, scenario: str):
    sub = df[df["bucket"] == bucket]
    pivot = sub.pivot(index="target_dte", columns="roll_dte", values=col)
    slug = _slug(bucket)
    pivot.to_csv(RESULTS_DIR / f"{slug}_{metric}_{scenario}.csv")

    fig, ax = plt.subplots(figsize=(8, 6))
    cmap = "RdYlGn_r" if metric == "maxdd" else "RdYlGn"
    im = ax.imshow(pivot.values, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("ROLL_DTE")
    ax.set_ylabel("TARGET_DTE")
    ax.set_title(f"{bucket}: {metric.upper()}  [{scenario}]")
    for r in range(pivot.shape[0]):
        for c in range(pivot.shape[1]):
            val = pivot.values[r, c]
            if not np.isnan(val):
                ax.text(c, r, f"{val:.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(OUT_DIR / f"{slug}_{metric}_{scenario}.png", dpi=150)
    plt.close(fig)
    return pivot


def global_summaries(df: pd.DataFrame) -> dict:
    cols = ["bucket", "target_dte", "roll_dte", "CAGR", "Max DD", "Sharpe"]
    tables = {}

    tables["by_bucket"] = (df.sort_values("Sharpe", ascending=False)
                            .groupby("bucket", as_index=False).first()[cols])
    tables["by_target_dte"] = (df.sort_values("Sharpe", ascending=False)
                               .groupby("target_dte", as_index=False).first()[cols])
    tables["by_roll_dte"] = (df.sort_values("Sharpe", ascending=False)
                             .groupby("roll_dte", as_index=False).first()[cols])

    # Max DD is stored negative; "smallest |Max DD|" = largest (least negative) value.
    overall = pd.DataFrame([
        df.loc[df["Sharpe"].idxmax(), cols].rename("Best Sharpe"),
        df.loc[df["CAGR"].idxmax(), cols].rename("Best CAGR"),
        df.loc[df["Max DD"].idxmax(), cols].rename("Smallest |Max DD|"),
    ])
    tables["overall"] = overall

    return tables


def main():
    print("=" * 82)
    print("GRID SEARCH: TARGET_DTE x ROLL_DTE x Moneyness Bucket  (CBA Ensemble + stop-loss)")
    print(f"TARGET_DTE grid : {TARGET_DTE_GRID}  (capped at 180 -- project's established limit)")
    print(f"ROLL_DTE grid   : {ROLL_DTE_GRID}")
    print(f"Stop-loss       : roll early if unrealized loss <= -{STOP_LOSS_PCT:.0%} of premium "
          f"(only executes if switching clears its own transaction cost)")
    print(f"Cost scenarios  : {COST_SCENARIOS}")
    print("=" * 82)

    print("\nFull per-bucket matrices and global cross-cut tables are saved to disk for every")
    print("scenario (record-keeping) but NOT printed below -- the printed/published summary")
    print("below is intentionally short. See results/grid_search/ for the full breakdown.")

    data = load_data()
    borrow_df = data[-1]
    print(f"\nTSLL borrow rate (real, quarterly, see borrow_rates.py): "
          f"mean={borrow_df['TSLL'].mean():.1%}  min={borrow_df['TSLL'].min():.1%}  "
          f"max={borrow_df['TSLL'].max():.1%}")
    scenario_best = []

    for scenario, costs in COST_SCENARIOS.items():
        borrow_rate = borrow_df["TSLL"] if costs["borrow"] else None
        print(f"\n{'#'*82}\nSCENARIO: {scenario.upper()}  "
              f"(TSLA {costs['tsla_cost_pct']:.1%}/leg, TSLL {costs['tsll_cost_pct']:.1%}/leg, "
              f"borrow={'real TSLL series' if costs['borrow'] else 'none'})\n{'#'*82}")
        df = run_grid(data, costs["tsla_cost_pct"], costs["tsll_cost_pct"], borrow_rate)
        df.to_csv(RESULTS_DIR / f"grid_raw_{scenario}.csv", index=False)

        # Record-keeping: save every matrix/table to disk, don't print them.
        for bucket in BUCKETS:
            for metric, col in [("cagr", "CAGR"), ("maxdd", "Max DD"), ("sharpe", "Sharpe")]:
                save_matrix(df, bucket, metric, col, scenario)
        tables = global_summaries(df)
        for name, t in tables.items():
            t.to_csv(RESULTS_DIR / f"global_best_{name}_{scenario}.csv", index=False)

        # Publishable: just the compact "best overall" table per scenario.
        print(f"\n--- Best overall [{scenario}] ---")
        print(tables["overall"].to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

        total_stop_loss_rolls = df["stop_loss_rolls"].sum()
        total_tc = df["transaction_costs_paid"].sum()
        total_borrow = df["borrow_paid"].sum()
        total_exit_misses = df["exit_misses"].sum()
        print(f"Stop-loss rolls fired: {total_stop_loss_rolls} (across {len(df)} grid cells)  "
              f"|  Transaction costs: ${total_tc:,.2f}  |  Borrow costs: ${total_borrow:,.2f}")
        print(f"Exit misses (wanted to roll, contract had no fill that day, held instead): "
              f"{total_exit_misses}")

        best_row = df.loc[df["Sharpe"].idxmax()]
        scenario_best.append({
            "scenario": scenario,
            "tsla_cost_pct": costs["tsla_cost_pct"], "tsll_cost_pct": costs["tsll_cost_pct"],
            "borrow_included": costs["borrow"],
            "bucket": best_row["bucket"], "target_dte": best_row["target_dte"],
            "roll_dte": best_row["roll_dte"], "CAGR": best_row["CAGR"],
            "Max DD": best_row["Max DD"], "Sharpe": best_row["Sharpe"],
            "stop_loss_rolls_total": total_stop_loss_rolls,
        })

    print("\n" + "=" * 82)
    print("CROSS-SCENARIO COMPARISON: best cell (by Sharpe) at each cost level")
    print("=" * 82)
    cross_df = pd.DataFrame(scenario_best)
    print(cross_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    cross_df.to_csv(RESULTS_DIR / "cross_scenario_best.csv", index=False)

    print(f"\nPer-scenario raw grids -> {RESULTS_DIR}/grid_raw_{{none,low,base,high}}.csv")
    print(f"Cross-scenario summary -> {RESULTS_DIR / 'cross_scenario_best.csv'}")
    print(f"Matrices + heatmaps    -> {RESULTS_DIR}/ , {OUT_DIR}/")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "results.txt"):
        main()
