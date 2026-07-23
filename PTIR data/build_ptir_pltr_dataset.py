"""Build the strategy-neutral PTIR–PLTR data-sharing package.

This exporter reads only the authoritative local market files used by the
validated V6.6–V6.9 research.  It does not import or execute a strategy engine.
All outputs are written under data/processed/ptir_shared/.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data/processed/ptir_shared"

PRICE_SOURCE = PROJECT_ROOT / "data/raw/market_prices/pltr_related_raw_prices.csv"
CLEAN_PRICE_CROSSCHECK = PROJECT_ROOT / "data/raw/market_prices/PTIR_clean_price_data.csv"
OPTION_OHLCV_SOURCE = PROJECT_ROOT / "data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet"
OPTION_UNIVERSE_SOURCE = PROJECT_ROOT / "data/raw/databento/pltr/pltr_call_universe_unique.parquet"
ATM_IV_SOURCE = PROJECT_ROOT / "data/processed/ptir/px_bt_with_iv.parquet"

SOURCE_FILES = [
    PRICE_SOURCE,
    CLEAN_PRICE_CROSSCHECK,
    OPTION_OHLCV_SOURCE,
    OPTION_UNIVERSE_SOURCE,
    ATM_IV_SOURCE,
]

MASTER_FILE = OUTPUT_DIR / "ptir_pltr_daily_master.csv"
ALIGNMENT_FILE = OUTPUT_DIR / "ptir_pltr_alignment_audit.csv"
OPTIONS_FILE = OUTPUT_DIR / "pltr_options_daily_long.parquet"
OPTIONS_SAMPLE_FILE = OUTPUT_DIR / "pltr_options_daily_sample.csv"
REFERENCE_FILE = OUTPUT_DIR / "pltr_atm35_reference_contracts.csv"
DICTIONARY_FILE = OUTPUT_DIR / "data_dictionary.md"
README_FILE = OUTPUT_DIR / "README.md"
VALIDATION_FILE = OUTPUT_DIR / "data_validation_report.csv"
MANIFEST_FILE = OUTPUT_DIR / "manifest.json"

REFERENCE_NOTICE = "REFERENCE SELECTION ONLY — teammate may construct a different option selector."
EQUITY_QUALITY_FLAG = "ADJUSTED_CLOSE_ONLY_OHLCV_UNAVAILABLE"
OPTION_MULTIPLIER = 100.0
RISK_FREE_RATE = 0.045


def relpath(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def require_sources() -> None:
    missing = [str(path) for path in SOURCE_FILES if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing authoritative local source files: {missing}")


def normalize_dates(values: pd.Series | pd.Index) -> pd.DatetimeIndex:
    dates = pd.to_datetime(values)
    if getattr(dates, "tz", None) is not None:
        dates = dates.tz_localize(None)
    return pd.DatetimeIndex(dates).normalize()


def load_equity_sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(PRICE_SOURCE, parse_dates=["Date"])
    expected = {"Date", "PLTR", "PTIR"}
    if not expected.issubset(raw.columns):
        raise ValueError(f"{relpath(PRICE_SOURCE)} lacks required columns {sorted(expected)}")
    raw = raw[["Date", "PLTR", "PTIR"]].copy()
    raw["Date"] = normalize_dates(raw["Date"])
    raw["PLTR"] = pd.to_numeric(raw["PLTR"], errors="coerce")
    raw["PTIR"] = pd.to_numeric(raw["PTIR"], errors="coerce")

    clean = pd.read_csv(CLEAN_PRICE_CROSSCHECK, parse_dates=["Date"])
    expected_clean = {"Date", "Underlying", "LETF"}
    if not expected_clean.issubset(clean.columns):
        raise ValueError(
            f"{relpath(CLEAN_PRICE_CROSSCHECK)} lacks required columns {sorted(expected_clean)}"
        )
    clean = clean[["Date", "Underlying", "LETF"]].copy()
    clean["Date"] = normalize_dates(clean["Date"])
    clean[["Underlying", "LETF"]] = clean[["Underlying", "LETF"]].apply(
        pd.to_numeric, errors="coerce"
    )
    return raw, clean


def validate_raw_equities(raw: pd.DataFrame, clean: pd.DataFrame) -> None:
    for ticker in ("PLTR", "PTIR"):
        observed = raw.loc[raw[ticker].notna(), ["Date", ticker]]
        if observed["Date"].duplicated().any():
            raise ValueError(f"Duplicate dates in {ticker} source series")
        if (observed[ticker] <= 0).any():
            raise ValueError(f"Nonpositive {ticker} source prices")
    if clean["Date"].duplicated().any():
        raise ValueError("Duplicate dates in clean PLTR/PTIR cross-check source")

    check = clean.merge(raw, on="Date", how="left", validate="one_to_one")
    if check[["PLTR", "PTIR"]].isna().any().any():
        raise ValueError("Clean cross-check dates are not fully represented in raw price source")
    pltr_error = float((check["Underlying"] - check["PLTR"]).abs().max())
    ptir_error = float((check["LETF"] - check["PTIR"]).abs().max())
    if pltr_error > 1e-12 or ptir_error > 1e-12:
        raise ValueError(
            f"Clean price cross-check mismatch: PLTR={pltr_error:.3e}, PTIR={ptir_error:.3e}"
        )


def build_alignment(raw: pd.DataFrame) -> pd.DataFrame:
    # The source has one common calendar column, but availability is audited
    # separately for each ticker so no missing date is silently discarded.
    frame = raw.copy().sort_values("Date", kind="mergesort").reset_index(drop=True)
    out = pd.DataFrame({"date": frame["Date"]})
    out["pltr_available"] = frame["PLTR"].notna()
    out["ptir_available"] = frame["PTIR"].notna()
    out["included_in_master"] = out["pltr_available"] & out["ptir_available"]
    out["exclusion_reason"] = np.select(
        [
            out["pltr_available"] & out["ptir_available"],
            ~out["pltr_available"] & out["ptir_available"],
            out["pltr_available"] & ~out["ptir_available"],
        ],
        ["INCLUDED", "PLTR_MISSING", "PTIR_MISSING"],
        default="BOTH_MISSING",
    )
    return out.sort_values("date", kind="mergesort").reset_index(drop=True)


def build_master(raw: pd.DataFrame) -> pd.DataFrame:
    common = raw.loc[raw["PLTR"].notna() & raw["PTIR"].notna()].copy()
    common = common.sort_values("Date", kind="mergesort").reset_index(drop=True)
    if common["Date"].duplicated().any():
        raise ValueError("Duplicate common dates before master construction")
    if (common[["PLTR", "PTIR"]] <= 0).any().any():
        raise ValueError("Invalid nonpositive close in common price data")

    n = len(common)
    nan = pd.Series(np.full(n, np.nan), dtype="float64")
    master = pd.DataFrame(
        {
            "date": common["Date"],
            "pltr_open": nan.copy(),
            "pltr_high": nan.copy(),
            "pltr_low": nan.copy(),
            "pltr_close": common["PLTR"].astype(float),
            # The source notebook used yfinance auto_adjust=True and retained
            # only Close.  Therefore the one available price is both the local
            # close field and the adjusted-close representation.
            "pltr_adj_close": common["PLTR"].astype(float),
            "pltr_volume": nan.copy(),
            "ptir_open": nan.copy(),
            "ptir_high": nan.copy(),
            "ptir_low": nan.copy(),
            "ptir_close": common["PTIR"].astype(float),
            "ptir_adj_close": common["PTIR"].astype(float),
            "ptir_volume": nan.copy(),
        }
    )
    master["pltr_return_1d"] = master["pltr_close"] / master["pltr_close"].shift(1) - 1
    master["ptir_return_1d"] = master["ptir_close"] / master["ptir_close"].shift(1) - 1
    master["pltr_return_5d"] = master["pltr_close"] / master["pltr_close"].shift(5) - 1
    master["pltr_return_20d"] = master["pltr_close"] / master["pltr_close"].shift(20) - 1
    master["pltr_realized_vol_20d"] = (
        master["pltr_return_1d"].rolling(20).std(ddof=1) * math.sqrt(252)
    )
    master["ptir_expected_2x_return"] = 2 * master["pltr_return_1d"]
    master["ptir_tracking_difference"] = (
        master["ptir_return_1d"] - master["ptir_expected_2x_return"]
    )
    master["both_prices_available"] = True
    master["data_quality_flag"] = EQUITY_QUALITY_FLAG
    return master


def load_option_sources() -> tuple[pd.DataFrame, pd.DataFrame]:
    ohlcv = pd.read_parquet(OPTION_OHLCV_SOURCE).copy()
    required_ohlcv = {"date", "symbol", "close", "volume"}
    if not required_ohlcv.issubset(ohlcv.columns):
        raise ValueError(f"Option OHLCV lacks columns {sorted(required_ohlcv)}")
    ohlcv["date"] = normalize_dates(ohlcv["date"])
    ohlcv["symbol"] = ohlcv["symbol"].astype(str)
    ohlcv["close"] = pd.to_numeric(ohlcv["close"], errors="coerce")
    ohlcv["volume"] = pd.to_numeric(ohlcv["volume"], errors="coerce")
    if ohlcv.duplicated(["date", "symbol"]).any():
        raise ValueError("Duplicate (date, symbol) rows in canonical option OHLCV")

    universe = pd.read_parquet(OPTION_UNIVERSE_SOURCE).copy()
    required_universe = {
        "raw_symbol", "strike", "expiration", "instrument_class", "underlying"
    }
    if not required_universe.issubset(universe.columns):
        raise ValueError(f"Option universe lacks columns {sorted(required_universe)}")
    universe["raw_symbol"] = universe["raw_symbol"].astype(str)
    universe["expiration"] = normalize_dates(universe["expiration"])
    universe["strike"] = pd.to_numeric(universe["strike"], errors="coerce")
    if universe["raw_symbol"].duplicated().any():
        raise ValueError("Duplicate raw symbols in option universe")
    if not universe["instrument_class"].eq("C").all():
        raise ValueError("Validated option universe is expected to contain calls only")
    if not universe["underlying"].eq("PLTR").all():
        raise ValueError("Validated option universe contains a non-PLTR underlying")
    return ohlcv, universe


def build_options_long(
    raw: pd.DataFrame, ohlcv: pd.DataFrame, universe: pd.DataFrame
) -> pd.DataFrame:
    definitions = universe[
        ["raw_symbol", "expiration", "strike", "instrument_class"]
    ].copy()
    merged = ohlcv.merge(
        definitions,
        left_on="symbol",
        right_on="raw_symbol",
        how="left",
        validate="many_to_one",
        indicator=True,
    )
    if not merged["_merge"].eq("both").all():
        missing = merged.loc[merged["_merge"] != "both", "symbol"].nunique()
        raise ValueError(f"{missing} option symbols lack validated definitions")
    merged = merged.drop(columns=["_merge", "raw_symbol"])

    pltr_map = raw.set_index("Date")["PLTR"]
    out = pd.DataFrame(
        {
            "date": merged["date"],
            "option_symbol": merged["symbol"],
            "expiration": merged["expiration"],
            "strike": merged["strike"].astype(float),
            "option_type": merged["instrument_class"].map({"C": "call", "P": "put"}),
            "close": merged["close"].astype(float),
            "volume": merged["volume"].astype(float),
        }
    )
    out["daily_dollar_volume"] = out["close"] * out["volume"] * OPTION_MULTIPLIER
    out["dte"] = (out["expiration"] - out["date"]).dt.days.astype("int64")
    out["underlying_close"] = out["date"].map(pltr_map).astype(float)
    out["moneyness"] = out["strike"] / out["underlying_close"] - 1

    # The canonical DataBento files contain prices, volume, and definitions,
    # but no vendor IV or Greeks.  Null float columns make that absence explicit
    # instead of silently substituting ATM model values for every contract.
    for column in ["implied_volatility", "delta", "gamma", "vega", "theta"]:
        out[column] = pd.Series(np.full(len(out), np.nan), dtype="float64")
    out["data_source"] = (
        "DataBento OPRA.PILLAR OHLCV-1d aggregate + local validated call definitions; "
        "IV/Greeks not supplied"
    )
    out["price_available"] = out["close"].notna() & out["close"].gt(0)
    out["liquidity_available"] = (
        out["price_available"] & out["volume"].notna() & out["volume"].gt(0)
    )
    return out.sort_values(["date", "option_symbol"], kind="mergesort").reset_index(drop=True)


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_delta(spot: float, strike: float, years: float, sigma: float) -> float:
    if not all(np.isfinite([spot, strike, years, sigma])):
        return np.nan
    if spot <= 0 or strike <= 0 or sigma <= 0 or years <= 0:
        return np.nan
    d1 = (
        math.log(spot / strike)
        + (RISK_FREE_RATE + 0.5 * sigma * sigma) * years
    ) / (sigma * math.sqrt(years))
    return normal_cdf(d1)


def build_atm35_reference(
    raw: pd.DataFrame, ohlcv: pd.DataFrame, universe: pd.DataFrame
) -> pd.DataFrame:
    definitions = universe[["raw_symbol", "strike", "expiration"]]
    master = ohlcv.merge(
        definitions,
        left_on="symbol",
        right_on="raw_symbol",
        how="inner",
        validate="many_to_one",
    )
    master["dte"] = (master["expiration"] - master["date"]).dt.days
    master = master.loc[(master["dte"] > 0) & (master["close"] > 0)].copy()

    option_dates = pd.DatetimeIndex(sorted(ohlcv["date"].unique()), name="date")
    raw_indexed = raw.set_index("Date")
    px = raw_indexed.reindex(option_dates)[["PLTR"]].ffill()
    pltr_lag = px["PLTR"].shift(1)
    master["selection_input_underlying_close_t_minus_1"] = master["date"].map(pltr_lag)
    master = master.loc[
        master["selection_input_underlying_close_t_minus_1"].notna()
    ].copy()
    master["moneyness_lag"] = (
        master["strike"] / master["selection_input_underlying_close_t_minus_1"] - 1
    )
    master["daily_dollar_volume"] = master["close"] * master["volume"] * OPTION_MULTIPLIER
    master = master.sort_values(["symbol", "date"], kind="mergesort")
    master["lagged_median_dollar_volume_20obs"] = master.groupby(
        "symbol", sort=False
    )["daily_dollar_volume"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=10).median()
    )
    master = master.sort_values(["date", "symbol"], kind="mergesort").reset_index(drop=True)
    eligible = master.loc[master["lagged_median_dollar_volume_20obs"] >= 50_000].copy()

    ladder = [
        (0, "L0_preferred_ATM35_DTE28_42", 28, 42, -0.03, 0.03, 35.0, 0.0),
        (1, "L1_fallback_ATM18_DTE15_22", 15, 22, -0.03, 0.03, 18.0, 0.0),
    ]
    picks: list[pd.DataFrame] = []
    for level, label, dte_lo, dte_hi, mny_lo, mny_hi, target_dte, target_mny in ladder:
        subset = eligible.loc[
            eligible["dte"].between(dte_lo, dte_hi)
            & eligible["moneyness_lag"].between(mny_lo, mny_hi)
        ].copy()
        if subset.empty:
            continue
        subset["selection_score"] = (
            (subset["dte"] - target_dte).abs() / max(target_dte, 1.0)
            + (subset["moneyness_lag"] - target_mny).abs() / 0.05
        )
        best = subset.loc[subset.groupby("date")["selection_score"].idxmin()].copy()
        best["fallback_level"] = level
        best["fallback_label"] = label
        picks.append(best)

    selected_columns = [
        "symbol", "expiration", "strike", "dte", "close", "volume",
        "daily_dollar_volume", "selection_input_underlying_close_t_minus_1",
        "lagged_median_dollar_volume_20obs", "fallback_level", "fallback_label",
    ]
    if picks:
        candidates = pd.concat(picks, ignore_index=True)
        candidates = candidates.sort_values(["date", "fallback_level"], kind="mergesort")
        selected = candidates.groupby("date", sort=True).first()[selected_columns]
    else:
        selected = pd.DataFrame(columns=selected_columns)
        selected.index.name = "date"

    ref = pd.DataFrame(index=option_dates).join(selected, how="left")
    ref["underlying_close"] = px["PLTR"]

    iv_source = pd.read_parquet(ATM_IV_SOURCE)
    if "pltr_atm_iv" not in iv_source.columns:
        raise ValueError(f"{relpath(ATM_IV_SOURCE)} lacks pltr_atm_iv")
    iv_source.index = normalize_dates(iv_source.index)
    ref["implied_volatility"] = iv_source["pltr_atm_iv"].reindex(option_dates).shift(1)
    ref["modeled_delta"] = [
        bs_call_delta(s, k, d / 365.0, sigma)
        for s, k, d, sigma in zip(
            ref["underlying_close"], ref["strike"], ref["dte"], ref["implied_volatility"]
        )
    ]
    ref["selection_available"] = ref["symbol"].notna() & ref["close"].gt(0)
    ref["reference_notice"] = REFERENCE_NOTICE
    ref = ref.reset_index().rename(
        columns={
            "symbol": "selected_symbol",
            "close": "option_close",
        }
    )
    return ref[
        [
            "date", "selected_symbol", "expiration", "strike", "dte",
            "underlying_close", "selection_input_underlying_close_t_minus_1",
            "option_close", "volume", "daily_dollar_volume",
            "lagged_median_dollar_volume_20obs", "implied_volatility",
            "modeled_delta", "fallback_level", "fallback_label",
            "selection_available", "reference_notice",
        ]
    ].sort_values("date", kind="mergesort").reset_index(drop=True)


def max_formula_error(actual: pd.Series, expected: pd.Series) -> float:
    if not actual.isna().equals(expected.isna()):
        return float("inf")
    differences = (actual - expected).abs().dropna()
    return 0.0 if differences.empty else float(differences.max())


def build_validation_report(
    raw: pd.DataFrame,
    clean: pd.DataFrame,
    master: pd.DataFrame,
    alignment: pd.DataFrame,
    options: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(name: str, passed: bool, observed: Any, expected: str, notes: str = "") -> None:
        rows.append(
            {
                "check_name": name,
                "passed": bool(passed),
                "observed_value": observed,
                "expected_condition": expected,
                "notes": notes,
            }
        )

    pltr = raw.loc[raw["PLTR"].notna(), ["Date", "PLTR"]]
    ptir = raw.loc[raw["PTIR"].notna(), ["Date", "PTIR"]]
    add("duplicate_date_count_pltr_daily", pltr["Date"].duplicated().sum() == 0,
        int(pltr["Date"].duplicated().sum()), "equals 0")
    add("duplicate_date_count_ptir_daily", ptir["Date"].duplicated().sum() == 0,
        int(ptir["Date"].duplicated().sum()), "equals 0")
    add("duplicate_date_count_master", master["date"].duplicated().sum() == 0,
        int(master["date"].duplicated().sum()), "equals 0")
    increasing = bool(master["date"].is_monotonic_increasing and master["date"].is_unique)
    add("master_dates_strictly_increasing", increasing, increasing, "True")
    add("missing_pltr_close_count", master["pltr_close"].isna().sum() == 0,
        int(master["pltr_close"].isna().sum()), "equals 0")
    add("missing_ptir_close_count", master["ptir_close"].isna().sum() == 0,
        int(master["ptir_close"].isna().sum()), "equals 0")
    nonpositive = int((master[["pltr_close", "ptir_close"]] <= 0).sum().sum())
    add("nonpositive_close_price_count", nonpositive == 0, nonpositive, "equals 0")
    negative_volume = int((master[["pltr_volume", "ptir_volume"]].stack() < 0).sum())
    add("negative_volume_count", negative_volume == 0, negative_volume, "equals 0",
        "Equity volume is unavailable and remains NaN; no negative observed values")

    expected_pltr_1d = master["pltr_close"] / master["pltr_close"].shift(1) - 1
    expected_ptir_1d = master["ptir_close"] / master["ptir_close"].shift(1) - 1
    return_error = max(
        max_formula_error(master["pltr_return_1d"], expected_pltr_1d),
        max_formula_error(master["ptir_return_1d"], expected_ptir_1d),
    )
    add("return_formula_maximum_error", return_error <= 1e-12, return_error, "<= 1e-12")
    error_5d = max_formula_error(
        master["pltr_return_5d"], master["pltr_close"] / master["pltr_close"].shift(5) - 1
    )
    add("five_day_return_formula_maximum_error", error_5d <= 1e-12, error_5d, "<= 1e-12")
    error_20d = max_formula_error(
        master["pltr_return_20d"], master["pltr_close"] / master["pltr_close"].shift(20) - 1
    )
    add("twenty_day_return_formula_maximum_error", error_20d <= 1e-12, error_20d, "<= 1e-12")
    expected_rv = expected_pltr_1d.rolling(20).std(ddof=1) * math.sqrt(252)
    error_rv = max_formula_error(master["pltr_realized_vol_20d"], expected_rv)
    add("realized_volatility_formula_maximum_error", error_rv <= 1e-12, error_rv, "<= 1e-12")
    expected_2x = 2 * master["pltr_return_1d"]
    error_2x = max_formula_error(master["ptir_expected_2x_return"], expected_2x)
    add("ptir_expected_2x_formula_maximum_error", error_2x <= 1e-12, error_2x, "<= 1e-12")
    expected_tracking = master["ptir_return_1d"] - master["ptir_expected_2x_return"]
    error_tracking = max_formula_error(master["ptir_tracking_difference"], expected_tracking)
    add("tracking_difference_formula_maximum_error", error_tracking <= 1e-12,
        error_tracking, "<= 1e-12")

    ptir_only = int(((~alignment["pltr_available"]) & alignment["ptir_available"]).sum())
    pltr_only = int((alignment["pltr_available"] & (~alignment["ptir_available"])).sum())
    common = int(alignment["included_in_master"].sum())
    add("ptir_only_date_count", True, ptir_only, ">= 0")
    add("pltr_only_date_count", True, pltr_only, ">= 0")
    add("common_date_count", common == len(master), common, f"equals master rows ({len(master)})")
    first = master["date"].min().date().isoformat()
    last = master["date"].max().date().isoformat()
    add("first_common_date", True, first, "reported")
    add("last_common_date", True, last, "reported")

    future_terms = ("future", "forward_return", "next_return", "lead_return", "t_plus")
    future_cols = [c for c in master.columns if any(term in c.lower() for term in future_terms)]
    add("no_future_return_columns_present", not future_cols, json.dumps(future_cols), "empty list")
    strategy_terms = (
        "strategy", "nav", "pnl", "signal", "policy", "governor", "hedge_quantity",
        "hedge_ratio", "position_quantity", "drawdown_action",
    )
    strategy_cols = [c for c in master.columns if any(term in c.lower() for term in strategy_terms)]
    add("no_strategy_output_columns_present", not strategy_cols, json.dumps(strategy_cols), "empty list")

    option_duplicates = int(options.duplicated(["date", "option_symbol"]).sum())
    add("option_date_symbol_duplicate_count", option_duplicates == 0, option_duplicates, "equals 0")
    expected_dte = (options["expiration"] - options["date"]).dt.days
    dte_error = int((options["dte"] - expected_dte).abs().max())
    add("option_dte_consistency_check", dte_error == 0, dte_error, "maximum absolute error equals 0")
    types = sorted(options["option_type"].dropna().unique().tolist())
    add("option_type_consistency_check", types == ["call"], json.dumps(types), '["call"]',
        "The validated local project option library contains calls only")

    clean_check = clean.merge(raw, on="Date", how="left", validate="one_to_one")
    clean_error = max(
        float((clean_check["Underlying"] - clean_check["PLTR"]).abs().max()),
        float((clean_check["LETF"] - clean_check["PTIR"]).abs().max()),
    )
    add("clean_price_source_crosscheck", clean_error <= 1e-12, clean_error, "<= 1e-12")
    add("adjusted_close_equals_local_close", bool(
        master["pltr_adj_close"].equals(master["pltr_close"])
        and master["ptir_adj_close"].equals(master["ptir_close"])
    ), True, "True", "Source used yfinance auto_adjust=True and retained only Close")
    return pd.DataFrame(rows)


def table_date_range(frame: pd.DataFrame, column: str = "date") -> dict[str, str] | None:
    if column not in frame.columns or frame.empty:
        return None
    dates = pd.to_datetime(frame[column]).dropna()
    if dates.empty:
        return None
    return {"first": dates.min().date().isoformat(), "last": dates.max().date().isoformat()}


def write_readme(
    master: pd.DataFrame,
    alignment: pd.DataFrame,
    options: pd.DataFrame,
    reference: pd.DataFrame,
) -> None:
    pltr_only = int((alignment["pltr_available"] & ~alignment["ptir_available"]).sum())
    ptir_only = int((~alignment["pltr_available"] & alignment["ptir_available"]).sum())
    readme = f"""# Strategy-neutral PTIR–PLTR shared data

