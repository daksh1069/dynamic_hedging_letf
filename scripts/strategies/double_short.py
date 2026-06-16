"""
Strategy 1 -- Double-Short (baseline): naked short TSLL.

Shorting $1 notional of TSLL is effectively a -2x bet on TSLA (TSLL's embedded
leverage), which is where the "double" comes from. This is the unhedged
baseline that Strategies 2 and 3 are compared against.

  - Primary: buy & hold short $1 TSLL from inception (no rebalancing).
    Equity can go negative -- margin wipeout if TSLA rallies hard.
  - Sensitivity: same -$1 short, but rebalanced back to -$1 notional at
    daily / weekly / monthly frequency, to show the impact of "rebalancing
    friction" / exposure drift.

Risk metrics are printed to the console; figures saved to
observations/strategies/double_short/. The buy & hold equity curve is saved
to results/double_short/equity.csv for the cross-strategy comparison.
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
from data_loader import load_tsll
from engine import buy_and_hold_equity, rebalanced_equity
from metrics import summarize, max_drawdown

OUT_DIR = ROOT / "observations" / "strategies" / "double_short"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "double_short"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def main():
    tsll = load_tsll()
    returns = tsll.set_index("Date")[["Close"]].rename(columns={"Close": "TSLL"}).pct_change().dropna()

    weights = {"TSLL": -1.0}
    equity_bh = buy_and_hold_equity(returns, weights)

    variants = {"Buy & Hold": equity_bh}
    for label, freq in [("Rebalanced Daily", "D"), ("Rebalanced Weekly", "W"), ("Rebalanced Monthly", "M")]:
        variants[label] = rebalanced_equity(returns, weights, freq=freq)

    print("=" * 78)
    print("STRATEGY 1 -- DOUBLE-SHORT (naked short TSLL): RISK METRICS")
    print("=" * 78)
    rows = []
    for name, equity in variants.items():
        eq_returns = equity.pct_change().dropna()
        rows.append(summarize(equity, eq_returns, name))
    metrics_df = pd.DataFrame(rows)
    print(metrics_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    n_negative = (equity_bh < 0).sum()
    print(f"\nBuy & Hold: equity goes negative (margin wipeout) on {n_negative:,} / "
          f"{len(equity_bh):,} days "
          f"(first on {equity_bh[equity_bh < 0].index.min().date() if n_negative else 'never'})")

    # ── Plots ────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, equity in variants.items():
        equity.plot(ax=ax, label=name)
    ax.axhline(0, color="grey", linestyle="--", linewidth=0.8)
    ax.set_title("Strategy 1 -- Double-Short TSLL: Equity Curves")
    ax.set_ylabel("Equity (start = 1.0)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "equity_curves.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5))
    dd = equity_bh / equity_bh.cummax() - 1
    dd.plot(ax=ax)
    ax.set_title(f"Strategy 1 -- Buy & Hold Drawdown (Max DD = {max_drawdown(equity_bh):.1%})")
    ax.set_ylabel("Drawdown")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "drawdown.png", dpi=150)
    plt.close(fig)

    equity_bh.rename("equity").to_csv(RESULTS_DIR / "equity.csv")
    print(f"\nFigures saved to {OUT_DIR}/")
    print(f"Equity curve saved to {RESULTS_DIR / 'equity.csv'}")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "results.txt"):
        main()
