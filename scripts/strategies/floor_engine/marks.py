"""No-arbitrage banded mark-to-market for option legs.

Thin TSLL chains carry stale closing quotes that occasionally violate bounds
which must hold in any arbitrage-free market. Marks are therefore confined
to their no-arbitrage bands; both clamps only remove prices that were never
tradeable:

  Floor (every leg): max(quote, own intrinsic). For the long call this is
  the value floor, realizable by exercise; for the short put liability it is
  the conservative direction and what assignment realizes.

  Ceiling (put legs only): the chained American parity bound
  P(t) <= C_c(t) + K_c - S_t, computed from the SAME tranche's freshly
  marked call leg. Since K_c >= K_p, this ceiling provably never falls below
  put intrinsic, so the band is always well defined.

The continuous per-tranche floor (engine.py) is a theorem only under these
bands; without the put-side ceiling, stale quotes create phantom floor
violations that are data artifacts, not economic losses.
"""
import pandas as pd


def mtm_leg(md, leg, d, cap=None):
    """Mark one leg on date d, confined to its no-arbitrage band.

    leg: dict with keys 'kind' ('C'/'P'), 'id', 'K', 'e' (expiry),
         'px' (last mark, used when no quote exists on d).
    cap: optional ceiling (put legs: pass px_call + K_c - S_t).
    Past expiry the leg is worth exactly intrinsic.
    """
    s_now = float(md.tsll_spot.loc[d])
    intrinsic = max(s_now - leg["K"], 0.0) if leg["kind"] == "C" else max(leg["K"] - s_now, 0.0)
    if d > leg["e"]:
        return intrinsic
    lut = md.call_lut if leg["kind"] == "C" else md.put_lut
    v = lut.get((leg["id"], d))
    px = max(float(v), intrinsic) if (v is not None and not pd.isna(v)) else max(leg["px"], intrinsic)
    if cap is not None:
        px = min(px, cap)
    return px
