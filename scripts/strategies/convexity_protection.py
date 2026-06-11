"""
Strategy 3 -- Convexity Protection: short $1 TSLL + long TSLA call(s).

The long call's hard payoff cap removes the need for daily delta rebalancing
(unlike Strategy 2): a TSLA rally that would blow up a naked short TSLL is
capped by the call's payoff, while in calm/down markets TSLL's decay is still
captured almost in full (we only spend `HEDGE_PCT` of notional on premium).

Mechanics:
  - TSLL leg: buy & hold short $1 notional from inception (Strategy 1's
    primary baseline, equity = 2 - cumprod(1+r_TSLL)) -- fixed, never reset.
    This is the point of the call hedge: it removes the *need* for the
    rebalancing-friction-inducing resets that wrecked Strategy 1's
    "Rebalanced Monthly" sensitivity (CAGR -67%, max DD -99.8%).
  - Call leg: at each monthly roll date, spend HEDGE_PCT of the (fixed) $1
    notional on a fresh TSLA call (or call spread) with DTE closest to
    TARGET_DTE in the requested moneyness bucket(s)
    (scripts/backtest/options_selection.py):
    n_contracts = HEDGE_PCT * 1.0 / (net_premium * 100).
  - Between rolls, the option leg is marked to market daily using px_last
    (or intrinsic value if the contract has expired before the next roll);
    its cumulative P&L is added on top of the TSLL buy & hold equity.

Variants:
  - ATM       : long 1 ATM call            (moneyness 0.95-1.05)
  - 10% OTM   : long 1 10%-OTM call        (moneyness 1.05-1.15)
  - 20% OTM   : long 1 20%-OTM call        (moneyness 1.15-1.25)
  - Spread    : long 10% OTM call, short 20% OTM call (capped upside)

Risk metrics are printed to the console; figures saved to
observations/strategies/convexity_protection/. Each variant's equity curve
is saved to results/convexity_protection/equity_{atm,otm10,otm20,spread}.csv.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from data_loader import load_tsla_underlying, load_tsla_calls, load_tsll
from metrics import summarize

OUT_DIR = ROOT / "observations" / "strategies" / "convexity_protection"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "convexity_protection"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "scripts" / "backtest"))
from options_selection import select_contract  # noqa: E402

TARGET_DTE = 60
HEDGE_PCT = 0.02

VARIANTS = {
    "ATM": (["ATM"], "atm"),
    "10% OTM": (["10% OTM"], "otm10"),
    "20% OTM": (["20% OTM"], "otm20"),
    "Spread": (["10% OTM", "20% OTM"], "spread"),
}


def simulate(returns, calls, spot, rebalance_dates, moneyness_buckets, price_lookup):
    """Buy & hold short $1 TSLL (Strategy 1's baseline equity, never reset)
    plus a long (and possibly short, for a spread) TSLA call position rolled
    monthly. `moneyness_buckets` has 1 entry for a single long call, or 2
    entries for a long/short vertical spread (long first, short second).
    """
    rebal_set = set(rebalance_dates) | {returns.index[0]}
    signs = [1, -1][:len(moneyness_buckets)]

    cum_tsll = (1 + returns["TSLL"]).cumprod()
    base_equity = 2.0 - cum_tsll  # Strategy 1's buy & hold short-TSLL equity

    equity = pd.Series(index=returns.index, dtype=float)
    legs = []  # each: dict(sign, raw_id, strike, expiry, n, price)
    option_pnl = 0.0
    n_unhedged = 0

    def mtm_price(raw_id, strike, expiry, date, last_known):
        if date > expiry:
            return max(spot.loc[date] - strike, 0.0)
        px = price_lookup.get((raw_id, date))
        if px is not None and not pd.isna(px):
            return float(px)
        return last_known

    for d in returns.index:
        if d in rebal_set:
            # Close out existing legs at today's prices.
            for leg in legs:
                px = mtm_price(leg["raw_id"], leg["strike"], leg["expiry"], d, leg["price"])
                option_pnl += leg["sign"] * leg["n"] * 100 * (px - leg["price"])

            # Roll into new contract(s), spending HEDGE_PCT of the fixed $1 notional.
            new_legs = []
            for bucket, sign in zip(moneyness_buckets, signs):
                row = select_contract(calls, spot, d, bucket, TARGET_DTE)
                if row is None:
                    new_legs = []
                    break
                new_legs.append({
                    "sign": sign, "raw_id": row["raw_id"], "strike": row["strike"],
                    "expiry": row["expiry"], "price": float(row["px_last"]),
                })
            if new_legs:
                net_premium = new_legs[0]["price"]
                if len(new_legs) == 2:
                    net_premium -= new_legs[1]["price"]
                if net_premium > 0:
                    n = HEDGE_PCT * 1.0 / (net_premium * 100)
                    for leg in new_legs:
                        leg["n"] = n
                    legs = new_legs
                else:
                    legs = []
            else:
                legs = []
            if not legs:
                n_unhedged += 1
        else:
            for leg in legs:
                px = mtm_price(leg["raw_id"], leg["strike"], leg["expiry"], d, leg["price"])
                option_pnl += leg["sign"] * leg["n"] * 100 * (px - leg["price"])
                leg["price"] = px

        equity.loc[d] = base_equity.loc[d] + option_pnl

    return equity, n_unhedged


def main():
    tsll = load_tsll()
    r_tsll = tsll.set_index("Date")["Close"].pct_change().dropna()
    returns = r_tsll.rename("TSLL").to_frame()

    spot = load_tsla_underlying().set_index("Date")["Close"].reindex(returns.index).ffill()
    calls = load_tsla_calls()
    price_lookup = calls.set_index(["raw_id", "date"])["px_last"].to_dict()

    # First common (returns x calls) date of each calendar month -> roll dates.
    common = returns.index.intersection(pd.DatetimeIndex(calls["date"].unique())).sort_values()
    periods = common.to_series().dt.to_period("M")
    rebalance_dates = common[~periods.duplicated()]

    print("=" * 78)
    print("STRATEGY 3 -- CONVEXITY PROTECTION (short TSLL + long TSLA call(s)): RISK METRICS")
    print("=" * 78)
    print(f"Target DTE at roll: {TARGET_DTE} days   Hedge spend: {HEDGE_PCT:.1%} of NAV   "
          f"Roll dates: {len(rebalance_dates)} (monthly)\n")

    rows = []
    curves = {}
    for name, (buckets, slug) in VARIANTS.items():
        equity, n_unhedged = simulate(returns, calls, spot, rebalance_dates, buckets, price_lookup)
        curves[name] = (equity, slug)
        eq_returns = equity.pct_change().dropna()
        row = summarize(equity, eq_returns, name)
        row["Unhedged Periods"] = n_unhedged
        rows.append(row)

    metrics_df = pd.DataFrame(rows)
    print(metrics_df.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    # ── Plots ────────────────────────────────────────────────────────────
    baseline = pd.read_csv(ROOT / "results" / "double_short" / "equity.csv",
                            index_col=0, parse_dates=True)["equity"]
    baseline = baseline.reindex(returns.index).dropna()
    baseline = baseline / baseline.iloc[0]

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, (equity, _) in curves.items():
        equity.plot(ax=ax, label=name)
    baseline.plot(ax=ax, label="Strategy 1: Double-Short (Buy & Hold, rebased)", linestyle="--")
    ax.set_title("Strategy 3 -- Convexity Protection: Equity Curves")
    ax.set_ylabel("Equity (start = 1.0)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT_DIR / "equity_curves.png", dpi=150)
    plt.close(fig)

    # ── Save results ─────────────────────────────────────────────────────
    for name, (equity, slug) in curves.items():
        equity.rename("equity").to_csv(RESULTS_DIR / f"equity_{slug}.csv")

    print(f"\nFigures saved to {OUT_DIR}/")
    print(f"Equity curves saved to {RESULTS_DIR}/equity_{{atm,otm10,otm20,spread}}.csv")


if __name__ == "__main__":
    main()
