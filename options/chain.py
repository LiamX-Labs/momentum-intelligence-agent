"""
Option chain retrieval via Alpaca Trading API.

Fetches available option contracts for an underlying symbol filtered by
expiration date range and contract type (CALL/PUT).

Uses the TradingClient for contract discovery and the
OptionHistoricalDataClient for live quotes/snapshots.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from alpaca.trading import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import ContractType
from alpaca.data import OptionHistoricalDataClient
from alpaca.data.requests import OptionSnapshotRequest

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

log = logging.getLogger(__name__)


@dataclass
class OptionContract:
    symbol: str
    underlying: str
    strike_price: float
    expiration_date: date
    contract_type: str                # "CALL" or "PUT"
    style: str
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    last_price: Optional[float] = None
    volume: int = 0
    open_interest: int = 0
    implied_volatility: Optional[float] = None
    delta: Optional[float] = None
    dte: int = 0

    @property
    def mid_price(self) -> Optional[float]:
        if self.bid_price is not None and self.ask_price is not None:
            if self.bid_price > 0 and self.ask_price > 0:
                return (self.bid_price + self.ask_price) / 2
            if self.ask_price is not None and self.ask_price > 0:
                return self.ask_price
        return self.last_price

    @property
    def spread_pct(self) -> Optional[float]:
        """Bid-ask spread as a percentage of mid.

        BUG FIX: this used to fabricate a conservative 5% spread whenever
        bid was zero or missing, which masked exactly the illiquid,
        zero-bid contracts the liquidity guards are supposed to catch
        (a $0.00 bid / $0.03 ask contract would report a fake 5% spread
        instead of the effectively-undefined/infinite real spread).
        Returns None when the spread can't be computed for real; callers
        must treat that as "reject" (the min-bid guard in the selector
        does exactly that), not as "assume it's fine".
        """
        if not self.ask_price or self.ask_price <= 0:
            return None
        if not self.bid_price or self.bid_price <= 0:
            return None
        mid = (self.bid_price + self.ask_price) / 2
        if mid <= 0:
            return None
        return (self.ask_price - self.bid_price) / mid

    @property
    def cost_per_contract(self) -> float:
        return (self.ask_price or self.last_price or 0.0) * 100


def _get_api_keys() -> tuple[str, str]:
    import os
    key = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "") or key
    return key, secret


def fetch_option_chain(
    symbol: str,
    direction: str,
    min_dte: int = 7,
    max_dte: int = 21,
    limit: int = 500,
) -> list[OptionContract]:
    """
    Fetch option contracts for a symbol within the DTE window.

    Args:
        symbol: Underlying stock ticker (e.g. 'AAPL')
        direction: 'CALL' or 'PUT'
        min_dte: Minimum days to expiration
        max_dte: Maximum days to expiration
        limit: Max contracts to return from Alpaca

    Returns:
        List of OptionContract objects (unsorted, unfiltered beyond DTE/type)
    """
    key, secret = _get_api_keys()
    today = date.today()
    start = today + timedelta(days=min_dte)
    end = today + timedelta(days=max_dte)

    ct = ContractType.CALL if direction.upper() == "CALL" else ContractType.PUT

    tc = TradingClient(api_key=key, secret_key=secret, paper=True)

    try:
        req = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            expiration_date_gte=start,
            expiration_date_lte=end,
            type=ct,
            limit=limit,
        )
        result = tc.get_option_contracts(req)
    except Exception as e:
        log.error(f"Failed to fetch option chain for {symbol}: {e}")
        return []

    contracts = result.option_contracts if hasattr(result, "option_contracts") else []
    if not contracts:
        return []

    oc = OptionHistoricalDataClient(api_key=key, secret_key=secret)
    symbols = [c.symbol for c in contracts]

    # Fetch snapshots in batches of 50
    snapshots: dict[str, any] = {}
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        try:
            snap = oc.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=batch))
            snapshots.update(snap)
        except Exception:
            continue

    results = []
    for c in contracts:
        snap_data = snapshots.get(c.symbol)
        bid = ask = last = bid_size = ask_size = iv = delta = None

        if snap_data and hasattr(snap_data, "latest_quote") and snap_data.latest_quote:
            q = snap_data.latest_quote
            bid = float(q.bid_price) if q.bid_price else None
            ask = float(q.ask_price) if q.ask_price else None
            bid_size = float(q.bid_size) if q.bid_size else None
            ask_size = float(q.ask_size) if q.ask_size else None

        if snap_data and hasattr(snap_data, "latest_trade") and snap_data.latest_trade:
            last = float(snap_data.latest_trade.price) if snap_data.latest_trade.price else None

        if snap_data and hasattr(snap_data, "implied_volatility") and snap_data.implied_volatility:
            iv = float(snap_data.implied_volatility)

        if snap_data and hasattr(snap_data, "greeks") and snap_data.greeks:
            g = snap_data.greeks
            delta = float(g.delta) if g.delta else None

        exp_date = c.expiration_date.date() if hasattr(c.expiration_date, "date") else c.expiration_date

        # BUG FIX: open_interest was never populated (always defaulted to 0
        # on the dataclass), so the selector had no liquidity signal beyond
        # bid/ask size. It's not on the snapshot -- it's on the OptionContract
        # object returned by the trading API's get_option_contracts() call,
        # as a string field (per the alpaca-py SDK model).
        try:
            open_interest = int(c.open_interest) if getattr(c, "open_interest", None) else 0
        except (TypeError, ValueError):
            open_interest = 0

        results.append(OptionContract(
            symbol=c.symbol,
            underlying=c.underlying_symbol,
            strike_price=float(c.strike_price),
            expiration_date=exp_date,
            contract_type=c.type.value if hasattr(c.type, "value") else str(c.type),
            style=c.style.value if hasattr(c.style, "value") else str(c.style),
            bid_price=bid,
            ask_price=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            last_price=last,
            open_interest=open_interest,
            implied_volatility=iv,
            delta=delta,
            dte=(exp_date - today).days,
        ))

    return results