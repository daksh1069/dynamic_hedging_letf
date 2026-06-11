"""
Pull <TICKER> daily OHLCV history via yfinance -- free, no Databento credits
used, no Bloomberg Terminal needed. This repo's LETF is TSLL (Direxion Daily
TSLA Bull 2X Shares).

Output: data/<TICKER>_ohlcv.xlsx (raw data export, alongside the team's other
Bloomberg-sourced raw Excel files in data/).

Usage: python excel_formula/scripts/09_fetch_ticker_ohlcv_yfinance.py TICKER
"""
import sys
from pathlib import Path

import yfinance as yf

if len(sys.argv) < 2:
    sys.exit("Usage: python excel_formula/scripts/09_fetch_ticker_ohlcv_yfinance.py TICKER")
TICKER = sys.argv[1]

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"

START = "2020-01-01"
END = "2026-06-11"


def main():
    df = yf.download(TICKER, start=START, end=END, auto_adjust=False)
    df = df.reset_index()
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    out_path = DATA_DIR / f"{TICKER}_ohlcv.xlsx"
    df.to_excel(out_path, index=False, sheet_name=TICKER)

    print(f"{TICKER}: {len(df):,} rows, {df['Date'].min().date()} -> {df['Date'].max().date()}")
    print(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
