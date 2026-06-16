"""
EDA #1 -- TSLA spot vs. TSLT / TSLL leveraged ETFs.

Covers:
  - Summary statistics (returns, volatility, skew/kurtosis)
  - Tracking performance: realized leverage (regression slope) vs TSLA
  - Rolling 63-day realized leverage
  - Volatility-decay validation (actual vs. naive 2x cumulative return)
  - Drawdown analysis for long and (unhedged) short LETF positions

Tables are printed to the console; figures are saved to observations/eda/.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from data_loader import load_tsla_underlying, load_tslt, load_tsll
from capture import capture_stdout

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "observations" / "eda"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def to_returns(df: pd.DataFrame, col: str) -> pd.Series:
    return df.set_index("Date")[col].pct_change().dropna()


def summary_row(r: pd.Series, name: str) -> dict:
    return {
        "Ticker": name,
        "N": len(r),
        "Start": r.index.min().date(),
        "End": r.index.max().date(),
        "Mean Daily Ret": r.mean(),
        "Daily Vol": r.std(),
        "Ann. Vol": r.std() * np.sqrt(252),
        "Min": r.min(),
        "Max": r.max(),
        "Skew": r.skew(),
        "Kurtosis": r.kurtosis(),
    }


def tracking_table(r_under: pd.Series, r_letf: pd.Series, name: str) -> pd.DataFrame:
    df = pd.concat([r_under.rename("under"), r_letf.rename("letf")], axis=1).dropna()
    slope, intercept = np.polyfit(df["under"], df["letf"], 1)
    corr = df["under"].corr(df["letf"])
    print(f"{name} vs TSLA: n={len(df):,}  beta={slope:.3f}  alpha={intercept:.5f}  corr={corr:.4f}")
    return df


def rolling_beta(df: pd.DataFrame, window: int = 63) -> pd.Series:
    cov = df["under"].rolling(window).cov(df["letf"])
    var = df["under"].rolling(window).var()
    return cov / var


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = equity / running_max - 1
    return dd.min()


def short_equity(r_letf: pd.Series) -> pd.Series:
    """Equity curve of an unhedged short LETF position (1 = initial capital)."""
    long_equity = (1 + r_letf).cumprod()
    return 2 - long_equity


def decay_ratio(r_under: pd.Series, r_letf: pd.Series, leverage: float) -> pd.DataFrame:
    df = pd.concat([r_under.rename("under"), r_letf.rename("letf")], axis=1).dropna()
    actual = (1 + df["letf"]).cumprod()
    naive = (1 + leverage * df["under"]).cumprod()
    return pd.DataFrame({"actual": actual, "naive_2x": naive, "ratio": actual / naive})


def cagr(equity: pd.Series) -> float:
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    return equity.iloc[-1] ** (1 / n_years) - 1


def main():
    tsla = load_tsla_underlying()[["Date", "Close"]].rename(columns={"Close": "TSLA"})
    tslt = load_tslt()[["Date", "Close"]].rename(columns={"Close": "TSLT"})
    tsll = load_tsll()[["Date", "Close"]].rename(columns={"Close": "TSLL"})

    r_tsla = to_returns(tsla, "TSLA")
    r_tslt = to_returns(tslt, "TSLT")
    r_tsll = to_returns(tsll, "TSLL")

    # ── Summary statistics ──────────────────────────────────────────────
    print("=" * 78)
    print("SUMMARY STATISTICS (daily returns)")
    print("=" * 78)
    stats_df = pd.DataFrame([
        summary_row(r_tsla, "TSLA"),
        summary_row(r_tslt, "TSLT"),
        summary_row(r_tsll, "TSLL"),
    ])
    print(stats_df.to_string(index=False))

    # ── Tracking performance vs TSLA ────────────────────────────────────
    print("\n" + "=" * 78)
    print("TRACKING PERFORMANCE vs TSLA (full sample, daily returns)")
    print("=" * 78)
    df_tslt = tracking_table(r_tsla, r_tslt, "TSLT")
    df_tsll = tracking_table(r_tsla, r_tsll, "TSLL")

    # ── Rolling 63d realized leverage ───────────────────────────────────
    beta_tslt = rolling_beta(df_tslt)
    beta_tsll = rolling_beta(df_tsll)

    fig, ax = plt.subplots(figsize=(10, 5))
    beta_tslt.plot(ax=ax, label="TSLT (rolling 63d beta)")
    beta_tsll.plot(ax=ax, label="TSLL (rolling 63d beta)")
    ax.axhline(2.0, color="grey", linestyle="--", label="Target leverage = 2x")
    ax.set_title("63-Day Rolling Realized Leverage vs TSLA")
    ax.set_ylabel("Beta")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "rolling_realized_leverage.png", dpi=150)
    plt.close(fig)

    # ── Volatility decay: actual vs naive 2x ────────────────────────────
    print("\n" + "=" * 78)
    print("VOLATILITY DECAY: actual cumulative return vs. naive 2x TSLA")
    print("=" * 78)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, (r_letf, name) in zip(axes, [(r_tslt, "TSLT"), (r_tsll, "TSLL")]):
        dr = decay_ratio(r_tsla, r_letf, leverage=2.0)
        cagr_actual = cagr(dr["actual"])
        cagr_naive = cagr(dr["naive_2x"])
        cagr_under = cagr((1 + r_tsla.loc[dr.index]).cumprod())
        print(f"{name}: CAGR actual={cagr_actual:+.2%}  naive 2x={cagr_naive:+.2%}  "
              f"underlying={cagr_under:+.2%}  decay (actual - naive 2x)={cagr_actual - cagr_naive:+.2%}/yr  "
              f"final ratio={dr['ratio'].iloc[-1]:.3f}")
        dr[["actual", "naive_2x"]].plot(ax=ax)
        ax.set_title(f"{name}: Actual vs Naive 2x TSLA (rebased)")
        ax.set_ylabel("Cumulative growth of $1")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "decay_actual_vs_naive2x.png", dpi=150)
    plt.close(fig)

    # ── Drawdowns: long underlying vs short LETF (unhedged) ─────────────
    print("\n" + "=" * 78)
    print("MAX DRAWDOWN")
    print("=" * 78)
    eq_tsla = (1 + r_tsla).cumprod()
    eq_tslt_long = (1 + r_tslt).cumprod()
    eq_tsll_long = (1 + r_tsll).cumprod()
    eq_tslt_short = short_equity(r_tslt)
    eq_tsll_short = short_equity(r_tsll)

    print(f"TSLA  (long)        : {max_drawdown(eq_tsla):+.2%}")
    print(f"TSLT  (long)        : {max_drawdown(eq_tslt_long):+.2%}")
    print(f"TSLL  (long)        : {max_drawdown(eq_tsll_long):+.2%}")
    print(f"TSLT  (short, naked): {max_drawdown(eq_tslt_short):+.2%}")
    print(f"TSLL  (short, naked): {max_drawdown(eq_tsll_short):+.2%}")

    fig, ax = plt.subplots(figsize=(10, 5))
    (eq_tslt_short / eq_tslt_short.cummax() - 1).plot(ax=ax, label="Short TSLT (unhedged)")
    (eq_tsll_short / eq_tsll_short.cummax() - 1).plot(ax=ax, label="Short TSLL (unhedged)")
    ax.set_title("Drawdown of an Unhedged Short LETF Position")
    ax.set_ylabel("Drawdown")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "short_letf_drawdown.png", dpi=150)
    plt.close(fig)

    # ── Rebased price chart since TSLT inception ────────────────────────
    common_start = tslt["Date"].min()
    rebased = pd.DataFrame({
        "TSLA": tsla.set_index("Date")["TSLA"],
        "TSLT": tslt.set_index("Date")["TSLT"],
        "TSLL": tsll.set_index("Date")["TSLL"],
    })
    rebased = rebased[rebased.index >= common_start].dropna()
    rebased = rebased / rebased.iloc[0] * 100

    fig, ax = plt.subplots(figsize=(10, 5))
    rebased.plot(ax=ax)
    ax.set_title(f"Rebased Price (=100) Since TSLT Inception ({common_start.date()})")
    ax.set_ylabel("Index level")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "rebased_prices_since_tslt_inception.png", dpi=150)
    plt.close(fig)

    print(f"\nFigures saved to {OUT_DIR}/")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "market_data_eda.txt"):
        main()
