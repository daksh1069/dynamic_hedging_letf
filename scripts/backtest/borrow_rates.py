"""
Approximate historical cost-to-borrow series for TSLA and TSLL.

We don't have Markit/IHS Securities Finance data (not in this institution's
WRDS subscription) or a downloadable export, so this is read off public
borrow-fee charts (companiesmarketcap.com) at quarterly granularity -- a
stated approximation, not measured daily data. Quarters before our earliest
chart-read data (2023 Q1) carry that quarter's rate backward, since we have
no data for that period (our backtests start Aug 2022).

TSLA stays in a tight ~0.25-0.55% band the entire time (solidly easy-to-
borrow) -- modeled as flat, since the variation is too small to matter.
TSLL swings from <1% in calm periods to 8-10% during TSLA-volatility spikes
(early 2024, mid 2024, early 2025, and a sustained climb into 2026) -- a
real, regime-dependent pattern, not noise -- modeled as a quarterly step
function.
"""
import pandas as pd

TSLA_RATE = 0.0040  # flat ~0.40%/yr, variation too small to model as time-varying

TSLL_QUARTERLY = {
    "2023Q1": 0.065, "2023Q2": 0.040, "2023Q3": 0.015, "2023Q4": 0.007,
    "2024Q1": 0.050, "2024Q2": 0.040, "2024Q3": 0.015, "2024Q4": 0.013,
    "2025Q1": 0.060, "2025Q2": 0.025, "2025Q3": 0.020, "2025Q4": 0.030,
    "2026Q1": 0.070, "2026Q2": 0.065,
}
_EARLIEST_QUARTER = "2023Q1"


def load_borrow_rates(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Daily TSLA/TSLL annualized borrow-rate series reindexed onto `dates`."""
    quarters = pd.PeriodIndex(dates, freq="Q").astype(str)
    tsll = pd.Series(
        [TSLL_QUARTERLY.get(q, TSLL_QUARTERLY[_EARLIEST_QUARTER]) for q in quarters],
        index=dates, name="TSLL",
    )
    tsla = pd.Series(TSLA_RATE, index=dates, name="TSLA")
    return pd.concat([tsla, tsll], axis=1)