## Purpose

PTIR is the GraniteShares 2x Long PLTR Daily ETF. PLTR is Palantir Technologies Inc., the underlying common stock. This package contains aligned market observations and a separate local PLTR call-option library. It contains no strategy signal, position, NAV, P&L, optimized state, or investment recommendation.

## Coverage

- Common PTIR/PLTR daily rows: **{len(master):,}**
- Daily master range: **{master['date'].min().date()} through {master['date'].max().date()}**
- PLTR-only source dates excluded from the master: **{pltr_only:,}**
- PTIR-only source dates excluded from the master: **{ptir_only:,}**
- PLTR option rows: **{len(options):,}**
- PLTR option range: **{options['date'].min().date()} through {options['date'].max().date()}**
- ATM35 reference rows: **{len(reference):,}**

## Files

- `ptir_pltr_daily_master.csv`: one row per common valid PTIR/PLTR date.
- `ptir_pltr_alignment_audit.csv`: union-date availability and explicit inclusion reason.
- `pltr_options_daily_long.parquet`: one row per date per validated PLTR call contract.
- `pltr_options_daily_sample.csv`: deterministic first 500 sorted option rows for inspection only.
- `pltr_atm35_reference_contracts.csv`: informational ATM35 reference selection; not a universal selector.
- `data_dictionary.md`: column lineage, units, timing safety, formulas, and missing-value meanings.
- `data_validation_report.csv`: mandatory reproducibility and data-quality checks.
- `manifest.json`: sizes, shapes, sources, date ranges, and SHA-256 checksums.
- `build_shared_dataset.py`: deterministic local exporter.

