"""
Option contract selector.

Applies deterministic filters to a list of OptionContract objects:
  1. DTE within configured range
  2. Liquidity: min bid price, min open interest, max bid-ask spread
  3. Strike proximity: strike must be within N% of the underlying
  4. Delta: within target range (real API delta, or a bounded
     Black-Scholes approximation when the API doesn't return greeks)

The AI never selects the contract — this module does.

BUG FIX SUMMARY (see options/greeks.py and options/chain.py for the
companion fixes):
  - Delta is now hard-rejected using the *best available* delta (real
    API greeks if present, otherwise the corrected Black-Scholes
    approximation) instead of only rejecting when real greeks happen
    to be present. Alpaca's paper options API commonly omits greeks,
    so the old code effectively never rejected on delta in practice.
  - Added an explicit strike-proximity filter
    (abs(strike - stock_price) / stock_price <= max pct).
  - Added a real minimum-bid guard (bid must be > $0.15 — a $0.00 bid
    is never acceptable) and a minimum open-interest guard.
  - Spread is now computed for real (see OptionContract.spread_pct);
    a missing/zero bid is rejected by the min-bid guard rather than
    silently treated as "a fine 5% spread".
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from config import get_config
from options.chain import OptionContract
from options.greeks import approximate_delta

log = logging.getLogger(__name__)


@dataclass
class SelectionResult:
    selected: Optional[OptionContract] = None
    candidates: list[OptionContract] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    reason: str = ""

    @property
    def success(self) -> bool:
        return self.selected is not None


def _effective_delta(
    contract: OptionContract,
    underlying_price: Optional[float],
) -> Optional[float]:
    """Real API delta if available, else the bounded BS approximation."""
    if contract.delta is not None:
        return contract.delta
    if not underlying_price:
        return None
    return approximate_delta(
        strike_price=contract.strike_price,
        underlying_price=underlying_price,
        contract_type=contract.contract_type,
        dte=contract.dte,
        iv=contract.implied_volatility,
    )


def select_contract(
    contracts: list[OptionContract],
    underlying_price: Optional[float] = None,
) -> SelectionResult:
    """
    Select the best option contract from a list of candidates.

    Hard filters (in order), ALL enforced regardless of whether delta
    came from the API or the approximation:
      1. DTE within range
      2. Has a valid quote (bid AND ask present)
      3. Min bid price (never buy a $0.00 bid contract)
      4. Min open interest
      5. Max bid-ask spread (real spread, no fabricated estimate)
      6. Strike proximity to underlying
      7. Delta within target range

    Then scores the survivors and picks the best.

    All thresholds come from config.yaml.
    """
    cfg = get_config()
    opt_cfg = cfg["options"]
    min_dte = opt_cfg["min_dte"]
    max_dte = opt_cfg["max_dte"]
    target_delta_min = opt_cfg["target_delta_min"]
    target_delta_max = opt_cfg["target_delta_max"]
    max_spread = opt_cfg["max_bid_ask_spread_pct"]
    min_bid = opt_cfg.get("min_bid_price", 0.15)
    min_oi = opt_cfg.get("min_open_interest", 100)
    max_strike_proximity = opt_cfg.get("strike_proximity_max_pct", 0.10)

    results = SelectionResult()
    passing: list[OptionContract] = []

    for c in contracts:
        # ── DTE filter ─────────────────────────────────────────
        if c.dte < min_dte:
            results.rejected.append((c.symbol, f"DTE {c.dte} < {min_dte}"))
            continue
        if c.dte > max_dte:
            results.rejected.append((c.symbol, f"DTE {c.dte} > {max_dte}"))
            continue

        # ── Quote filter ───────────────────────────────────────
        if c.ask_price is None or c.ask_price <= 0:
            results.rejected.append((c.symbol, "No valid ask"))
            continue
        if c.bid_price is None or c.bid_price <= 0:
            results.rejected.append((c.symbol, "No valid bid (bid <= 0)"))
            continue

        # ── Minimum bid (liquidity guard #1) ────────────────────
        # NEVER buy an option with a near-zero bid: it can be sold
        # for essentially nothing and the "premium" was noise, not
        # a real market. This is what let the $40-strike-put-with-
        # $0.00-bid contracts through before.
        if c.bid_price <= min_bid:
            results.rejected.append(
                (c.symbol, f"Bid ${c.bid_price:.2f} <= min ${min_bid:.2f}")
            )
            continue

        # ── Open interest (liquidity guard #2) ──────────────────
        if c.open_interest < min_oi:
            results.rejected.append(
                (c.symbol, f"Open interest {c.open_interest} < {min_oi}")
            )
            continue

        # ── Spread filter (liquidity guard #3) ──────────────────
        # spread_pct is None when it can't be computed for real (see
        # OptionContract.spread_pct) -- treat that as a reject, not
        # as "assume it's fine".
        spread = c.spread_pct
        if spread is None:
            results.rejected.append((c.symbol, "Spread could not be determined"))
            continue
        if spread > max_spread:
            results.rejected.append((c.symbol, f"Spread {spread:.1%} > {max_spread:.0%}"))
            continue

        # ── Strike proximity filter ─────────────────────────────
        if underlying_price and underlying_price > 0:
            proximity = abs(c.strike_price - underlying_price) / underlying_price
            if proximity > max_strike_proximity:
                results.rejected.append(
                    (c.symbol, f"Strike {proximity:.1%} from underlying > {max_strike_proximity:.0%}")
                )
                continue

        # ── Delta filter (HARD reject, real or approximated) ───
        delta = _effective_delta(c, underlying_price)
        if delta is None:
            results.rejected.append((c.symbol, "No delta available (real or approximated)"))
            continue

        if c.contract_type.upper() == "CALL":
            if delta < target_delta_min or delta > target_delta_max:
                results.rejected.append(
                    (c.symbol, f"Delta {delta:.2f} outside [{target_delta_min}-{target_delta_max}]")
                )
                continue
        else:
            abs_delta = abs(delta)
            if abs_delta < target_delta_min or abs_delta > target_delta_max:
                results.rejected.append(
                    (c.symbol, f"|Delta| {abs_delta:.2f} outside [{target_delta_min}-{target_delta_max}]")
                )
                continue

        passing.append(c)

    results.candidates = passing

    if not passing:
        results.reason = f"0/{len(contracts)} contracts passed filters"
        return results

    # ── Score and pick best ────────────────────────────────────
    # Score = spread quality (lower is better) + delta proximity + liquidity
    best = None
    best_score = -1.0
    target_delta = (target_delta_min + target_delta_max) / 2

    for c in passing:
        score = 0.0
        delta = _effective_delta(c, underlying_price)

        # Spread score: 0-40 points
        spread = c.spread_pct or 0
        score += max(0, 40 - spread * 200)

        # Delta proximity: 0-30 points
        if delta is not None:
            proximity = 1.0 - min(abs(abs(delta) - target_delta), 0.3) / 0.3
            score += 30 * proximity

        # Liquidity: 0-30 points (bid/ask size + open interest)
        bid_size = c.bid_size or 0
        ask_size = c.ask_size or 0
        quote_liquidity = min(bid_size + ask_size, 1000) / 1000
        oi_liquidity = min(c.open_interest, 1000) / 1000
        score += 15 * quote_liquidity + 15 * oi_liquidity

        if score > best_score:
            best_score = score
            best = c

    if best:
        results.selected = best
        results.reason = (
            f"Selected {best.symbol} (score={best_score:.0f}, DTE={best.dte}, "
            f"spread={best.spread_pct or 0:.1%}, OI={best.open_interest}, "
            f"delta={_effective_delta(best, underlying_price):.2f})"
        )
    else:
        results.reason = "No contract scored above threshold"

    return results
