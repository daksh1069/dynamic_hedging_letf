# Strategy 2: Delta-Adjusted Arbitrage (Rejected)

## Idea

Long h times TSLA against short $1 TSLL. Sizing the long TSLA leg to TSLL's
realized leverage neutralizes most day-to-day market exposure, leaving the
LETF's tracking drag and decay as the harvested return, while the long TSLA
leg shields against the rally that would blow up a naked short.

## Variants

- Primary: dynamic hedge ratio h_t equal to the rolling 63-day realized beta
  of TSLL on TSLA, lagged one day, rebalanced daily.
- Sensitivities: static h = 2.0; financing cost sweeps on the ~2.8x gross
  notional; a real-data estimate using the TSLL borrow-fee series for the
  short leg plus an assumed margin-loan rate on the long leg.

## Headline result, and why it is rejected

On paper the dynamic variant was the best number in the project: CAGR 15.5%,
annualized volatility 5.4%, Sharpe 2.69, maximum drawdown -10.0%, Calmar 1.54
on the common window. Two findings invalidated it as a deliverable:

1. Look-ahead bias (main report, Section 10). The realized-beta hedge ratio,
   even lagged one day, embeds information about the return-generating window
   that a live trader would not have exploited the same way; correcting the
   estimation windows materially degrades the strategy, and the headline
   backtest overstates achievable performance. The main report's Remediation
   Attempts (Section 9) document the correction attempts and their failure.
2. Cost fragility. The edge requires rebalancing roughly 2.8x gross notional
   daily at near-zero cost while TSLL is frequently hard to borrow; realistic
   borrow and margin costs consume much of the edge.

Consequence for later work: this project treats delta-arbitrage style hedge
ratios as out of bounds, and the final engine (doc 04) was built model-free,
with no estimated hedge ratios anywhere. The strategy is retained in the
repository as the historical record and as the motivating cautionary example
for the pre-registration discipline used later.

## Code and reproduction

- `scripts/strategies/delta_arb.py` (frozen historical record):
  `venv/bin/python3 scripts/strategies/delta_arb.py`
- Figures: `observations/strategies/delta_arb/`; equity CSV:
  `results/delta_arb/equity.csv`
- Cross-strategy table: `observations/strategies/results.txt` (produced by
  `scripts/strategies/compare_all.py`)