## Authoritative local sources

1. `data/raw/market_prices/pltr_related_raw_prices.csv`, columns `Date`, `PLTR`, and `PTIR`. This is the exact close-price file loaded by the validated V6.6–V6.9 engines.
2. `data/raw/market_prices/PTIR_clean_price_data.csv`, columns `Date`, `Underlying`, and `LETF`, used as a strict equality cross-check.
3. `data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet`, canonical local DataBento call OHLCV rows.
4. `data/raw/databento/pltr/pltr_call_universe_unique.parquet`, validated call definitions (`raw_symbol`, `strike`, `expiration`, `instrument_class`, `underlying`).
5. `data/processed/ptir/px_bt_with_iv.parquet`, column `pltr_atm_iv`, used only for the lagged modeled IV and Delta in the ATM35 reference file.

No replacement data were downloaded.

## Important equity-data limitation

The source notebook downloaded yfinance data using `auto_adjust=True` and retained only the `Close` field. Therefore `pltr_close`/`ptir_close` are adjusted closing series, and their `*_adj_close` columns contain the same values. Open, high, low, and volume are not present in the validated local equity source and remain blank (`NaN`). They were not fabricated or downloaded from a different source.

## Return definitions

- One-day return: close divided by the preceding included trading-date close, minus one.
- Five- and twenty-day PLTR returns: close divided by the close 5 or 20 included sessions earlier, minus one.
- Twenty-day realized volatility: sample standard deviation (`ddof=1`) of the last 20 one-day PLTR returns, annualized by `sqrt(252)`.
- Expected PTIR 2x return: two times the same-date PLTR one-day return.
- Tracking difference: PTIR one-day return minus expected 2x PLTR return.

