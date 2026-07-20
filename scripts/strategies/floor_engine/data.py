"""Market data assembly for the floor engine.

Wraps the shared loaders (scripts/eda/data_loader.py) and borrow series
(scripts/backtest/borrow_rates.py) into one MarketData object so every
engine function receives its inputs explicitly instead of via notebook
globals.
"""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from data_loader import (load_tsll, load_tsll_calls, load_tsll_puts,          # noqa: E402
                          load_tsla_underlying, load_tsla_calls)
from borrow_rates import load_borrow_rates                                     # noqa: E402


def _with_chain_columns(chain: pd.DataFrame, spot: pd.Series) -> pd.DataFrame:
    """Volume-filtered chain frame with dte / spot / moneyness columns."""
    out = chain[chain["px_volume"] > 0].copy()
    out = out[out["px_last"].notna() & (out["px_last"] > 0)]
    out["dte"]       = (pd.to_datetime(out["expiry"]) - pd.to_datetime(out["date"])).dt.days
    out["spot"]      = out["date"].map(spot)
    out["moneyness"] = out["strike"] / out["spot"]
    return out


@dataclass
class MarketData:
    """Everything the engine needs, loaded once."""
    tsll_spot:  pd.Series
    tsll_calls: pd.DataFrame          # full long-format call chain
    tsll_puts:  pd.DataFrame          # full long-format put chain
    tsll_cvol:  pd.DataFrame          # volume-filtered calls + dte/moneyness
    tsll_pvol:  pd.DataFrame          # volume-filtered puts + dte/moneyness
    call_lut:   dict                  # (raw_id, date) -> px_last
    put_lut:    dict
    sim_dates:  pd.DatetimeIndex      # first TSLL option date onward
    borrow:     pd.Series             # TSLL annualized borrow rate, daily
    # Lazily populated by load_lineage_extras() (only the lineage comparison
    # needs TSLA data):
    tsla_spot:  pd.Series = field(default=None, repr=False)
    tsla_calls: pd.DataFrame = field(default=None, repr=False)
    tsla_lut:   dict = field(default=None, repr=False)
    tsla_sigma: pd.Series = field(default=None, repr=False)
    tsll_sigma: pd.Series = field(default=None, repr=False)


def load_market_data() -> MarketData:
    """Load and assemble all TSLL-side inputs (the guaranteed engine is
    TSLL-only; TSLA extras are loaded separately for the lineage chart)."""
    tsll_spot  = load_tsll().set_index("Date")["Close"]
    tsll_calls = load_tsll_calls()
    tsll_puts  = load_tsll_puts()

    tsll_cvol = _with_chain_columns(tsll_calls, tsll_spot)
    tsll_pvol = _with_chain_columns(tsll_puts, tsll_spot)

    sim_dates = tsll_spot.index[tsll_spot.index >= tsll_cvol["date"].min()]

    return MarketData(
        tsll_spot=tsll_spot,
        tsll_calls=tsll_calls,
        tsll_puts=tsll_puts,
        tsll_cvol=tsll_cvol,
        tsll_pvol=tsll_pvol,
        call_lut=tsll_calls.set_index(["raw_id", "date"])["px_last"].to_dict(),
        put_lut=tsll_puts.set_index(["raw_id", "date"])["px_last"].to_dict(),
        sim_dates=sim_dates,
        borrow=load_borrow_rates(tsll_spot.index)["TSLL"],
    )


def load_lineage_extras(md: MarketData) -> MarketData:
    """Attach the TSLA-side data used only by the static-hybrid reproduction
    in the strategy lineage comparison."""
    md.tsla_spot  = (load_tsla_underlying().set_index("Date")["Close"]
                     .reindex(md.tsll_spot.index).ffill())
    md.tsla_calls = load_tsla_calls()
    md.tsla_lut   = md.tsla_calls.set_index(["raw_id", "date"])["px_last"].to_dict()
    md.tsla_sigma = (md.tsla_spot.pct_change().rolling(21).std() * 252 ** 0.5).ffill().bfill()
    md.tsll_sigma = (md.tsll_spot.pct_change().rolling(21).std() * 252 ** 0.5).ffill().bfill()
    return md
