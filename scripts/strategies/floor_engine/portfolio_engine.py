"""The drawdown-constrained convexity protection engine.

Core invariants (derivations in latex/tsla_tsll_hedging_report.tex):

  Per-tranche reservation, exact at any strike:
      call-only  L  = n * (C + K_c - S0)
      collar     L' = n * (C + K_c - S0 - P_p)
  and each tranche's mark-to-market is >= -L (resp. -L') at EVERY instant,
  via the no-arbitrage bands enforced in marks.py.

  Settled accounting: the budget and the high water mark ATH* are keyed
  exclusively to settled checkpoints (all tranches closed; all-cash days are
  trivially settled), never to daily marks. This removes mark-driven
  procyclicality. Reservations are CUMULATIVE per cycle and reset only at
  checkpoints; releasing them on mid-cycle closes would let one cycle's
  cumulative risk exceed the loss budget.

  Cycle ceiling: all tranches settle when daily marks reach E0 * (1 + g),
  converting equity peaks into checkpoints. Together these give
      E(t)  >= max((1 - l) E0, (1 - d) ATH*)          (frictionless)
      MaxDD <= (d + g) / (1 + g)                      (frictionless)
  With borrow fees the floor acquires a tracked leak; see verify.py.

Every tranche's expiry is on or before the cycle anchor expiry, so all
guarantees in a cycle co-fire at one settlement date.
"""
from dataclasses import dataclass

import pandas as pd

from config import (LOSS_BUDGET, DD_LIMIT, GAIN_TRIGGER, COST_GATE, R_RF_D,
                    MIN_NET_COST_FRAC, MIN_NOTIONAL_FRAC)
from marks import mtm_leg
from selection import select_call, select_put


@dataclass
class EngineResult:
    equity:        pd.Series      # daily equity (notional = 1)
    deployed_frac: pd.Series      # short notional / equity, daily
    log:           pd.DataFrame   # one row per tranche
    diag:          pd.DataFrame   # floor, E0, ATH*, borrow trackers, daily
    checkpoints:   pd.DataFrame   # settlement dates and types


