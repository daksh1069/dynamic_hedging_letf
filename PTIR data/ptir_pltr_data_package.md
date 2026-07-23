# Strategy-neutral PTIR–PLTR shared data

## Purpose

PTIR is the GraniteShares 2x Long PLTR Daily ETF. PLTR is Palantir Technologies Inc., the underlying common stock. This package contains aligned market observations and a separate local PLTR call-option library. It contains no strategy signal, position, NAV, P&L, optimized state, or investment recommendation.

## Coverage

- Common PTIR/PLTR daily rows: **463**
- Daily master range: **2024-09-04 through 2026-07-10**
- PLTR-only source dates excluded from the master: **987**
- PTIR-only source dates excluded from the master: **0**
- PLTR option rows: **102,407**
- PLTR option range: **2024-09-04 through 2026-06-12**
- ATM35 reference rows: **445**

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

The ATM35 file is labeled `REFERENCE SELECTION ONLY — teammate may construct a different option selector.` It reproduces the existing deterministic reference convention: target 35 DTE, preferred 28–42 DTE and ±3% lagged moneyness, 20-observation lagged median dollar volume of at least $50,000, then the existing ATM18 fallback. Its IV is lagged modeled ATM IV, not vendor contract IV.

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
