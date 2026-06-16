"""
Inspect and summarise both options parquet files.

Saves all printed output to observations/eda/miscellaneous/inspect_options_data.txt
(overwritten on every run).

Prints:
  - Shape, columns, dtypes
  - Date range, unique contracts, unique dates
  - Sparsity: actual rows vs. possible (contract × date) cells
  - px_last and px_volume statistics
  - DTE distribution
  - Contracts-per-day distribution
  - Strike distribution
  - File sizes on disk

Run from the project root:
    venv/bin/python3 scripts/eda/miscellaneous/inspect_options_data.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))

from capture import capture_stdout

DATA_DIR = ROOT / "data" / "processed"
OUT_DIR = ROOT / "observations" / "eda" / "miscellaneous"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("TSLA_calls", DATA_DIR / "TSLA_calls_close.parquet"),
    ("TSLL_calls", DATA_DIR / "TSLL_calls_close.parquet"),
]


def inspect(name, path):
    print(f"\n{'='*60}")
    print(f"  {name}  ({path.name})")
    print(f"{'='*60}")
    size_mb = path.stat().st_size / 1_048_576
    print(f"File size : {size_mb:.1f} MB")

    df = pd.read_parquet(path)
    print(f"Shape     : {df.shape[0]:,} rows × {df.shape[1]} columns")
    print(f"Columns   : {list(df.columns)}")
    print(f"\ndtypes:\n{df.dtypes.to_string()}")

    print(f"\nDate range      : {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"Expiry range    : {df['expiry'].min().date()} → {df['expiry'].max().date()}")
    print(f"Unique contracts: {df['raw_id'].nunique():,}")
    print(f"Unique dates    : {df['date'].nunique():,}")

    n_contracts = df["raw_id"].nunique()
    n_dates = df["date"].nunique()
    possible = n_contracts * n_dates
    print(f"\nSparsity")
    print(f"  Possible (contract × date) cells : {possible:,}")
    print(f"  Actual rows in parquet           : {len(df):,}")
    print(f"  Fill rate (rows / possible)      : {len(df)/possible:.1%}")
    print(f"  px_last non-null rate            : {df['px_last'].notna().mean():.1%}")

    print(f"\npx_last statistics:")
    print(df["px_last"].describe().to_string())

    if "px_volume" in df.columns:
        print(f"\npx_volume statistics:")
        print(df["px_volume"].describe().to_string())

    df["dte"] = (df["expiry"] - df["date"]).dt.days
    print(f"\nDTE statistics:")
    print(df["dte"].describe().to_string())
    print(f"  DTE < 0 (post-expiry rows) : {(df['dte'] < 0).sum():,}")

    daily = df.groupby("date")["raw_id"].nunique()
    print(f"\nContracts per trading day:")
    print(f"  min={daily.min()}  median={daily.median():.0f}  "
          f"mean={daily.mean():.1f}  max={daily.max()}")

    print(f"\nStrike statistics:")
    print(df["strike"].describe().to_string())


def main():
    print(f"Options data inspection — generated from {__file__}")
    print(f"Project root: {ROOT}")
    for name, path in TARGETS:
        inspect(name, path)
    print()


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "inspect_options_data.txt"):
        main()
