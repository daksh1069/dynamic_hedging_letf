"""Performance metrics and reference strategies for comparison."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from options_selection import select_contract, bs_delta                        # noqa: E402

from config import TARGET_DTE, MAX_DTE, R_RF                                   # noqa: E402
from selection import select_tsll_relaxed                                      # noqa: E402


def quick_stats(eq: pd.Series, label: str) -> dict:
    """CAGR / Sharpe / MaxDD / Calmar for an equity curve starting at 1.0."""
    ret    = eq.pct_change().dropna()
    n_yrs  = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr   = eq.iloc[-1] ** (1.0 / n_yrs) - 1.0
    sharpe = ret.mean() / ret.std() * 252 ** 0.5 if ret.std() > 0 else float("nan")
    maxdd  = float((eq / eq.cummax() - 1.0).min())
    return {"Strategy": label, "CAGR": cagr, "Sharpe": sharpe, "MaxDD": maxdd,
            "Calmar": cagr / abs(maxdd) if maxdd != 0 else float("nan")}


def naked_short_equity(md, sim_dates=None) -> pd.Series:
    """Benchmark: short 1/S0 TSLL shares, unhedged, no rebalancing."""
    dates = md.sim_dates if sim_dates is None else sim_dates
    s0 = float(md.tsll_spot.loc[dates[0]])
    return 2.0 - md.tsll_spot.loc[dates] / s0


def static_hybrid_equity(md, sim_dates=None, notional=1.0, lever=2.0) -> pd.Series:
    """Faithful reproduction of the main report's static convexity
    protection (guaranteed_floor_hybrid_sandbox.ipynb): a FIXED share count
    forever, three-tier call fill, cycles held to expiry. No deleveraging,
    no budget, no ceiling, no gate, no cash interest, no borrow.

    Requires md to be loaded with load_lineage_extras() (TSLA side).
    Reproduces the published +19.42% CAGR / -19.70% MaxDD exactly.
    """
    dates = md.sim_dates if sim_dates is None else sim_dates
    s0    = float(md.tsll_spot.loc[dates[0]])
    n_sh  = notional / s0
    n_ct  = n_sh / 100
    equity = pd.Series(index=dates, dtype=float)
    pos_l = pos_a = None
    opnl = spnl = 0.0
    s_prev = s0

    def mtm(pos, d):
        lut  = md.call_lut if pos["ul"] == "tsll" else md.tsla_lut
        spot = md.tsll_spot if pos["ul"] == "tsll" else md.tsla_spot
        if d > pos["e"]:
            return max(float(spot.loc[d]) - pos["K"], 0.0)
        px = lut.get((pos["id"], d))
        return float(px) if (px is not None and not pd.isna(px)) else pos["px"]

    for d in dates:
        s_t   = float(md.tsll_spot.loc[d])
        spnl += n_sh * (s_prev - s_t)
        s_prev = s_t
        exp   = pos_l["e"] if pos_l is not None else (pos_a["e"] if pos_a is not None else None)
        need  = (exp is None) or (d > exp)
        for pos in (pos_l, pos_a):
            if pos is not None:
                px = mtm(pos, d)
                opnl += pos["n"] * 100 * (px - pos["px"])
                pos["px"] = px
        if need:
            pos_l = pos_a = None
            s_a   = float(md.tsla_spot.loc[d])
            sig_l = float(md.tsll_sigma.loc[d]) if d in md.tsll_sigma.index else 0.5
            sig_a = float(md.tsla_sigma.loc[d]) if d in md.tsla_sigma.index else 0.5
            row = select_contract(md.tsll_calls, md.tsll_spot, d, "ATM",
                                  TARGET_DTE, max_dte=MAX_DTE)
            if row is not None:
                pos_l = {"ul": "tsll", "id": row["raw_id"], "K": float(row["strike"]),
                         "e": row["expiry"], "n": n_ct, "px": float(row["px_last"])}
            else:
                rr = select_tsll_relaxed(md, d)
                if rr is not None:
                    exp_r = pd.Timestamp(rr["expiry"])
                    pos_l = {"ul": "tsll", "id": rr["raw_id"], "K": float(rr["strike"]),
                             "e": exp_r, "n": n_ct, "px": float(rr["px_last"])}
                    t_l = max((exp_r - d).days / 365.25, 1 / 365.25)
                    dl  = bs_delta(s_t, float(rr["strike"]), t_l, R_RF, sig_l)
                    gap = max(lever * n_sh * s_t - dl * n_ct * 100 * s_t, 0.0)
                    if gap > 0:
                        ra = select_contract(md.tsla_calls, md.tsla_spot, d, "ATM",
                                             TARGET_DTE, max_dte=MAX_DTE)
                        if ra is not None:
                            t_a = (ra["expiry"] - d).days / 365.25
                            da  = bs_delta(s_a, float(ra["strike"]), t_a, R_RF, sig_a)
                            pos_a = {"ul": "tsla", "id": ra["raw_id"],
                                     "K": float(ra["strike"]), "e": ra["expiry"],
                                     "n": gap / (max(da, 0.01) * 100 * s_a),
                                     "px": float(ra["px_last"])}
                else:
                    ra = select_contract(md.tsla_calls, md.tsla_spot, d, "ATM",
                                         TARGET_DTE, max_dte=MAX_DTE)
                    if ra is not None:
                        t_a = (ra["expiry"] - d).days / 365.25
                        da  = bs_delta(s_a, float(ra["strike"]), t_a, R_RF, sig_a)
                        pos_a = {"ul": "tsla", "id": ra["raw_id"],
                                 "K": float(ra["strike"]), "e": ra["expiry"],
                                 "n": (lever * n_sh * s_t) / (max(da, 0.01) * 100 * s_a),
                                 "px": float(ra["px_last"])}
        equity.loc[d] = notional + spnl + opnl
    return equity
