"""
EDA #2 -- TSLA call-option universe: coverage and moneyness exploration.

Covers:
  - Overall coverage: contracts, date range, expiry range, strike range
  - Data quality: missing px_last / px_volume
  - Moneyness (strike / TSLA spot) and DTE distributions
  - Contract availability by (moneyness bucket x DTE bucket) -- the buckets
    used to pick representative contracts for the short-TSLL + long-call
    backtest, restricted to TSLL's available date range (2022-08-09 onward)

Tables are printed to the console; figures are saved to observations/eda/.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data_loader import load_tsla_underlying, load_tsla_calls, load_tsll
from capture import capture_stdout

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "observations" / "eda"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MONEYNESS_BINS = [0, 0.95, 1.05, 1.15, 1.25, np.inf]
MONEYNESS_LABELS = ["ITM", "ATM", "10% OTM", "20% OTM", "Far OTM"]

DTE_BINS = [0, 45, 90, 180, np.inf]
DTE_LABELS = ["15-45", "45-90", "90-180", "180+"]


def main():
    calls = load_tsla_calls()
    spot = load_tsla_underlying()[["Date", "Close"]].rename(columns={"Date": "date", "Close": "spot"})
    tsll_start = load_tsll()["Date"].min()

    # ── Overall coverage ────────────────────────────────────────────────
    print("=" * 78)
    print("OVERALL COVERAGE")
    print("=" * 78)
    n_contracts = calls["raw_id"].nunique()
    print(f"Contracts            : {n_contracts:,}")
    print(f"Total rows           : {len(calls):,}")
    print(f"Trading dates        : {calls['date'].min().date()} -> {calls['date'].max().date()}")
    print(f"Expiries             : {calls['expiry'].min().date()} -> {calls['expiry'].max().date()}")
    print(f"Strikes              : {calls['strike'].min():.2f} -> {calls['strike'].max():.2f}")

    # ── Data quality ─────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("DATA QUALITY")
    print("=" * 78)
    n_total = len(calls)
    n_px_missing = calls["px_last"].isna().sum()
    n_vol_missing = calls["px_volume"].isna().sum()
    n_px_nonpos = (calls["px_last"] <= 0).sum()
    print(f"px_last  missing     : {n_px_missing:,} / {n_total:,}  ({n_px_missing / n_total:.1%})")
    print(f"px_last  <= 0        : {n_px_nonpos:,} / {n_total:,}  ({n_px_nonpos / n_total:.1%})")
    print(f"px_volume missing    : {n_vol_missing:,} / {n_total:,}  ({n_vol_missing / n_total:.1%})")

    # ── Moneyness / DTE ──────────────────────────────────────────────────
    df = calls.dropna(subset=["px_last"]).merge(spot, on="date", how="inner")
    df = df[df["px_last"] > 0]
    df["moneyness"] = df["strike"] / df["spot"]
    df["dte"] = (df["expiry"] - df["date"]).dt.days
    df = df[df["dte"] > 0]
    df["moneyness_bucket"] = pd.cut(df["moneyness"], bins=MONEYNESS_BINS, labels=MONEYNESS_LABELS)
    df["dte_bucket"] = pd.cut(df["dte"], bins=DTE_BINS, labels=DTE_LABELS)

    print("\n" + "=" * 78)
    print(f"MONEYNESS x DTE COVERAGE -- avg # contracts/day, TSLL period ({tsll_start.date()} onward)")
    print("=" * 78)
    df_tsll = df[df["date"] >= tsll_start]
    daily_counts = (
        df_tsll.groupby(["date", "moneyness_bucket", "dte_bucket"], observed=True)
        .size()
        .reset_index(name="n")
    )
    coverage = (
        daily_counts.groupby(["moneyness_bucket", "dte_bucket"], observed=True)["n"]
        .mean()
        .unstack("dte_bucket")
        .reindex(index=MONEYNESS_LABELS, columns=DTE_LABELS)
    )
    print(coverage.round(1).to_string())

    n_days_total = df_tsll["date"].nunique()
    print(f"\n(Trading days in TSLL period: {n_days_total:,})")

    # ── Plots ────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    axes[0].hist(df["dte"], bins=50)
    axes[0].set_title("DTE Distribution (all contract-days)")
    axes[0].set_xlabel("Days to expiry")

    axes[1].hist(df["moneyness"], bins=50, range=(0.5, 2.0))
    axes[1].axvline(1.0, color="grey", linestyle="--", label="ATM")
    axes[1].set_title("Moneyness Distribution (strike / spot)")
    axes[1].set_xlabel("Strike / Spot")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "options_dte_moneyness_dist.png", dpi=150)
    plt.close(fig)

    focus = df[
        df["moneyness_bucket"].isin(["ATM", "10% OTM", "20% OTM"])
        & df["dte_bucket"].isin(["15-45", "45-90", "90-180"])
    ]
    daily = (
        focus.groupby(["date", "moneyness_bucket"], observed=True)
        .size()
        .unstack("moneyness_bucket")
        .reindex(columns=["ATM", "10% OTM", "20% OTM"])
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    daily.plot(ax=ax)
    ax.axvline(tsll_start, color="grey", linestyle="--", label="TSLL inception")
    ax.set_title("Available Call Contracts/Day by Moneyness (DTE 15-180)")
    ax.set_ylabel("# contracts")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "options_coverage_by_moneyness.png", dpi=150)
    plt.close(fig)

    print(f"\nFigures saved to {OUT_DIR}/")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "options_eda.txt"):
        main()
