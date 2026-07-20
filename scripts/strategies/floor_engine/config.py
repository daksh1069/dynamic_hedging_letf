"""Engine parameters and notation.

Notation (deliberately Latin: alpha, gamma and delta carry standard meanings
in finance, excess return and the option Greeks, that would collide here):

    l  (LOSS_BUDGET)   per-cycle cumulative worst-case loss budget, as a
                       fraction of settled equity E0
    d  (DD_LIMIT)      drawdown limit against the settled high water mark ATH*
    g  (GAIN_TRIGGER)  cycle ceiling: settle all tranches when daily marks
                       reach E0 * (1 + g)
    q  (COST_GATE)     favorability gate: a tranche may open only if its net
                       floor cost (C + K_c - S0 - P_p) / S0 is at most q

Master equation: guaranteed MaxDD <= (d + g) / (1 + g). The headline
configuration below gives a bound of exactly 15.0 percent. The one-parameter
risk dial sets x = l = d = g, with bound 2x / (1 + x).

All four headline values are a-priori choices, registered before the data
runs; none was tuned on the backtest (q in particular is not identifiable
from ~20 tranches and must not be re-fit).
"""

# Headline configuration (guaranteed MaxDD bound = (d+g)/(1+g) = 15.0%)
LOSS_BUDGET  = 0.08    # l
DD_LIMIT     = 0.082   # d
GAIN_TRIGGER = 0.08    # g
COST_GATE    = 0.15    # q

# Risk-free rate (annualized) credited daily on undeployed cash
R_RF   = 0.05
R_RF_D = R_RF / 252

# Contract selection
TARGET_DTE        = 90     # target days to expiry for a fresh anchor
MAX_DTE           = 110    # anchor upper bound
MIN_DTE_STRICT    = 60     # anchor lower bound ("strict" window, project-wide intent)
RELAX_MIN_DTE     = 45     # relaxed fallback window
RELAX_MAX_DTE     = 120
RELAX_MONEY_LO    = 0.80   # relaxed fallback moneyness band
RELAX_MONEY_HI    = 1.20
MIN_TOPUP_DTE     = 20     # top-ups shorter than this are not worth real-world costs

# Collar put leg (a-priori rules)
PUT_MONEY_LO      = 0.70   # 10-30 percent out of the money
PUT_MONEY_HI      = 0.90
PUT_TARGET_MONEY  = 0.80   # select the put closest to 20 percent OTM
MIN_NET_COST_FRAC = 0.005  # net cost below this => stale put quote => call-only

# Anti-dust gate: skip tranches smaller than this fraction of E0 in notional
MIN_NOTIONAL_FRAC = 0.01

# Risk dial ladder (x = l = d = g)
RISK_DIAL_LADDER = [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.15]


def master_bound(d: float = DD_LIMIT, g: float = GAIN_TRIGGER) -> float:
    """Guaranteed MaxDD bound (d + g) / (1 + g), frictionless."""
    return (d + g) / (1.0 + g)


def dial_bound(x: float) -> float:
    """Risk-dial bound 2x / (1 + x) for x = l = d = g."""
    return 2.0 * x / (1.0 + x)
