"""
Inspect TSLA spot and TSLL OHLCV source data.

Saves all printed output to observations/eda/miscellaneous/inspect_spot_data.txt
(overwritten on every run).

Prints:
  - Shape, columns, date range
  - Close price statistics
  - Missing-value summary
  - Overlap check against the CBA analysis window (2022-08-12 → 2026-06-10)

Run from the project root:
    venv/bin/python3 scripts/eda/miscellaneous/inspect_spot_data.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))

from capture import capture_stdout
from data_loader import load_tsla_underlying, load_tsll

OUT_DIR = ROOT / "observations" / "eda" / "miscellaneous"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CBA_START = pd.Timestamp("2022-08-12")
CBA_END   = pd.Timestamp("2026-06-10")


def inspect_df(name, df, date_col="Date", price_col="Close", source=""):
    print(f"\n{'='*60}")
    print(f"  {name}  {f'({source})' if source else ''}")
    print(f"{'='*60}")
    print(f"Shape   : {df.shape[0]:,} rows × {df.shape[1]} columns")
    print(f"Columns : {list(df.columns)}")
    print(f"\nDate range: {df[date_col].min().date()} → {df[date_col].max().date()}")

    print(f"\n{price_col} statistics:")
    print(df[price_col].describe().to_string())

    missing = df.isnull().sum()
    if missing.any():
        print(f"\nMissing values:\n{missing[missing > 0].to_string()}")
    else:
        print(f"\nMissing values: none")

    in_window = df[(df[date_col] >= CBA_START) & (df[date_col] <= CBA_END)]
    print(f"\nCBA window ({CBA_START.date()} → {CBA_END.date()}):")
    print(f"  Rows in window : {len(in_window):,}")
    print(f"  Close in window: min={in_window[price_col].min():.2f}  "
          f"max={in_window[price_col].max():.2f}  "
          f"mean={in_window[price_col].mean():.2f}")


def main():
    print(f"Spot data inspection — generated from {__file__}")
    print(f"Project root: {ROOT}")

    tsla = load_tsla_underlying()
    inspect_df("TSLA spot", tsla, source="data/Excel3_Underlying_Data.xlsx → sheet TSLA")

    tsll = load_tsll()
    inspect_df("TSLL OHLCV", tsll, source="data/TSLL_ohlcv.xlsx (yfinance)")
    print()


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "inspect_spot_data.txt"):
        main()
