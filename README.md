# Still a WIP

# Dynamic Hedging of a Leveraged ETF Position — TSLA / TSLL

This repo contains the data-acquisition pipeline and source data for the
**TSLA / TSLL** workstream of a larger team project on hedging leveraged ETF (LETF)
positions.

## 1. Project Context

**Project**: "Optimal Hedging Strategy of a Leveraged ETF Position" — a team project
(mentor: **Nitesh Kumar**).

**Strategy direction** (decided in the team's 2026-06-04 meeting): **Convexity
Protection** — short the leveraged ETF (LETF) and hold a long call option on either the
LETF or its underlying. LETFs suffer from volatility decay over time, so pairing a short
LETF position with a long call aims to cap downside while retaining convexity. Open
questions the team is testing: calls on the LETF vs. calls on the underlying, maturity
choice, ATM vs. OTM strikes, and the resulting hedge cost vs. risk reduction. Puts are
not needed (a short-LETF position is already short delta).

**Team tickers**: each member owns one underlying/LETF pair —
MSTR/MSTU, SMCI/SMCX, TSLA/TSLT (note: this repo's pipeline targets **TSLL**, see
below), COIN/CONL, PLTR/PLTU, MU/MUU, ETH/ETHT, NG1/BOIL, SOXX/SOXL, AVGO/AVL, NVO/NVOX,
NVDA/NVDL, MSOS/MSOX. **This repo covers TSLA / TSLL** (Tesla / Direxion Daily TSLA Bull
2X), owned by **Daksh Kumar**, paired with teammate Shubham Balodi. Other tickers are
teammates' own work and out of scope here.

**Data scope** (per Nitesh's guidance, 2026-06-10): only **`PX_LAST`** (closing price)
is needed for the options — no bid-ask, Greeks, IV, or intraday data. Contract term
should be **< ~1 quarter (~<90 DTE)**, applied as a filter at backtest time. End-of-day
data is sufficient throughout.

## 2. Overview

The pipeline answers one question: *for every TSLA call option that's a plausible
hedge candidate (2020–2026, 15–180 DTE, 80%–130% moneyness at some point in its life),
what was its daily closing price and volume — at $0 cost?*

It starts from team-wide Bloomberg exports in `data/`, narrows down to TSLA's ~3,800
relevant call contracts, decodes their Bloomberg IDs via OpenFIGI, pulls daily
`PX_LAST`/`PX_VOLUME` history via a Bloomberg Terminal BDH workbook, and combines that
with TSLA spot and TSLL OHLCV pulled for free via `yfinance`. The result is three clean
Parquet/CSV datasets (see [Data Schema](#6-data-schema)), ready for backtesting the
convexity-protection strategy.

## 3. Repository Structure

```
dynamic_hedging_project/
├── README.md
├── requirements.txt           # pip dependencies
├── .env                        # API keys (gitignored, not committed)
├── .gitignore
├── venv/                        # Python 3.9 virtualenv (gitignored)
│
├── excel_formula/                # LEGACY: Bloomberg formula templates + the pipeline that
│   ├── Excel1_Benchmarks.xlsx     # originally produced data/*.xlsx. Not run going forward --
│   ├── Excel2_LETF_Data.xlsx      # EDA and the backtest read directly from data/. Kept for
│   ├── Excel3_Underlying_Data.xlsx# reference/regeneration only.
│   └── scripts/                   # archival pipeline, 01 → 08 (see Section 5)
│       ├── 01_process_excel5.py
│       ├── 02_decode_openfigi.py
│       ├── 03_filter_contracts.py
│       ├── 04_fetch_tsll_yfinance.py
│       ├── 05_prep_tsla_bdh_full.py
│       ├── 06_check_bdh_full.py
│       ├── 07_parse_bdh_full.py
│       └── 08_fetch_tsla_spot_yfinance.py
│
├── data/                          # ── raw inputs, read directly by scripts/ ──
│   ├── Excel5_OptionTickers_Final.xlsx   # raw: quarterly OPT_CHAIN BBG IDs, 2020-2026
│   ├── Excel2_LETF_Data.xlsx             # raw: per-LETF BDP + BDH (13 LETFs incl. TSLT)
│   ├── Excel3_Underlying_Data.xlsx       # raw: per-underlying BDP + BDH (13 names, incl. TSLA)
│   ├── Benchmarks.xlsx                   # raw: SPY / QQQ / VIX / 3M T-bill BDH
│   ├── TSLL_ohlcv.xlsx                   # raw: TSLL OHLCV via yfinance (excel_formula/scripts/04)
│   ├── TSLA_calls_PXLAST_full_filled.xlsx# raw: TSLA call-option universe (3,797 contracts)
│   └── processed/                        # cached/parsed datasets, regenerated automatically
│       └── TSLA_calls_close.parquet      #   by scripts/eda/data_loader.py on first run
│
├── scripts/                       # ── all analysis code ──
│   └── eda/
│       ├── data_loader.py             # shared loaders for the raw Excel files in data/
│       └── market_data_eda.py         # TSLA/TSLT/TSLL stats, tracking, decay, drawdown
│
├── observations/                  # ── figures/plots saved by scripts/ ──
│   └── eda/
│       ├── rolling_realized_leverage.png
│       ├── decay_actual_vs_naive2x.png
│       ├── short_letf_drawdown.png
│       └── rebased_prices_since_tslt_inception.png
│
└── results/                        # ── final backtest results (TBD) ──
```

> **Current state**: `data/` holds the raw/source files listed above (plus
> `TSLL_ohlcv.xlsx`, fetched via `excel_formula/scripts/04`). `Excel5b_UniqueTickers_ForDecode.xlsx`,
> `decoded/`, `filtered/`, and `TSLA_calls_PXLAST_full.xlsx` are intermediate pipeline
> artifacts that are **not needed going forward** — EDA and the backtest read directly
> from the raw `data/*.xlsx` files (see `scripts/eda/`). Older intermediate
> artifacts/side-tracks (Databento pull, OpenFIGI decode cache, etc.) were archived to a
> backup folder outside this repo.

### Conventions for `scripts/`, `observations/`, and `results/`

- **`scripts/<topic>/`** — analysis code, organized by topic (e.g. `scripts/eda/`).
  Exploratory scripts are *not* numbered (numbering is reserved for the legacy ordered
  pipeline in `excel_formula/scripts/`).
- **`observations/<topic>/`** — figures/plots saved by the corresponding
  `scripts/<topic>/` script. Summary statistics and tables are printed to the console,
  not written to files.
- **`results/`** — final backtest outputs.

To run an EDA script: `venv/bin/python3 scripts/eda/market_data_eda.py` (run from the
project root; each script resolves paths relative to its own location).

## 4. Setup

**Requirements**: Python 3.9+ (developed on 3.9.6).

```bash
# from the project root
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Environment variables

Create a `.env` file in the project root (already gitignored):

```bash
DATABENTO_API_KEY=your-key-here     # only needed to re-run the (archived) Databento side-track
OPENFIGI_API_KEY=your-key-here      # needed for 02_decode_openfigi.py -- the decode
                                     # cache (_checkpoint.json) is not in this repo, so
                                     # a fresh run makes ~1,462 API requests (~6 min)
```

Scripts load it via `load_dotenv(dotenv_path=ROOT/".env")`.

### Bloomberg Terminal access

Step 02 (OpenFIGI decode), steps 05–07 (BDH pull), and the `excel_formula/Excel1/2/3_*.xlsx`
formula templates require a live **Bloomberg Terminal** connection (Excel BDP/BDH
add-in) to refresh `=BDP(...)`/`=BDH(...)` formulas. Steps 01, 03, 04, 08 run unattended.

## 5. Data Pipeline

The pipeline in `excel_formula/scripts/` is numbered `01`–`08` and reads/writes
everything under `data/`. Steps 1–4 and 8 run unattended; steps 5–7 require one manual
Bloomberg Terminal round-trip (refresh the generated workbook, then "Paste Special →
Values").

| # | Script | Input | Output | Notes |
|---|--------|-------|--------|-------|
| 01 | `01_process_excel5.py` | `data/Excel5_OptionTickers_Final.xlsx` | `data/Excel5b_UniqueTickers_ForDecode.xlsx` | Dedupe every unique call-option BBG ID per underlying (146,157 total across all 11 tickers). Local, free. |
| 02 | `02_decode_openfigi.py` | `data/Excel5b_UniqueTickers_ForDecode.xlsx` | `data/decoded/*_decoded.xlsx` | Decode BBG IDs → FIGI/expiry/strike/type via the OpenFIGI API. Resumable via `decoded/_checkpoint.json`. |
| 03 | `03_filter_contracts.py` | `data/decoded/*_decoded.xlsx` | `data/filtered/*_calls_filtered.xlsx` | Filter to calls only, expiry 2020-2026, 15-180 DTE, 80%-130% moneyness at some point in life (uses `data/Excel3_Underlying_Data.xlsx`). TSLA: 31,034 → 3,797 contracts. |
| 04 | `04_fetch_tsll_yfinance.py` | — (yfinance) | `data/processed/TSLL_ohlcv.{parquet,csv}` | TSLL daily OHLCV, free. |
| 05 | `05_prep_tsla_bdh_full.py` | `data/filtered/TSLA_calls_filtered.xlsx` | `data/TSLA_calls_PXLAST_full.xlsx` | Generates a 19-batch BDH workbook (one `=BDH()` block per security) for `PX_LAST`/`PX_VOLUME`. **Manual step**: refresh on Bloomberg Terminal, paste-as-values batch by batch → `TSLA_calls_PXLAST_full_filled.xlsx`. |
| 06 | `06_check_bdh_full.py` | `data/TSLA_calls_PXLAST_full_filled.xlsx` | console report | Sanity-checks every batch/block for errors, row counts, and date coverage. |
| 07 | `07_parse_bdh_full.py` | `data/TSLA_calls_PXLAST_full_filled.xlsx` | `data/processed/TSLA_calls_close.parquet` | Parses the filled BDH workbook into a clean long-format table. |
| 08 | `08_fetch_tsla_spot_yfinance.py` | — (yfinance) | `data/processed/TSLA_spot_ohlcv.{parquet,csv}` | TSLA split-adjusted spot OHLCV, free, used for moneyness classification. |

### Standalone Bloomberg formula templates

`excel_formula/Excel1_Benchmarks.xlsx`, `Excel2_LETF_Data.xlsx`, and
`Excel3_Underlying_Data.xlsx` are self-sufficient Bloomberg formula workbooks (BDP/BDH)
that, when refreshed on a Terminal and pasted-as-values, would (re)produce the raw
`data/Benchmarks.xlsx`, `Excel2_LETF_Data.xlsx`, and `Excel3_Underlying_Data.xlsx`. They
are not wired into the numbered pipeline above — kept as-is for reference/regeneration.

## 6. Data Schema

The three datasets below land in `data/processed/` once steps 04, 07, and 08 have been
run. They are the inputs for the backtest.

### `TSLA_calls_close.parquet`

532,258 rows × 7 columns — daily closing price/volume for 3,786 of the 3,797 filtered
TSLA call contracts (the remaining 11, all 2020 expiries, returned no Bloomberg
history and were dropped). Date range 2020-01-02 → 2026-06-10; expiries span
2020-01-17 → 2026-12-18.

| Column | Type | Description |
|---|---|---|
| `raw_id` | string | Bloomberg security ID + market sector, e.g. `"BBG00J7GWRB8 Equity"` |
| `figi` | string | FIGI (same as `raw_id` without the `" Equity"` suffix) |
| `expiry` | datetime64 | Option expiration date |
| `strike` | float64 | Strike price (current/split-adjusted, matches `TSLA_calls_filtered.xlsx`) |
| `date` | datetime64 | Trading date |
| `px_last` | float64 | Closing price (Bloomberg `PX_LAST`) |
| `px_volume` | float64 | Daily contract volume (Bloomberg `PX_VOLUME`) |

### `TSLL_ohlcv.{parquet,csv}`

962 rows × 7 columns — TSLL daily OHLCV from inception (2022-08-09) → 2026-06-09, via
`yfinance`.

| Column | Type | Description |
|---|---|---|
| `Date` | datetime64 | Trading date |
| `Open`, `High`, `Low`, `Close` | float64 | Daily OHLC |
| `Adj Close` | float64 | Dividend/split-adjusted close |
| `Volume` | int64 | Daily share volume |

### `TSLA_spot_ohlcv.{parquet,csv}`

1,617 rows × 7 columns — TSLA daily OHLCV, 2020-01-02 → 2026-06-09, via `yfinance`.
Same schema as `TSLL_ohlcv` above. Used to classify each option's moneyness
(strike vs. spot) at backtest time.

## 7. Status & Next Steps

**Data pull validated**: the pipeline above has previously been run end-to-end at **$0
cost** — Bloomberg BDH + yfinance, instead of the originally-estimated $61.19 Databento
pull (now archived outside this repo). The processed datasets it produces feed directly
into the backtest.

**Data acquisition is complete.** All inputs now live as raw Excel files directly in
`data/` — `Excel2_LETF_Data.xlsx` (TSLT), `Excel3_Underlying_Data.xlsx` (TSLA),
`TSLL_ohlcv.xlsx` (yfinance), `TSLA_calls_PXLAST_full_filled.xlsx` (3,797 call
contracts), and `Benchmarks.xlsx` (SPY/QQQ/VIX/T-bill). The `excel_formula/` pipeline
(steps 01-08) is now legacy/archival — it was used to *produce* these raw files and does
not need to be re-run. EDA and the backtest read directly from `data/*.xlsx`.

**Next steps** (per Nitesh: "start coding a simple backtest"):
1. Build a simple backtest: **short TSLL (LETF) + long TSLA call**, across moneyness
   buckets (ATM, 10% OTM, 20% OTM), term < ~1 quarter.
2. For each rebalance date, classify each call by moneyness using TSLA spot close
   (from `Excel3_Underlying_Data.xlsx`) vs. `strike`, and DTE = `expiry - date`.
3. Pick one representative contract per (date, moneyness bucket, DTE bucket) and track
   P&L of short-TSLL + long-call vs. short-TSLL-alone.
4. Decide rebalancing frequency (daily data in hand; can resample to weekly/monthly).

## 8. Out of Scope

- Other tickers (MSTR, MSOS, SMCI, COIN, PLTR, NVO, MU, AVGO, NVDA, SOXX) — teammates'
  own workstreams.
- Puts — calls only.
- Bid-ask spreads, Greeks, implied vol — confirmed not needed by Nitesh.
- Intraday data — end-of-day only.