Warm-up observations remain `NaN`. No return is backfilled, forward-filled, or replaced with zero.

## Trading-timing warning

> A feature calculated using date t closing prices cannot be used to earn date t close-to-close return. For a strategy executed at date t close, the feature must be based on information available through t-1 unless the strategy explicitly models a later execution time.

The primary master is a research data table, not a pre-lagged trading feature table. Users must apply their own lag consistent with their execution assumptions.

## Missing-data treatment

The master uses only dates with both closes. Every source date is retained in the alignment audit. No price is forward-filled or backfilled in the daily master. Structural lookback gaps and unavailable equity OHLCV fields remain `NaN`.

## Option-data structure

The Parquet file contains the project’s validated **call-only** DataBento library. Price and volume are local vendor-derived aggregate fields. Contract IV and Greeks are not supplied by the canonical source, so `implied_volatility`, `delta`, `gamma`, `vega`, and `theta` are explicitly null in the long file. `liquidity_available` means a positive close and positive same-date volume; it is not a tradability recommendation and is not safe as a t-close decision input.

The ATM35 file is labeled `{REFERENCE_NOTICE}` It reproduces the existing deterministic reference convention: target 35 DTE, preferred 28–42 DTE and ±3% lagged moneyness, 20-observation lagged median dollar volume of at least $50,000, then the existing ATM18 fallback. Its IV is lagged modeled ATM IV, not vendor contract IV.

