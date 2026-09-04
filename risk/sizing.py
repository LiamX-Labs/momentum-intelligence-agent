"""
Options position sizing.

Calculates the number of option contracts to trade based on:
  - Account equity
  - Maximum risk per trade (configurable % of portfolio)
  - Option premium (cost per contract)
  - Contract multiplier (typically 100)

For options, position size is calculated as:
  max_loss = account_equity * max_risk_per_trade
  cost_per_contract = option_premium * contract_multiplier
  max_contracts = floor(max_loss / cost_per_contract)

All calculations are deterministic — no LLM involvement.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from config import get_config

log = logging.getLogger(__name__)

CONTRACT_MULTIPLIER = 100


@dataclass
class PositionSizeResult:
    """Result of a position sizing calculation."""

    max_contracts: int
    max_loss_dollar: float
    cost_per_contract: float
    total_cost: float
    account_equity: float
    risk_pct: float
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.max_contracts > 0


def calculate_position_size(
    account_equity: float,
    option_premium: float,
    max_risk_pct: Optional[float] = None,
    contract_multiplier: int = CONTRACT_MULTIPLIER,
) -> PositionSizeResult:
    """
    Calculate the number of option contracts to trade.

    Args:
        account_equity: Current account equity in dollars.
        option_premium: Price of one option contract (per share).
        max_risk_pct: Maximum risk as a fraction of portfolio (default from config).
        contract_multiplier: Shares per contract (default 100).

    Returns:
        PositionSizeResult with max_contracts and cost breakdown.
    """
    cfg = get_config()

    if max_risk_pct is None:
        max_risk_pct = cfg["risk"]["max_risk_per_trade"]

    if option_premium <= 0:
        return PositionSizeResult(
            max_contracts=0,
            max_loss_dollar=0.0,
            cost_per_contract=0.0,
            total_cost=0.0,
            account_equity=account_equity,
            risk_pct=max_risk_pct,
            error=f"Option premium must be positive (got {option_premium})",
        )

    max_loss_dollar = account_equity * max_risk_pct
    cost_per_contract = option_premium * contract_multiplier

    if cost_per_contract > max_loss_dollar:
        return PositionSizeResult(
            max_contracts=0,
            max_loss_dollar=max_loss_dollar,
            cost_per_contract=cost_per_contract,
            total_cost=0.0,
            account_equity=account_equity,
            risk_pct=max_risk_pct,
            error=f"Option premium ${option_premium:.2f} × {contract_multiplier} = "
                  f"${cost_per_contract:.0f} exceeds max loss ${max_loss_dollar:.0f}",
        )

    max_contracts = int(max_loss_dollar // cost_per_contract)
    total_cost = max_contracts * cost_per_contract

    return PositionSizeResult(
        max_contracts=max_contracts,
        max_loss_dollar=max_loss_dollar,
        cost_per_contract=cost_per_contract,
        total_cost=total_cost,
        account_equity=account_equity,
        risk_pct=max_risk_pct,
    )


def calculate_partial_size(
    account_equity: float,
    option_premium: float,
    target_risk_pct: float = 0.005,
    contract_multiplier: int = CONTRACT_MULTIPLIER,
) -> PositionSizeResult:
    """
    Calculate a smaller position size for partial entries or scaling in.

    Uses a lower risk percentage (default 0.5%) for partial positions.
    """
    return calculate_position_size(
        account_equity=account_equity,
        option_premium=option_premium,
        max_risk_pct=target_risk_pct,
        contract_multiplier=contract_multiplier,
    )