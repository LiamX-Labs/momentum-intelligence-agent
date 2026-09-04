"""
Market regime classifier.

Deterministic: uses SPY technicals, VIX, and S&P 500 breadth to classify
the current regime as BULL / NEUTRAL / BEAR.

Per build plan Section 16:
  - SPY above/below EMA 20
  - SPY above/below EMA 50
  - SPY realized volatility
  - VIX if available
  - % of S&P 500 above 20 EMA
  - % above 50 EMA
  - Sector breadth

The regime controls portfolio exposure; the LLM cannot override it.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


class Regime(Enum):
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"


@dataclass
class RegimeResult:
    regime: Regime
    spy_vs_ema20: float
    spy_vs_ema50: float
    pct_above_ema20: float
    pct_above_ema50: float
    spy_volatility: float
    vix: Optional[float]
    max_exposure: float


def classify_regime(
    spy_df: pd.DataFrame,
    universe_df: pd.DataFrame,
    vix: Optional[float] = None,
    bull_exposure: float = 1.0,
    neutral_exposure: float = 0.6,
    bear_exposure: float = 0.25,
) -> RegimeResult:
    """
    Classify current market regime.

    SPY must be fetched with at least 100 days of history for accurate
    EMA 50.  The universe must have at least 50+ bars for EMA 50 on
    breadth to be meaningful.

    Signals (6 total, each worth 1 point):
      1. SPY close > EMA 20
      2. SPY close > EMA 50
      3. SPY EMA 20 > EMA 50 (golden cross)
      4. % of S&P 500 above EMA 20 > 50%
      5. % of S&P 500 above EMA 50 > 50%
      6. SPY realized vol within 1 std of recent range (not panic)

    Scoring: 4-6 → BULL · 2-3 → NEUTRAL · 0-1 → BEAR
    """
    spy_latest = spy_df.sort_values("date").iloc[-1]
    spy_close = spy_latest["close"]
    spy_ema20 = spy_latest.get("ema_20", spy_close)
    spy_ema50 = spy_latest.get("ema_50", spy_close)

    spy_vs_ema20 = (spy_close - spy_ema20) / spy_ema20 * 100
    spy_vs_ema50 = (spy_close - spy_ema50) / spy_ema50 * 100

    # SPY realized volatility (20-day, annualized)
    spy_vol = 0.0
    if "realized_vol_20" in spy_latest.index or isinstance(spy_latest, pd.Series):
        spy_vol = float(spy_latest.get("realized_vol_20", 0) or 0)
    if spy_vol == 0 and "realized_vol_20" in spy_df.columns:
        spy_vol = float(spy_df["realized_vol_20"].dropna().iloc[-1]) if not spy_df["realized_vol_20"].dropna().empty else 0.0

    # SPY vol 60-day rolling rank for context
    spy_vol_60d = spy_df["realized_vol_20"].dropna().tail(60) if "realized_vol_20" in spy_df.columns else pd.Series(dtype=float)
    vol_high = spy_vol > spy_vol_60d.quantile(0.80) if len(spy_vol_60d) > 5 else False

    # ── Universe breadth ────────────────────────────────────────
    latest_date = universe_df["date"].max()
    latest = universe_df[universe_df["date"] == latest_date]

    pct_above_20 = 0.0
    pct_above_50 = 0.0
    if not latest.empty:
        if "ema_20" in latest.columns:
            above_20 = latest["close"] > latest["ema_20"]
            pct_above_20 = above_20.mean() * 100
        if "ema_50" in latest.columns:
            above_50 = latest["close"] > latest["ema_50"]
            pct_above_50 = above_50.mean() * 100

    # ── Scoring ─────────────────────────────────────────────────
    bull_signals = 0
    if spy_vs_ema20 > 0:
        bull_signals += 1
    if spy_vs_ema50 > 0:
        bull_signals += 1
    if spy_ema20 > spy_ema50:
        bull_signals += 1
    if pct_above_20 > 50:
        bull_signals += 1
    if pct_above_50 > 50:
        bull_signals += 1
    if not vol_high:
        bull_signals += 1

    if bull_signals >= 4:
        regime = Regime.BULL
        max_exposure = bull_exposure
    elif bull_signals <= 1:
        regime = Regime.BEAR
        max_exposure = bear_exposure
    else:
        regime = Regime.NEUTRAL
        max_exposure = neutral_exposure

    log.info(
        f"Regime: {regime.value.upper()} "
        f"(signals={bull_signals}/6, "
        f"SPY_vs_EMA20={spy_vs_ema20:+.1f}%, "
        f"SPY_vs_EMA50={spy_vs_ema50:+.1f}%, "
        f"EMA20>EMA50={spy_ema20 > spy_ema50}, "
        f"breadth_EMA20={pct_above_20:.0f}%, "
        f"breadth_EMA50={pct_above_50:.0f}%, "
        f"vol_20d={spy_vol:.1%}, "
        f"vol_high={vol_high}, "
        f"VIX={vix}, "
        f"max_exposure={max_exposure:.0%})"
    )

    return RegimeResult(
        regime=regime,
        spy_vs_ema20=spy_vs_ema20,
        spy_vs_ema50=spy_vs_ema50,
        pct_above_ema20=pct_above_20,
        pct_above_ema50=pct_above_50,
        spy_volatility=spy_vol,
        vix=vix,
        max_exposure=max_exposure,
    )