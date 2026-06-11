"""
Pull <TICKER> daily OHLCV (split-adjusted) via yfinance -- needed for
moneyness (ATM/OTM) classification against the option chain.

Output: data/processed/<TICKER>_spot_ohlcv.parquet and .csv

Usage: python excel_formula/scripts/08_fetch_ticker_spot_yfinance.py TICKER
"""
import sys
from pathlib import Path

import yfinance as yf

if len(sys.argv) < 2:
    sys.exit("Usage: python excel_formula/scripts/08_fetch_ticker_spot_yfinance.py TICKER")
TICKER = sys.argv[1]

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "processed"

START = "2020-01-01"
END = "2026-06-10"


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    df = yf.download(TICKER, start=START, end=END, auto_adjust=False)
    df = df.reset_index()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    out_parquet = DATA_DIR / f"{TICKER}_spot_ohlcv.parquet"
    out_csv = DATA_DIR / f"{TICKER}_spot_ohlcv.csv"
    df.to_parquet(out_parquet)
    df.to_csv(out_csv, index=False)

    print(f"{TICKER}: {len(df):,} rows, {df['Date'].min().date()} -> {df['Date'].max().date()}")
    print(f"Saved -> {out_parquet}")
    print(f"Saved -> {out_csv}")


if __name__ == "__main__":
    main()
