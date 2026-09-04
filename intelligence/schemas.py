"""
Structured output schemas for the K2 analyst and Qwen critic agents.

All fields use Pydantic for validation.  These schemas ensure the LLMs can
never produce free-form output that directly triggers an order.
"""

from pydantic import BaseModel, Field


class K2AnalystOutput(BaseModel):
    """Output schema for Kimi K2-Instruct — primary trading intelligence agent."""

    symbol: str = Field(description="Stock ticker symbol")
    direction: str = Field(
        description="CALL or PUT", pattern="^(CALL|PUT)$"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Overall confidence in the trade (0-1)"
    )
    thesis: str = Field(
        description=(
            "Concise trading thesis explaining why momentum + fundamentals + "
            "catalysts support continuation. 3-5 sentences."
        )
    )
    momentum_quality: float = Field(
        ge=0.0, le=1.0, description="Assessment of momentum signal quality (0-1)"
    )
    fundamental_quality: float = Field(
        ge=0.0, le=1.0, description="Assessment of fundamental strength (0-1)"
    )
    catalyst_strength: float = Field(
        ge=0.0, le=1.0, description="Assessment of catalyst strength (0-1)"
    )
    risk_level: float = Field(
        ge=0.0, le=1.0, description="Risk level — higher = riskier (0-1)"
    )
    expected_holding_days: int = Field(
        ge=1, le=10, description="Expected number of trading days to hold"
    )
    invalidation: str = Field(
        description=(
            "Conditions that would invalidate the thesis. 2-3 specific, "
            "measurable conditions."
        )
    )
    catalyst_classification: str = Field(
        description="POSITIVE, NEGATIVE, NEUTRAL, ALREADY_PRICED, or UNCERTAIN",
        pattern="^(POSITIVE|NEGATIVE|NEUTRAL|ALREADY_PRICED|UNCERTAIN)$",
    )
    key_risks: list[str] = Field(
        default_factory=list,
        description="Top 2-3 specific risks for this trade",
    )


class QwenCriticOutput(BaseModel):
    """Output schema for Qwen — independent adversarial critic."""

    symbol: str = Field(description="Stock ticker symbol")
    recommendation: str = Field(
        description="APPROVE or REJECT", pattern="^(APPROVE|REJECT)$"
    )
    thesis_valid: bool = Field(
        description="Whether the critic finds K2's thesis fundamentally sound"
    )
    adjusted_confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Critic-adjusted confidence after adversarial review",
    )
    risk_score: float = Field(
        ge=0.0, le=1.0, description="Critic's independent risk assessment (0-1)"
    )

    momentum_assessment: str = Field(
        description="STRONG, ADEQUATE, WEAK, or EXHAUSTED",
        pattern="^(STRONG|ADEQUATE|WEAK|EXHAUSTED)$",
    )
    fundamental_assessment: str = Field(
        description="POSITIVE, NEUTRAL, or NEGATIVE",
        pattern="^(POSITIVE|NEUTRAL|NEGATIVE)$",
    )
    catalyst_assessment: str = Field(
        description="POSITIVE, NEUTRAL, NEGATIVE, ALREADY_PRICED, or NO_DATA",
        pattern="^(POSITIVE|NEUTRAL|NEGATIVE|ALREADY_PRICED|NO_DATA)$",
    )

    concerns: list[str] = Field(
        default_factory=list,
        description="2-5 specific concerns that challenge K2's thesis",
    )
    contradictions: list[str] = Field(
        default_factory=list,
        description="Any contradictions found in the data or thesis",
    )
    invalidation_conditions: list[str] = Field(
        default_factory=list,
        description="Specific conditions that would invalidate the trade",
    )

    # Shortcut properties for decision engine
    @property
    def is_rejected(self) -> bool:
        return self.recommendation == "REJECT" or not self.thesis_valid

    @property
    def is_approved(self) -> bool:
        return self.recommendation == "APPROVE" and self.thesis_valid


class ReporterVerdict(BaseModel):
    """Single candidate verdict in the reporter's summary."""

    symbol: str = Field(description="Ticker symbol")
    approved: bool = Field(description="Whether the trade was ultimately approved")
    direction: str = Field(description="CALL or PUT")
    k2_agreed: bool = Field(description="Whether K2 was confident in this trade")
    qwen_agreed: bool = Field(description="Whether Qwen approved")
    final_score: float = Field(ge=0.0, le=1.0)
    why_approved_or_rejected: str = Field(
        description="1-3 sentences explaining the key reason for approval or rejection"
    )
    key_concern: str = Field(
        default="",
        description="The single biggest concern or risk, if any",
    )


class ReporterOutput(BaseModel):
    """Output schema for the cycle reporter agent."""

    cycle_number: int = Field(description="Which cycle this report covers")
    regime: str = Field(description="Market regime during this cycle")
    total_candidates: int = Field(description="Number of candidates analyzed")
    total_approved: int = Field(description="Number of candidates approved")
    total_rejected: int = Field(description="Number of candidates rejected")
    summary: str = Field(
        description=(
            "2-4 paragraph narrative summary of the entire cycle: "
            "what market conditions were, which sectors dominated, "
            "why the approved trades were selected, why rejections happened. "
            "Written in plain English for a human trader to quickly understand "
            "what the system did and why."
        )
    )
    verdicts: list[ReporterVerdict] = Field(
        default_factory=list,
        description="Individual verdict for each candidate",
    )