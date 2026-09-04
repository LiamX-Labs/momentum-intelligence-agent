"""
Cycle Reporter Agent — Summarizes agent decisions after each cycle.

After all candidates have been evaluated by K2 + Qwen, the reporter
writes a plain-English summary explaining which trades were approved,
which were rejected, and WHY. This gives human traders a quick read
on what the system did without having to inspect every debate.
"""

import json
import logging

from intelligence.featherless import chat
from intelligence.prompts import build_reporter_prompt
from intelligence.schemas import ReporterOutput

log = logging.getLogger(__name__)

REPORTER_MODEL = "deepseek-ai/DeepSeek-V3.2"


def run_reporter(
    cycle_number: int,
    regime: str,
    decisions: list[dict],
    model: str | None = None,
) -> ReporterOutput | None:
    model = model or REPORTER_MODEL

    system_prompt = (
        "You are a trading cycle reporter. You summarize the decisions made "
        "by an autonomous AI trading system in plain English. "
        "You produce strictly structured JSON. "
        "Never include markdown formatting or extra commentary — only raw JSON. "
        "Be concise and specific. Explain WHY decisions were made, not just WHAT."
    )

    user_prompt = build_reporter_prompt(
        cycle_number=cycle_number,
        regime=regime,
        decisions=decisions,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response = chat(messages=messages, model=model, temperature=0.4, max_tokens=2048)
    except Exception as e:
        log.error(f"Reporter LLM call failed: {e}")
        return None

    try:
        data = _extract_json(response)
        return ReporterOutput(**data)
    except Exception as e:
        log.error(f"Reporter output parsing failed: {e}")
        log.debug(f"Raw response: {response[:500]}")
        return None


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)