## Python loading example

```python
import pandas as pd

df = pd.read_csv(
    "data/processed/ptir_shared/ptir_pltr_daily_master.csv",
    parse_dates=["date"],
)

df = df.sort_values("date").set_index("date")

print(df.head())
print(df.tail())
print(df.isna().sum())
```

```python
options = pd.read_parquet(
    "data/processed/ptir_shared/pltr_options_daily_long.parquet"
)
```

## Simple R loading example

```r
daily <- read.csv("data/processed/ptir_shared/ptir_pltr_daily_master.csv")
daily$date <- as.Date(daily$date)
daily <- daily[order(daily$date), ]

# Requires the arrow package for Parquet:
options <- arrow::read_parquet(
  "data/processed/ptir_shared/pltr_options_daily_long.parquet"
)
```

## Known limitations

- Equity OHLC and volume are unavailable locally.
- Close and adjusted close cannot be separated because the local download retained only auto-adjusted Close.
- The option library ends before the daily equity master.
- DataBento option bars are the project’s existing aggregated OHLCV representation, not an official closing auction or NBBO snapshot.
- The long option file contains calls only because puts were not validated for this project.
- The long option file has no contract-specific vendor IV or Greeks.
- The ATM35 reference file is informational and embeds one existing selection convention; another researcher may construct a different selector.

## No strategy claim

