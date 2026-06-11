"""
Pull TSLL (Direxion Daily TSLA Bull 2X Shares) daily OHLCV history via
yfinance -- free, no Databento credits used, no Bloomberg Terminal needed.

Output: data/TSLL_ohlcv.xlsx (raw data export, alongside the team's other
Bloomberg-sourced raw Excel files in data/).
"""
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"

TICKER = "TSLL"
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
