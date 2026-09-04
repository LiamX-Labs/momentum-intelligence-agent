"""
Position Monitoring Agent.

Continuously evaluates every open position against its entry thesis:
  - Current P&L (stop-loss, profit-taking)
  - Momentum rank deterioration
  - Technical invalidation (close below EMA, RSI extremes)
  - Time in position vs max holding days
  - Market regime change
  - New catalyst/news

The monitoring engine is deterministic — the LLM is consulted only for
thesis-relevance evaluation, never for exit authorization.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from config import get_config

log = logging.getLogger(__name__)


@dataclass
class PositionRecord:
    """Represents an open position with its entry thesis."""

    symbol: str
    option_symbol: str
    direction: str            # "CALL" or "PUT"
    entry_time: datetime
    entry_price: float
    quantity: int
    thesis: str
    invalidation: str
    confidence: float
    expected_holding_days: int
    max_holding_days: int
    entry_momentum_rank: int
    entry_close: float
    order_id: str = ""
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: Optional[float] = None


@dataclass
class MonitorResult:
    """Result of monitoring a single position."""

    symbol: str
    option_symbol: str
    should_exit: bool = False
    exit_reason: str = ""
    exit_triggers: list[str] = field(default_factory=list)
    current_price: Optional[float] = None
    current_pnl_pct: Optional[float] = None
    days_held: int = 0
    current_momentum_rank: Optional[int] = None
    rank_change: int = 0


def _days_between(d1: date | datetime, d2: date | datetime) -> int:
    """Compute calendar days between two dates/datetimes."""
    if isinstance(d1, datetime):
        d1 = d1.date()
    if isinstance(d2, datetime):
        d2 = d2.date()
    return (d2 - d1).days


def check_exit_conditions(
    position: PositionRecord,
    current_price: Optional[float] = None,
    current_momentum_rank: Optional[int] = None,
    current_regime: str = "NEUTRAL",
    current_close: Optional[float] = None,
    ema_20: Optional[float] = None,
    rsi_14: Optional[float] = None,
    today: Optional[date] = None,
) -> MonitorResult:
    """
    Evaluate all exit conditions for a position.

    Exit conditions (checked in order of severity):
      1. Hard stop-loss: current P&L <= -50% of entry
      2. Time stop: days held >= max_holding_days
      3. Profit taking: +50% → partial signal, +100% → full exit
      4. Momentum deterioration: rank fell significantly
      5. Technical invalidation: close below EMA, RSI reversal
      6. Thesis time: approaching expected holding without profit
      7. Market regime: regime turned hostile

    Returns MonitorResult with should_exit flag and reason.
    """
    cfg = get_config()
    today = today or date.today()
    result = MonitorResult(
        symbol=position.symbol,
        option_symbol=position.option_symbol,
        current_price=current_price,
        days_held=_days_between(position.entry_time, today),
        current_momentum_rank=current_momentum_rank,
    )

    if current_momentum_rank is not None and position.entry_momentum_rank > 0:
        result.rank_change = position.entry_momentum_rank - current_momentum_rank

    # ── P&L calculation ──────────────────────────────────────────
    # BUG FIX: this used to flip the sign for PUT positions, as if
    # `entry_price`/`current_price` were the *underlying stock* price
    # (where a bearish/short thesis profits as price falls). They are
    # not -- they're the OPTION PREMIUM (see main.py: entry_price =
    # contract.ask_price at entry, current_price = live option quote).
    # This system only ever goes long options (long calls for a
    # bullish thesis, long puts for a bearish one) -- it never writes/
    # shorts contracts. A long position's P&L is always
    # (current_premium - entry_premium) / entry_premium, regardless of
    # whether the contract is a call or a put: a long put's premium
    # RISES as the underlying falls, so this formula already captures
    # the bearish payoff correctly without a direction-based sign flip.
    # The old PUT-only inverted formula made the system think a put
    # that was gaining value (premium rising) was losing money, and
    # vice versa -- which could trigger stop-losses/profit-takes at
    # exactly the wrong times.
    if current_price is not None and position.entry_price > 0:
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        result.current_pnl_pct = round(pnl_pct, 4)
        result.current_price = current_price

    # ── 1. Hard stop-loss (50% loss) ─────────────────────────────
    if result.current_pnl_pct is not None and result.current_pnl_pct <= -0.50:
        result.exit_triggers.append(f"HARD STOP: {result.current_pnl_pct:.0%} loss")
        result.should_exit = True
        result.exit_reason = f"Hard stop-loss triggered: {result.current_pnl_pct:.0%} loss"
        return result

    # ── 2. Time stop (max holding days) ──────────────────────────
    if result.days_held >= position.max_holding_days:
        result.exit_triggers.append(f"TIME STOP: {result.days_held}/{position.max_holding_days} days")
        result.should_exit = True
        result.exit_reason = f"Max holding period reached ({result.days_held}/{position.max_holding_days} days)"
        return result

    # ── 3. Profit taking ─────────────────────────────────────────
    if result.current_pnl_pct is not None and result.current_pnl_pct >= 1.00:
        result.exit_triggers.append(f"PROFIT TARGET: +{result.current_pnl_pct:.0%} (≥100%)")
        result.should_exit = True
        result.exit_reason = f"Full profit target reached: +{result.current_pnl_pct:.0%}"
        return result

    if result.current_pnl_pct is not None and result.current_pnl_pct >= 0.50:
        result.exit_triggers.append(f"PARTIAL PROFIT: +{result.current_pnl_pct:.0%} (≥50%)")
        # Signal partial exit — in MVP, full exit on 50%+ is acceptable too
        result.should_exit = True
        result.exit_reason = f"Profit target reached: +{result.current_pnl_pct:.0%}"
        return result

    # ── 4. Momentum deterioration ────────────────────────────────
    if current_momentum_rank is not None and position.entry_momentum_rank > 0:
        if current_momentum_rank > 50 or position.entry_momentum_rank <= 10 and current_momentum_rank > 30:
            result.exit_triggers.append(
                f"MOMENTUM DECAY: rank {position.entry_momentum_rank} → {current_momentum_rank}"
            )
            result.should_exit = True
            result.exit_reason = f"Momentum rank deteriorated ({position.entry_momentum_rank} → {current_momentum_rank})"
            return result

    # ── 5. Technical invalidation ────────────────────────────────
    # NOTE: this direction mapping (CALL invalidated below EMA20, PUT
    # invalidated above EMA20) is checked against the UNDERLYING's
    # close vs. its own EMA20 -- correct as written: a bullish/CALL
    # thesis is invalidated when the stock closes below its trend
    # average, a bearish/PUT thesis is invalidated when it closes
    # above it. Do not confuse this with the P&L calculation above,
    # which operates on the option PREMIUM and was the actual
    # inverted-sign bug (now fixed) -- these are two different
    # signals on two different quantities.
    if current_close is not None and ema_20 is not None and ema_20 > 0:
        if position.direction.upper() == "CALL" and current_close < ema_20:
            result.exit_triggers.append(f"TECHNICAL: close ${current_close:.2f} < EMA20 ${ema_20:.2f}")
            result.should_exit = True
            result.exit_reason = f"Price ${current_close:.2f} below 20 EMA ${ema_20:.2f} — thesis invalidated"
            return result
        if position.direction.upper() == "PUT" and current_close > ema_20:
            result.exit_triggers.append(f"TECHNICAL: close ${current_close:.2f} > EMA20 ${ema_20:.2f}")
            result.should_exit = True
            result.exit_reason = f"Price ${current_close:.2f} above 20 EMA ${ema_20:.2f} — thesis invalidated"
            return result

    if rsi_14 is not None:
        if position.direction.upper() == "CALL" and rsi_14 < 30:
            result.exit_triggers.append(f"RSI COLLAPSE: RSI={rsi_14:.0f} < 30")
            result.should_exit = True
            result.exit_reason = f"RSI collapsed to {rsi_14:.0f} — momentum reversed"
            return result
        if position.direction.upper() == "PUT" and rsi_14 > 70:
            result.exit_triggers.append(f"RSI SURGE: RSI={rsi_14:.0f} > 70")
            result.should_exit = True
            result.exit_reason = f"RSI surged to {rsi_14:.0f} — momentum reversed"
            return result

    # ── 6. Approaching expected holding with no profit ───────────
    if result.days_held >= position.expected_holding_days:
        if result.current_pnl_pct is None or result.current_pnl_pct < 0.10:
            result.exit_triggers.append(
                f"THESIS EXPIRY: {result.days_held}d held, expected {position.expected_holding_days}d, "
                f"without meaningful profit"
            )
            result.should_exit = True
            result.exit_reason = (
                f"Thesis timeframe expired ({result.days_held}/{position.expected_holding_days} days) "
                f"without meaningful profit"
            )
            return result

    # ── 7. Market regime turned hostile ──────────────────────────
    if current_regime == "BEAR" and position.direction.upper() == "CALL":
        result.exit_triggers.append("REGIME: BEAR market against CALL position")
        # Don't force-exit here — let other conditions decide. This is advisory.

    # All conditions passed — hold the position
    return result