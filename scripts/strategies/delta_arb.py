"""
Strategy 2 -- Delta-Adjusted Arbitrage: long h*TSLA + short $1 TSLL.

Sizing the long TSLA leg to TSLL's realized leverage on TSLA neutralizes most
of the day-to-day market exposure, leaving (mostly) the LETF's tracking
drag/decay -- this is what's meant to harvest "volatility decay" while also
shielding against macro tail risk (a TSLA rally that would blow up a naked
short TSLL is offset by the long TSLA leg).

  - Primary: dynamic hedge ratio h_t = rolling 63-day realized beta of TSLL
    vs TSLA (cov/var, same calc as the EDA's rolling_beta), lagged 1 day to
    avoid lookahead. Weights {"TSLL": -1, "TSLA": h_{t-1}}, rebalanced daily.
  - Sensitivity: static h = 2.0 (TSLL's nominal target leverage).
  - Sensitivity: daily borrow/financing cost on gross notional (|TSLL| +
    |TSLA|, ~2.8x), at a few annual rates -- this strategy's edge depends on
    being able to rebalance ~2.8x gross notional daily for free, which is
    optimistic (TSLL is often hard-to-borrow).
  - Real-data estimate: same idea, but using the actual TSLL borrow-fee
    series (scripts/backtest/borrow_rates.py, read off public charts) for
    the short TSLL leg, plus a separate flat assumed margin-loan rate for
    the long TSLA leg -- these are two different costs (short-borrow fee vs.
    margin interest on a long position), not one blended sensitivity rate.

Risk metrics are printed to the console; figures saved to
observations/strategies/delta_arb/. The dynamic-hedge equity curve is saved
to results/delta_arb/equity.csv for the cross-strategy comparison.
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
from data_loader import load_tsla_underlying, load_tsll
from engine import rebalanced_equity
from metrics import summarize
from borrow_rates import load_borrow_rates

OUT_DIR = ROOT / "observations" / "strategies" / "delta_arb"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "delta_arb"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ROLL_WINDOW = 63
BORROW_RATES = [0.00, 0.03, 0.06, 0.10]  # annualized, on gross notional -- assumed sensitivity bounds
TSLA_MARGIN_RATE = 0.065  # flat assumed margin-loan rate for the LONG TSLA leg (not a borrow fee --
                          # TSLA's real "cost to borrow" chart data is for shorting, irrelevant here)


def with_borrow_leg(returns_v: pd.DataFrame, weights, borrow_rate: float):
    """Add a synthetic "Borrow" leg charging `borrow_rate`/yr on gross notional
    (|TSLL| + |TSLA|), via rebalanced_equity's daily-rebalance machinery.
    """
    r = returns_v.copy()
    r["Borrow"] = borrow_rate / 252
    if isinstance(weights, dict):
        w = dict(weights)
        w["Borrow"] = -(abs(weights.get("TSLL", 0.0)) + abs(weights.get("TSLA", 0.0)))
    else:
        w = weights.copy()
        w["Borrow"] = -(w["TSLL"].abs() + w["TSLA"].abs())
    return r, w


def with_real_borrow_leg(returns_v: pd.DataFrame, weights, tsll_borrow_series: pd.Series,
                         tsla_margin_rate: float):
    """Like with_borrow_leg, but split into the two costs that actually apply:
    the real day-varying TSLL borrow-fee series (borrow_rates.py) on the
    short TSLL leg, and a separate flat assumed margin-loan rate on the long
    TSLA leg. These are economically different (short-borrow fee vs. margin
    interest on a long position) and shouldn't share one blended rate.
    """
    r = returns_v.copy()
    tsll_rate = tsll_borrow_series.reindex(r.index).ffill().bfill()
    r["BorrowTSLL"] = tsll_rate / 252
    r["MarginTSLA"] = tsla_margin_rate / 252
    if isinstance(weights, dict):
        w = dict(weights)
        w["BorrowTSLL"] = -abs(weights.get("TSLL", 0.0))
        w["MarginTSLA"] = -abs(weights.get("TSLA", 0.0))
    else:
        w = weights.copy()
        w["BorrowTSLL"] = -w["TSLL"].abs()
        w["MarginTSLA"] = -w["TSLA"].abs()
    return r, w


def main():
    tsla = load_tsla_underlying()[["Date", "Close"]].rename(columns={"Close": "TSLA"})
    tsll = load_tsll()[["Date", "Close"]].rename(columns={"Close": "TSLL"})

    r_tsla = tsla.set_index("Date")["TSLA"].pct_change()
    r_tsll = tsll.set_index("Date")["TSLL"].pct_change()
    returns = pd.concat([r_tsla, r_tsll], axis=1).dropna()
    returns.columns = ["TSLA", "TSLL"]

    # Rolling realized beta of TSLL vs TSLA, lagged 1 day to avoid lookahead.
    cov = returns["TSLA"].rolling(ROLL_WINDOW).cov(returns["TSLL"])
    var = returns["TSLA"].rolling(ROLL_WINDOW).var()
    beta = (cov / var).shift(1)

    weights_dyn = pd.DataFrame({"TSLL": -1.0, "TSLA": beta})
    valid = weights_dyn.dropna().index
    returns_v = returns.loc[valid]
    weights_dyn = weights_dyn.loc[valid]
    beta_v = beta.loc[valid]

    equity_dyn = rebalanced_equity(returns_v, weights_dyn, freq="D")
    equity_static = rebalanced_equity(returns_v, {"TSLL": -1.0, "TSLA": 2.0}, freq="D")

    variants = {
        "Dynamic Beta Hedge": equity_dyn,
        "Static 2x Hedge": equity_static,
    }

    gross_notional = 1.0 + beta_v.mean()   # |TSLL| + |TSLA|
    print("=" * 78)
    print("STRATEGY 2 -- DELTA-ADJUSTED ARBITRAGE (long h*TSLA + short TSLL): RISK METRICS")
    print("=" * 78)
    rows = []
    for name, equity in variants.items():
        eq_returns = equity.pct_change().dropna()
        rows.append(summarize(equity, eq_returns, name))
    metrics_df = pd.DataFrame(rows)
    print(metrics_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    print(f"\nDynamic hedge ratio h_t (rolling {ROLL_WINDOW}d beta, lagged 1d): "
          f"mean={beta_v.mean():.3f}  min={beta_v.min():.3f}  max={beta_v.max():.3f}")

    # ── Borrow-cost sensitivity (Dynamic Beta only) ───────────────────────
    # TSLL is often hard-to-borrow (HTB); cost charged on gross notional.
    print(f"\n{'─'*78}")
    print(f"BORROW-COST SENSITIVITY  (Dynamic Beta, gross notional ≈ {gross_notional:.2f}x)")
    print(f"{'─'*78}")
    borrow_rows = []
    for rate in BORROW_RATES:
        r_b, w_b = with_borrow_leg(returns_v, weights_dyn, rate)
        eq_b = rebalanced_equity(r_b, w_b, freq="D")
        eq_ret_b = eq_b.pct_change().dropna()
        row = summarize(eq_b, eq_ret_b, f"Borrow {rate:.0%}/yr")
        row["Annual Drag $"] = round(rate * gross_notional, 4)
        borrow_rows.append(row)
    borrow_df = pd.DataFrame(borrow_rows)
    print(borrow_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    print("\nNote: excludes transaction costs (~0.05-0.10% per rebalance × 252 days).")

    # ── Borrow cost: real TSLL series + assumed TSLA margin rate ──────────
    print(f"\n{'─'*78}")
    print("BORROW-COST: REAL TSLL BORROW-FEE SERIES + ASSUMED TSLA MARGIN RATE")
    print("(TSLL series is approximate -- read off public borrow-fee charts at quarterly")
    print(" granularity, see scripts/backtest/borrow_rates.py. TSLA leg uses a flat")
    print(f" assumed margin-loan rate ({TSLA_MARGIN_RATE:.1%}/yr) since that's financing a LONG")
    print(" position, not a short-borrow fee -- TSLA's real borrow-fee chart doesn't apply here.)")
    print(f"{'─'*78}")
    tsll_borrow_series = load_borrow_rates(returns_v.index)["TSLL"]
    r_real, w_real = with_real_borrow_leg(returns_v, weights_dyn, tsll_borrow_series, TSLA_MARGIN_RATE)
    eq_real = rebalanced_equity(r_real, w_real, freq="D")
    eq_ret_real = eq_real.pct_change().dropna()
    row_real = summarize(eq_real, eq_ret_real, "Real TSLL Borrow + TSLA Margin")
    row_real["Avg TSLL Rate"] = round(float(tsll_borrow_series.mean()), 4)
    row_real["TSLA Margin Rate"] = TSLA_MARGIN_RATE
    real_df = pd.DataFrame([row_real])
    print(real_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    # ── Plots ────────────────────────────────────────────────────────────
    baseline = pd.read_csv(ROOT / "results" / "double_short" / "equity.csv",
                            index_col=0, parse_dates=True)["equity"]
    baseline = baseline.reindex(equity_dyn.index).dropna()
    baseline = baseline / baseline.iloc[0]

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, equity in variants.items():
        equity.plot(ax=ax, label=name)
    baseline.plot(ax=ax, label="Strategy 1: Double-Short (Buy & Hold, rebased)", linestyle="--")
    ax.set_title("Strategy 2 -- Delta-Adjusted Arbitrage: Equity Curves")
    ax.set_ylabel("Equity (start = 1.0)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "equity_curves.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    beta_v.plot(ax=ax, label="Dynamic hedge ratio $h_t$")
    ax.axhline(2.0, color="grey", linestyle="--", label="Static 2x")
    ax.set_title(f"Strategy 2 -- Rolling {ROLL_WINDOW}-Day Realized Beta (TSLL vs TSLA), lagged 1d")
    ax.set_ylabel("Hedge ratio h")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "hedge_ratio.png", dpi=150)
    plt.close(fig)

    equity_dyn.rename("equity").to_csv(RESULTS_DIR / "equity.csv")
    print(f"\nFigures saved to {OUT_DIR}/")
    print(f"Equity curve saved to {RESULTS_DIR / 'equity.csv'}")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "results.txt"):
        main()