def simulate(md, sim_dates=None, loss_budget=LOSS_BUDGET, dd_limit=DD_LIMIT,
             gain_trigger=GAIN_TRIGGER, cost_gate=COST_GATE,
             use_puts=True, use_borrow=False, notional=1.0) -> EngineResult:
    """Run the engine over sim_dates (defaults to md.sim_dates).

    use_puts=False  -> call-only variant (no collar leg).
    use_borrow=True -> daily short-borrow fee b_t/252 * n_sh * S_t flows into
                       equity, so sizing/ceiling/checkpoint decisions see it
                       (realized returns, not an ex-post overlay).
    """
    dates = md.sim_dates if sim_dates is None else sim_dates

    equity        = pd.Series(index=dates, dtype=float)
    deployed_frac = pd.Series(index=dates, dtype=float)
    floor_s       = pd.Series(index=dates, dtype=float)
    e0_s          = pd.Series(index=dates, dtype=float)
    ath_s         = pd.Series(index=dates, dtype=float)
    bcyc_s        = pd.Series(index=dates, dtype=float)
    bcum_s        = pd.Series(index=dates, dtype=float)
    bath_s        = pd.Series(index=dates, dtype=float)

    total_spnl = total_opnl = total_cpnl = total_bpnl = 0.0
    cycle_borrow    = 0.0
    b_at_ath        = 0.0            # cumulative borrow when ATH* was last set
    s_prev          = float(md.tsll_spot.loc[dates[0]])
    undeployed_cash = notional
    total_n_sh      = 0.0
    open_positions  = []
    e0              = notional
    ath_star        = notional
    anchor_e        = None
    cycle_reserved  = 0.0
    log             = []
    checkpoints     = []

    for d in dates:
        s_t = float(md.tsll_spot.loc[d])

        # Daily accruals on yesterday's holdings
        total_spnl += total_n_sh * (s_prev - s_t)
        total_cpnl += undeployed_cash * R_RF_D
        if use_borrow and total_n_sh > 0:
            fee = float(md.borrow.loc[d]) / 252.0 * total_n_sh * s_t
            total_bpnl   += fee
            cycle_borrow += fee
        s_prev = s_t

        # Mark every leg; the put's parity ceiling uses the fresh call mark
        for pos in open_positions:
            call_leg = pos["legs"][0]
            px_c = mtm_leg(md, call_leg, d)
            total_opnl += call_leg["side"] * pos["n_sh"] * (px_c - call_leg["px"])
            call_leg["px"] = px_c
            if len(pos["legs"]) > 1:
                put_leg = pos["legs"][1]
                px_p = mtm_leg(md, put_leg, d, cap=px_c + call_leg["K"] - s_t)
                total_opnl += put_leg["side"] * pos["n_sh"] * (px_p - put_leg["px"])
                put_leg["px"] = px_p

        equity_now = notional + total_spnl + total_opnl + total_cpnl - total_bpnl

        # Cycle ceiling: settle everything at E0 * (1 + g)
        ceiling_hit = bool(open_positions) and equity_now >= e0 * (1.0 + gain_trigger)

        still_open = []
        for pos in open_positions:
            if ceiling_hit or d > pos["e"]:
                total_n_sh      -= pos["n_sh"]
                # Return EXACTLY the entry collateral; price movement is
                # already fully captured via total_spnl (returning n*S_exit
                # would double count it and corrupt cash availability).
                undeployed_cash += pos["capital_at_open"]
                log.append({"start": pos["start"], "end": d, "n_sh": pos["n_sh"],
                            "reserved": pos["reserved"], "tier": pos["tier"],
                            "net_cost_pct": pos["net_cost_pct"],
                            "has_put": pos["has_put"],
                            "ceiling": ceiling_hit, "open_at_end": False})
            else:
                still_open.append(pos)
        open_positions = still_open

        # Checkpoint: all settled (all-cash days are trivially settled)
        if not open_positions:
            if anchor_e is not None or ceiling_hit:
                checkpoints.append({"date": d, "E0": equity_now,
                                    "type": "ceiling" if ceiling_hit else "expiry"})
            e0 = equity_now
            if equity_now > ath_star:
                ath_star = equity_now
                b_at_ath = total_bpnl       # ATH-branch borrow leak measures from here
            anchor_e       = None
            cycle_reserved = 0.0
            cycle_borrow   = 0.0

        # Deployment: budget from settled values, cumulative per cycle
        budget = min(loss_budget * e0, e0 - (1.0 - dd_limit) * ath_star) - cycle_reserved
        if budget > 0 and undeployed_cash > 1e-9:
            new_pos = _try_open(md, d, s_t, e0, budget, undeployed_cash,
                                anchor_e, cost_gate, use_puts)
            if new_pos is not None:
                total_n_sh      += new_pos["n_sh"]
                undeployed_cash -= new_pos["capital_at_open"]
                cycle_reserved  += new_pos["reserved"]
                open_positions.append(new_pos)
                if anchor_e is None:
                    anchor_e = new_pos["e"]

        equity.loc[d]        = equity_now
        deployed_frac.loc[d] = (total_n_sh * s_t) / equity_now if equity_now > 0 else 0.0
        floor_s.loc[d]       = max((1.0 - loss_budget) * e0, (1.0 - dd_limit) * ath_star)
        e0_s.loc[d]          = e0
        ath_s.loc[d]         = ath_star
        bcyc_s.loc[d]        = cycle_borrow
        bcum_s.loc[d]        = total_bpnl
        bath_s.loc[d]        = b_at_ath

    for pos in open_positions:
        log.append({"start": pos["start"], "end": dates[-1], "n_sh": pos["n_sh"],
                    "reserved": pos["reserved"], "tier": pos["tier"],
                    "net_cost_pct": pos["net_cost_pct"], "has_put": pos["has_put"],
                    "ceiling": False, "open_at_end": True})

    diag = pd.DataFrame({"floor": floor_s, "E0": e0_s, "ath_star": ath_s,
                         "borrow_cycle": bcyc_s, "borrow_cum": bcum_s,
                         "borrow_at_ath": bath_s})
    return EngineResult(equity, deployed_frac, pd.DataFrame(log), diag,
                        pd.DataFrame(checkpoints))


def _try_open(md, d, s_t, e0, remaining_budget, undeployed_cash,
              anchor_e, cost_gate, use_puts):
    """Open one tranche from the pool, or return None.

    Sizing: the exact per-share reservation w = C + K_c - S0 - P_p consumes
    remaining_budget, capped by available cash; skip if the resulting
    notional is below MIN_NOTIONAL_FRAC of settled equity (anti-dust) or the
    net floor cost fraction w/S exceeds the cost gate q (park instead;
    parking never hurts the floor).
    """
    row, kind = select_call(md, d, anchor_e)
    if row is None:
        return None
    c_px, k_c = float(row["px_last"]), float(row["strike"])
    expiry    = pd.Timestamp(row["expiry"])

    put = select_put(md, d, expiry) if use_puts else None
    p_px = float(put["px_last"]) if put is not None else 0.0
    k_p  = float(put["strike"])  if put is not None else float("nan")

    w = c_px + k_c - s_t - p_px
    if put is not None and w < MIN_NET_COST_FRAC * s_t:
        put, p_px, k_p = None, 0.0, float("nan")     # stale put quote: call-only
        w = c_px + k_c - s_t
    w = max(w, 1e-9)

    if w / s_t > cost_gate:
        return None                                   # unfavorable: park

    n_sh = min(remaining_budget / w, undeployed_cash / s_t)
    if n_sh <= 0 or n_sh * s_t < MIN_NOTIONAL_FRAC * e0:
        return None

    legs = [{"side": +1, "kind": "C", "id": row["raw_id"], "K": k_c,
             "e": expiry, "px": c_px}]
    if put is not None:
        legs.append({"side": -1, "kind": "P", "id": put["raw_id"], "K": k_p,
                     "e": expiry, "px": p_px})
    return {"legs": legs, "e": expiry, "n_sh": n_sh,
            "reserved": n_sh * w, "capital_at_open": n_sh * s_t,
            "start": d, "tier": f"TSLL {kind}",
            "net_cost_pct": w / s_t * 100, "has_put": put is not None}
