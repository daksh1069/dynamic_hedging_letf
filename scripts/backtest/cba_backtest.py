"""
Cost-Benefit Analysis: Short TSLL + Long Call Hedge.

Compares two hedging variants against an unhedged baseline:
  Benchmark : naked short $1 TSLL (buy & hold)
  Strategy A: short TSLL + long TSLA call (call on the underlying)
  Strategy B: short TSLL + long TSLL call (call on the LETF itself)

Parameters:
  - Analysis window : 2022-08-12 → 2026-06-10 (limited by TSLL options history)
  - DTE filter      : 0 < dte ≤ 180; roll when held DTE drops below 14
  - Moneyness       : ATM (0.95-1.05), 10% OTM (1.05-1.15), 20% OTM (1.15-1.25)
  - Hedge spend     : 2% of $1 short notional per roll (HEDGE_PCT)
  - Target DTE      : ≈60 days (pick contract closest to this in the bucket)

TSLL options are sparse (median ~49 contracts/day vs ~373 for TSLA).
Strategy B tracks fill rate and miss days as first-class CBA outputs.

Figures → observations/strategies/cba/
Results → results/cba/equity_*.csv
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "backtest"))

from capture import capture_stdout
from data_loader import load_tsla_underlying, load_tsll, load_tsla_calls, load_tsll_calls
from metrics import summarize, cagr as metric_cagr
from options_selection import select_contract, bs_delta

OUT_DIR = ROOT / "observations" / "strategies" / "cba"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = ROOT / "results" / "cba"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

START       = pd.Timestamp("2022-08-12")
END         = pd.Timestamp("2026-06-10")
TARGET_DTE  = 180
ROLL_DTE    = 14
MAX_DTE     = 180
TSLL_LEVER  = 2.0   # TSLL nominal leverage vs TSLA
R_RF        = 0.05  # risk-free rate proxy (annualised)
VOL_WINDOW  = 21    # days for realised-vol used in BS delta

BUCKETS = ["ATM", "10% OTM", "20% OTM"]


def simulate(returns, calls, calls_spot, price_lookup, moneyness_bucket,
             sigma_series, leverage_factor):
    """Short $1 TSLL (buy & hold) + delta-neutral call, rolled on DTE trigger.

    `calls_spot` is the underlying spot (TSLA for Strategy A, TSLL for B).
    `sigma_series` is the rolling realised vol of that underlying.
    `leverage_factor` is the dollar-delta of the short TSLL per unit of the
    call's underlying (2.0 for TSLA calls, 1.0 for TSLL calls).

    Sizing: n = (leverage_factor × cum_tsll) / (Δ_call × 100 × calls_spot).
    Returns (equity, stats).
    """
    cum_tsll = (1 + returns["TSLL"]).cumprod()
    base_equity = 2.0 - cum_tsll

    equity = pd.Series(index=returns.index, dtype=float)
    position = None
    option_pnl = 0.0
    stats = {
        "roll_attempts": 0,
        "fills": 0,
        "misses": 0,
        "miss_dates": [],
        "hedge_cost": 0.0,
    }

    def mtm_price(raw_id, strike, expiry, date, last_known):
        if date > expiry:
            s = calls_spot.loc[date]
            return max(s - strike, 0.0)
        px = price_lookup.get((raw_id, date))
        if px is not None and not pd.isna(px):
            return float(px)
        return last_known

    for d in returns.index:
        held_dte = (position["expiry"] - d).days if position is not None else -1
        need_roll = (position is None) or (held_dte < ROLL_DTE)

        if need_roll:
            if position is not None:
                px = mtm_price(position["raw_id"], position["strike"],
                               position["expiry"], d, position["price"])
                option_pnl += position["n"] * 100 * (px - position["price"])
                position = None

            stats["roll_attempts"] += 1
            row = select_contract(calls, calls_spot, d, moneyness_bucket,
                                  TARGET_DTE, max_dte=MAX_DTE)
            if row is not None:
                entry = float(row["px_last"])
                S = float(calls_spot.loc[d])
                sigma = float(sigma_series.loc[d]) if d in sigma_series.index else 0.5
                T = (row["expiry"] - d).days / 365.25
                delta = bs_delta(S, float(row["strike"]), T, R_RF, sigma)

                short_delta = leverage_factor * float(cum_tsll.loc[d])
                n = short_delta / (delta * 100 * S)

                position = {
                    "raw_id": row["raw_id"],
                    "strike": float(row["strike"]),
                    "expiry": row["expiry"],
                    "n": n,
                    "price": entry,
                }
                stats["fills"] += 1
                stats["hedge_cost"] += n * 100 * entry
            else:
                stats["misses"] += 1
                stats["miss_dates"].append(d)
        else:
            if position is not None:
                px = mtm_price(position["raw_id"], position["strike"],
                               position["expiry"], d, position["price"])
                option_pnl += position["n"] * 100 * (px - position["price"])
                position["price"] = px

        equity.loc[d] = base_equity.loc[d] + option_pnl

    return equity, stats


def _position_cost(row, spot_val, sigma_val, leverage, cum_val, date):
    """Delta-neutral cost (total premium $) for a candidate contract.  Returns
    (cost, n, entry_price) or (inf, 0, 0) when row is None."""
    if row is None:
        return float("inf"), 0.0, 0.0
    entry = float(row["px_last"])
    T = max((row["expiry"] - date).days / 365.25, 1 / 365)
    delta = bs_delta(float(spot_val), float(row["strike"]), T, R_RF, sigma_val)
    n = leverage * cum_val / (max(delta, 0.01) * 100 * float(spot_val))
    return n * 100 * entry, n, entry


def _best_alternative(d, cum_val,
                      tsla_calls, tsla_spot, tsla_sigma,
                      tsll_calls, tsll_spot, tsll_sigma,
                      target_dte, max_dte, buckets):
    """Search every (moneyness bucket × underlying) combination for the
    cheapest delta-neutral candidate available on date `d`.

    Returns (cost, underlying, bucket, row, n, entry) for the global cheapest
    candidate, or None if nothing is available in any bucket/underlying.
    """
    sig_a = float(tsla_sigma.loc[d]) if d in tsla_sigma.index else 0.5
    sig_b = float(tsll_sigma.loc[d]) if d in tsll_sigma.index else 0.5

    best = None
    for bucket in buckets:
        row_a = select_contract(tsla_calls, tsla_spot, d, bucket, target_dte, max_dte=max_dte)
        cost_a, n_a, entry_a = _position_cost(row_a, tsla_spot.loc[d], sig_a, TSLL_LEVER, cum_val, d)
        if row_a is not None and (best is None or cost_a < best[0]):
            best = (cost_a, "tsla", bucket, row_a, n_a, entry_a)

        row_b = select_contract(tsll_calls, tsll_spot, d, bucket, target_dte, max_dte=max_dte)
        cost_b, n_b, entry_b = _position_cost(row_b, tsll_spot.loc[d], sig_b, 1.0, cum_val, d)
        if row_b is not None and (best is None or cost_b < best[0]):
            best = (cost_b, "tsll", bucket, row_b, n_b, entry_b)

    return best


def simulate_ensemble(returns,
                      tsla_calls, tsla_spot, tsla_lookup, tsla_vol_lookup, tsla_sigma,
                      tsll_calls, tsll_spot, tsll_lookup, tsll_vol_lookup, tsll_sigma,
                      moneyness_bucket, target_dte, roll_dte, max_dte,
                      stop_loss_pct=None, tsla_cost_pct=0.0, tsll_cost_pct=0.0,
                      tsll_borrow_rate=None, coverage_band=None):
    """On each roll day price both a TSLA call and a TSLL call (same bucket).
    Enter whichever provides delta-neutral coverage at lower total premium.
    Fall back to the other if one underlying has no contract available.

    `stop_loss_pct`, if set, adds a mid-cycle override: if the held position's
    unrealized loss (vs its own entry premium) breaches this fraction, search
    *every* bucket/underlying combination for a cheaper delta-neutral
    alternative. With transaction costs active, the switch only executes if
    the premium saved exceeds the cost of actually closing the current leg
    and opening the new one -- otherwise the position is held unchanged.

    `coverage_band`, if set to a (low, high) tuple, adds a second, independent
    mid-cycle trigger: if the delta-coverage ratio (hedge's dollar delta /
    target dollar delta -- see `coverage_ratio()`) drifts outside [low, high],
    the position is resized in place (same bucket/underlying, re-priced fresh
    at today's spot/vol/T) unconditionally -- no cost-benefit gate, since this
    is risk restoration, not bargain-hunting. It deliberately does NOT reuse
    the stop-loss's "switch only if cheaper" logic: a systemic move decays
    every bucket/underlying's premium together, so "is something cheaper"
    rarely clears during exactly the crash this is meant to catch, while a
    cost-gated switch still fires opportunistically (and expensively) on
    ordinary noise elsewhere. Tried that combined version first and it made
    results worse across the board -- separating the two triggers (cost-
    driven switch vs. risk-driven resize) is the fix.  Sandbox-only feature:
    defaults to `None` (disabled) everywhere else, so the published CBA table
    and the grid search are both unaffected unless explicitly passed.

    `tsla_cost_pct`/`tsll_cost_pct` are the *baseline* per-leg transaction cost
    (fraction of that leg's dollar premium) at "typical" vol/liquidity. We
    don't have bid/ask data, only px_last + px_volume, so we approximate the
    real half-spread cost with this baseline rate scaled by two signals we do
    have: realised vol relative to its own median (spreads widen in high-vol
    regimes -- the same pattern visible in real TSLL borrow-fee data) and the
    traded contract's own volume relative to its underlying's median volume
    (a specific contract trading thin that day implies a wider effective
    spread on that trade). Both multipliers are clipped to avoid blow-ups on
    an illiquid/zero-volume day.

    `tsll_borrow_rate`, if given, is a daily annualized-rate Series (see
    borrow_rates.load_borrow_rates) charged on the *current* short-TSLL
    notional (cum_tsll, which grows as TSLL appreciates) -- this is the cost
    of actually holding the short, on top of the option-leg transaction
    costs above. There's no TSLA borrow leg here since this strategy never
    shorts TSLA shares (only long calls).

    Exiting a held position (on a scheduled roll or a stop-loss switch) is
    NOT assumed to always fill: `tsla_vol_lookup`/`tsll_vol_lookup` are used
    to check whether that specific contract actually traded (px_volume > 0)
    on the day we want out. If it didn't, we hold the position one more day
    and try again -- a quote with zero volume is a stale price, not a real
    fill. The one exception is letting a contract run past its own expiry,
    which settles to intrinsic value automatically with no counterparty
    needed. select_contract() (options_selection.py) enforces the same
    volume requirement on the entry side.
    """
    sigma_baseline = {
        "tsla": float(tsla_sigma.median()) if tsla_sigma.median() > 0 else 0.5,
        "tsll": float(tsll_sigma.median()) if tsll_sigma.median() > 0 else 0.5,
    }
    volume_baseline = {
        "tsla": float(tsla_calls["px_volume"].median()),
        "tsll": float(tsll_calls["px_volume"].median()),
    }

    def cost_of(underlying, premium_value, date, volume):
        rate = tsla_cost_pct if underlying == "tsla" else tsll_cost_pct
        sigma_series = tsla_sigma if underlying == "tsla" else tsll_sigma
        sig_now = float(sigma_series.loc[date]) if date in sigma_series.index else sigma_baseline[underlying]
        vol_mult = np.clip(sig_now / sigma_baseline[underlying], 0.5, 2.5)
        liq_mult = np.clip(volume_baseline[underlying] / max(volume, 1.0), 0.5, 3.0)
        return premium_value * rate * vol_mult * liq_mult

    cum_tsll = (1 + returns["TSLL"]).cumprod()
    base_equity = 2.0 - cum_tsll
    total_borrow_paid = 0.0
    if tsll_borrow_rate is not None:
        br = tsll_borrow_rate.reindex(returns.index).ffill().bfill()
        daily_borrow = br / 252 * cum_tsll
        base_equity = base_equity - daily_borrow.cumsum()
        total_borrow_paid = float(daily_borrow.sum())
    equity = pd.Series(index=returns.index, dtype=float)
    n_track = pd.Series(index=returns.index, dtype=float)  # contract count `n` held each day (NaN if unhedged)
    coverage_track = pd.Series(index=returns.index, dtype=float)  # delta-coverage ratio each day (NaN if unhedged)
    position = None   # adds "underlying": "tsla"|"tsll" key vs regular simulate
    option_pnl = 0.0
    stats = {
        "roll_attempts": 0, "fills": 0,
        "fills_tsla": 0, "fills_tsll": 0,
        "misses": 0, "miss_dates": [], "hedge_cost": 0.0,
        "stop_loss_rolls": 0, "transaction_costs_paid": 0.0,
        "borrow_paid": total_borrow_paid, "exit_misses": 0,
        "coverage_band_rolls": 0,
    }

    def mtm(pos, date):
        spot = tsla_spot if pos["underlying"] == "tsla" else tsll_spot
        lkp  = tsla_lookup if pos["underlying"] == "tsla" else tsll_lookup
        if date > pos["expiry"]:
            return max(float(spot.loc[date]) - pos["strike"], 0.0)
        px = lkp.get((pos["raw_id"], date))
        if px is not None and not pd.isna(px):
            return float(px)
        return pos["price"]

    def can_exit(pos, date):
        """Past expiry, settlement is automatic (no counterparty needed).
        Otherwise require px_volume > 0 on this exact contract/date -- a
        quote with no trading that day isn't a real fill."""
        if date > pos["expiry"]:
            return True
        vol_lkp = tsla_vol_lookup if pos["underlying"] == "tsla" else tsll_vol_lookup
        vol = vol_lkp.get((pos["raw_id"], date))
        return vol is not None and not pd.isna(vol) and vol > 0

    def coverage_ratio(pos, date):
        """Dollar-delta coverage: (hedge's current dollar delta) / (target dollar delta
        being hedged). Solved to exactly 1.0 at the moment a position is sized -- drifts
        between rolls as spot/vol/time-to-expiry move the option's delta while `n` stays
        fixed (gamma drift); resets back toward 1.0 at the next roll or stop-loss switch."""
        spot_series = tsla_spot if pos["underlying"] == "tsla" else tsll_spot
        sigma_series = tsla_sigma if pos["underlying"] == "tsla" else tsll_sigma
        lev = TSLL_LEVER if pos["underlying"] == "tsla" else 1.0
        spot_t = float(spot_series.loc[date])
        T = max((pos["expiry"] - date).days / 365.25, 1 / 365)
        sigma_t = float(sigma_series.loc[date]) if date in sigma_series.index else 0.5
        delta_t = bs_delta(spot_t, pos["strike"], T, R_RF, sigma_t)
        hedge_dollar_delta = pos["n"] * delta_t * 100 * spot_t
        target_dollar_delta = lev * float(cum_tsll.loc[date])
        return hedge_dollar_delta / target_dollar_delta if target_dollar_delta != 0 else float("nan")

    for d in returns.index:
        held_dte = (position["expiry"] - d).days if position is not None else -1
        want_roll = (position is None) or (held_dte < roll_dte)
        exitable = position is None or can_exit(position, d)

        if want_roll and exitable:
            if position is not None:
                px = mtm(position, d)
                option_pnl += position["n"] * 100 * (px - position["price"])
                close_cost = cost_of(position["underlying"], position["n"] * 100 * px,
                                     d, position["entry_volume"])
                option_pnl -= close_cost
                stats["transaction_costs_paid"] += close_cost
                position = None

            stats["roll_attempts"] += 1
            cum_val = float(cum_tsll.loc[d])
            sig_a = float(tsla_sigma.loc[d]) if d in tsla_sigma.index else 0.5
            sig_b = float(tsll_sigma.loc[d]) if d in tsll_sigma.index else 0.5

            row_a = select_contract(tsla_calls, tsla_spot, d, moneyness_bucket,
                                    target_dte, max_dte=max_dte)
            row_b = select_contract(tsll_calls, tsll_spot, d, moneyness_bucket,
                                    target_dte, max_dte=max_dte)

            cost_a, n_a, entry_a = _position_cost(
                row_a, tsla_spot.loc[d], sig_a, TSLL_LEVER, cum_val, d)
            cost_b, n_b, entry_b = _position_cost(
                row_b, tsll_spot.loc[d], sig_b, 1.0, cum_val, d)

            # Pick cheaper; fall back to available if one is missing
            if cost_a <= cost_b and row_a is not None:
                chosen, row, n, entry, ul = "tsla", row_a, n_a, entry_a, "tsla"
                stats["fills_tsla"] += 1
            elif row_b is not None:
                chosen, row, n, entry, ul = "tsll", row_b, n_b, entry_b, "tsll"
                stats["fills_tsll"] += 1
            elif row_a is not None:
                chosen, row, n, entry, ul = "tsla", row_a, n_a, entry_a, "tsla"
                stats["fills_tsla"] += 1
            else:
                chosen = None

            if chosen is not None:
                entry_volume = float(row["px_volume"]) if pd.notna(row.get("px_volume")) else volume_baseline[ul]
                open_cost = cost_of(ul, n * 100 * entry, d, entry_volume)
                option_pnl -= open_cost
                stats["transaction_costs_paid"] += open_cost
                position = {
                    "underlying": ul, "raw_id": row["raw_id"],
                    "strike": float(row["strike"]), "expiry": row["expiry"],
                    "n": n, "price": entry, "entry_price": entry,
                    "bucket": moneyness_bucket, "entry_volume": entry_volume,
                }
                stats["fills"] += 1
                stats["hedge_cost"] += n * 100 * entry
            else:
                stats["misses"] += 1
                stats["miss_dates"].append(d)
        else:
            if position is not None:
                px = mtm(position, d)
                option_pnl += position["n"] * 100 * (px - position["price"])
                position["price"] = px

                if want_roll and not exitable:
                    # Wanted to roll on schedule but this contract didn't trade today --
                    # not a real fill opportunity. Hold and retry on the next day.
                    stats["exit_misses"] += 1
                elif exitable:
                    unrealized_pct = (px - position["entry_price"]) / position["entry_price"]
                    loss_trigger = stop_loss_pct is not None and unrealized_pct <= -stop_loss_pct
                    cov_now = coverage_ratio(position, d) if coverage_band is not None else None
                    band_trigger = (coverage_band is not None
                                    and (cov_now < coverage_band[0] or cov_now > coverage_band[1]))

                    if loss_trigger:
                        # Stop-loss: a cost-minimization question -- is there a meaningfully
                        # cheaper alternative (any bucket/underlying) worth switching into?
                        # Switch only if the premium saved clears the cost of switching.
                        cum_val = float(cum_tsll.loc[d])
                        alt = _best_alternative(d, cum_val,
                                                tsla_calls, tsla_spot, tsla_sigma,
                                                tsll_calls, tsll_spot, tsll_sigma,
                                                target_dte, max_dte, BUCKETS)

                        cur_calls = tsla_calls if position["underlying"] == "tsla" else tsll_calls
                        cur_spot_series = tsla_spot if position["underlying"] == "tsla" else tsll_spot
                        cur_sigma = (float(tsla_sigma.loc[d]) if position["underlying"] == "tsla"
                                    else float(tsll_sigma.loc[d]))
                        cur_lev = TSLL_LEVER if position["underlying"] == "tsla" else 1.0
                        row_cur = select_contract(cur_calls, cur_spot_series, d, position["bucket"],
                                                  target_dte, max_dte=max_dte)
                        cost_cur, _, _ = _position_cost(
                            row_cur, cur_spot_series.loc[d], cur_sigma, cur_lev, cum_val, d)

                        if alt is not None:
                            alt_cost, ul, bucket_chosen, row, n, entry = alt
                            alt_volume = float(row["px_volume"]) if pd.notna(row.get("px_volume")) else volume_baseline[ul]
                            benefit = cost_cur - alt_cost
                            switch_cost = (cost_of(position["underlying"], position["n"] * 100 * px,
                                                  d, position["entry_volume"])
                                          + cost_of(ul, n * 100 * entry, d, alt_volume))
                            if benefit > switch_cost:
                                option_pnl -= switch_cost
                                stats["transaction_costs_paid"] += switch_cost
                                position = {
                                    "underlying": ul, "raw_id": row["raw_id"],
                                    "strike": float(row["strike"]), "expiry": row["expiry"],
                                    "n": n, "price": entry, "entry_price": entry,
                                    "bucket": bucket_chosen, "entry_volume": alt_volume,
                                }
                                stats["hedge_cost"] += n * 100 * entry
                                stats["stop_loss_rolls"] += 1
                        # else: switching wouldn't clear its own cost -- hold position unchanged

                    elif band_trigger:
                        # Coverage band: a risk-restoration question, not a bargain hunt --
                        # a systemic move (e.g. a crash) decays every bucket/underlying
                        # together, so "is something cheaper" rarely clears during exactly
                        # the move this is meant to catch. Resize in place instead: re-price
                        # the SAME bucket/underlying fresh at today's spot/vol/T, paying the
                        # close+open cost unconditionally as long as a real contract is
                        # available -- no cost-benefit gate, because the point is restoring
                        # coverage, not finding a deal.
                        cum_val = float(cum_tsll.loc[d])
                        cur_calls = tsla_calls if position["underlying"] == "tsla" else tsll_calls
                        cur_spot_series = tsla_spot if position["underlying"] == "tsla" else tsll_spot
                        cur_sigma = (float(tsla_sigma.loc[d]) if position["underlying"] == "tsla"
                                    else float(tsll_sigma.loc[d]))
                        cur_lev = TSLL_LEVER if position["underlying"] == "tsla" else 1.0
                        row_cur = select_contract(cur_calls, cur_spot_series, d, position["bucket"],
                                                  target_dte, max_dte=max_dte)
                        cost_cur, n_new, entry_new = _position_cost(
                            row_cur, cur_spot_series.loc[d], cur_sigma, cur_lev, cum_val, d)

                        if row_cur is not None:
                            new_volume = (float(row_cur["px_volume"])
                                         if pd.notna(row_cur.get("px_volume"))
                                         else volume_baseline[position["underlying"]])
                            resize_cost = (cost_of(position["underlying"], position["n"] * 100 * px,
                                                  d, position["entry_volume"])
                                          + cost_of(position["underlying"], n_new * 100 * entry_new,
                                                  d, new_volume))
                            option_pnl -= resize_cost
                            stats["transaction_costs_paid"] += resize_cost
                            position = {
                                "underlying": position["underlying"], "raw_id": row_cur["raw_id"],
                                "strike": float(row_cur["strike"]), "expiry": row_cur["expiry"],
                                "n": n_new, "price": entry_new, "entry_price": entry_new,
                                "bucket": position["bucket"], "entry_volume": new_volume,
                            }
                            stats["hedge_cost"] += n_new * 100 * entry_new
                            stats["coverage_band_rolls"] += 1
                        # else: no contract available to resize into -- hold position unchanged

        equity.loc[d] = base_equity.loc[d] + option_pnl
        n_track.loc[d] = position["n"] if position is not None else float("nan")
        coverage_track.loc[d] = coverage_ratio(position, d) if position is not None else float("nan")

    stats["n_series"] = n_track
    stats["coverage_series"] = coverage_track
    return equity, stats


def build_row(name, equity, stats, bench_cagr, n_years, show_fill):
    eq_ret = equity.pct_change().dropna()
    row = summarize(equity, eq_ret, name)

    if stats is not None:
        ann_cost = stats["hedge_cost"] / n_years
        benefit = row["CAGR"] - bench_cagr
        row["Hedge Cost $"] = round(stats["hedge_cost"], 4)
        row["Hedge Eff."] = round(benefit / ann_cost, 3) if ann_cost > 0 else float("nan")
    else:
        row["Hedge Cost $"] = "--"
        row["Hedge Eff."] = "--"

    if show_fill and stats is not None:
        rate = stats["fills"] / stats["roll_attempts"] if stats["roll_attempts"] else 0
        row["Fill Rate"] = f"{rate:.1%}"
        row["Miss Days"] = stats["misses"]
    else:
        row["Fill Rate"] = "--"
        row["Miss Days"] = "--"

    return row


def make_equity_figure(curves, out_dir):
    fig, ax = plt.subplots(figsize=(11, 6))
    for name, equity in curves.items():
        ls = "--" if name == "Benchmark" else "-"
        c = "grey" if name == "Benchmark" else None
        equity.plot(ax=ax, label=name, linestyle=ls, color=c)
    ax.axhline(1.0, color="lightgrey", linestyle=":", linewidth=0.8)
    ax.set_title(f"CBA: Equity Curves ({START.date()} → {END.date()})")
    ax.set_ylabel("Equity (start = 1.0)")
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(out_dir / "equity_curves.png", dpi=150)
    plt.close(fig)


def make_drawdown_figure(curves, out_dir):
    fig, ax = plt.subplots(figsize=(11, 5))
    for name, equity in curves.items():
        dd = equity / equity.cummax() - 1
        ls = "--" if name == "Benchmark" else "-"
        c = "grey" if name == "Benchmark" else None
        dd.plot(ax=ax, label=name, linestyle=ls, color=c)
    ax.set_title("CBA: Drawdown Comparison")
    ax.set_ylabel("Drawdown from peak")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "drawdown_comparison.png", dpi=150)
    plt.close(fig)


def make_fill_rate_figure(fill_stats_b, out_dir):
    buckets = list(fill_stats_b.keys())
    fill_rates = [
        s["fills"] / s["roll_attempts"] * 100 if s["roll_attempts"] else 0
        for s in fill_stats_b.values()
    ]
    miss_days = [s["misses"] for s in fill_stats_b.values()]

    fig, ax1 = plt.subplots(figsize=(7, 5))
    bars = ax1.bar(buckets, fill_rates, color=["#f4a261", "#e76f51", "#e9c46a"])
    ax1.set_ylabel("Fill Rate (%)")
    ax1.set_ylim(0, 105)
    ax1.set_title("Strategy B (TSLL Calls): Fill Rate by Moneyness Bucket")
    for bar, rate in zip(bars, fill_rates):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{rate:.1f}%", ha="center", va="bottom", fontsize=10)

    ax2 = ax1.twinx()
    ax2.plot(buckets, miss_days, marker="o", color="navy", linewidth=2, label="Miss Days")
    ax2.set_ylabel("Miss Days (count)")
    ax2.legend(loc="upper right")

    fig.tight_layout()
    fig.savefig(out_dir / "tsll_fill_rate.png", dpi=150)
    plt.close(fig)


def main():
    # ── Load spot & LETF returns ─────────────────────────────────────────
    tsll_df = load_tsll()
    r_tsll = tsll_df.set_index("Date")["Close"].pct_change().dropna()
    r_tsll = r_tsll[(r_tsll.index >= START) & (r_tsll.index <= END)]
    returns = r_tsll.rename("TSLL").to_frame()
    n_years = (returns.index[-1] - returns.index[0]).days / 365.25

    tsla_spot = (load_tsla_underlying()
                 .set_index("Date")["Close"]
                 .reindex(returns.index).ffill())
    tsll_spot = (tsll_df.set_index("Date")["Close"]
                 .reindex(returns.index).ffill())

    # ── Load options ─────────────────────────────────────────────────────
    tsla_calls = load_tsla_calls()
    tsll_calls = load_tsll_calls()

    tsla_lookup = tsla_calls.set_index(["raw_id", "date"])["px_last"].to_dict()
    tsll_lookup = tsll_calls.set_index(["raw_id", "date"])["px_last"].to_dict()
    tsla_vol_lookup = tsla_calls.set_index(["raw_id", "date"])["px_volume"].to_dict()
    tsll_vol_lookup = tsll_calls.set_index(["raw_id", "date"])["px_volume"].to_dict()

    # Realised-vol series for BS delta (one per underlying)
    tsla_sigma = (tsla_spot.pct_change()
                  .rolling(VOL_WINDOW).std() * (252 ** 0.5)).ffill().bfill()
    tsll_sigma = (tsll_spot.pct_change()
                  .rolling(VOL_WINDOW).std() * (252 ** 0.5)).ffill().bfill()

    # ── Benchmark: naked short TSLL ──────────────────────────────────────
    cum = (1 + returns["TSLL"]).cumprod()
    bench_raw = 2.0 - cum
    bench_eq = bench_raw / bench_raw.iloc[0]
    bench_cagr = metric_cagr(bench_eq)

    print("=" * 82)
    print("COST-BENEFIT ANALYSIS: Short TSLL + Long Call Hedge  [DELTA-NEUTRAL SIZING]")
    print(f"Window : {START.date()} → {END.date()}  ({n_years:.1f} years)")
    print(f"Params : DTE 0–{MAX_DTE}d, roll @ {ROLL_DTE}d  |  Target DTE {TARGET_DTE}d  |  "
          f"r={R_RF:.0%}, vol window={VOL_WINDOW}d")
    print("Strategy A: n = (2×cum_tsll)/(Δ_tsla×100×tsla_spot)  "
          "[TSLL lever=2x vs TSLA]")
    print("Strategy B: n = (1×cum_tsll)/(Δ_tsll×100×tsll_spot)  "
          "[direct TSLL delta hedge]")
    print("=" * 82)

    curves = {"Benchmark": bench_eq}
    rows = [build_row("Benchmark", bench_eq, None, bench_cagr, n_years, show_fill=False)]
    fill_stats_b = {}

    for bucket in BUCKETS:
        print(f"  Simulating A-{bucket} ...", flush=True)
        eq_a, stats_a = simulate(returns, tsla_calls, tsla_spot, tsla_lookup,
                                 bucket, tsla_sigma, leverage_factor=TSLL_LEVER)
        eq_a = eq_a / eq_a.iloc[0]
        curves[f"A-{bucket}"] = eq_a
        rows.append(build_row(f"A-{bucket}", eq_a, stats_a,
                              bench_cagr, n_years, show_fill=False))

        print(f"  Simulating B-{bucket} ...", flush=True)
        eq_b, stats_b = simulate(returns, tsll_calls, tsll_spot, tsll_lookup,
                                 bucket, tsll_sigma, leverage_factor=1.0)
        eq_b = eq_b / eq_b.iloc[0]
        curves[f"B-{bucket}"] = eq_b
        rows.append(build_row(f"B-{bucket}", eq_b, stats_b,
                              bench_cagr, n_years, show_fill=True))
        fill_stats_b[bucket] = stats_b

    # ── Ensemble: cheapest-on-the-day (TSLA vs TSLL) ────────────────────
    ens_stats = {}
    for bucket in BUCKETS:
        print(f"  Simulating Ensemble-{bucket} ...", flush=True)
        eq_e, stats_e = simulate_ensemble(
            returns,
            tsla_calls, tsla_spot, tsla_lookup, tsla_vol_lookup, tsla_sigma,
            tsll_calls, tsll_spot, tsll_lookup, tsll_vol_lookup, tsll_sigma,
            bucket, TARGET_DTE, ROLL_DTE, MAX_DTE, stop_loss_pct=None)
        eq_e = eq_e / eq_e.iloc[0]
        curves[f"Ens-{bucket}"] = eq_e
        rows.append(build_row(f"Ens-{bucket}", eq_e, stats_e,
                              bench_cagr, n_years, show_fill=True))
        ens_stats[bucket] = stats_e

    print()
    metrics_df = pd.DataFrame(rows)
    print(metrics_df.to_string(index=False))

    # ── Strategy B fill detail ───────────────────────────────────────────
    print("\nStrategy B — TSLL call fill detail:")
    for bucket, s in fill_stats_b.items():
        rate = s["fills"] / s["roll_attempts"] * 100 if s["roll_attempts"] else 0
        print(f"  {bucket:>10s}: {s['fills']}/{s['roll_attempts']} fills "
              f"({rate:.1f}%)  |  {s['misses']} miss days")

    print("\nEnsemble — pick selection:")
    for bucket, s in ens_stats.items():
        tot = s["fills_tsla"] + s["fills_tsll"]
        print(f"  {bucket:>10s}: TSLA {s['fills_tsla']}/{tot} "
              f"({s['fills_tsla']/tot*100:.0f}%)  TSLL {s['fills_tsll']}/{tot} "
              f"({s['fills_tsll']/tot*100:.0f}%)  |  {s['misses']} miss days")

    # ── Figures & results ────────────────────────────────────────────────
    make_equity_figure(curves, OUT_DIR)
    make_drawdown_figure(curves, OUT_DIR)
    make_fill_rate_figure(fill_stats_b, OUT_DIR)

    for name, equity in curves.items():
        slug = name.lower().replace(" ", "_").replace("%", "pct")
        equity.rename("equity").to_csv(RESULTS_DIR / f"equity_{slug}.csv")

    print(f"\nFigures  → {OUT_DIR}/")
    print(f"Equity CSVs → {RESULTS_DIR}/")


if __name__ == "__main__":
    with capture_stdout(OUT_DIR / "results.txt"):
        main()
