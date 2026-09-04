"""
S&P 500 universe provider.

MVP: uses a static list of current S&P 500 constituents.
Research requirement: point-in-time membership for backtesting (not built here).
"""

import json
from datetime import date
from pathlib import Path


SP500_TICKERS_PATH = Path(__file__).parent / "sp500_tickers.json"


def _load_static_tickers() -> list[str]:
    if SP500_TICKERS_PATH.exists():
        with open(SP500_TICKERS_PATH) as f:
            return json.load(f)
    raise FileNotFoundError(
        f"S&P 500 ticker list not found at {SP500_TICKERS_PATH}. "
        "Run 'python -m market.universe --scrape' or provide a ticker list."
    )


def get_universe(as_of_date: date | None = None) -> list[str]:
    """
    Return the S&P 500 universe for a given date.

    MVP: returns the current static list regardless of as_of_date.
    Future: use point-in-time historical constituent data.
    """
    return _load_static_tickers()