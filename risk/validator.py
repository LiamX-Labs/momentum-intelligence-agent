"""
Deterministic Risk Validator.

Runs ALL hard gates before a trade is authorized.  The LLM (K2 + Qwen)
produces a recommendation; this module determines whether it is actually
tradable under the current portfolio, risk, and market constraints.

Every gate is deterministic.  Every rejection has a specific reason.
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from config import get_config

from market.regime import RegimeResult
from fundamentals.earnings import EarningsSnapshot, should_reject_for_earnings
from risk.limits import (
    LimitCheckResult,
    check_max_risk_per_trade,
    check_max_open_positions,
    check_portfolio_premium_exposure,
    check_symbol_exposure,
    check_regime_exposure,
)
from risk.sizing import PositionSizeResult, calculate_position_size

log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of running all deterministic risk gates."""

    approved: bool
    reason: str = ""
    gates: list[tuple[str, bool, str]] = field(default_factory=list)
    position_size: Optional[PositionSizeResult] = None


def validate_trade(
    symbol: str,
    direction: str,
    k2_confidence: float,
    qwen_recommendation: str,
    qwen_confidence: float,
    qwen_risk_score: float,
    momentum_score: float,
    final_score: float,
    account_equity: float,
    current_positions: int,
    current_exposure: float,
    current_premium: float,
    option_premium: float,
    regime_result: RegimeResult,
    earnings: Optional[EarningsSnapshot] = None,
    today: Optional[date] = None,
) -> ValidationResult:
    """
    Run all deterministic gates for a trade candidate.

    Returns a ValidationResult with the gate-by-gate breakdown and
    a position size if approved.
    """
    cfg = get_config()
    gates: list[tuple[str, bool, str]] = []
    today = today or date.today()

    demo_cfg = cfg.get("demo", {})
    demo_mode = demo_cfg.get("enabled", False)
    qwen_advisory = demo_cfg.get("qwen_advisory_only", True) and demo_mode
    override_risk = demo_cfg.get("override_risk_gates", True) and demo_mode

    # ── Gate 1: AI recommendation ──────────────────────────────────
    min_confidence = cfg["ai"]["min_confidence"]
    if cfg["ai"]["require_critic"] and qwen_recommendation == "REJECT":
        if qwen_advisory:
            gates.append(
                ("AI: Qwen critic", True,
                 f"Qwen rejected but DEMO mode — advisory only (recommendation=REJECT)")
            )
        else:
            gates.append(
                ("AI: Qwen critic", False,
                 f"Qwen rejected the trade (recommendation=REJECT)")
            )
            return ValidationResult(approved=False, reason="Qwen critic rejected", gates=gates)
    else:
        gates.append(
            ("AI: Qwen critic", True,
             f"Qwen approved (adj_confidence={qwen_confidence:.2f})")
        )

    if k2_confidence < min_confidence:
        if demo_mode:
            gates.append(
                ("AI: K2 confidence", True,
                 f"K2 confidence {k2_confidence:.2f} below minimum {min_confidence} — DEMO override")
            )
        else:
            gates.append(
                ("AI: K2 confidence", False,
                 f"K2 confidence {k2_confidence:.2f} below minimum {min_confidence}")
            )
            return ValidationResult(approved=False, reason="K2 confidence too low", gates=gates)
    else:
        gates.append(
            ("AI: K2 confidence", True,
             f"K2 confidence {k2_confidence:.2f} >= {min_confidence}")
        )

    # ── Gate 2: Momentum threshold ─────────────────────────────────
    min_momentum = cfg["decision"]["min_momentum_score"]
    if momentum_score < min_momentum:
        gates.append(
            ("Momentum", False,
             f"Score {momentum_score:.0f} below minimum {min_momentum}")
        )
        return ValidationResult(approved=False, reason="Momentum score too low", gates=gates)

    gates.append(
        ("Momentum", True, f"Score {momentum_score:.0f} >= {min_momentum}")
    )

    # ── Gate 3: Final score ────────────────────────────────────────
    if final_score < 0.50:
        gates.append(
            ("Final score", False, f"Final score {final_score:.2f} below 0.50")
        )
        return ValidationResult(approved=False, reason="Final score too low", gates=gates)

    gates.append(
        ("Final score", True, f"Final score {final_score:.2f} >= 0.50")
    )

    # ── Gate 4: Market regime exposure ──────────────────────────────
    regime_exposure = _regime_exposure_check(regime_result, account_equity,
                                              current_exposure, option_premium)
    gates.append(("Market regime", regime_exposure.passed, regime_exposure.reason or "OK"))
    if not regime_exposure.passed:
        return ValidationResult(approved=False, reason=regime_exposure.reason or "Regime limits", gates=gates)

    # ── Gate 5: Max open positions ──────────────────────────────────
    pos_check = check_max_open_positions(current_positions)
    gates.append(("Max positions", pos_check.passed, pos_check.reason or "OK"))
    if not pos_check.passed:
        return ValidationResult(approved=False, reason=pos_check.reason or "Max positions", gates=gates)

    # ── Gate 6: Position sizing ─────────────────────────────────────
    sizing = calculate_position_size(account_equity, option_premium)
    if not sizing.is_valid:
        gates.append(
            ("Position sizing", False, sizing.error or "Position sizing failed")
        )
        return ValidationResult(approved=False, reason=sizing.error or "Sizing failed", gates=gates)

    gates.append(
        ("Position sizing", True,
         f"{sizing.max_contracts} contracts at ${sizing.cost_per_contract:.0f}/contract "
         f"(total ${sizing.total_cost:.0f})")
    )

    # ── Gate 7: Max risk per trade ─────────────────────────────────
    risk_check = check_max_risk_per_trade(account_equity, sizing.total_cost)
    gates.append(("Max risk/trade", risk_check.passed, risk_check.reason or "OK"))
    if not risk_check.passed:
        return ValidationResult(approved=False, reason=risk_check.reason or "Risk limit", gates=gates)

    # ── Gate 8: Portfolio premium exposure ──────────────────────────
    premium_check = check_portfolio_premium_exposure(
        account_equity, current_premium, sizing.total_cost
    )
    gates.append(("Portfolio premium", premium_check.passed, premium_check.reason or "OK"))
    if not premium_check.passed:
        return ValidationResult(approved=False, reason=premium_check.reason or "Premium limit", gates=gates)

    # ── Gate 9: Symbol exposure ────────────────────────────────────
    symbol_check = check_symbol_exposure(account_equity, symbol, sizing.total_cost)
    gates.append(("Symbol exposure", symbol_check.passed, symbol_check.reason or "OK"))
    if not symbol_check.passed:
        return ValidationResult(approved=False, reason=symbol_check.reason or "Symbol exposure", gates=gates)

    # ── Gate 10: Earnings risk ─────────────────────────────────────
    if earnings is not None:
        holding_days = cfg["risk"]["max_holding_days"]
        if should_reject_for_earnings(earnings, holding_days=holding_days, today=today):
            gates.append(
                ("Earnings risk", False,
                 f"Earnings event {earnings.next_earnings_date} falls within "
                 f"{holding_days}-day holding period")
            )
            return ValidationResult(approved=False, reason="Earnings in holding period", gates=gates)

        gates.append(
            ("Earnings risk", True,
             f"No earnings in holding period "
             f"(next: {earnings.next_earnings_date or 'unknown'})")
        )
    else:
        gates.append(("Earnings risk", True, "No earnings data available"))

    # ── Gate 11: Qwen risk score ───────────────────────────────────
    hr = cfg["hard_reject"]
    if qwen_risk_score > hr["risk_score_above"]:
        if override_risk:
            gates.append(
                ("Qwen risk score", True,
                 f"Qwen risk score {qwen_risk_score:.2f} exceeds threshold {hr['risk_score_above']} — DEMO override")
            )
        else:
            gates.append(
                ("Qwen risk score", False,
                 f"Qwen risk score {qwen_risk_score:.2f} exceeds threshold {hr['risk_score_above']}")
            )
            return ValidationResult(approved=False, reason=f"Qwen risk score {qwen_risk_score:.2f} too high", gates=gates)
    else:
        gates.append(
            ("Qwen risk score", True,
             f"Qwen risk score {qwen_risk_score:.2f} <= {hr['risk_score_above']}")
        )

    return ValidationResult(
        approved=True,
        reason="All gates passed",
        gates=gates,
        position_size=sizing,
    )


def _regime_exposure_check(
    regime: RegimeResult,
    equity: float,
    current_exposure: float,
    new_exposure: float,
) -> LimitCheckResult:
    """Map the regime result to the exposure check."""
    return check_regime_exposure(
        account_equity=equity,
        max_exposure_ratio=regime.max_exposure,
        current_exposure=current_exposure,
        new_exposure=new_exposure,
    )