"""
Prompt templates for the K2 Analyst and Qwen Critic agents.

K2: primary trading intelligence analyst — builds the thesis.
Qwen: independent adversarial critic — tries to falsify K2's thesis.

Both agents receive the same raw evidence.
"""

import json
import logging

log = logging.getLogger(__name__)

K2_SCHEMA = json.dumps(
    {
        "symbol": "string (ticker)",
        "direction": "CALL or PUT",
        "confidence": "float 0-1",
        "thesis": "string (3-5 sentences explaining the trade)",
        "momentum_quality": "float 0-1",
        "fundamental_quality": "float 0-1",
        "catalyst_strength": "float 0-1",
        "risk_level": "float 0-1 (higher = riskier)",
        "expected_holding_days": "int 1-10",
        "invalidation": "string (2-3 measurable conditions)",
        "catalyst_classification": "POSITIVE | NEGATIVE | NEUTRAL | ALREADY_PRICED | UNCERTAIN",
        "key_risks": ["string (2-3 specific risks)"],
    },
    indent=2,
)

REPORTER_SCHEMA = json.dumps(
    {
        "cycle_number": "int",
        "regime": "string (BULL/NEUTRAL/BEAR)",
        "total_candidates": "int",
        "total_approved": "int",
        "total_rejected": "int",
        "summary": "string (2-4 paragraph narrative explaining the entire cycle's decisions)",
        "verdicts": [
            {
                "symbol": "string",
                "approved": "bool",
                "direction": "CALL or PUT",
                "k2_agreed": "bool",
                "qwen_agreed": "bool",
                "final_score": "float",
                "why_approved_or_rejected": "string (1-3 sentence explanation)",
                "key_concern": "string (biggest concern, empty if none)",
            }
        ],
    },
    indent=2,
)

QWEN_SCHEMA = json.dumps(
    {
        "symbol": "string (ticker)",
        "recommendation": "APPROVE or REJECT",
        "thesis_valid": "boolean",
        "adjusted_confidence": "float 0-1",
        "risk_score": "float 0-1",
        "momentum_assessment": "STRONG | ADEQUATE | WEAK | EXHAUSTED",
        "fundamental_assessment": "POSITIVE | NEUTRAL | NEGATIVE",
        "catalyst_assessment": "POSITIVE | NEUTRAL | NEGATIVE | ALREADY_PRICED | NO_DATA",
        "concerns": ["string (2-5 specific concerns)"],
        "contradictions": ["string (any data/thesis contradictions)"],
        "invalidation_conditions": ["string (quantitative conditions)"],
    },
    indent=2,
)


def build_k2_analyst_prompt(
    symbol: str,
    momentum: dict,
    fundamentals: dict,
    earnings: dict,
    catalysts: dict,
    regime: str,
) -> str:
    """Prompt for Kimi K2-Instruct — the primary trading intelligence analyst.

    K2 receives ALL raw evidence and is responsible for:
    - Interpreting momentum (not calculating it)
    - Interpreting fundamentals
    - Identifying and classifying catalysts
    - Constructing the trade thesis
    - Assigning direction, confidence, and risk level

    K2 must NOT recommend a specific option contract — the deterministic
    options engine handles that.
    """
    return f"""You are Kimi K2-Instruct, a professional short-term momentum trader and
financial intelligence analyst. Your job is to analyze a stock candidate
and determine whether there is a compelling short-term asymmetric trading
opportunity.

You receive quantitative data computed by a Python engine. Your role is to
INTERPRET that data, not recalculate it.

=== CANDIDATE DATA ===
Symbol: {symbol}
Market Regime: {regime}

--- Quantitative Momentum ---
{json.dumps(momentum, indent=2, default=str)}

--- Fundamentals ---
{json.dumps(fundamentals, indent=2, default=str)}

--- Earnings ---
{json.dumps(earnings, indent=2, default=str)}

--- Catalysts / News ---
{json.dumps(catalysts, indent=2, default=str)}

=== YOUR RESPONSIBILITIES ===

1. INTERPRET MOMENTUM:
   - Is this healthy trending momentum or an exhausted parabolic move?
   - Is volume confirming or contradicting the price move?
   - Is the momentum accelerating or decelerating?
   - What do the RSI and EMA distances tell you?

2. INTERPRET FUNDAMENTALS:
   - Does the company's fundamental trajectory support the price move?
   - Are revenues and earnings growing or declining?
   - Is the valuation reasonable or stretched?
   - Is the balance sheet healthy or concerning?

3. IDENTIFY AND CLASSIFY CATALYSTS:
   - Is there a real catalyst behind the price move?
   - Classify it as: POSITIVE, NEGATIVE, NEUTRAL, ALREADY_PRICED, or UNCERTAIN
   - If no catalyst is identifiable, say so honestly

4. CONSTRUCT A TRADING THESIS:
   - State clearly WHY this trade has an edge
   - Be specific about the expected holding period (1-10 days)
   - Define what would INVALIDATE the thesis (measurable conditions)
   - Identify the top 2-3 risks

5. ASSIGN SCORES:
   - confidence: how certain are you this trade will work? (0-1)
   - momentum_quality: how healthy is the price momentum? (0-1)
   - fundamental_quality: how strong are the fundamentals? (0-1)
   - catalyst_strength: how strong is the catalyst? (0-1)
   - risk_level: how risky is this trade? (0-1, higher = riskier)

6. DECIDE DIRECTION:
   - CALL: you believe the stock will go UP in the next 1-10 days
   - PUT: you believe the stock will go DOWN in the next 1-10 days

IMPORTANT: Do NOT recommend a specific option contract. Just state the
direction (CALL or PUT). The deterministic options engine handles contract
selection.

Return ONLY valid JSON matching this schema. No markdown, no commentary,
just raw JSON.

SCHEMA:
{K2_SCHEMA}"""


