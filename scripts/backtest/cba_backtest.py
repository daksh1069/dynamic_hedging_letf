"""
Cost-Benefit Analysis: Short TSLL + Long Call Hedge.

Compares two hedging variants against an unhedged baseline:
  Benchmark : naked short $1 TSLL (buy & hold)
  Strategy A: short TSLL + long TSLA call (call on the underlying)
  Strategy B: short TSLL + long TSLL call (call on the LETF itself)

Parameters:
  - Analysis window : 2022-08-12 → 2026-06-10 (limited by TSLL options history)
  - DTE filter      : 0 < dte ≤ 180; roll when held DTE drops below 14
  - Moneyness       : ATM (0.95-1.05), 10% OTM (1.05-1.15), 20% OTM (1.15-1.25)
  - Hedge spend     : 2% of $1 short notional per roll (HEDGE_PCT)
  - Target DTE      : ≈60 days (pick contract closest to this in the bucket)

TSLL options are sparse (median ~49 contracts/day vs ~373 for TSLA).
Strategy B tracks fill rate and miss days as first-class CBA outputs.

Figures → observations/strategies/cba/
Results → results/cba/equity_*.csv
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from capture import capture_stdout
from data_loader import load_tsla_underlying, load_tsll, load_tsla_calls, load_tsll_calls
from metrics import summarize, cagr as metric_cagr
from options_selection import select_contract, bs_delta

OUT_DIR = ROOT / "observations" / "strategies" / "cba"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "cba"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

START       = pd.Timestamp("2022-08-12")
END         = pd.Timestamp("2026-06-10")
TARGET_DTE  = 180
ROLL_DTE    = 14
MAX_DTE     = 180
TSLL_LEVER  = 2.0   # TSLL nominal leverage vs TSLA
R_RF        = 0.05  # risk-free rate proxy (annualised)
VOL_WINDOW  = 21    # days for realised-vol used in BS delta

BUCKETS = ["ATM", "10% OTM", "20% OTM"]


def simulate(returns, calls, calls_spot, price_lookup, moneyness_bucket,
             sigma_series, leverage_factor):
    """Short $1 TSLL (buy & hold) + delta-neutral call, rolled on DTE trigger.

    `calls_spot` is the underlying spot (TSLA for Strategy A, TSLL for B).
    `sigma_series` is the rolling realised vol of that underlying.
    `leverage_factor` is the dollar-delta of the short TSLL per unit of the
    call's underlying (2.0 for TSLA calls, 1.0 for TSLL calls).

    Sizing: n = (leverage_factor × cum_tsll) / (Δ_call × 100 × calls_spot).
    Returns (equity, stats).
    """
    cum_tsll = (1 + returns["TSLL"]).cumprod()
    base_equity = 2.0 - cum_tsll

    equity = pd.Series(index=returns.index, dtype=float)
    position = None
    option_pnl = 0.0
    stats = {
        "roll_attempts": 0,
        "fills": 0,
        "misses": 0,
        "miss_dates": [],
        "hedge_cost": 0.0,
    }

    def mtm_price(raw_id, strike, expiry, date, last_known):
        if date > expiry:
            s = calls_spot.loc[date]
            return max(s - strike, 0.0)
        px = price_lookup.get((raw_id, date))
        if px is not None and not pd.isna(px):
            return float(px)
        return last_known

    for d in returns.index:
        held_dte = (position["expiry"] - d).days if position is not None else -1
        need_roll = (position is None) or (held_dte < ROLL_DTE)

        if need_roll:
            if position is not None:
                px = mtm_price(position["raw_id"], position["strike"],
                               position["expiry"], d, position["price"])
                option_pnl += position["n"] * 100 * (px - position["price"])
                position = None

            stats["roll_attempts"] += 1
            row = select_contract(calls, calls_spot, d, moneyness_bucket,
                                  TARGET_DTE, max_dte=MAX_DTE)
            if row is not None:
                entry = float(row["px_last"])
                S = float(calls_spot.loc[d])
                sigma = float(sigma_series.loc[d]) if d in sigma_series.index else 0.5
                T = (row["expiry"] - d).days / 365.25
                delta = bs_delta(S, float(row["strike"]), T, R_RF, sigma)

                short_delta = leverage_factor * float(cum_tsll.loc[d])
                n = short_delta / (delta * 100 * S)

                position = {
                    "raw_id": row["raw_id"],
                    "strike": float(row["strike"]),
                    "expiry": row["expiry"],
                    "n": n,
                    "price": entry,
                }
                stats["fills"] += 1
                stats["hedge_cost"] += n * 100 * entry
            else:
                stats["misses"] += 1
                stats["miss_dates"].append(d)
        else:
            if position is not None:
                px = mtm_price(position["raw_id"], position["strike"],
                               position["expiry"], d, position["price"])
                option_pnl += position["n"] * 100 * (px - position["price"])
                position["price"] = px

        equity.loc[d] = base_equity.loc[d] + option_pnl

    return equity, stats


def _position_cost(row, spot_val, sigma_val, leverage, cum_val, date):
    """Delta-neutral cost (total premium $) for a candidate contract.  Returns
    (cost, n, entry_price) or (inf, 0, 0) when row is None."""
    if row is None:
        return float("inf"), 0.0, 0.0
    entry = float(row["px_last"])
    T = max((row["expiry"] - date).days / 365.25, 1 / 365)
    delta = bs_delta(float(spot_val), float(row["strike"]), T, R_RF, sigma_val)
    n = leverage * cum_val / (max(delta, 0.01) * 100 * float(spot_val))
    return n * 100 * entry, n, entry


def simulate_ensemble(returns,
                      tsla_calls, tsla_spot, tsla_lookup, tsla_sigma,
                      tsll_calls, tsll_spot, tsll_lookup, tsll_sigma,
                      moneyness_bucket):
    """On each roll day price both a TSLA call and a TSLL call (same bucket).
    Enter whichever provides delta-neutral coverage at lower total premium.
    Fall back to the other if one underlying has no contract available.
    """
    cum_tsll = (1 + returns["TSLL"]).cumprod()
    base_equity = 2.0 - cum_tsll
    equity = pd.Series(index=returns.index, dtype=float)
    position = None   # adds "underlying": "tsla"|"tsll" key vs regular simulate
    option_pnl = 0.0
    stats = {
        "roll_attempts": 0, "fills": 0,
        "fills_tsla": 0, "fills_tsll": 0,
        "misses": 0, "miss_dates": [], "hedge_cost": 0.0,
    }

    def mtm(pos, date):
        spot = tsla_spot if pos["underlying"] == "tsla" else tsll_spot
        lkp  = tsla_lookup if pos["underlying"] == "tsla" else tsll_lookup
        if date > pos["expiry"]:
            return max(float(spot.loc[date]) - pos["strike"], 0.0)
        px = lkp.get((pos["raw_id"], date))
        if px is not None and not pd.isna(px):
            return float(px)
        return pos["price"]

    for d in returns.index:
        held_dte = (position["expiry"] - d).days if position is not None else -1
        need_roll = (position is None) or (held_dte < ROLL_DTE)

        if need_roll:
            if position is not None:
                option_pnl += position["n"] * 100 * (mtm(position, d) - position["price"])
                position = None

            stats["roll_attempts"] += 1
            cum_val = float(cum_tsll.loc[d])
            sig_a = float(tsla_sigma.loc[d]) if d in tsla_sigma.index else 0.5
            sig_b = float(tsll_sigma.loc[d]) if d in tsll_sigma.index else 0.5

            row_a = select_contract(tsla_calls, tsla_spot, d, moneyness_bucket,
                                    TARGET_DTE, max_dte=MAX_DTE)
            row_b = select_contract(tsll_calls, tsll_spot, d, moneyness_bucket,
                                    TARGET_DTE, max_dte=MAX_DTE)

            cost_a, n_a, entry_a = _position_cost(
                row_a, tsla_spot.loc[d], sig_a, TSLL_LEVER, cum_val, d)
            cost_b, n_b, entry_b = _position_cost(
                row_b, tsll_spot.loc[d], sig_b, 1.0, cum_val, d)

            # Pick cheaper; fall back to available if one is missing
            if cost_a <= cost_b and row_a is not None:
                chosen, row, n, entry, ul = "tsla", row_a, n_a, entry_a, "tsla"
                stats["fills_tsla"] += 1
            elif row_b is not None:
                chosen, row, n, entry, ul = "tsll", row_b, n_b, entry_b, "tsll"
                stats["fills_tsll"] += 1
            elif row_a is not None:
                chosen, row, n, entry, ul = "tsla", row_a, n_a, entry_a, "tsla"
                stats["fills_tsla"] += 1
            else:
                chosen = None

            if chosen is not None:
                position = {
                    "underlying": ul, "raw_id": row["raw_id"],
                    "strike": float(row["strike"]), "expiry": row["expiry"],
                    "n": n, "price": entry,
                }
                stats["fills"] += 1
                stats["hedge_cost"] += n * 100 * entry
            else:
                stats["misses"] += 1
                stats["miss_dates"].append(d)
        else:
            if position is not None:
                px = mtm(position, d)
                option_pnl += position["n"] * 100 * (px - position["price"])
                position["price"] = px

        equity.loc[d] = base_equity.loc[d] + option_pnl

    return equity, stats


def build_row(name, equity, stats, bench_cagr, n_years, show_fill):
    eq_ret = equity.pct_change().dropna()
    row = summarize(equity, eq_ret, name)

    if stats is not None:
        ann_cost = stats["hedge_cost"] / n_years
        benefit = row["CAGR"] - bench_cagr
        row["Hedge Cost $"] = round(stats["hedge_cost"], 4)
        row["Hedge Eff."] = round(benefit / ann_cost, 3) if ann_cost > 0 else float("nan")
    else:
        row["Hedge Cost $"] = "--"
        row["Hedge Eff."] = "--"

    if show_fill and stats is not None:
        rate = stats["fills"] / stats["roll_attempts"] if stats["roll_attempts"] else 0
        row["Fill Rate"] = f"{rate:.1%}"
        row["Miss Days"] = stats["misses"]
    else:
        row["Fill Rate"] = "--"
        row["Miss Days"] = "--"

    return row


def make_equity_figure(curves, out_dir):
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, equity in curves.items():
        ls = "--" if name == "Benchmark" else "-"
        c = "grey" if name == "Benchmark" else None
        equity.plot(ax=ax, label=name, linestyle=ls, color=c)
    ax.axhline(1.0, color="lightgrey", linestyle=":", linewidth=0.8)
    ax.set_title(f"CBA: Equity Curves ({START.date()} → {END.date()})")
    ax.set_ylabel("Equity (start = 1.0)")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_dir / "equity_curves.png", dpi=150)
    plt.close(fig)


def make_drawdown_figure(curves, out_dir):
    fig, ax = plt.subplots(figsize=(11, 5))
    for name, equity in curves.items():
        dd = equity / equity.cummax() - 1
        ls = "--" if name == "Benchmark" else "-"
        c = "grey" if name == "Benchmark" else None
        dd.plot(ax=ax, label=name, linestyle=ls, color=c)
    ax.set_title("CBA: Drawdown Comparison")
    ax.set_ylabel("Drawdown from peak")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "drawdown_comparison.png", dpi=150)
    plt.close(fig)


def make_fill_rate_figure(fill_stats_b, out_dir):
    buckets = list(fill_stats_b.keys())
    fill_rates = [
        s["fills"] / s["roll_attempts"] * 100 if s["roll_attempts"] else 0
        for s in fill_stats_b.values()
    ]
    miss_days = [s["misses"] for s in fill_stats_b.values()]

    fig, ax1 = plt.subplots(figsize=(7, 5))
    bars = ax1.bar(buckets, fill_rates, color=["#f4a261", "#e76f51", "#e9c46a"])
    ax1.set_ylabel("Fill Rate (%)")
    ax1.set_ylim(0, 105)
    ax1.set_title("Strategy B (TSLL Calls): Fill Rate by Moneyness Bucket")
    for bar, rate in zip(bars, fill_rates):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{rate:.1f}%", ha="center", va="bottom", fontsize=10)

    ax2 = ax1.twinx()
    ax2.plot(buckets, miss_days, marker="o", color="navy", linewidth=2, label="Miss Days")
    ax2.set_ylabel("Miss Days (count)")
    ax2.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(out_dir / "tsll_fill_rate.png", dpi=150)
    plt.close(fig)


def main():
    # ── Load spot & LETF returns ─────────────────────────────────────────
    tsll_df = load_tsll()
    r_tsll = tsll_df.set_index("Date")["Close"].pct_change().dropna()
    r_tsll = r_tsll[(r_tsll.index >= START) & (r_tsll.index <= END)]
    returns = r_tsll.rename("TSLL").to_frame()
    n_years = (returns.index[-1] - returns.index[0]).days / 365.25

    tsla_spot = (load_tsla_underlying()
                 .set_index("Date")["Close"]
                 .reindex(returns.index).ffill())
    tsll_spot = (tsll_df.set_index("Date")["Close"]
                 .reindex(returns.index).ffill())

    # ── Load options ─────────────────────────────────────────────────────
    tsla_calls = load_tsla_calls()
    tsll_calls = load_tsll_calls()

    tsla_lookup = tsla_calls.set_index(["raw_id", "date"])["px_last"].to_dict()
    tsll_lookup = tsll_calls.set_index(["raw_id", "date"])["px_last"].to_dict()

    # Realised-vol series for BS delta (one per underlying)
    tsla_sigma = (tsla_spot.pct_change()
                  .rolling(VOL_WINDOW).std() * (252 ** 0.5)).ffill().bfill()
    tsll_sigma = (tsll_spot.pct_change()
                  .rolling(VOL_WINDOW).std() * (252 ** 0.5)).ffill().bfill()

    # ── Benchmark: naked short TSLL ──────────────────────────────────────
    cum = (1 + returns["TSLL"]).cumprod()
    bench_raw = 2.0 - cum
    bench_eq = bench_raw / bench_raw.iloc[0]
    bench_cagr = metric_cagr(bench_eq)

    print("=" * 82)
    print("COST-BENEFIT ANALYSIS: Short TSLL + Long Call Hedge  [DELTA-NEUTRAL SIZING]")
    print(f"Window : {START.date()} → {END.date()}  ({n_years:.1f} years)")
    print(f"Params : DTE 0–{MAX_DTE}d, roll @ {ROLL_DTE}d  |  Target DTE {TARGET_DTE}d  |  "
          f"r={R_RF:.0%}, vol window={VOL_WINDOW}d")
    print("Strategy A: n = (2×cum_tsll)/(Δ_tsla×100×tsla_spot)  "
          "[TSLL lever=2x vs TSLA]")
    print("Strategy B: n = (1×cum_tsll)/(Δ_tsll×100×tsll_spot)  "
          "[direct TSLL delta hedge]")
    print("=" * 82)

    curves = {"Benchmark": bench_eq}
    rows = [build_row("Benchmark", bench_eq, None, bench_cagr, n_years, show_fill=False)]
    fill_stats_b = {}

    for bucket in BUCKETS:
        print(f"  Simulating A-{bucket} ...", flush=True)
        eq_a, stats_a = simulate(returns, tsla_calls, tsla_spot, tsla_lookup,
                                 bucket, tsla_sigma, leverage_factor=TSLL_LEVER)
        eq_a = eq_a / eq_a.iloc[0]
        curves[f"A-{bucket}"] = eq_a
        rows.append(build_row(f"A-{bucket}", eq_a, stats_a,
                              bench_cagr, n_years, show_fill=False))

        print(f"  Simulating B-{bucket} ...", flush=True)
        eq_b, stats_b = simulate(returns, tsll_calls, tsll_spot, tsll_lookup,
                                 bucket, tsll_sigma, leverage_factor=1.0)
        eq_b = eq_b / eq_b.iloc[0]
        curves[f"B-{bucket}"] = eq_b
        rows.append(build_row(f"B-{bucket}", eq_b, stats_b,
                              bench_cagr, n_years, show_fill=True))
        fill_stats_b[bucket] = stats_b

    # ── Ensemble: cheapest-on-the-day (TSLA vs TSLL) ────────────────────
    ens_stats = {}
    for bucket in BUCKETS:
        print(f"  Simulating Ensemble-{bucket} ...", flush=True)
        eq_e, stats_e = simulate_ensemble(
            returns,
            tsla_calls, tsla_spot, tsla_lookup, tsla_sigma,
            tsll_calls, tsll_spot, tsll_lookup, tsll_sigma,
            bucket)
        eq_e = eq_e / eq_e.iloc[0]
        curves[f"Ens-{bucket}"] = eq_e
        rows.append(build_row(f"Ens-{bucket}", eq_e, stats_e,
                              bench_cagr, n_years, show_fill=True))
        ens_stats[bucket] = stats_e

    print()
    metrics_df = pd.DataFrame(rows)
    print(metrics_df.to_string(index=False))

    # ── Strategy B fill detail ───────────────────────────────────────────
    print("\nStrategy B — TSLL call fill detail:")
    for bucket, s in fill_stats_b.items():
        rate = s["fills"] / s["roll_attempts"] * 100 if s["roll_attempts"] else 0
        print(f"  {bucket:>10s}: {s['fills']}/{s['roll_attempts']} fills "
              f"({rate:.1f}%)  |  {s['misses']} miss days")

    print("\nEnsemble — pick selection:")
    for bucket, s in ens_stats.items():
        tot = s["fills_tsla"] + s["fills_tsll"]
        print(f"  {bucket:>10s}: TSLA {s['fills_tsla']}/{tot} "
              f"({s['fills_tsla']/tot*100:.0f}%)  TSLL {s['fills_tsll']}/{tot} "
              f"({s['fills_tsll']/tot*100:.0f}%)  |  {s['misses']} miss days")

    # ── Figures & results ────────────────────────────────────────────────
    make_equity_figure(curves, OUT_DIR)
    make_drawdown_figure(curves, OUT_DIR)
    make_fill_rate_figure(fill_stats_b, OUT_DIR)

    for name, equity in curves.items():
        slug = name.lower().replace(" ", "_").replace("%", "pct")
        equity.rename("equity").to_csv(RESULTS_DIR / f"equity_{slug}.csv")

    print(f"\nFigures  → {OUT_DIR}/")
    print(f"Equity CSVs → {RESULTS_DIR}/")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "results.txt"):
        main()
