# PTIR–PLTR shared-data dictionary

> A feature calculated using date t closing prices cannot be used to earn date t close-to-close return. For a strategy executed at date t close, the feature must be based on information available through t-1 unless the strategy explicitly models a later execution time.

`Safe for a t-close decision` refers to availability before executing at date t close. It does not by itself establish that a field is suitable for a particular strategy.

## `ptir_pltr_daily_master.csv`

| Column | Data type | Definition | Units | Source | Raw/derived | Formula | Lookback | Safe for a t-close decision? | Missing-value interpretation |
|---|---|---|---|---|---|---|---|---|---|
| `date` | datetime64[ns] | Trading-session date | date | data/raw/market_prices/pltr_related_raw_prices.csv: Date | raw | — | none | Yes | Never missing |
| `pltr_open` | float64 | PLTR open price; unavailable locally | USD/share | not available in validated source | raw placeholder | — | none | No | Always NaN because source retained adjusted close only |
| `pltr_high` | float64 | PLTR high price; unavailable locally | USD/share | not available in validated source | raw placeholder | — | none | No | Always NaN because source retained adjusted close only |
| `pltr_low` | float64 | PLTR low price; unavailable locally | USD/share | not available in validated source | raw placeholder | — | none | No | Always NaN because source retained adjusted close only |
| `pltr_close` | float64 | PLTR local auto-adjusted closing price | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PLTR | raw | — | none | No; date-t close is not known before that close | Missing dates excluded from master |
| `pltr_adj_close` | float64 | PLTR adjusted close; equal to local close because yfinance auto_adjust=True | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PLTR | raw alias | pltr_adj_close = pltr_close | none | No | Missing dates excluded from master |
| `pltr_volume` | float64 | PLTR share volume; unavailable locally | shares | not available in validated source | raw placeholder | — | none | No | Always NaN |
| `ptir_open` | float64 | PTIR open price; unavailable locally | USD/share | not available in validated source | raw placeholder | — | none | No | Always NaN because source retained adjusted close only |
| `ptir_high` | float64 | PTIR high price; unavailable locally | USD/share | not available in validated source | raw placeholder | — | none | No | Always NaN because source retained adjusted close only |
| `ptir_low` | float64 | PTIR low price; unavailable locally | USD/share | not available in validated source | raw placeholder | — | none | No | Always NaN because source retained adjusted close only |
| `ptir_close` | float64 | PTIR local auto-adjusted closing price | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PTIR | raw | — | none | No; date-t close is not known before that close | Missing dates excluded from master |
| `ptir_adj_close` | float64 | PTIR adjusted close; equal to local close because yfinance auto_adjust=True | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PTIR | raw alias | ptir_adj_close = ptir_close | none | No | Missing dates excluded from master |
| `ptir_volume` | float64 | PTIR share volume; unavailable locally | shares | not available in validated source | raw placeholder | — | none | No | Always NaN |
| `pltr_return_1d` | float64 | PLTR close-to-close one-session return | decimal return | derived from master | derived | pltr_close / pltr_close.shift(1) - 1 | 1 prior included session | No; safe from t+1 onward | First row is NaN |
| `ptir_return_1d` | float64 | PTIR close-to-close one-session return | decimal return | derived from master | derived | ptir_close / ptir_close.shift(1) - 1 | 1 prior included session | No; safe from t+1 onward | First row is NaN |
| `pltr_return_5d` | float64 | PLTR five-session close return | decimal return | derived from master | derived | pltr_close / pltr_close.shift(5) - 1 | 5 prior included sessions | No; safe from t+1 onward | First 5 rows are NaN |
| `pltr_return_20d` | float64 | PLTR twenty-session close return | decimal return | derived from master | derived | pltr_close / pltr_close.shift(20) - 1 | 20 prior included sessions | No; safe from t+1 onward | First 20 rows are NaN |
| `pltr_realized_vol_20d` | float64 | Annualized 20-session realized volatility, sample standard deviation | annualized decimal volatility | derived from master | derived | rolling_std(pltr_return_1d, 20, ddof=1) * sqrt(252) | 20 valid one-day returns | No; safe from t+1 onward | First 20 rows are NaN |
| `ptir_expected_2x_return` | float64 | Mechanical twice-PLTR daily return comparator | decimal return | derived from master | derived | 2 * pltr_return_1d | 1 prior included session | No; safe from t+1 onward | NaN when PLTR return is NaN |
| `ptir_tracking_difference` | float64 | PTIR return minus the mechanical 2x PLTR comparator | decimal return | derived from master | derived | ptir_return_1d - ptir_expected_2x_return | 1 prior included session | No; safe from t+1 onward | NaN when either input return is NaN |
| `both_prices_available` | bool | Whether both source closes exist | boolean | derived from source availability | derived | pltr_close.notna() and ptir_close.notna() | none | Yes | Always True in common-date master |
| `data_quality_flag` | object | Human-readable structural data limitation | text | exporter | derived metadata | constant adjusted-close-only warning | none | Yes | Never missing |