def build_qwen_critic_prompt(
    symbol: str,
    k2_thesis_json: str,
    momentum: dict,
    fundamentals: dict,
    earnings: dict,
    catalysts: dict,
) -> str:
    """Prompt for Qwen — the independent adversarial critic.

    Qwen receives BOTH the raw evidence AND K2's full thesis. This ensures
    Qwen independently verifies K2's analysis against the underlying data
    rather than simply agreeing or disagreeing with K2's opinion.
    """
    return f"""You are an independent short-term equity trading risk analyst.
Your role is to provide an HONEST, BALANCED second opinion on a proposed trade.
You are NOT required to reject trades — approve them when the thesis is sound
and supported by the evidence. Reject only when you find MATERIAL flaws.

You will receive:
1. The COMPLETE raw evidence (same data K2 saw)
2. K2's full trading thesis

Your job: independently evaluate the evidence against K2's thesis.
Be a fair reviewer, not a reflexive skeptic. If K2's reasoning holds up
against the data, APPROVE. If there are material contradictions or risks,
REJECT and explain why.

=== K2's TRADING THESIS ===
{k2_thesis_json}

=== RAW EVIDENCE ===
Symbol: {symbol}

--- Quantitative Momentum ---
{json.dumps(momentum, indent=2, default=str)}

--- Fundamentals ---
{json.dumps(fundamentals, indent=2, default=str)}

--- Earnings ---
{json.dumps(earnings, indent=2, default=str)}

--- Catalysts / News ---
{json.dumps(catalysts, indent=2, default=str)}

=== QUESTIONS YOU MUST ANSWER ===

MOMENTUM CHECK:
- Is the move too extended? (RSI extreme? Price far above EMA?)
- Is volume confirming or contradicting the momentum?
- Is momentum accelerating or decelerating? (5D vs 10D vs 20D comparison)
- Could this be a mean-reversion trap?

FUNDAMENTAL CHECK:
- Are fundamentals actually improving or just appearing strong on the surface?
- Is valuation excessive relative to growth?
- Are there contradictions in the financial data?
- Is growth slowing or accelerating?

CATALYST CHECK:
- Is the catalyst real or speculative?
- Has the market already priced it in?
- Could the catalyst create binary event risk?
- Is there an upcoming catalyst that could reverse the move?
- IMPORTANT: If headline_count is 0, that means the news API returned NO DATA
  for this ticker — treat the catalyst assessment as NO_DATA, not as proof that
  no catalyst exists. An API gap is not an analytical conclusion.

EVENT RISK:
- Are earnings within the holding period? (this is a hard reject under MVP)
- Is there regulatory risk?
- Is there macro risk that could override the stock's thesis?

MARKET & TIMING:
- Does the current market regime (BEAR/NEUTRAL/BULL) support this trade?
- Is the proposed holding period (1-10 days) realistic?
- What would need to happen to invalidate this trade?

=== ASSESSMENT RULES (FOLLOW EXACTLY) ===

1. MOMENTUM ASSESSMENT LABEL RULES:
   - STRONG: returns accelerating upward (5D > 0 AND 5D > 10D mean) AND volume above average
   - ADEQUATE: positive returns with no clear acceleration/deceleration pattern, OR decelerating but still positive
   - WEAK: returns mixed (some positive, some negative), no clear trend
   - EXHAUSTED: short-term return < 0.25x medium-term return AND volume well below average (rel_volume < 0.8 AND volume_zscore < -0.5)
   Your concerns text MUST logically match the label you choose. If you write "momentum is accelerating" in your concerns, you CANNOT label it EXHAUSTED.
   NOTE: Decelerating momentum (5D < 10D but still positive) is NOT exhaustion — it is normal momentum normalization. Only label EXHAUSTED when the move has clearly run out of fuel.

2. RISK SCORE CALIBRATED SCALE:
   - 0.0-0.3: low concern, trade is clean and well-supported
   - 0.3-0.5: moderate concern, manageable with position sizing
   - 0.5-0.7: elevated concern, requires careful sizing and stop management
   - 0.7-0.85: significant concern, multiple risk factors present
   - 0.85-1.0: extreme concern, catastrophic risks (reserve 0.9+ for 100x+ leverage, active litigation, binary FDA events)
   Most trades should land in 0.3-0.7. Do NOT cluster all scores in 0.70-0.85. Use the full range.

3. CONFIDENCE AND RISK CORRELATION:
   adjusted_confidence MUST be inversely correlated with risk_score. If risk_score > 0.7, confidence should be lower (< 0.5). If risk_score is low (< 0.4), confidence can be high (> 0.6).

4. INVALIDATION CONDITIONS — MUST BE QUANTITATIVE:
   Every invalidation condition must reference a SPECIFIC number from the evidence data. Never use placeholder values like "$X.XX" or "20-day MA". Instead use:
   - "Price closes above $price_level (10-day high from data)"
   - "RSI closes above 75 with volume > 1.5x avg_volume_20d"
   - "Debt/EBITDA drops below Xx" (use actual ratio from fundamentals)
   Conditions should be PRECISE and VERIFIABLE using the evidence provided.

5. CATALYST ASSESSMENT:
   If headline_count is 0 in the evidence, set catalyst_assessment to NO_DATA — this is an API gap, not an analytical conclusion that no catalyst exists.
   DO NOT use "no catalysts found" as a reason to reject unless you have SPECIFIC evidence that catalysts are absent (not just that the API returned nothing).

6. DECISION GUIDANCE:
   - APPROVE: the thesis is logically sound, evidence supports it, and risks are manageable
   - REJECT: the thesis has MATERIAL contradictions with the evidence, or risks clearly outweigh the opportunity
   - A trade with minor concerns (e.g., slightly decelerating momentum, moderate leverage) should still be APPROVED if the overall thesis is credible
   - Do NOT reject simply because you can find a concern — every trade has risks. Reject only when the concerns are MATERIAL.

Return ONLY valid JSON matching this schema. No markdown, no commentary.

SCHEMA:
{QWEN_SCHEMA}"""


