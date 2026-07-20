# Dynamic Hedging of a Leveraged ETF Position — TSLA / TSLL

Ground-up rebuild. Everything that existed before this point (old scripts, README,
report, results, observations) has been moved to `deprecated/` and is not used as a
foundation for anything below — no inherited parameters, no inherited conclusions, no
reused code. Only the raw data survives untouched.

## What's actually true right now

**Data available in `data/`** (raw, unmodified inputs):

| File | Contents |
|---|---|
| `TSLA_calls_PXLAST_full_filled.xlsx` | TSLA call option chain, daily `PX_LAST`/`PX_VOLUME` |
| `TSLL_calls_PXLAST_full.xlsx` | TSLL call option chain, daily `PX_LAST`/`PX_VOLUME` |
| `Excel3_Underlying_Data.xlsx` | TSLA underlying OHLCV |
| `Excel2_LETF_Data.xlsx` | TSLL/TSLT LETF OHLCV |
| `TSLL_ohlcv.xlsx` | TSLL OHLCV (yfinance) |
| `Benchmarks.xlsx` | SPY / QQQ / VIX / 3M T-bill |
| `Excel5_OptionTickers_Final.xlsx` | Raw option ticker universe |
| `processed/` | Cached parquet of parsed option chains |

Every parameter used anywhere in `scripts/sandbox/` — leverage relationship between TSLL
and TSLA, moneyness, days-to-expiry, roll frequency, coverage-band width, hedge-buffer
size, which instrument to hedge with — is derived empirically from this data via
train/held-out-test validation, not assumed. Three exceptions are stated, declared
conventions rather than derived values: the risk-free rate (5%), the borrow-fee /
transaction-cost assumptions (real TSLL borrow-fee levels + a stated transaction-cost
rate), and the volatility/beta estimation window (`ESTIMATION_WINDOW = 21` trading days,
~1 calendar month, the standard industry convention). The estimation window is
deliberately *not* selected by comparing candidate windows against future realized
outcomes — that would be predicting the market, which this project treats as out of
scope (if we could reliably predict volatility, we wouldn't need a hedge). A one-off
forecast-accuracy check (`scripts/sandbox/lever0_estimation_window_sandbox.ipynb`) found
21 is not a poor choice among candidates {5,10,15,21,42,63}, but that check is a sanity
confirmation, not the selection method, and isn't reused elsewhere in the project.

## Setup

```bash
# from the project root
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m ipykernel install --user --name dynamic-hedging   # so Jupyter sees this venv's kernel
```

Run a notebook headlessly (no manual cell-by-cell execution, avoids stale-state risk):

```bash
jupyter nbconvert --to notebook --execute --inplace scripts/sandbox/<notebook>.ipynb
```

## Structure

```
scripts/sandbox/    self-contained Jupyter notebooks, one per experiment stage
results/             outputs (equity CSVs) once notebooks are run
observations/        outputs (plots, printed metrics) once notebooks are run
deprecated/          everything from before this rebuild — not imported, not referenced
```

See `scripts/sandbox/00_foundation_sandbox.ipynb` for the starting point.
