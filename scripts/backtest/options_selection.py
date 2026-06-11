"""Contract-selection helper for the convexity-protection backtest.

Reuses the moneyness bucket definitions from scripts/eda/options_eda.py.
"""
import pandas as pd

MONEYNESS_RANGES = {
    "ATM": (0.95, 1.05),
    "10% OTM": (1.05, 1.15),
    "20% OTM": (1.15, 1.25),
}


def select_contract(calls_df: pd.DataFrame, spot: pd.Series, date: pd.Timestamp,
                     moneyness_bucket: str, target_dte: int):
    """Pick the live contract whose moneyness falls in `moneyness_bucket` and
    whose DTE is closest to `target_dte`, as of `date`.

    `calls_df` is the long-format table from load_tsla_calls() (columns:
    raw_id, expiry, strike, date, px_last, ...). `spot` is TSLA close,
    indexed by date. Returns the selected row (pd.Series), or None if no
    contract qualifies.
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