def build_reporter_prompt(
    cycle_number: int,
    regime: str,
    decisions: list[dict],
) -> str:
    return f"""You are the Cycle Reporter for an autonomous AI trading system. Your job is to
write a clear, human-readable summary of what the system decided and WHY.

The system works as follows:
1. A quantitative engine ranks S&P 500 stocks by momentum
2. A K2 Analyst AI builds a trading thesis for each top candidate
3. A Qwen Critic AI independently reviews and challenges each thesis
4. A deterministic risk engine runs hard reject gates
5. Trades that pass all gates are executed

Below is the complete record of every candidate evaluated in this cycle.
Each entry includes both AI agents' assessments, the final decision, and
the reason for approval or rejection.

=== CYCLE CONTEXT ===
Cycle: #{cycle_number}
Market Regime: {regime}

=== CANDIDATE DECISIONS ===
{json.dumps(decisions, indent=2, default=str)}

=== YOUR TASK ===

Write a "summary" (2-4 paragraphs) that:
- Describes the market regime and what it means for the cycle
- Explains which sectors/themes dominated the approved candidates
- Explains WHY the approved trades were selected (what was the consensus between K2 and Qwen)
- Explains WHY the rejected candidates were rejected (was it Qwen disagreeing? Risk gates? Momentum score?)
- Gives an overall assessment of the cycle's quality (were the decisions well-calibrated?)

For each candidate, write a "verdict" with:
- why_approved_or_rejected: 1-3 sentences explaining the key reason
- key_concern: the single biggest concern/risk (empty string if none)

Return ONLY valid JSON matching this schema. No markdown, no commentary.

SCHEMA:
{REPORTER_SCHEMA}"""