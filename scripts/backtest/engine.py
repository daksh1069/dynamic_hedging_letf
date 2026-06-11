"""Equity-curve simulators shared by the strategy backtests.

Conventions:
  - `returns` is a DataFrame of daily simple returns, columns = leg names.
  - `weights` give each leg's dollar exposure as a fraction of NAV (negative
    = short). They need not sum to 1 -- the remainder is implicit cash.
  - All equity curves are normalized so that NAV = 1.0 "before" the first
    date in `returns.index` (i.e. equity.iloc[0] already reflects that date's
    return).
"""
import pandas as pd


def buy_and_hold_equity(returns: pd.DataFrame, weights: dict) -> pd.Series:
    """Fixed initial dollar weights, no rebalancing -- positions just compound
    with their own returns. Equity can go negative for shorts (margin wipeout).
    """
    cum = (1 + returns).cumprod()
    equity = pd.Series(1 - sum(weights.values()), index=returns.index)
    for leg, w in weights.items():
        equity = equity + w * cum[leg]
    return equity


def rebalanced_equity(returns: pd.DataFrame, weights, freq: str = "D") -> pd.Series:
    """Target weights rebalanced at `freq` ("D"/"W"/"M").

    Between rebalance dates, each leg's dollar notional drifts with its own
    return (buy & hold); at each rebalance date, notionals are reset to
    `weights * NAV`.

    `weights` is either a constant dict, or a DataFrame aligned to
    `returns.index` giving per-date target weights (for time-varying hedge
    ratios) -- the weight on date `d` is applied to date `d`'s return.
    """
    dates = returns.index
    periods = pd.Series(dates, index=dates).dt.to_period(freq)
    is_rebal = periods.ne(periods.shift(1))
    is_rebal.iloc[0] = True

    legs = list(returns.columns)
    equity = pd.Series(index=dates, dtype=float)
    nav = 1.0
    notional = {leg: 0.0 for leg in legs}
    for d in dates:
        if is_rebal.loc[d]:
            w = weights if isinstance(weights, dict) else weights.loc[d].to_dict()
            notional = {leg: w.get(leg, 0.0) * nav for leg in legs}
        pnl = sum(notional[leg] * returns.loc[d, leg] for leg in legs)
        nav += pnl
        equity.loc[d] = nav
        notional = {leg: notional[leg] * (1 + returns.loc[d, leg]) for leg in legs}
    return equity
