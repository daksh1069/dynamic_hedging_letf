"""Contract-selection helper for the convexity-protection backtest.

Reuses the moneyness bucket definitions from scripts/eda/options_eda.py.
"""
import numpy as np
import pandas as pd
from scipy.stats import norm


def bs_delta(S: float, K: float, T_years: float, r: float, sigma: float) -> float:
    """Black-Scholes N(d1) delta for a European call.

    Returns a value in (0, 1). Clipped to [0.01, 1.0] to avoid infinite sizing.
    """
    if T_years <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 1.0 if S > K else 0.01
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T_years) / (sigma * np.sqrt(T_years))
    return float(max(norm.cdf(d1), 0.01))

MONEYNESS_RANGES = {
    "ATM": (0.95, 1.05),
    "10% OTM": (1.05, 1.15),
    "20% OTM": (1.15, 1.25),
}


def select_contract(calls_df: pd.DataFrame, spot: pd.Series, date: pd.Timestamp,
                     moneyness_bucket: str, target_dte: int, max_dte: int = None):
    """Pick the live contract whose moneyness falls in `moneyness_bucket` and
    whose DTE is closest to `target_dte`, as of `date`.

    `calls_df` is the long-format table from load_tsla_calls() or
    load_tsll_calls() (columns: raw_id, expiry, strike, date, px_last, ...).
    `spot` is the underlying's close, indexed by date (TSLA for TSLA calls,
    TSLL for TSLL calls). `max_dte` optionally caps the DTE filter.
    Returns the selected row (pd.Series), or None if no contract qualifies.
    """
    lo, hi = MONEYNESS_RANGES[moneyness_bucket]
    day = calls_df[calls_df["date"] == date]
    if day.empty:
        return None

    s = spot.loc[date]
    moneyness = day["strike"] / s
    dte = (day["expiry"] - date).dt.days
    mask = (
        (moneyness >= lo) & (moneyness < hi)
        & (dte > 0)
        & day["px_last"].notna() & (day["px_last"] > 0)
    )
    if max_dte is not None:
        mask = mask & (dte <= max_dte)
    candidates = day[mask]
    if candidates.empty:
        return None

    dte_c = (candidates["expiry"] - date).dt.days
    idx = (dte_c - target_dte).abs().idxmin()
    return candidates.loc[idx]


def contract_price(calls_df: pd.DataFrame, raw_id: str, date: pd.Timestamp):
    """px_last of `raw_id` on `date`, or None if not found."""
    row = calls_df[(calls_df["raw_id"] == raw_id) & (calls_df["date"] == date)]
    if row.empty or pd.isna(row["px_last"].iloc[0]):
        return None
    return float(row["px_last"].iloc[0])
