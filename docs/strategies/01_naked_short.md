# Strategy 1: Naked Short TSLL (Double-Short Baseline)

## Idea

Short $1 notional of TSLL, the Direxion Daily TSLA Bull 2X ETF, and hold. The
short is effectively a -2x bet on TSLA (hence "double-short"), motivated by
the volatility decay that leveraged ETFs suffer from daily rebalancing. This
is the unhedged baseline every other strategy is measured against.

## Variants

- Primary: buy and hold short $1 from inception, no rebalancing. Equity can
  go negative (margin wipeout if TSLA rallies hard).
- Sensitivity: the same short rebalanced back to -$1 notional daily, weekly,
  and monthly, showing the cost of rebalancing friction (the monthly variant
  reached -67% CAGR with a -99.8% maximum drawdown).

## Results

Buy and hold over the common comparison window (2022-11-08 to 2026-06-08):
CAGR -0.9%, annualized volatility 71.6%, maximum drawdown -81.1%. Over the
floor-engine window (2022-08-12 to 2026-06-10) computed analytically:
CAGR +11.93%, maximum drawdown -74.20%, Calmar 0.161. Either way the naked
short carries catastrophic drawdown risk; the decay harvest is real but the
path is untradeable.

## Code and reproduction

- `scripts/strategies/double_short.py` (frozen historical record):
  `venv/bin/python3 scripts/strategies/double_short.py`
- Figures: `observations/strategies/double_short/`; equity CSV:
  `results/double_short/equity.csv`
- The analytic curve also appears in the floor-engine lineage comparison
  (`scripts/strategies/floor_engine/stats.py`, `naked_short_equity`).
