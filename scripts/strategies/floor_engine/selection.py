"""Contract selection: anchors, expiry-matched top-ups, and the collar put.

Anchor selection reuses the project-wide select_contract picker
(scripts/backtest/options_selection.py, ATM bucket) with the strict
60-110 DTE window enforced here (select_contract itself has no minimum-DTE
parameter), falling back to a relaxed 45-120 DTE / 0.80-1.20 moneyness
window. The exact reservation formula holds for ANY strike, so the relaxed
fallback keeps the full floor guarantee.

Top-ups must expire on or before the cycle anchor (exact expiry match
preferred) so every open tranche settles at one checkpoint; that shared
settlement date is what makes the aggregate floor enforceable.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from options_selection import select_contract                                  # noqa: E402

from config import (TARGET_DTE, MAX_DTE, MIN_DTE_STRICT, MIN_TOPUP_DTE,        # noqa: E402
                    RELAX_MIN_DTE, RELAX_MAX_DTE, RELAX_MONEY_LO, RELAX_MONEY_HI,
                    PUT_MONEY_LO, PUT_MONEY_HI, PUT_TARGET_MONEY)


def select_tsll_relaxed(md, d):
    """Most-ATM TSLL call within the relaxed DTE/moneyness window, or None."""
    day = md.tsll_cvol[md.tsll_cvol["date"] == d]
    w = day[(day["dte"] >= RELAX_MIN_DTE) & (day["dte"] <= RELAX_MAX_DTE)
            & (day["moneyness"] >= RELAX_MONEY_LO) & (day["moneyness"] <= RELAX_MONEY_HI)]
    if w.empty:
        return None
    w = w.copy()
    w["ad"] = (w["moneyness"] - 1.0).abs()
    w["dd"] = (w["dte"] - TARGET_DTE).abs()
    return w.sort_values(["ad", "dd"]).iloc[0]


def select_expiry_match_call(md, d, anchor_e, min_dte=MIN_TOPUP_DTE):
    """Top-up call: expiry ON the anchor date if one trades today, else the
    nearest expiry BEFORE it (never after, which would outlive the shared
    settlement checkpoint)."""
    day = md.tsll_cvol[md.tsll_cvol["date"] == d]
    w = day[(day["expiry"] <= anchor_e) & (day["dte"] >= min_dte)
            & (day["moneyness"] >= RELAX_MONEY_LO) & (day["moneyness"] <= RELAX_MONEY_HI)]
    if w.empty:
        return None
    w = w.copy()
    w["ed"] = (anchor_e - w["expiry"]).dt.days   # 0 = exact anchor match, preferred
    w["ad"] = (w["moneyness"] - 1.0).abs()
    return w.sort_values(["ed", "ad"]).iloc[0]


def select_call(md, d, anchor_e):
    """Full call-leg selection. Returns (row, kind) with kind in
    {'anchor', 'anchor-rlx', 'top-up'}, or (None, None)."""
    if anchor_e is None:
        row = select_contract(md.tsll_calls, md.tsll_spot, d, "ATM",
                              TARGET_DTE, max_dte=MAX_DTE)
        if row is not None and (row["expiry"] - d).days >= MIN_DTE_STRICT:
            return row, "anchor"
        rr = select_tsll_relaxed(md, d)
        if rr is not None:
            return rr, "anchor-rlx"
        return None, None
    rr = select_expiry_match_call(md, d, anchor_e)
    if rr is not None:
        return rr, "top-up"
    return None, None


def select_put(md, d, expiry):
    """Collar put: same expiry as the call leg, moneyness in
    [PUT_MONEY_LO, PUT_MONEY_HI], closest to PUT_TARGET_MONEY. Or None."""
    pday = md.tsll_pvol[(md.tsll_pvol["date"] == d)
                        & (md.tsll_pvol["expiry"] == expiry)
                        & (md.tsll_pvol["moneyness"] >= PUT_MONEY_LO)
                        & (md.tsll_pvol["moneyness"] <= PUT_MONEY_HI)]
    if pday.empty:
        return None
    pday = pday.copy()
    pday["td"] = (pday["moneyness"] - PUT_TARGET_MONEY).abs()
    return pday.sort_values("td").iloc[0]