## `ptir_pltr_alignment_audit.csv`

| Column | Data type | Definition | Units | Source | Raw/derived | Formula | Lookback | Safe for a t-close decision? | Missing-value interpretation |
|---|---|---|---|---|---|---|---|---|---|
| `date` | datetime64[ns] | Union source date | date | data/raw/market_prices/pltr_related_raw_prices.csv: Date | raw | — | none | Yes | Never missing |
| `pltr_available` | bool | PLTR close exists on date | boolean | data/raw/market_prices/pltr_related_raw_prices.csv: PLTR | derived availability | PLTR.notna() | none | Yes | Never missing |
| `ptir_available` | bool | PTIR close exists on date | boolean | data/raw/market_prices/pltr_related_raw_prices.csv: PTIR | derived availability | PTIR.notna() | none | Yes | Never missing |
| `included_in_master` | bool | Both closes exist and date is included | boolean | derived | derived | pltr_available and ptir_available | none | Yes | Never missing |
| `exclusion_reason` | object | Explicit inclusion/exclusion category | text | derived | derived | INCLUDED / PLTR_MISSING / PTIR_MISSING / BOTH_MISSING | none | Yes | Never missing |

## `pltr_options_daily_long.parquet`

| Column | Data type | Definition | Units | Source | Raw/derived | Formula | Lookback | Safe for a t-close decision? | Missing-value interpretation |
|---|---|---|---|---|---|---|---|---|---|
| `date` | datetime64[ns] | Option-bar session date | date | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: date | vendor-derived raw | — | none | Yes | Never missing |
| `option_symbol` | object | OPRA raw option symbol | identifier | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: symbol | vendor raw | — | none | Yes | Never missing |
| `expiration` | datetime64[ns] | Contract expiration date | date | data/raw/databento/pltr/pltr_call_universe_unique.parquet: expiration | vendor definition | — | none | Yes | Never missing |
| `strike` | float64 | Call strike price | USD/share | data/raw/databento/pltr/pltr_call_universe_unique.parquet: strike | vendor definition | — | none | Yes | Never missing |
| `option_type` | object | Contract type | text | data/raw/databento/pltr/pltr_call_universe_unique.parquet: instrument_class | vendor definition mapped | C -> call | none | Yes | Never missing; calls only |
| `close` | float64 | Project canonical aggregated daily option close | USD/share | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: close | vendor-derived raw | — | none | No; known after date-t bar completes | Missing means no price; source currently complete |
| `volume` | float64 | Aggregated daily contracts traded | contracts | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: volume | vendor-derived raw | — | none | No; date-t completed volume is not available before close | Missing means volume unavailable |
| `daily_dollar_volume` | float64 | Same-date option premium turnover | USD | derived | derived | close * volume * 100 | none | No | NaN when close or volume is missing |
| `dte` | int64 | Calendar days to expiration | days | derived | derived | expiration - date | none | Yes | Never missing |
| `underlying_close` | float64 | Same-date PLTR adjusted close | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PLTR | raw join | — | none | No | NaN if PLTR close unavailable |
| `moneyness` | float64 | Strike relative to same-date PLTR close | decimal | derived | derived | strike / underlying_close - 1 | none | No | NaN if underlying close unavailable |
| `implied_volatility` | float64 | Contract-specific implied_volatility; not supplied in validated source | decimal volatility | not available | missing placeholder | — | none | No | Always NaN; no substitution performed |
| `delta` | float64 | Contract-specific delta; not supplied in validated source | model-dependent Greek units | not available | missing placeholder | — | none | No | Always NaN; no substitution performed |
| `gamma` | float64 | Contract-specific gamma; not supplied in validated source | model-dependent Greek units | not available | missing placeholder | — | none | No | Always NaN; no substitution performed |
| `vega` | float64 | Contract-specific vega; not supplied in validated source | model-dependent Greek units | not available | missing placeholder | — | none | No | Always NaN; no substitution performed |
| `theta` | float64 | Contract-specific theta; not supplied in validated source | model-dependent Greek units | not available | missing placeholder | — | none | No | Always NaN; no substitution performed |
| `data_source` | object | Price/definition provenance and model-field warning | text | exporter metadata | derived metadata | — | none | Yes | Never missing |
| `price_available` | bool | Positive option close exists | boolean | derived | derived | close.notna() and close > 0 | none | No | Never missing |
| `liquidity_available` | bool | Positive same-date close and volume exist; not a lagged tradability filter | boolean | derived | derived | price_available and volume > 0 | none | No | Never missing |

## `pltr_atm35_reference_contracts.csv`

