"""
Cross-strategy comparison: combined risk-metrics table + overlaid equity
curves for all three strategies --

  1. Double-Short (naked short TSLL, buy & hold)
  2. Delta-Adjusted Arbitrage (long h*TSLA + short TSLL, dynamic beta hedge)
  3. Convexity Protection (short TSLL + long TSLA call(s)), 4 variants

All curves are rebased to 1.0 over the common overlapping date range (the
shortest backtest window among the saved equity curves -- Strategy 2's,
which starts ~63 trading days later due to its rolling-beta warm-up) for an
apples-to-apples comparison.

Risk-metrics table printed to console; figure saved to
observations/strategies/comparison.png.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from metrics import summarize

OUT_DIR = ROOT / "observations" / "strategies"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results"

CURVES = {
    "1: Double-Short (Buy & Hold)": RESULTS_DIR / "double_short" / "equity.csv",
    "2: Delta-Adjusted Arb (Dynamic Beta)": RESULTS_DIR / "delta_arb" / "equity.csv",
    "3: Convexity -- ATM": RESULTS_DIR / "convexity_protection" / "equity_atm.csv",
    "3: Convexity -- 10% OTM": RESULTS_DIR / "convexity_protection" / "equity_otm10.csv",
    "3: Convexity -- 20% OTM": RESULTS_DIR / "convexity_protection" / "equity_otm20.csv",
    "3: Convexity -- Spread": RESULTS_DIR / "convexity_protection" / "equity_spread.csv",
}


def main():
    raw = {name: pd.read_csv(path, index_col=0, parse_dates=True)["equity"]
           for name, path in CURVES.items()}

    common_start = max(s.index.min() for s in raw.values())
    common_end = min(s.index.max() for s in raw.values())
    print(f"Common comparison window: {common_start.date()} -> {common_end.date()}\n")

    rebased = {}
    for name, s in raw.items():
        s = s.loc[(s.index >= common_start) & (s.index <= common_end)]
        rebased[name] = s / s.iloc[0]

    print("=" * 78)
    print("CROSS-STRATEGY RISK METRICS (common window, rebased to 1.0)")
    print("=" * 78)
    rows = []
    for name, equity in rebased.items():
        eq_returns = equity.pct_change().dropna()
        rows.append(summarize(equity, eq_returns, name))
    metrics_df = pd.DataFrame(rows)
    print(metrics_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    fig, ax = plt.subplots(figsize=(11, 6))
    for name, equity in rebased.items():
        equity.plot(ax=ax, label=name)
    ax.axhline(1.0, color="grey", linestyle="--", linewidth=0.8)
    ax.set_title(f"Strategy Comparison: Equity Curves (rebased, {common_start.date()} -> {common_end.date()})")
    ax.set_ylabel("Equity (start = 1.0)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "comparison.png", dpi=150)
    plt.close(fig)

    print(f"\nFigure saved to {OUT_DIR / 'comparison.png'}")


if __name__ == "__main__":
    main()
