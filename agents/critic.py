"""
Qwen Critic Agent — Independent Adversarial Review.

Uses Qwen3.8-27B to independently challenge K2's trading thesis.
Qwen receives BOTH the raw evidence and K2's thesis, allowing it
to verify K2's reasoning against the underlying data.

This is NOT a second opinion — it is adversarial review. Qwen's job
is to try to falsify the trade, not confirm it.
"""

import json
import logging

from intelligence.featherless import chat
from intelligence.prompts import build_qwen_critic_prompt
from intelligence.schemas import K2AnalystOutput, QwenCriticOutput

log = logging.getLogger(__name__)

QWEN_MODEL = "Qwen/Qwen3-32B"


def run_critic(
    symbol: str,
    k2_output: K2AnalystOutput,
    momentum: dict,
    fundamentals: dict,
    earnings: dict,
    catalysts: dict,
    model: str | None = None,
) -> QwenCriticOutput | None:
    """Run Qwen critic for a single candidate.

    Qwen receives the SAME raw evidence as K2 PLUS K2's full thesis,
    enabling independent verification against the underlying data.

    Returns a validated QwenCriticOutput or None if the LLM fails.
    """
    model = model or QWEN_MODEL

    system_prompt = (
        "You are an independent short-term equity trading risk analyst. "
        "You provide an honest, balanced second opinion on trading theses. "
        "You independently assess the same raw evidence the primary analyst saw. "
        "Approve when the thesis is sound and supported by evidence. "
        "Reject only when you find MATERIAL flaws or contradictions. "
        "Evaluate metrics within sector context (e.g., SaaS models naturally carry deferred revenue liabilities that lower current ratios). "
        "You produce strictly structured JSON. "
        "Never include markdown formatting or extra commentary — only raw JSON. "
        "Be honest: if the thesis is sound, say so. If it has flaws, expose them."
    )

    user_prompt = build_qwen_critic_prompt(
        symbol=symbol,
        k2_thesis_json=k2_output.model_dump_json(indent=2),
        momentum=momentum,
        fundamentals=fundamentals,
        earnings=earnings,
        catalysts=catalysts,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = chat(messages=messages, model=model, temperature=0.3, max_tokens=2048)
    except Exception as e:
        log.error(f"Qwen critic LLM call failed for {symbol}: {e}")
        # Try fallback model
        try:
            response = chat(messages=messages, model="deepseek-ai/DeepSeek-V3.2", temperature=0.3, max_tokens=2048)
            log.info(f"    Qwen fallback to DeepSeek-V3.2 succeeded")
        except Exception as e2:
            log.error(f"Qwen fallback also failed: {e2}")
            return None

    log.debug(f"Qwen raw response ({len(response)} chars): {response[:300]}")

    try:
        data = _extract_json(response)
        return QwenCriticOutput(**data)
    except Exception as e:
        log.error(f"Qwen critic output parsing failed for {symbol}: {e}")
        log.debug(f"Raw response: {response[:500]}")
        return None


def _extract_json(text: str) -> dict:
    """Extract valid JSON from LLM output, with repair attempts."""
    text = text.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    # Attempt 1: raw parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt 2: fix trailing commas
    import re
    fixed = re.sub(r",(\s*[}\]])", r"\1", text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Attempt 3: replace literal newlines inside quoted strings
    def _escape_string_newlines(s: str) -> str:
        result = []
        in_string = False
        escape_next = False
        for ch in s:
            if escape_next:
                result.append(ch)
                escape_next = False
                continue
            if ch == "\\":
                result.append(ch)
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                result.append(ch)
                continue
            if in_string and ch == "\n":
                result.append("\\n")
                continue
            result.append(ch)
        return "".join(result)

    fixed = _escape_string_newlines(fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Attempt 4: try relaxed JSON (json5)
    try:
        import json5
        data = json5.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Last resort — re-raise
    return json.loads(text)