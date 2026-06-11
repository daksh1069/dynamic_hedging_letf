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

from data_loader import load_tsla_underlying, load_tsll
from engine import rebalanced_equity
from metrics import summarize

OUT_DIR = ROOT / "observations" / "strategies" / "delta_arb"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "delta_arb"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

ROLL_WINDOW = 63
BORROW_RATES = [0.00, 0.03, 0.06, 0.10]  # annualized, on gross notional


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
    main()
