"""
Portfolio-level risk limits.

Enforces configurable hard caps on per-trade risk, total open positions,
portfolio option premium exposure, and per-symbol concentration.

All functions are deterministic — no LLM involvement.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config import get_config

log = logging.getLogger(__name__)


@dataclass
class LimitCheckResult:
    passed: bool
    reason: Optional[str] = None
    current_value: float = 0.0
    limit_value: float = 0.0


def check_max_risk_per_trade(
    account_equity: float,
    max_loss: float,
) -> LimitCheckResult:
    """Check that the max loss on this trade does not exceed the risk limit."""
    cfg = get_config()
    max_risk_pct = cfg["risk"]["max_risk_per_trade"]
    max_risk_dollar = account_equity * max_risk_pct

    if max_loss > max_risk_dollar:
        return LimitCheckResult(
            passed=False,
            reason=f"Max loss ${max_loss:.0f} exceeds risk limit ${max_risk_dollar:.0f} "
                   f"({max_risk_pct:.0%} of ${account_equity:.0f})",
            current_value=max_loss,
            limit_value=max_risk_dollar,
        )
    return LimitCheckResult(passed=True, current_value=max_loss, limit_value=max_risk_dollar)


def check_max_open_positions(current_positions: int) -> LimitCheckResult:
    """Check that adding a position won't exceed the max open positions."""
    cfg = get_config()
    max_positions = cfg["risk"]["max_open_positions"]

    if current_positions >= max_positions:
        return LimitCheckResult(
            passed=False,
            reason=f"Max open positions ({max_positions}) already reached "
                   f"({current_positions} positions)",
            current_value=current_positions,
            limit_value=max_positions,
        )
    return LimitCheckResult(passed=True, current_value=current_positions, limit_value=max_positions)


def check_portfolio_premium_exposure(
    account_equity: float,
    total_premium: float,
    new_premium: float,
) -> LimitCheckResult:
    """Check that total option premium does not exceed portfolio limit."""
    cfg = get_config()
    max_premium_pct = cfg["risk"]["max_portfolio_option_premium"]
    max_premium = account_equity * max_premium_pct
    projected_total = total_premium + new_premium

    if projected_total > max_premium:
        return LimitCheckResult(
            passed=False,
            reason=f"Total premium ${projected_total:.0f} would exceed "
                   f"max ${max_premium:.0f} ({max_premium_pct:.0%})",
            current_value=projected_total,
            limit_value=max_premium,
        )
    return LimitCheckResult(passed=True, current_value=projected_total, limit_value=max_premium)


def check_symbol_exposure(
    account_equity: float,
    symbol: str,
    new_exposure: float,
    existing_exposure: float = 0.0,
) -> LimitCheckResult:
    """Check that per-symbol exposure does not exceed the limit."""
    cfg = get_config()
    max_exp_pct = cfg["risk"]["max_symbol_exposure"]
    max_exp = account_equity * max_exp_pct
    total_exp = existing_exposure + new_exposure

    if total_exp > max_exp:
        return LimitCheckResult(
            passed=False,
            reason=f"Symbol {symbol} exposure ${total_exp:.0f} exceeds "
                   f"max ${max_exp:.0f} ({max_exp_pct:.0%})",
            current_value=total_exp,
            limit_value=max_exp,
        )
    return LimitCheckResult(passed=True, current_value=total_exp, limit_value=max_exp)


def check_regime_exposure(
    account_equity: float,
    max_exposure_ratio: float,
    current_exposure: float,
    new_exposure: float,
) -> LimitCheckResult:
    """Check that total portfolio exposure respects the market regime cap."""
    max_total = account_equity * max_exposure_ratio
    projected = current_exposure + new_exposure

    if projected > max_total:
        return LimitCheckResult(
            passed=False,
            reason=f"Portfolio exposure ${projected:.0f} exceeds "
                   f"regime limit ${max_total:.0f} ({max_exposure_ratio:.0%})",
            current_value=projected,
            limit_value=max_total,
        )
    return LimitCheckResult(passed=True, current_value=projected, limit_value=max_total)