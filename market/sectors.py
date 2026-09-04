"""
Sector mapper — maps S&P 500 tickers to GICS sectors via yfinance.

Called once per cycle (cached per symbol) so momentum engine can
compute sector-relative strength per build plan Section 6.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# Lazy in-memory cache (persists within a single Python process)
_sector_cache: dict[str, Optional[str]] = {}


def get_sector(symbol: str) -> Optional[str]:
    """Return the GICS sector for a stock symbol, or None if unavailable."""
    if symbol in _sector_cache:
        return _sector_cache[symbol]

    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        sector = info.get("sector") or info.get("industry")
        _sector_cache[symbol] = sector
        return sector
    except Exception:
        _sector_cache[symbol] = None
        return None


def get_sector_map(symbols: list[str]) -> dict[str, Optional[str]]:
    """Return a dict of symbol → sector for a batch of symbols."""
    result: dict[str, Optional[str]] = {}
    for sym in symbols:
        if sym in _sector_cache:
            result[sym] = _sector_cache[sym]
        else:
            result[sym] = get_sector(sym)
    return result