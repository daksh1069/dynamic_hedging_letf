"""Shared risk-metric functions for the strategy backtests."""
import numpy as np
import pandas as pd


def cagr(equity: pd.Series) -> float:
    n_years = (equity.index[-1] - equity.index[0]).days / 365.25
    end = equity.iloc[-1]
    if end <= 0:
        return -1.0
    return end ** (1 / n_years) - 1


def ann_vol(returns: pd.Series) -> float:
    return returns.std() * np.sqrt(252)


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    excess = returns - rf / 252
    vol = excess.std()
    if vol == 0:
        return np.nan
    return excess.mean() / vol * np.sqrt(252)


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = equity / running_max - 1
    return dd.min()


def calmar(equity: pd.Series) -> float:
    mdd = max_drawdown(equity)
    if mdd == 0:
        return np.nan
    return cagr(equity) / abs(mdd)


def summarize(equity: pd.Series, returns: pd.Series, name: str) -> dict:
    return {
        "Strategy": name,
        "CAGR": cagr(equity),
        "Ann. Vol": ann_vol(returns),
        "Sharpe": sharpe(returns),
        "Max DD": max_drawdown(equity),
        "Calmar": calmar(equity),
    }
