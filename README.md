# Dynamic Hedging of a Leveraged ETF Position: TSLA / TSLL

This repository holds the data-acquisition pipeline, source data, and strategy research
for the **TSLA / TSLL** workstream of a larger team project on hedging leveraged ETF
(LETF) positions. The final deliverable is a guaranteed-floor convexity protection
engine whose maximum drawdown is capped by a closed-form bound; see
[Section 8](#8-guaranteed-floor-engine-final-result).

## 1. Project Context

**Project**: "Optimal Hedging Strategy of a Leveraged ETF Position", a team project.

**Strategy direction** (decided in the team's 2026-06-04 meeting): **Convexity
Protection**, meaning short the leveraged ETF (LETF) and hold a long call option on
either the LETF or its underlying. LETFs suffer from volatility decay over time, so
pairing a short LETF position with a long call aims to cap downside while retaining
convexity. The final engine (Section 8) extends this with a short out-of-the-money put
leg, a collar, which lowers the net cost of the floor by selling rich crash insurance.

**Team tickers**: each member owns one underlying/LETF pair:
MSTR/MSTU, SMCI/SMCX, TSLA/TSLT (note: this repository's pipeline targets **TSLL**, see
below), COIN/CONL, PLTR/PLTU, MU/MUU, ETH/ETHT, NG1/BOIL, SOXX/SOXL, AVGO/AVL, NVO/NVOX,
NVDA/NVDL, MSOS/MSOX. **This repository covers TSLA / TSLL** (Tesla / Direxion Daily TSLA
Bull 2X), owned by **Daksh Kumar**, paired with teammate Shubham Balodi. Other tickers
are teammates' own work and out of scope here.

**Data scope** (decided 2026-06-10, since extended): only **`PX_LAST`** (closing price)
and `PX_VOLUME` are pulled for options. No bid-ask, Greeks, IV, or intraday data. The
scope was initially call-only; it was later extended to **put chains** (for the collar
leg) and to an approximate **short-borrow-fee** series (for realized returns). End-of-day
data is sufficient throughout.

## 2. Overview

The pipeline answers one question: *for every TSLA and TSLL option (call or put) that is
a plausible hedge candidate (2020-2026, 15-180 DTE, 80%-130% moneyness at some point in
its life), what was its daily closing price and volume, at zero data cost?*

It starts from team-wide Bloomberg exports in `data/`, narrows down to the relevant
contracts, decodes their Bloomberg IDs via OpenFIGI, pulls daily `PX_LAST`/`PX_VOLUME`
history via a Bloomberg Terminal BDH workbook, and combines that with TSLA spot and TSLL
OHLCV pulled for free via `yfinance`. The result is clean Parquet/CSV datasets (see
[Data Schema](#7-data-schema)), ready for backtesting.

On top of that data, `scripts/` implements the exploratory Cost-Benefit Analysis
(Section 8) and the final guaranteed-floor engine.

## 3. Repository Structure

```
dynamic_hedging_project/
|-- README.md
|-- requirements.txt            # pip dependencies
|-- .env                         # API keys (gitignored, not committed)
|-- .gitignore
|-- venv/                        # Python 3.9 virtualenv (gitignored)
|
|-- excel_formula/                # Bloomberg formula templates + the numbered pipeline that
|   |-- Excel1_Benchmarks.xlsx     # (re)produces data/*.xlsx. EDA and backtests read
|   |-- Excel2_LETF_Data.xlsx      # directly from data/. This pipeline is for
|   |-- Excel3_Underlying_Data.xlsx# regenerating/extending the raw inputs (e.g. puts, new tickers).
|   |-- Excel5_OptionTickers_Final.xlsx
|   +-- scripts/                   # numbered pipeline, 00a-00b + 01-03 + 05-09 (see Section 6)
|       +-- 00a..09_*.py           #   OPTION_TYPE env var switches every step between calls and puts
|
|-- data/                          # -- raw inputs, read directly by scripts/ --
|   |-- Excel5_OptionTickers_Final.xlsx   # raw: quarterly OPT_CHAIN BBG IDs, 2020-2026
|   |-- Excel2_LETF_Data.xlsx             # raw: per-LETF BDP + BDH (13 LETFs incl. TSLT)
|   |-- Excel3_Underlying_Data.xlsx       # raw: per-underlying BDP + BDH (13 names, incl. TSLA)
|   |-- Benchmarks.xlsx                   # raw: SPY / QQQ / VIX / 3M T-bill BDH
|   |-- TSLL_ohlcv.xlsx                   # raw: TSLL OHLCV via yfinance
|   |-- TSLA_calls_PXLAST_full_filled.xlsx# raw: TSLA call universe (filled BDH)
|   |-- TSLA_puts_PXLAST_full_filled.xlsx # raw: TSLA put universe (filled BDH)
|   |-- TSLL_puts_PXLAST_full_filled.xlsx # raw: TSLL put universe (filled BDH)
|   +-- processed/                        # cached/parsed datasets
|       |-- TSLA_calls_close.parquet
|       |-- TSLL_calls_close.parquet
|       |-- TSLA_puts_close.parquet
|       +-- TSLL_puts_close.parquet
|
|-- scripts/                       # -- all analysis code --
|   |-- eda/
|   |   |-- data_loader.py             # shared loaders (calls, puts, spot, OHLCV, benchmarks)
|   |   +-- market_data_eda.py         # TSLA/TSLT/TSLL stats, tracking, decay, drawdown
|   |-- backtest/
|   |   |-- cba_backtest.py            # Cost-Benefit Analysis engine
|   |   |-- options_selection.py       # contract picker (moneyness bucket + DTE)
|   |   |-- borrow_rates.py            # approximate TSLA/TSLL borrow-fee series
|   |   +-- engine.py, metrics.py, grid_search.py
|   |-- strategies/                    # naked short, delta-arb, convexity, double-short
|   +-- utils/                         # research notebooks (see Section 8)
|       |-- final_guaranteed_floor_project.ipynb   # <-- consolidated final result
|       |-- continuous_capital_recycling_sandbox.ipynb
|       |-- put_financed_floor_sandbox.ipynb
|       +-- (earlier floor sandboxes)
|
|-- observations/                  # -- figures/plots saved by scripts/ --
|   |-- eda/
|   +-- strategies/{cba, final, sandbox, ...}
|
|-- results/                        # -- backtest output CSVs --
+-- latex/                          # -- project report --
    |-- main.tex                       # (maintained on Overleaf; build artifacts in repo)
    +-- guaranteed_floor_addendum.tex  # addendum: the guaranteed-floor engine (Section 8)
```

### Conventions for `scripts/`, `observations/`, and `results/`

- **`scripts/<topic>/`**: analysis code, organized by topic (`eda`, `backtest`,
  `strategies`, `utils`). Numbering is reserved for the legacy ordered pipeline in
  `excel_formula/scripts/`.
- **`observations/<topic>/`**: figures/plots saved by the corresponding code. Summary
  tables are printed to the console.
- **`results/`**: final backtest output CSVs.

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
OPENFIGI_API_KEY=your-key-here      # needed for 02_decode_openfigi.py
```

Scripts load it via `load_dotenv(dotenv_path=ROOT/".env")`.

### Bloomberg Terminal access

Steps 05-07 (BDH pull) and the `excel_formula/Excel*.xlsx` formula templates require a
live **Bloomberg Terminal** connection (Excel BDP/BDH/BDS add-in) to refresh the
formulas. Step 02 (OpenFIGI decode) needs `OPENFIGI_API_KEY` but otherwise runs
unattended. Steps 00a, 00b, 01, 03, 08, 09 run fully unattended; they only *build* the
formula templates, and a Terminal is needed afterward to refresh and paste-as-values.

## 5. Running the Analysis

All notebooks and scripts run from the project root using the venv interpreter.

```bash
# EDA
venv/bin/python3 scripts/eda/market_data_eda.py

# The final guaranteed-floor engine (consolidated, self-contained):
venv/bin/jupyter nbconvert --to notebook --execute --inplace \
  scripts/utils/final_guaranteed_floor_project.ipynb
```

## 6. Data Pipeline

The pipeline in `excel_formula/scripts/` is numbered `00a`-`00b`, `01`-`03`, `05`-`09`
(no `04`) and reads/writes files under `data/` and `excel_formula/`. It was originally
built for calls; every step now honors an **`OPTION_TYPE`** environment variable
(`C` for calls, the default, or `P` for puts), so the identical pipeline produces the put
datasets by re-running with `OPTION_TYPE=P`. Steps 05, 06, 07, 08, 09 also take the
underlying's ticker as a required command-line argument.

| # | Script | Output | Notes |
|---|--------|--------|-------|
| 00a | `00a_build_excel5.py` | `Excel5_OptionTickers_Final.xlsx` | Quarterly OPT_CHAIN `=BDS()` template; `CHAIN_PUT_CALL_TYPE_OVRD` follows `OPTION_TYPE`. |
| 00b | `00b_build_excel3.py` | `Excel3_Underlying_Data.xlsx` | Per-underlying daily OHLCV + TRI `=BDH()` template, used by step 03 for moneyness. |
| 01 | `01_process_excel5.py` | `Excel5b_UniqueTickers_ForDecode.xlsx` | Dedupe every unique option BBG ID per underlying. |
| 02 | `02_decode_openfigi.py` | `data/decoded/*_decoded.xlsx` | Decode BBG IDs to FIGI/expiry/strike/type via OpenFIGI. Resumable. |
| 03 | `03_filter_contracts.py` | `data/filtered/*_{calls,puts}_filtered.xlsx` | Filter to `OPTION_TYPE`, expiry 2020-2026, 15-180 DTE, 80%-130% moneyness at some point in life. |
| 05 | `05_prep_ticker_bdh_full.py TICKER` | `excel_formula/<TICKER>_..._PXLAST_full.xlsx` | Batched BDH workbook for `PX_LAST`/`PX_VOLUME`. Manual Terminal round-trip, then paste-as-values into `data/`. |
| 06 | `06_check_bdh_full.py TICKER` | console report | Sanity-checks batches for errors, row counts, coverage. |
| 07 | `07_parse_bdh_full.py TICKER` | `data/processed/<TICKER>_{calls,puts}_close.parquet` | Parses the filled workbook into a clean long table. |
| 08 | `08_fetch_ticker_spot_yfinance.py TICKER` | `data/processed/<TICKER>_spot_ohlcv.*` | Split-adjusted spot OHLCV, free. |
| 09 | `09_fetch_ticker_ohlcv_yfinance.py TICKER` | `data/<TICKER>_ohlcv.xlsx` | Daily OHLCV for any ticker (e.g. the LETF), free. |

`Excel1_Benchmarks.xlsx` and `Excel2_LETF_Data.xlsx` are self-sufficient Bloomberg
formula workbooks kept for reference. `Excel3_Underlying_Data.xlsx` is wired in
(generated by step 00b, consumed by step 03).

## 7. Data Schema

All files live in `data/` (raw inputs) or `data/processed/` (parsed/cached outputs).
Loader functions are in `scripts/eda/data_loader.py`. Every option parquet shares the
same seven-column long format: `raw_id`, `figi`, `expiry`, `strike`, `date`, `px_last`,
`px_volume`.

### Processed option datasets (`data/processed/`)

| Dataset | Rows | Contracts | Date range | Loader |
|---|---|---|---|---|
| `TSLA_calls_close.parquet` | 532,258 | 3,786 | 2020-01-02 to 2026-06-10 | `load_tsla_calls()` |
| `TSLL_calls_close.parquet` | 46,867 | 689 | 2022-08-12 to 2026-06-10 | `load_tsll_calls()` |
| `TSLA_puts_close.parquet` | 442,076 | 3,786 | 2020-01-02 to 2026-06-10 | `load_tsla_puts()` |
| `TSLL_puts_close.parquet` | 55,978 | 1,348 | 2022-08-10 to 2026-06-10 | `load_tsll_puts()` |

TSLL chains are significantly sparser than TSLA (median around 49 contracts per day),
which is the binding liquidity constraint on the LETF-native strategies. TSLL put
liquidity is nonetheless sufficient for the collar: on 93% of days with a qualifying call
anchor, a same-expiry 10%-30% out-of-the-money put also trades, at a median premium near
10% of spot.

### Raw OHLCV and reference files (`data/`)

- **`TSLL_ohlcv.xlsx`**: TSLL daily OHLCV from inception (2022-08-09) to 2026-06-10 via
  `yfinance`. Loaded by `load_tsll()`.
- **`Excel3_Underlying_Data.xlsx`**: one sheet per underlying; TSLA sheet is the spot
  series (via `load_tsla_underlying()`).
- **`Excel2_LETF_Data.xlsx`**: one sheet per LETF; TSLT via `load_tslt()`.
- **`Benchmarks.xlsx`**: SPY / QQQ / VIX / US 3M T-bill, via `load_benchmarks()`.
- **`TSL*_PXLAST_full_filled.xlsx`**: raw filled Bloomberg BDH workbooks, the source
  files for the processed parquets. Not read directly by analysis code.

### Borrow rates (`scripts/backtest/borrow_rates.py`)

`load_borrow_rates(dates)` returns daily annualized borrow-fee series for TSLA (flat near
0.40%) and TSLL (quarterly step function, 0.7% to 7.0%, spiking in TSLA volatility
regimes). This is a stated approximation read from public borrow-fee charts, not measured
daily securities-finance data.

## 8. Guaranteed-Floor Engine (Final Result)

The research notebooks in `scripts/utils/` develop, in sequence, a portfolio hedging
engine whose maximum drawdown is capped by a closed-form bound rather than an observed
backtest number. The consolidated, self-contained version is
`final_guaranteed_floor_project.ipynb`; the full write-up is
`latex/guaranteed_floor_addendum.tex`.

**Construction.** Each tranche shorts TSLL, buys a long ATM TSLL call, and optionally
sells an OTM TSLL put (a collar). The per-share worst-case loss (the reservation) is an
exact algebraic identity, `L = C + K_c - S_0` (call-only) or `L' = C + K_c - S_0 - P_p`
(collar), valid at any strike and, via no-arbitrage bounds on American options, at every
instant rather than only at expiry. A settled-equity accounting scheme keys the risk
budget to checkpoint equity rather than daily marks, which removes procyclicality. A
cycle ceiling converts equity peaks into checkpoints, yielding the master equation

```
guaranteed MaxDD  <=  (d + g) / (1 + g)
```

where `l` is the per-cycle loss budget, `d` the drawdown limit against the settled high
water mark, `g` the gain trigger, and `q` the deployment cost gate (Latin letters by
design: alpha, gamma, and delta already carry standard meanings in finance). Setting
`x = l = d = g` gives a one-parameter risk dial with bound `2x/(1+x)`:
the investor picks the drawdown guarantee, and the backtest reports what it earned. A
favorability gate deploys capital only when the net floor cost is at most 15% of
protected notional.

**Results** (2022-08-12 to 2026-06-10, headline config `l=8%, d=8.2%, g=8%, q=15%`,
guaranteed bound 15.0%):

| Strategy | CAGR | Sharpe | Max DD | Calmar |
|---|---|---|---|---|
| Collar, frictionless | +15.69% | 0.899 | -12.29% | 1.277 |
| Collar with borrow (realized) | +10.41% | 0.680 | -15.21% | 0.684 |
| Call-only, frictionless | +14.00% | 0.841 | -11.29% | 1.240 |
| Call-only with borrow (realized) | +13.42% | 0.706 | -15.44% | 0.869 |
| Naked short TSLL (benchmark) | +13.30% | n/a | -79.60% | 0.167 |

Across all configurations tested (four full-period variants, two holdout halves each, and
seven risk-dial settings), the daily equity path produced zero violations of its
leak-adjusted analytic floor over 960 days each. Returns are concentrated in the crash
regime, which is the intended profile for a hedge; the bound holds in every regime.
Figures in `observations/strategies/final/`.

## 9. Earlier Result: Cost-Benefit Analysis

An exploratory CBA (`scripts/backtest/cba_backtest.py`) compared strategies over
2022-08-12 to 2026-06-10 with a fixed 2% hedge spend per roll:

| Strategy | CAGR | Ann. Vol | Max DD | Fill Rate |
|---|---|---|---|---|
| Benchmark (naked short TSLL) | 13.3% | 67.2% | -79.6% | n/a |
| A-ATM (TSLA call) | 14.0% | 57.1% | -74.2% | ~100% |
| **A-20% OTM (TSLA call)** | **17.4%** | **42.9%** | **-61.2%** | **~100%** |
| B-20% OTM (TSLL call) | 15.8% | 45.2% | -64.1% | 42% |

Key finding: TSLA calls dominate on a fixed-spend basis, while LETF-native (TSLL) hedges
are capacity-constrained. The guaranteed-floor engine of Section 8 is LETF-native by
design (its algebraic floor requires the call and short to be on the same instrument) and
addresses the sparsity by deploying only when a qualifying contract exists and parking
otherwise.

## 10. Scope and Limitations

- Options: calls are bought and OTM puts are sold (the collar). The earlier "puts not
  needed" note referred to *buying* puts, which is redundant on an already-short-delta
  book; *selling* them harvests premium and is a distinct trade.
- Costs: short-borrow fees are modeled (approximate, quarterly). Bid-ask spreads are the
  principal unmodeled cost and are adverse; the dataset was scoped to closing prices, so
  spreads cannot be estimated from it.
- Data: end-of-day only; thin TSLL chains; trades execute at the observed close; position
  size is not capped against contract volume; TSLL distributions to the share lender are
  not modeled.
- The guaranteed drawdown bound is a theorem given the stated assumptions. Reported CAGRs
  are a single 3.8-year history.
