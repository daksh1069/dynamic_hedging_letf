# Strategy 4: Drawdown-Constrained Convexity Protection (Final)

The final deliverable: a multi-tranche portfolio version of convexity
protection whose maximum drawdown is capped by a closed-form, model-free
bound, with an optional put-financed collar. Full derivations in
`latex/tsla_tsll_hedging_report.tex`; production code in
`scripts/strategies/floor_engine/`.

## Notation

Latin letters by design; alpha, gamma, and delta carry standard meanings in
finance (excess return, option Greeks) that would collide here.

| Symbol | Code constant | Meaning | Headline value |
|---|---|---|---|
| l | `LOSS_BUDGET` | per-cycle loss budget, fraction of settled equity | 8% |
| d | `DD_LIMIT` | drawdown limit vs the settled high water mark | 8.2% |
| g | `GAIN_TRIGGER` | cycle ceiling on daily marks | 8% |
| q | `COST_GATE` | max net floor cost per dollar protected | 15% |

All four are a-priori choices registered before the data runs; q in
particular is not identifiable from ~20 tranches and must not be re-fit.

## Construction (one paragraph each)

**Tranche.** Short n TSLL shares at S0, long n/100 TSLL calls at strike K_c
(premium C), optionally short n/100 same-expiry TSLL puts at K_p (premium
P_p collected). Exact reservation, valid at any strike: L = n(C + K_c - S0),
collar L' = L - n P_p. Via no-arbitrage bounds on American options (call at
least intrinsic; put-call parity; vertical spread), each tranche's mark is
at least -L' at every instant, not only at expiry. Marks are confined to
those no-arbitrage bands (`marks.py`); stale thin-chain quotes outside the
bands were never tradeable prices.

**Settled accounting.** The budget and high water mark ATH* are keyed only
to settled checkpoints (all tranches closed), never daily marks, removing
mark-driven procyclicality. Reservations accumulate per cycle:
sum(L_i) <= min(l E0, E0 - (1 - d) ATH*). All tranches in a cycle share (or
precede) one anchor expiry, so every guarantee co-fires at one settlement.

**Master equation.** The ceiling settles all tranches when marks reach
E0 (1 + g), converting peaks into checkpoints. Result:
MaxDD <= (d + g) / (1 + g) = 15.0% at the headline configuration. The
one-parameter risk dial x = l = d = g gives bound 2x/(1+x).

**Favorability gate.** Deploy only if (C + K_c - S0 - P_p)/S0 <= q. A
tranche breaks even only if TSLL falls by more than its net floor cost, so
the gate refuses to pay more than 15 cents per dollar protected. Parking
never hurts the floor. Ablation: removing the gate cut CAGR from 14.0% to
4.9%.

**Collar.** Selling the rich TSLL crash insurance (median ~10% of spot for
10-30% OTM, 93% same-expiry pairing with call anchors) cuts the net floor
cost by roughly a third, raising deployment and returns at the cost of
capping per-cycle crash gains, which the tight ceiling was already capping
in practice. Selling puts does not contradict the earlier "puts not needed"
finding, which was about buying them.

**Borrow.** Daily fee b_t/252 times short market value, from the quarterly
approximate series in `scripts/backtest/borrow_rates.py`, flows into equity
so decisions see it. Borrow is not premium-boundable, so the floor acquires
a tracked leak (E0 branch: borrow since the last checkpoint; ATH* branch:
borrow since ATH* was set) and the bound gains dB/(ATH*(1+g)). Both remain
theorems because B is measured.

## Headline results (2022-08-12 to 2026-06-10, bound 15.0%)

| Variant | CAGR | Sharpe | MaxDD | Calmar |
|---|---|---|---|---|
| Collar, frictionless | +15.69% | 0.899 | -12.29% | 1.277 |
| Collar with borrow (realized) | +10.41% | 0.680 | -15.21% | 0.684 |
| Call-only, frictionless | +14.00% | 0.841 | -11.29% | 1.240 |
| Call-only with borrow (realized) | +13.42% | 0.706 | -15.44% | 0.869 |
| Static hybrid (prior best, reference) | +19.42% | 0.928 | -19.70% | 0.986 |

Verification: zero leak-adjusted floor violations across every full-period
variant, both holdout halves per variant, and all seven risk-dial
configurations (960 days each). Realized drawdowns used 75 to 96 percent of
their guaranteed envelopes, so the bound is informative, not vacuous.

Key qualitative findings: the ranking flips under realized borrow (the
collar's higher deployment pays proportionally more fees, and most of its
4.78 pp/yr drag is path divergence rather than direct cost); returns are
crash-regime concentrated (holdout H1 ~+33%/yr, benign H2 roughly flat),
which is the intended profile for a hedge; and risk stops paying beyond
x ~ 10% on the dial.

## Honest limitations

Bid-ask spreads are the principal unmodeled cost (dataset is closing prices
by design) and are adverse on both option legs. Borrow rates are quarterly
chart-read approximations. Trades execute at the observed close. Position
size is not capped against contract volume. TSLL distributions to the share
lender are not modeled. Daily closes can gap past trigger lines by one day's
move. The bound column is a theorem given these assumptions; every CAGR
column is one 3.8-year history.

## Code and reproduction

- Production package: `scripts/strategies/floor_engine/` (`config`, `data`,
  `selection`, `marks`, `portfolio_engine`, `stats`, `verify`, `plots`,
  `reproduce_results`)
- Reproduce everything: `venv/bin/python3 scripts/strategies/floor_engine/reproduce_results.py`
  (writes figures to `observations/strategies/final/`, tables and equity
  CSVs to `results/floor_engine/`, and fails loudly if any guarantee or the
  static-hybrid reproduction check does not hold)
- Research record: `scripts/utils/sandbox/prod_experiments/final_guaranteed_floor_project.ipynb` and
  the sandbox notebooks alongside it
- Write-up: `latex/tsla_tsll_hedging_report.tex`
