"""
Featherless AI API client.

Thin wrapper around the OpenAI Python client (Featherless is API-compatible).
Supports multiple model selection.  Includes retry logic for transient API
failures (empty responses, rate limits).
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

log = logging.getLogger(__name__)

BASE_URL = "https://api.featherless.ai/v1"
MAX_RETRIES = 2
RETRY_DELAY = 3


def get_client() -> OpenAI:
    key = os.environ.get("FEATHERLESS_API_KEY", "")
    if not key:
        raise RuntimeError(
            "FEATHERLESS_API_KEY environment variable must be set. "
            "Get yours at https://featherless.ai/account/api-keys"
        )
    return OpenAI(
        base_url=BASE_URL,
        api_key=key,
        default_headers={
            "HTTP-Referer": "https://github.com/momentum-intelligence-agent",
            "X-Title": "Momentum Intelligence Agent",
        },
    )


def chat(
    messages: list[dict],
    model: str,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    seed: int = 42,
) -> str:
    """Send a chat completion request with retry logic."""
    client = get_client()

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed + attempt,
            )

            content = None
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content

            if content:
                return content

            log.warning(
                f"Empty response from {model} (attempt {attempt + 1}/{MAX_RETRIES + 1})"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

        except Exception as e:
            log.warning(
                f"API call to {model} failed (attempt {attempt + 1}): {e}"
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
                continue
            raise

    raise RuntimeError(f"All {MAX_RETRIES + 1} attempts to {model} returned empty content")