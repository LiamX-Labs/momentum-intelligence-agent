"""
Option greeks helper utilities.

Provides fallback delta approximation when the Alpaca snapshot API
doesn't return greeks data (common in paper trading environments).

BUG FIX (Options Selection Algorithm):
----------------------------------------
The previous approximation used a hand-tuned *linear* formula
(``raw = 0.90 - (moneyness - 0.85) * steepness``) that is not bounded
correctly. For far out-of-the-money contracts it doesn't decay toward
0 the way a real option's delta does -- it keeps moving linearly and
overshoots past zero into the *opposite* sign entirely. For example a
deep OTM PUT (strike far below the stock price) computed a delta of
+1.0 (should be ~0), and a deep OTM CALL (strike far above the stock
price) computed a delta of -1.0 (should be ~0). Combined with
``options/selector.py`` only hard-rejecting on *real* API delta (and
using the approximation for scoring only), this let garbage deep-OTM,
near-zero-premium contracts (e.g. a $40 strike put against a $148
stock) pass every filter.

This module now uses a standard Black-Scholes d1 / normal-CDF delta,
which is monotonic and correctly bounded: it asymptotes to 0 for far
OTM contracts and to +/-1 for far ITM contracts, regardless of how far
out the strike is.
"""

import logging
import math
from typing import Optional

log = logging.getLogger(__name__)

# Reasonable defaults when real IV / risk-free rate aren't available.
# 35% annualized vol is a sane mid-point for the momentum/small-cap
# names this system trades; the risk-free rate barely moves delta at
# these short (7-21 DTE) horizons so a static estimate is fine.
DEFAULT_IV = 0.35
DEFAULT_RISK_FREE_RATE = 0.05


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using the exact erf-based formula (no scipy dep)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def approximate_delta(
    strike_price: float,
    underlying_price: float,
    contract_type: str,
    dte: int = 14,
    iv: Optional[float] = None,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """
    Approximate delta using the Black-Scholes d1 / N(d1) formula.

    - ATM options have delta ~0.50 (calls) or ~-0.50 (puts)
    - ITM options approach +/-1.0 as moneyness increases
    - OTM options approach 0 as moneyness decreases (never crosses
      into the opposite sign, unlike the old linear approximation)

    This is still an approximation (it assumes a flat IV when the
    real one isn't known), but it is a *bounded, monotonic, correctly
    signed* one, which real greeks from the API should always be
    preferred over.
    """
    if not underlying_price or underlying_price <= 0 or not strike_price or strike_price <= 0:
        return 0.0

    is_call = contract_type.upper() == "CALL"
    t = max(dte, 1) / 365.0
    sigma = iv if iv and iv > 0 else DEFAULT_IV

    try:
        d1 = (
            math.log(underlying_price / strike_price)
            + (risk_free_rate + 0.5 * sigma * sigma) * t
        ) / (sigma * math.sqrt(t))
    except (ValueError, ZeroDivisionError):
        return 0.0

    call_delta = _norm_cdf(d1)
    return call_delta if is_call else call_delta - 1.0


def approximate_iv_from_premium(
    option_premium: float,
    underlying_price: float,
    strike_price: float,
    dte: int,
    is_call: bool = True,
) -> float:
    """
    Very rough IV approximation from option premium.

    Uses: IV ≈ premium / (underlying * sqrt(DTE/365) * 0.4)

    Only use when API IV is unavailable.
    """
    if underlying_price <= 0 or dte <= 0:
        return 0.0

    time_factor = (dte / 365) ** 0.5
    expected_move = underlying_price * time_factor * 0.4

    if expected_move <= 0:
        return 0.0

    return option_premium / expected_move
