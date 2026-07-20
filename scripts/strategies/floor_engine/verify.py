"""Verification of the pre-registered guarantees against realized paths.

Frictionless floor (theorem):
    E(t) >= max((1 - l) E0, (1 - d) ATH*)

With borrow the floor acquires a tracked leak, with the leak term depending
on which branch binds (a naive per-cycle adjustment produces phantom
violations on all-cash recovery days):
    E(t) >= max( (1 - l) E0  - B_cycle(t),
                 (1 - d) ATH* - [B(t) - B(t_ATH*)] )
and the drawdown bound becomes (d + g)/(1 + g) + max dB / (ATH* (1 + g))
with dB = B(t) - B(t_ATH*). Both remain theorems because B is measured.
"""
import numpy as np
import pandas as pd

from config import LOSS_BUDGET, DD_LIMIT, GAIN_TRIGGER, master_bound


def verify(result, loss_budget=LOSS_BUDGET, dd_limit=DD_LIMIT,
           gain_trigger=GAIN_TRIGGER, label="") -> dict:
    """Check floor adherence and the drawdown bound for one EngineResult.

    Returns a dict of verification facts; 'floor_violations' must be 0 for
    the guarantee to have held on this path.
    """
    eq, diag = result.equity, result.diag
    d_b = diag["borrow_cum"] - diag["borrow_at_ath"]
    adj_floor = np.maximum(
        (1.0 - loss_budget) * diag["E0"] - diag["borrow_cycle"],
        (1.0 - dd_limit) * diag["ath_star"] - d_b,
    )
    maxdd     = float((eq / eq.cummax() - 1.0).min())
    bound     = master_bound(dd_limit, gain_trigger)
    bound_adj = bound + float((d_b / (diag["ath_star"] * (1.0 + gain_trigger))).max())
    return {
        "label": label,
        "floor_violations": int((eq < adj_floor - 1e-9).sum()),
        "raw_floor_days_below": int((eq < diag["floor"] - 1e-9).sum()),
        "days": len(eq),
        "realized_maxdd": maxdd,
        "bound_frictionless": bound,
        "bound_leak_adjusted": bound_adj,
        "within_bound": abs(maxdd) <= bound_adj + 1e-9,
        "max_leak_dB": float(d_b.max()),
        "max_cycle_borrow": float(diag["borrow_cycle"].max()),
    }


def print_report(v: dict) -> None:
    print(f"=== {v['label']} ===")
    print(f"Leak-adjusted floor violations (theorem): {v['floor_violations']} / "
          f"{v['days']} days  |  raw-floor days below (informational): "
          f"{v['raw_floor_days_below']}")
    status = "WITHIN BOUND" if v["within_bound"] else "BOUND EXCEEDED -- investigate"
    print(f"MaxDD: realized {v['realized_maxdd']:.2%} vs leak-adjusted bound "
          f"-{v['bound_leak_adjusted']:.2%} (frictionless -{v['bound_frictionless']:.1%}) "
          f"-> {status}")
    print(f"Max ATH-branch borrow leak dB: {v['max_leak_dB']:.5f} "
          f"({v['max_leak_dB'] * 100:.2f}% of notional) | "
          f"max single-cycle borrow: {v['max_cycle_borrow'] * 100:.2f}%\n")


def verification_table(vs) -> pd.DataFrame:
    return pd.DataFrame(vs).set_index("label")