This dataset does not contain a profitable strategy, confirmed alpha, investment advice, or a recommendation to buy, sell, short, or hedge PTIR or PLTR.
"""
    README_FILE.write_text(readme, encoding="utf-8")


def write_data_dictionary(
    master: pd.DataFrame,
    alignment: pd.DataFrame,
    options: pd.DataFrame,
    reference: pd.DataFrame,
    validation: pd.DataFrame,
) -> None:
    # tuple: definition, units, source, classification, formula, lookback,
    # safe-for-t-close, missing interpretation
    docs: dict[str, dict[str, tuple[str, str, str, str, str, str, str, str]]] = {
        "ptir_pltr_daily_master.csv": {},
        "ptir_pltr_alignment_audit.csv": {},
        "pltr_options_daily_long.parquet": {},
        "pltr_atm35_reference_contracts.csv": {},
        "data_validation_report.csv": {},
    }

    m = docs["ptir_pltr_daily_master.csv"]
    m["date"] = ("Trading-session date", "date", relpath(PRICE_SOURCE)+": Date", "raw", "", "none", "Yes", "Never missing")
    for ticker in ("pltr", "ptir"):
        source_col = ticker.upper()
        for field in ("open", "high", "low"):
            m[f"{ticker}_{field}"] = (f"{ticker.upper()} {field} price; unavailable locally", "USD/share", "not available in validated source", "raw placeholder", "", "none", "No", "Always NaN because source retained adjusted close only")
        m[f"{ticker}_close"] = (f"{ticker.upper()} local auto-adjusted closing price", "USD/share", f"{relpath(PRICE_SOURCE)}: {source_col}", "raw", "", "none", "No; date-t close is not known before that close", "Missing dates excluded from master")
        m[f"{ticker}_adj_close"] = (f"{ticker.upper()} adjusted close; equal to local close because yfinance auto_adjust=True", "USD/share", f"{relpath(PRICE_SOURCE)}: {source_col}", "raw alias", f"{ticker}_adj_close = {ticker}_close", "none", "No", "Missing dates excluded from master")
        m[f"{ticker}_volume"] = (f"{ticker.upper()} share volume; unavailable locally", "shares", "not available in validated source", "raw placeholder", "", "none", "No", "Always NaN")
    m["pltr_return_1d"] = ("PLTR close-to-close one-session return", "decimal return", "derived from master", "derived", "pltr_close / pltr_close.shift(1) - 1", "1 prior included session", "No; safe from t+1 onward", "First row is NaN")
    m["ptir_return_1d"] = ("PTIR close-to-close one-session return", "decimal return", "derived from master", "derived", "ptir_close / ptir_close.shift(1) - 1", "1 prior included session", "No; safe from t+1 onward", "First row is NaN")
    m["pltr_return_5d"] = ("PLTR five-session close return", "decimal return", "derived from master", "derived", "pltr_close / pltr_close.shift(5) - 1", "5 prior included sessions", "No; safe from t+1 onward", "First 5 rows are NaN")
    m["pltr_return_20d"] = ("PLTR twenty-session close return", "decimal return", "derived from master", "derived", "pltr_close / pltr_close.shift(20) - 1", "20 prior included sessions", "No; safe from t+1 onward", "First 20 rows are NaN")
    m["pltr_realized_vol_20d"] = ("Annualized 20-session realized volatility, sample standard deviation", "annualized decimal volatility", "derived from master", "derived", "rolling_std(pltr_return_1d, 20, ddof=1) * sqrt(252)", "20 valid one-day returns", "No; safe from t+1 onward", "First 20 rows are NaN")
    m["ptir_expected_2x_return"] = ("Mechanical twice-PLTR daily return comparator", "decimal return", "derived from master", "derived", "2 * pltr_return_1d", "1 prior included session", "No; safe from t+1 onward", "NaN when PLTR return is NaN")
    m["ptir_tracking_difference"] = ("PTIR return minus the mechanical 2x PLTR comparator", "decimal return", "derived from master", "derived", "ptir_return_1d - ptir_expected_2x_return", "1 prior included session", "No; safe from t+1 onward", "NaN when either input return is NaN")
    m["both_prices_available"] = ("Whether both source closes exist", "boolean", "derived from source availability", "derived", "pltr_close.notna() and ptir_close.notna()", "none", "Yes", "Always True in common-date master")
    m["data_quality_flag"] = ("Human-readable structural data limitation", "text", "exporter", "derived metadata", "constant adjusted-close-only warning", "none", "Yes", "Never missing")

    a = docs["ptir_pltr_alignment_audit.csv"]
    a["date"] = ("Union source date", "date", relpath(PRICE_SOURCE)+": Date", "raw", "", "none", "Yes", "Never missing")
    a["pltr_available"] = ("PLTR close exists on date", "boolean", relpath(PRICE_SOURCE)+": PLTR", "derived availability", "PLTR.notna()", "none", "Yes", "Never missing")
    a["ptir_available"] = ("PTIR close exists on date", "boolean", relpath(PRICE_SOURCE)+": PTIR", "derived availability", "PTIR.notna()", "none", "Yes", "Never missing")
    a["included_in_master"] = ("Both closes exist and date is included", "boolean", "derived", "derived", "pltr_available and ptir_available", "none", "Yes", "Never missing")
    a["exclusion_reason"] = ("Explicit inclusion/exclusion category", "text", "derived", "derived", "INCLUDED / PLTR_MISSING / PTIR_MISSING / BOTH_MISSING", "none", "Yes", "Never missing")

    o = docs["pltr_options_daily_long.parquet"]
    o["date"] = ("Option-bar session date", "date", relpath(OPTION_OHLCV_SOURCE)+": date", "vendor-derived raw", "", "none", "Yes", "Never missing")
    o["option_symbol"] = ("OPRA raw option symbol", "identifier", relpath(OPTION_OHLCV_SOURCE)+": symbol", "vendor raw", "", "none", "Yes", "Never missing")
    o["expiration"] = ("Contract expiration date", "date", relpath(OPTION_UNIVERSE_SOURCE)+": expiration", "vendor definition", "", "none", "Yes", "Never missing")
    o["strike"] = ("Call strike price", "USD/share", relpath(OPTION_UNIVERSE_SOURCE)+": strike", "vendor definition", "", "none", "Yes", "Never missing")
    o["option_type"] = ("Contract type", "text", relpath(OPTION_UNIVERSE_SOURCE)+": instrument_class", "vendor definition mapped", "C -> call", "none", "Yes", "Never missing; calls only")
    o["close"] = ("Project canonical aggregated daily option close", "USD/share", relpath(OPTION_OHLCV_SOURCE)+": close", "vendor-derived raw", "", "none", "No; known after date-t bar completes", "Missing means no price; source currently complete")
    o["volume"] = ("Aggregated daily contracts traded", "contracts", relpath(OPTION_OHLCV_SOURCE)+": volume", "vendor-derived raw", "", "none", "No; date-t completed volume is not available before close", "Missing means volume unavailable")
    o["daily_dollar_volume"] = ("Same-date option premium turnover", "USD", "derived", "derived", "close * volume * 100", "none", "No", "NaN when close or volume is missing")
    o["dte"] = ("Calendar days to expiration", "days", "derived", "derived", "expiration - date", "none", "Yes", "Never missing")
    o["underlying_close"] = ("Same-date PLTR adjusted close", "USD/share", relpath(PRICE_SOURCE)+": PLTR", "raw join", "", "none", "No", "NaN if PLTR close unavailable")
    o["moneyness"] = ("Strike relative to same-date PLTR close", "decimal", "derived", "derived", "strike / underlying_close - 1", "none", "No", "NaN if underlying close unavailable")
    for greek in ("implied_volatility", "delta", "gamma", "vega", "theta"):
        units = "decimal volatility" if greek == "implied_volatility" else "model-dependent Greek units"
        o[greek] = (f"Contract-specific {greek}; not supplied in validated source", units, "not available", "missing placeholder", "", "none", "No", "Always NaN; no substitution performed")
    o["data_source"] = ("Price/definition provenance and model-field warning", "text", "exporter metadata", "derived metadata", "", "none", "Yes", "Never missing")
    o["price_available"] = ("Positive option close exists", "boolean", "derived", "derived", "close.notna() and close > 0", "none", "No", "Never missing")
    o["liquidity_available"] = ("Positive same-date close and volume exist; not a lagged tradability filter", "boolean", "derived", "derived", "price_available and volume > 0", "none", "No", "Never missing")

    r = docs["pltr_atm35_reference_contracts.csv"]
    r["date"] = ("Reference trade/session date", "date", relpath(OPTION_OHLCV_SOURCE)+": date calendar", "raw calendar", "", "none", "Yes", "Never missing")
    r["selected_symbol"] = ("Reference selector contract symbol", "identifier", "derived from local option library", "derived reference", "lowest deterministic fallback level and minimum selection score", "20 prior contract observations for liquidity", "No; file confirms executable t-close data ex post", "NaN when no selection")
    r["expiration"] = ("Selected contract expiration", "date", relpath(OPTION_UNIVERSE_SOURCE)+": expiration", "vendor definition", "", "none", "No as packaged; tied to ex-post selection availability", "NaN when unavailable")
    r["strike"] = ("Selected contract strike", "USD/share", relpath(OPTION_UNIVERSE_SOURCE)+": strike", "vendor definition", "", "none", "No as packaged", "NaN when unavailable")
    r["dte"] = ("Selected contract calendar DTE", "days", "derived", "derived", "expiration - date", "none", "No as packaged", "NaN when unavailable")
    r["underlying_close"] = ("Same-date PLTR adjusted close", "USD/share", relpath(PRICE_SOURCE)+": PLTR", "raw join", "", "none", "No", "NaN only if source close missing")
    r["selection_input_underlying_close_t_minus_1"] = ("Prior option-session PLTR close used for moneyness", "USD/share", relpath(PRICE_SOURCE)+": PLTR", "lagged raw", "PLTR close shifted one option session", "1 prior option session", "Yes", "NaN at first date or no selection")
    r["option_close"] = ("Selected option same-date close", "USD/share", relpath(OPTION_OHLCV_SOURCE)+": close", "vendor-derived raw", "", "none", "No", "NaN when unavailable")
    r["volume"] = ("Selected option same-date volume", "contracts", relpath(OPTION_OHLCV_SOURCE)+": volume", "vendor-derived raw", "", "none", "No", "NaN when unavailable")
    r["daily_dollar_volume"] = ("Selected option same-date premium turnover", "USD", "derived", "derived", "option_close * volume * 100", "none", "No", "NaN when unavailable")
    r["lagged_median_dollar_volume_20obs"] = ("Contract trailing median dollar volume strictly through t-1", "USD", "derived", "derived lagged liquidity", "shift(1).rolling(20, min_periods=10).median()", "10–20 prior observations", "Yes", "NaN before sufficient history or no selection")
    r["implied_volatility"] = ("One-session-lagged modeled ATM IV, not contract quote IV", "decimal volatility", relpath(ATM_IV_SOURCE)+": pltr_atm_iv", "modeled and lagged", "pltr_atm_iv.shift(1)", "1 prior option session", "Yes", "NaN when unavailable")
    r["modeled_delta"] = ("Black–Scholes call Delta using same-date PLTR close and lagged ATM IV", "decimal Delta", "derived model", "modeled", "BS_call_delta(underlying_close, strike, dte/365, lagged ATM IV, r=4.5%)", "lagged IV; same-date spot", "No; depends on date-t close", "NaN when model input unavailable")
    r["fallback_level"] = ("0 preferred ATM35; 1 existing ATM18 fallback", "integer", "derived selector", "derived reference", "minimum available ladder level", "lagged liquidity", "No as packaged", "NaN when unavailable")
    r["fallback_label"] = ("Human-readable fallback level", "text", "derived selector", "derived reference", "", "lagged liquidity", "No as packaged", "NaN when unavailable")
    r["selection_available"] = ("Reference symbol and positive t-close exist", "boolean", "derived", "derived", "selected_symbol.notna() and option_close > 0", "none", "No; t-close availability is known ex post", "Never missing")
    r["reference_notice"] = ("Prominent non-universal-selector warning", "text", "exporter", "metadata", "constant notice", "none", "Yes", "Never missing")

    v = docs["data_validation_report.csv"]
    v["check_name"] = ("Stable validation identifier", "text", "exporter", "derived audit", "", "none", "Yes", "Never missing")
    v["passed"] = ("Whether check met its declared condition", "boolean", "exporter", "derived audit", "check-specific", "none", "Yes", "Never missing")
    v["observed_value"] = ("Observed check result", "mixed/text serialization", "exporter", "derived audit", "check-specific", "none", "Yes", "Never missing")
    v["expected_condition"] = ("Declared pass condition", "text", "exporter", "metadata", "", "none", "Yes", "Never missing")
    v["notes"] = ("Interpretation or limitation", "text", "exporter", "metadata", "", "none", "Yes", "Blank if no extra note")

    frames = {
        "ptir_pltr_daily_master.csv": master,
        "ptir_pltr_alignment_audit.csv": alignment,
        "pltr_options_daily_long.parquet": options,
        "pltr_atm35_reference_contracts.csv": reference,
        "data_validation_report.csv": validation,
    }
    for filename, frame in frames.items():
        missing_docs = set(frame.columns) - set(docs[filename])
        extra_docs = set(docs[filename]) - set(frame.columns)
        if missing_docs or extra_docs:
            raise ValueError(f"Data dictionary mismatch for {filename}: missing={missing_docs}, extra={extra_docs}")

    lines = [
        "# PTIR–PLTR shared-data dictionary",
        "",
        "> A feature calculated using date t closing prices cannot be used to earn date t close-to-close return. For a strategy executed at date t close, the feature must be based on information available through t-1 unless the strategy explicitly models a later execution time.",
        "",
        "`Safe for a t-close decision` refers to availability before executing at date t close. It does not by itself establish that a field is suitable for a particular strategy.",
        "",
    ]
    for filename, frame in frames.items():
        lines.extend([
            f"## `{filename}`",
            "",
            "| Column | Data type | Definition | Units | Source | Raw/derived | Formula | Lookback | Safe for a t-close decision? | Missing-value interpretation |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ])
        for column in frame.columns:
            definition, units, source, kind, formula, lookback, safe, missing = docs[filename][column]
            values = [
                f"`{column}`", str(frame[column].dtype), definition, units, source,
                kind, formula or "—", lookback, safe, missing,
            ]
            values = [str(x).replace("|", "\\|").replace("\n", " ") for x in values]
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    lines.extend([
        "## Manifest fields",
        "",
        "`manifest.json` records filename, byte size, row and column counts where applicable, SHA-256 checksum, authoritative local sources, and date range. The manifest cannot contain a stable checksum of itself because adding that checksum changes the file; this self-referential limitation is explicitly recorded.",
        "",
    ])
    DICTIONARY_FILE.write_text("\n".join(lines), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(metadata: dict[str, dict[str, Any]]) -> None:
    files = []
    for filename in sorted(metadata):
        path = OUTPUT_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Cannot manifest missing output: {filename}")
        item = {
            "filename": filename,
            "file_size_bytes": path.stat().st_size,
            "row_count": metadata[filename].get("row_count"),
            "column_count": metadata[filename].get("column_count"),
            "sha256": sha256_file(path),
            "authoritative_source_files": metadata[filename].get("sources", []),
            "date_range": metadata[filename].get("date_range"),
        }
        files.append(item)
    manifest = {
        "package": "Strategy-neutral PTIR–PLTR shared data",
        "created_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "files": files,
        "manifest_self_entry": {
            "filename": MANIFEST_FILE.name,
            "sha256": None,
            "notes": "A manifest cannot contain its own stable SHA-256 checksum because that value changes the file.",
        },
    }
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verify_manifest() -> None:
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    mismatches = []
    for item in manifest["files"]:
        path = OUTPUT_DIR / item["filename"]
        observed = sha256_file(path)
        if observed != item["sha256"]:
            mismatches.append(item["filename"])
    if mismatches:
        raise ValueError(f"Manifest checksum mismatch: {mismatches}")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    require_sources()
    raw, clean = load_equity_sources()
    validate_raw_equities(raw, clean)
    alignment = build_alignment(raw)
    master = build_master(raw)
    ohlcv, universe = load_option_sources()
    options = build_options_long(raw, ohlcv, universe)
    reference = build_atm35_reference(raw, ohlcv, universe)
    validation = build_validation_report(raw, clean, master, alignment, options)

    master.to_csv(MASTER_FILE, index=False, date_format="%Y-%m-%d", float_format="%.12g")
    alignment.to_csv(ALIGNMENT_FILE, index=False, date_format="%Y-%m-%d")
    options.to_parquet(OPTIONS_FILE, index=False)
    options.head(500).to_csv(
        OPTIONS_SAMPLE_FILE, index=False, date_format="%Y-%m-%d", float_format="%.12g"
    )
    reference.to_csv(REFERENCE_FILE, index=False, date_format="%Y-%m-%d", float_format="%.12g")
    validation.to_csv(VALIDATION_FILE, index=False)
    write_readme(master, alignment, options, reference)
    write_data_dictionary(master, alignment, options, reference, validation)

    if not validation["passed"].all():
        failed = validation.loc[~validation["passed"], "check_name"].tolist()
        print(f"Mandatory validation failed: {failed}", file=sys.stderr)
        return 1

    common_sources = [relpath(PRICE_SOURCE), relpath(CLEAN_PRICE_CROSSCHECK)]
    option_sources = [relpath(OPTION_OHLCV_SOURCE), relpath(OPTION_UNIVERSE_SOURCE)]
    metadata = {
        Path(__file__).name: {"sources": [], "date_range": None},
        MASTER_FILE.name: {
            "row_count": len(master), "column_count": len(master.columns),
            "sources": common_sources, "date_range": table_date_range(master),
        },
        ALIGNMENT_FILE.name: {
            "row_count": len(alignment), "column_count": len(alignment.columns),
            "sources": [relpath(PRICE_SOURCE)], "date_range": table_date_range(alignment),
        },
        OPTIONS_FILE.name: {
            "row_count": len(options), "column_count": len(options.columns),
            "sources": option_sources + [relpath(PRICE_SOURCE)],
            "date_range": table_date_range(options),
        },
        OPTIONS_SAMPLE_FILE.name: {
            "row_count": min(500, len(options)), "column_count": len(options.columns),
            "sources": [OPTIONS_FILE.name], "date_range": table_date_range(options.head(500)),
        },
        REFERENCE_FILE.name: {
            "row_count": len(reference), "column_count": len(reference.columns),
            "sources": option_sources + [relpath(PRICE_SOURCE), relpath(ATM_IV_SOURCE)],
            "date_range": table_date_range(reference),
        },
        DICTIONARY_FILE.name: {"sources": ["build_shared_dataset.py"], "date_range": None},
        README_FILE.name: {"sources": ["build_shared_dataset.py"], "date_range": None},
        VALIDATION_FILE.name: {
            "row_count": len(validation), "column_count": len(validation.columns),
            "sources": common_sources + option_sources, "date_range": None,
        },
    }
    write_manifest(metadata)
    verify_manifest()

    pltr_only = int((alignment["pltr_available"] & ~alignment["ptir_available"]).sum())
    ptir_only = int((~alignment["pltr_available"] & alignment["ptir_available"]).sum())
    print(
        "Shared dataset complete: "
        f"daily_rows={len(master)}, daily_range={master['date'].min().date()}..{master['date'].max().date()}, "
        f"option_rows={len(options)}, option_range={options['date'].min().date()}..{options['date'].max().date()}, "
        f"pltr_only_dates={pltr_only}, ptir_only_dates={ptir_only}, "
        f"validations={int(validation['passed'].sum())}/{len(validation)}, "
        f"output={OUTPUT_DIR}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
