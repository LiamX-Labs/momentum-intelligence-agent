"""
K2 Analyst Agent — Primary Trading Intelligence.

Uses Kimi K2-Instruct to analyze candidates and produce structured
trading theses.  K2 interprets momentum, fundamentals, catalysts, and
constructs the trade thesis — but never selects an option contract.
"""

import json, re
import logging

from intelligence.featherless import chat
from intelligence.prompts import build_k2_analyst_prompt
from intelligence.schemas import K2AnalystOutput

log = logging.getLogger(__name__)

K2_MODEL = "moonshotai/Kimi-K2-Instruct"


def run_analyst(
    symbol: str,
    momentum: dict,
    fundamentals: dict,
    earnings: dict,
    catalysts: dict,
    regime: str,
    model: str | None = None,
) -> K2AnalystOutput | None:
    """Run K2 analyst for a single candidate.

    Returns a validated K2AnalystOutput or None if the LLM fails.
    """
    model = model or K2_MODEL

    system_prompt = (
        "You are a professional momentum trader and financial intelligence analyst. "
        "You produce strictly structured JSON analysis. "
        "Never include markdown formatting or extra commentary — only raw JSON. "
        "You interpret quantitative data; you do NOT recalculate it. "
        "You do NOT recommend specific option contracts — only direction (CALL/PUT)."
    )

    user_prompt = build_k2_analyst_prompt(
        symbol=symbol,
        momentum=momentum,
        fundamentals=fundamentals,
        earnings=earnings,
        catalysts=catalysts,
        regime=regime,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = chat(messages=messages, model=model, temperature=0.3, max_tokens=1024)
    except Exception as e:
        log.error(f"K2 analyst LLM call failed for {symbol}: {e}")
        return None

    try:
        data = _extract_json(response)
        return K2AnalystOutput(**data)
    except Exception as e:
        log.error(f"K2 analyst output parsing failed for {symbol}: {e}")
        log.debug(f"Raw response: {response[:500]}")
        return None


def _extract_json(text: str) -> dict:
    """Extract valid JSON from LLM output, with repair attempts."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    import re
    fixed = re.sub(r",(\s*[}\]])", r"\1", text)

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

    try:
        import json5
        data = json5.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return json.loads(text)