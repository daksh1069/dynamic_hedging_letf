# PTIR / PLTR Shared Data — Quick Guide

- **PTIR** = GraniteShares 2x Long PLTR Daily ETF
- **PLTR** = Palantir Technologies Inc. (the underlying stock)

## Files in this folder

| File | What's in it | Rows / cols | Date range |
|---|---|---|---|
| `ptir_pltr_daily_master.csv` | **Start here.** One row per date: PLTR close, PTIR close, 1/5/20-day returns, 20-day realized vol, expected 2x return, tracking difference | 463 rows / 22 cols | 2024‑09‑04 → 2026‑07‑10 |
| `pltr_options_daily_long.parquet` | PLTR call options, one row per contract per date: strike, expiration, close, volume, dollar volume, DTE, moneyness (no IV/Greeks — not supplied by the vendor) | 102,407 rows / 19 cols | 2024‑09‑04 → 2026‑06‑12 |
| `pltr_options_daily_sample.csv` | First 500 rows of the option file, for a quick look without loading the full Parquet | 500 rows / 19 cols | 2024‑09‑04 → 2024‑09‑10 |
| `pltr_atm35_reference_contracts.csv` | One example "closest-to-35-day, near-the-money" option pick per date — a *reference* selection only, not the only valid way to pick contracts | 445 rows / 17 cols | 2024‑09‑04 → 2026‑06‑12 |
| `ptir_pltr_alignment_audit.csv` | Every date where PLTR and/or PTIR data exists, and whether it made it into the daily master (and why not, if excluded) | 1,450 rows / 5 cols | 2020‑09‑30 → 2026‑07‑10 |
| `data_validation_report.csv` | Reproducibility/sanity checks run when this package was built (row counts, checksums, cross-file consistency) | 26 checks | — |
| `manifest.json` | File sizes, row/column counts, and SHA-256 checksums for every file above — use this to confirm nothing got corrupted in transfer | — | — |

## Two things to know before you build a strategy on this

1. **Timing:** a feature built from date-`t` closing prices is not known
   until *after* the date-`t` close. If your strategy trades at the `t`
   close, use only information through `t-1` unless you explicitly model
   later execution. Nothing in this data is pre-lagged for you.
2. **What's missing:** PLTR/PTIR open, high, low, and volume are not
   available (only adjusted close). Option contracts have no vendor IV or
   Greeks (those columns are present but always null). The option file is
   **calls only** — no puts.

## Loading it

```python
import pandas as pd

daily = pd.read_csv("ptir_pltr_daily_master.csv", parse_dates=["date"])
options = pd.read_parquet("pltr_options_daily_long.parquet")
```

## Want more detail?

- Full column-by-column definitions (units, formulas, lookback, whether a
  field is safe to use at a `t`-close decision): `data_dictionary_ptir_pltr.md`.
- Full package background and known limitations:
  `ptir_pltr_data_package.md`