| Column | Data type | Definition | Units | Source | Raw/derived | Formula | Lookback | Safe for a t-close decision? | Missing-value interpretation |
|---|---|---|---|---|---|---|---|---|---|
| `date` | datetime64[ns] | Reference trade/session date | date | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: date calendar | raw calendar | — | none | Yes | Never missing |
| `selected_symbol` | object | Reference selector contract symbol | identifier | derived from local option library | derived reference | lowest deterministic fallback level and minimum selection score | 20 prior contract observations for liquidity | No; file confirms executable t-close data ex post | NaN when no selection |
| `expiration` | datetime64[ns] | Selected contract expiration | date | data/raw/databento/pltr/pltr_call_universe_unique.parquet: expiration | vendor definition | — | none | No as packaged; tied to ex-post selection availability | NaN when unavailable |
| `strike` | float64 | Selected contract strike | USD/share | data/raw/databento/pltr/pltr_call_universe_unique.parquet: strike | vendor definition | — | none | No as packaged | NaN when unavailable |
| `dte` | float64 | Selected contract calendar DTE | days | derived | derived | expiration - date | none | No as packaged | NaN when unavailable |
| `underlying_close` | float64 | Same-date PLTR adjusted close | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PLTR | raw join | — | none | No | NaN only if source close missing |
| `selection_input_underlying_close_t_minus_1` | float64 | Prior option-session PLTR close used for moneyness | USD/share | data/raw/market_prices/pltr_related_raw_prices.csv: PLTR | lagged raw | PLTR close shifted one option session | 1 prior option session | Yes | NaN at first date or no selection |
| `option_close` | float64 | Selected option same-date close | USD/share | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: close | vendor-derived raw | — | none | No | NaN when unavailable |
| `volume` | float64 | Selected option same-date volume | contracts | data/raw/databento/pltr/pltr_selected_calls_ohlcv_1d_aggregated.parquet: volume | vendor-derived raw | — | none | No | NaN when unavailable |
| `daily_dollar_volume` | float64 | Selected option same-date premium turnover | USD | derived | derived | option_close * volume * 100 | none | No | NaN when unavailable |
| `lagged_median_dollar_volume_20obs` | float64 | Contract trailing median dollar volume strictly through t-1 | USD | derived | derived lagged liquidity | shift(1).rolling(20, min_periods=10).median() | 10–20 prior observations | Yes | NaN before sufficient history or no selection |
| `implied_volatility` | float64 | One-session-lagged modeled ATM IV, not contract quote IV | decimal volatility | data/processed/ptir/px_bt_with_iv.parquet: pltr_atm_iv | modeled and lagged | pltr_atm_iv.shift(1) | 1 prior option session | Yes | NaN when unavailable |
| `modeled_delta` | float64 | Black–Scholes call Delta using same-date PLTR close and lagged ATM IV | decimal Delta | derived model | modeled | BS_call_delta(underlying_close, strike, dte/365, lagged ATM IV, r=4.5%) | lagged IV; same-date spot | No; depends on date-t close | NaN when model input unavailable |
| `fallback_level` | float64 | 0 preferred ATM35; 1 existing ATM18 fallback | integer | derived selector | derived reference | minimum available ladder level | lagged liquidity | No as packaged | NaN when unavailable |
| `fallback_label` | object | Human-readable fallback level | text | derived selector | derived reference | — | lagged liquidity | No as packaged | NaN when unavailable |
| `selection_available` | bool | Reference symbol and positive t-close exist | boolean | derived | derived | selected_symbol.notna() and option_close > 0 | none | No; t-close availability is known ex post | Never missing |
| `reference_notice` | object | Prominent non-universal-selector warning | text | exporter | metadata | constant notice | none | Yes | Never missing |

## `data_validation_report.csv`

| Column | Data type | Definition | Units | Source | Raw/derived | Formula | Lookback | Safe for a t-close decision? | Missing-value interpretation |
|---|---|---|---|---|---|---|---|---|---|
| `check_name` | object | Stable validation identifier | text | exporter | derived audit | — | none | Yes | Never missing |
| `passed` | bool | Whether check met its declared condition | boolean | exporter | derived audit | check-specific | none | Yes | Never missing |
| `observed_value` | object | Observed check result | mixed/text serialization | exporter | derived audit | check-specific | none | Yes | Never missing |
| `expected_condition` | object | Declared pass condition | text | exporter | metadata | — | none | Yes | Never missing |
| `notes` | object | Interpretation or limitation | text | exporter | metadata | — | none | Yes | Blank if no extra note |

## Manifest fields

`manifest.json` records filename, byte size, row and column counts where applicable, SHA-256 checksum, authoritative local sources, and date range. The manifest cannot contain a stable checksum of itself because adding that checksum changes the file; this self-referential limitation is explicitly recorded.
