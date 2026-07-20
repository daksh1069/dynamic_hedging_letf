"""Final figures for the drawdown-constrained convexity protection engine.

Every figure is self-documenting: titles carry the parameter set so no chart
depends on surrounding text. Figures are written to
observations/strategies/final/ and, when the directory exists, mirrored to
latex/figures/ so the report always embeds the current versions.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

from config import (LOSS_BUDGET, DD_LIMIT, GAIN_TRIGGER, COST_GATE,
                    master_bound, dial_bound)

ROOT      = Path(__file__).resolve().parents[3]
OBS_DIR   = ROOT / "observations" / "strategies" / "final"
LATEX_FIG = ROOT / "latex" / "figures"

plt.style.use("seaborn-v0_8-whitegrid")

_CFG = (f"loss budget l={LOSS_BUDGET:.0%}, drawdown limit d={DD_LIMIT:.1%}, "
        f"gain trigger g={GAIN_TRIGGER:.0%}, cost gate q={COST_GATE:.0%}, "
        f"bound={master_bound():.1%}")


def _save(fig, obs_name: str, latex_name: str = None) -> None:
    OBS_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(OBS_DIR / obs_name, dpi=150, bbox_inches="tight")
    if latex_name and LATEX_FIG.exists():
        fig.savefig(LATEX_FIG / latex_name, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_equity_floor_deployment(collar, collar_borrow, call_only) -> None:
    """Equity vs the active analytic floor, plus deployment, headline config."""
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                                    gridspec_kw={"height_ratios": [2, 1]})
    ax0.plot(collar.equity.index, collar.equity, color="seagreen", lw=1.5,
             label="Drawdown-Constrained Convexity Protection (Collar)")
    ax0.plot(collar_borrow.equity.index, collar_borrow.equity, color="darkgoldenrod",
             lw=1.3, label="Collar, with borrow costs")
    ax0.plot(call_only.equity.index, call_only.equity, color="steelblue", lw=1.0,
             alpha=0.7, label="Drawdown-Constrained Convexity Protection (Call)")
    ax0.plot(collar.diag.index, collar.diag["floor"], color="indianred", lw=1.0,
             ls="--", label="Active analytic floor (collar)")
    for _, cp in collar.checkpoints.iterrows():
        ax0.axvline(cp["date"], color="grey" if cp["type"] == "expiry" else "darkorange",
                    lw=0.5, alpha=0.4)
    ax0.set_ylabel("Equity (notional = 1)")
    ax0.set_title("Drawdown-Constrained Convexity Protection: Equity and Guaranteed Floor\n"
                  f"{_CFG}  |  grey vline = expiry checkpoint, orange = ceiling")
    ax0.legend(fontsize=9, loc="upper left")

    ax1.fill_between(collar_borrow.deployed_frac.index,
                     collar_borrow.deployed_frac * 100, color="darkgoldenrod", alpha=0.25)
    ax1.plot(collar_borrow.deployed_frac.index, collar_borrow.deployed_frac * 100,
             color="darkgoldenrod", lw=1.0, label="Collar, with borrow costs")
    ax1.plot(call_only.deployed_frac.index, call_only.deployed_frac * 100,
             color="steelblue", lw=0.9, alpha=0.8, label="Call variant")
    ax1.set_ylabel("Capital deployed (% of equity)")
    ax1.yaxis.set_major_formatter(mticker.PercentFormatter())
    ax1.legend(fontsize=9, loc="upper right")
    ax1.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    _save(fig, "final_equity_floor_deployment.png", "gf_equity_floor_deployment.png")


def plot_risk_dial(dial_df) -> None:
    """Risk dial frontier. dial_df indexed by x-label with Bound/CAGR/MaxDD."""
    fig, ax = plt.subplots(figsize=(9, 5))
    bx = dial_df["Bound"] * 100
    ax.plot(bx, dial_df["CAGR"] * 100, color="seagreen", marker="o", lw=1.6,
            label="Realized CAGR")
    ax.plot(bx, dial_df["MaxDD"].abs() * 100, color="indianred", marker="s",
            lw=1.6, ls="--", label="Realized |MaxDD|")
    ax.plot(bx, bx, color="grey", lw=0.9, ls=":", label="Guaranteed bound (reference)")
    for xv, r in dial_df.iterrows():
        ax.annotate(f"x={xv}", (r["Bound"] * 100, r["CAGR"] * 100),
                    textcoords="offset points", xytext=(6, 6), fontsize=8)
    ax.set_xlabel("Guaranteed MaxDD bound (%)")
    ax.set_ylabel("%")
    ax.set_title("Risk Dial Frontier: Drawdown-Constrained Convexity Protection (Collar)\n"
                 "x = l = d = g (loss budget = drawdown limit = gain trigger), "
                 f"bound = 2x/(1+x), cost gate q = {COST_GATE:.0%}, frictionless")
    ax.legend(fontsize=9)
    fig.tight_layout()
    _save(fig, "final_risk_dial.png", "gf_risk_dial.png")


def plot_lineage(eq_naked, eq_static, eq_call, eq_collar) -> None:
    """One equity axis from the naked short to the collar engine."""
    fig, ax = plt.subplots(figsize=(14, 6.5))
    ax.plot(eq_naked.index, eq_naked, color="#b0b0b0", lw=1.1,
            label="Naked Short TSLL")
    ax.plot(eq_static.index, eq_static, color="steelblue", lw=1.4,
            label="Static Convexity Protection (full notional)")
    ax.plot(eq_call.index, eq_call, color="darkorange", lw=1.4,
            label="Drawdown-Constrained Convexity Protection (Call)")
    ax.plot(eq_collar.index, eq_collar, color="seagreen", lw=1.7,
            label="Drawdown-Constrained Convexity Protection (Collar)")
    ax.axhline(1.0, color="black", lw=0.5)
    ax.set_ylabel("Equity (notional = 1)")
    ax.set_title("Convexity Protection Equity Curves, Frictionless: "
                 "Static vs. Drawdown-Constrained\n"
                 f"dynamic variants at {_CFG}")
    ax.legend(fontsize=9, loc="upper left")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    _save(fig, "final_lineage_equity_curves.png", "gf_lineage_equity_curves.png")
