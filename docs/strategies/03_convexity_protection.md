# Strategy 3: Convexity Protection (Static Guaranteed Floor)

The best static approach in the project. Source of record:
`scripts/utils/sandbox/prod_experiments/guaranteed_floor_hybrid_sandbox.ipynb`.

## Implementation

Short a FIXED share count of TSLL forever: `n_shares = notional / S_inception`,
never resized. Each cycle, buy exactly `n_shares / 100` call contracts
(share-matched) and hold the cycle to the contract's own expiry. Share-matching
on the same instrument makes the worst case algebraic: at expiry the cycle
cannot lose more than the premium paid, because above the strike the call
payoff cancels the short share for share.

Three-tier contract fill per cycle:

| Tier | Condition | Label | Floor |
|---|---|---|---|
| 1 | TSLL call, strict ATM, 60-110 DTE | TSLL full | guaranteed |
| 2 | TSLL call, relaxed 45-120 DTE, 0.80-1.20 moneyness, plus TSLA calls sized to the remaining dollar-delta gap | TSLL+TSLA partial | guaranteed on the TSLL leg |
| 3 | No TSLL call at all: TSLA calls sized delta-neutral for the full 2x position | TSLA only | best effort, no guarantee |

Marks: daily `px_last` per contract (carried when no trade printed), intrinsic
value after expiry. No deleveraging, no risk budget, no cash interest, no
borrow costs. Simulation starts at the first date TSLL options exist
(2022-08-12).

## Result (2022-08-12 to 2026-06-10)

CAGR +19.42%, Sharpe 0.928, maximum drawdown -19.70%, Calmar 0.986. The floor
held on every guaranteed cycle (zero breaches). This is the "prior best"
reference row in every later comparison, and the starting point that the
drawdown-constrained engine (doc 04) extends.

## Code and reproduction

- Research record: `scripts/utils/sandbox/prod_experiments/guaranteed_floor_hybrid_sandbox.ipynb`
- Production port (same logic, asserts the published +19.42% CAGR):
  `venv/bin/python3 scripts/strategies/static_guaranteed_floor.py`
  Figure to `observations/strategies/static_guaranteed_floor/`, equity CSV to
  `results/static_guaranteed_floor/equity.csv`. Core simulation:
  `scripts/strategies/floor_engine/stats.py` (`static_hybrid_equity`).

Related: the earlier fixed-premium-spend Cost-Benefit Analysis
(`scripts/backtest/cba_backtest.py`) is indexed in `docs/results.md`.
