"""
Technical indicators computed on OHLCV data.

When ``bar_multiplier`` is set in the data config (e.g. 6 for 4h bars),
EMA periods and rolling windows are scaled to maintain equivalent
time windows.
"""

import pandas as pd
import numpy as np

from config import get_config


def _scale(n: int) -> int:
    mult = get_config().get("data", {}).get("bar_multiplier", 1)
    return max(1, int(n * mult))


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_realized_volatility(series: pd.Series, period: int = 20) -> pd.Series:
    log_returns = np.log(series / series.shift(1))
    mult = get_config().get("data", {}).get("bar_multiplier", 1)
    ann_factor = np.sqrt(365 * mult)
    return log_returns.rolling(window=_scale(period)).std() * ann_factor


def compute_all_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technical indicators per symbol group."""
    results = []
    for symbol, group in df.groupby("symbol"):
        group = group.sort_values("date").copy()
        close = group["close"]

        for p in [5, 10, 20, 50]:
            sp = _scale(p)
            group[f"ema_{p}"] = compute_ema(close, sp)
            group[f"dist_ema_{p}_pct"] = (close - group[f"ema_{p}"]) / group[f"ema_{p}"] * 100

        group["atr_14"] = compute_atr(group, _scale(14))
        group["atr_pct"] = group["atr_14"] / close * 100
        group["rsi_14"] = compute_rsi(close, _scale(14))
        group["realized_vol_20"] = compute_realized_volatility(close, 20)
        group["vol_expansion"] = (
            group["realized_vol_20"] / group["realized_vol_20"].shift(_scale(20))
        )
        group["vol_expansion"] = group["vol_expansion"].fillna(1.0)

        group["recent_high_20"] = group["high"].rolling(_scale(20)).max()
        group["recent_low_20"] = group["low"].rolling(_scale(20)).min()
        group["distance_from_high_20_pct"] = (
            (close - group["recent_high_20"]) / group["recent_high_20"] * 100
        )

        group["breakout"] = group["close"] > group["recent_high_20"].shift(1)

        results.append(group)

    return pd.concat(results, ignore_index=True)