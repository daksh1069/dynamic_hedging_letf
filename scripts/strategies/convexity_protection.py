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

from capture import capture_stdout
from data_loader import load_tsla_underlying, load_tsla_calls, load_tsll
from metrics import summarize

OUT_DIR = ROOT / "observations" / "strategies" / "convexity_protection"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "convexity_protection"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "scripts" / "backtest"))
from options_selection import select_contract, bs_delta  # noqa: E402

TARGET_DTE  = 180
ROLL_DTE    = 14
MAX_DTE     = 180
TSLL_LEVER  = 2.0   # TSLL nominal leverage vs TSLA
R_RF        = 0.05  # risk-free rate proxy (annualised)
VOL_WINDOW  = 21    # days for realised-vol estimate used in BS delta

VARIANTS = {
    "ATM": (["ATM"], "atm"),
    "10% OTM": (["10% OTM"], "otm10"),
    "20% OTM": (["20% OTM"], "otm20"),
    "Spread": (["10% OTM", "20% OTM"], "spread"),
}


def simulate(returns, calls, spot, moneyness_buckets, price_lookup, sigma_series):
    """Buy & hold short $1 TSLL plus a delta-neutral long (or spread) TSLA call.

    At each roll the call is sized so its dollar delta exactly offsets the
    short-TSLL dollar delta: n = (TSLL_LEVER × cum_tsll) / (Δ × 100 × spot).
    As TSLL appreciates, the required hedge grows automatically.

    `moneyness_buckets` has 1 entry (single long call) or 2 (long/short spread).
    `sigma_series` is the rolling realised-vol of TSLA, indexed by date.
    """
    signs = [1, -1][:len(moneyness_buckets)]

    cum_tsll = (1 + returns["TSLL"]).cumprod()
    base_equity = 2.0 - cum_tsll

    equity = pd.Series(index=returns.index, dtype=float)
    legs = []
    option_pnl = 0.0
    n_unhedged = 0
    total_hedge_cost = 0.0

    def mtm_price(raw_id, strike, expiry, date, last_known):
        if date > expiry:
            return max(spot.loc[date] - strike, 0.0)
        px = price_lookup.get((raw_id, date))
        if px is not None and not pd.isna(px):
            return float(px)
        return last_known

    for d in returns.index:
        primary_dte = (legs[0]["expiry"] - d).days if legs else -1
        need_roll = not legs or primary_dte < ROLL_DTE

        if need_roll:
            for leg in legs:
                px = mtm_price(leg["raw_id"], leg["strike"], leg["expiry"], d, leg["price"])
                option_pnl += leg["sign"] * leg["n"] * 100 * (px - leg["price"])

            new_legs = []
            for bucket, sign in zip(moneyness_buckets, signs):
                row = select_contract(calls, spot, d, bucket, TARGET_DTE, max_dte=MAX_DTE)
                if row is None:
                    new_legs = []
                    break
                new_legs.append({
                    "sign": sign, "raw_id": row["raw_id"],
                    "strike": float(row["strike"]), "expiry": row["expiry"],
                    "price": float(row["px_last"]),
                })

            if new_legs:
                S = float(spot.loc[d])
                sigma = float(sigma_series.loc[d]) if d in sigma_series.index else 0.5

                # Compute BS delta for each leg.
                leg_deltas = []
                for leg in new_legs:
                    T = (leg["expiry"] - d).days / 365.25
                    leg_deltas.append(bs_delta(S, leg["strike"], T, R_RF, sigma))

                # Size so dollar delta of call(s) = dollar delta of short TSLL.
                # For a spread, size by the LONG leg's delta — the short leg reduces
                # premium cost but is not the sizing target (avoids n→∞ when Δ1≈Δ2).
                sizing_delta = max(leg_deltas[0], 0.01)
                short_delta = TSLL_LEVER * float(cum_tsll.loc[d])
                n = short_delta / (sizing_delta * 100 * S)

                net_premium = new_legs[0]["price"]
                if len(new_legs) == 2:
                    net_premium -= new_legs[1]["price"]

                if net_premium > 0:
                    for leg in new_legs:
                        leg["n"] = n
                    legs = new_legs
                    total_hedge_cost += n * 100 * net_premium
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

    return equity, n_unhedged, total_hedge_cost


def main():
    tsll = load_tsll()
    r_tsll = tsll.set_index("Date")["Close"].pct_change().dropna()
    returns = r_tsll.rename("TSLL").to_frame()

    spot = load_tsla_underlying().set_index("Date")["Close"].reindex(returns.index).ffill()
    r_tsla = spot.pct_change()
    sigma_series = r_tsla.rolling(VOL_WINDOW).std() * (252 ** 0.5)
    sigma_series = sigma_series.ffill().bfill()

    calls = load_tsla_calls()
    price_lookup = calls.set_index(["raw_id", "date"])["px_last"].to_dict()

    print("=" * 78)
    print("STRATEGY 3 -- CONVEXITY PROTECTION (short TSLL + long TSLA call(s)): RISK METRICS")
    print("=" * 78)
    print(f"Target DTE: {TARGET_DTE}d   Roll trigger: DTE < {ROLL_DTE}d   "
          f"Max DTE: {MAX_DTE}d   Sizing: DELTA-NEUTRAL (TSLL lever={TSLL_LEVER}x, "
          f"r={R_RF:.0%}, vol window={VOL_WINDOW}d)\n")

    rows = []
    curves = {}
    for name, (buckets, slug) in VARIANTS.items():
        equity, n_unhedged, hedge_cost = simulate(
            returns, calls, spot, buckets, price_lookup, sigma_series)
        curves[name] = (equity, slug)
        eq_returns = equity.pct_change().dropna()
        row = summarize(equity, eq_returns, name)
        row["Unhedged Days"] = n_unhedged
        row["Total Hedge Cost $"] = round(hedge_cost, 4)
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
    with capture_stdout(OUT_DIR / "results.txt"):
        main()
