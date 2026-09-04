import gc
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

log = logging.getLogger(__name__)


def fetch_bars(
    symbols: list[str],
    start: date | datetime,
    end: date | datetime,
    interval: str = "1d",
    batch_size: int = 20,
) -> pd.DataFrame:
    """Fetch OHLCV bars via yfinance at the given interval and return a DataFrame.

    For ``"4h"`` / ``"1h"`` intervals, ``date`` stays as full datetime because
    multiple bars share the same calendar date.  For ``"1d"`` it is truncated
    to ``date`` for backward compatibility.
    """
    records = []
    total = len(symbols)

    for i in range(0, total, batch_size):
        batch = symbols[i : i + batch_size]
        log.debug("Fetching batch %d/%d (%d symbols)", i // batch_size + 1, (total + batch_size - 1) // batch_size, len(batch))
        data = None
        try:
            data = yf.download(
                batch, start=start, end=end, progress=False,
                auto_adjust=True, group_by="ticker", interval=interval,
            )
        except Exception:
            continue

        if data.empty:
            del data
            continue

        for sym in batch:
            try:
                sym_data = data if len(batch) == 1 else data[sym]
                if sym_data is None or sym_data.empty:
                    continue
                if isinstance(sym_data.columns, pd.MultiIndex):
                    sym_data = sym_data.droplevel(0, axis=1)
                for idx, row in sym_data.iterrows():
                    records.append({
                        "symbol": sym,
                        "date": idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
                        "open": row.get("Open", row.get("open", 0)),
                        "high": row.get("High", row.get("high", 0)),
                        "low": row.get("Low", row.get("low", 0)),
                        "close": row.get("Close", row.get("close", 0)),
                        "volume": row.get("Volume", row.get("volume", 0)),
                    })
            except (KeyError, Exception):
                continue

        del data
        gc.collect()

    df = pd.DataFrame(records)
    if df.empty:
        return df
    if interval == "1d":
        df["date"] = pd.to_datetime(df["date"]).dt.date
    else:
        df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)


def fetch_daily_bars(
    symbols: list[str],
    start: date | datetime,
    end: date | datetime,
    adjustment: str = "all",
    batch_size: int = 50,
) -> pd.DataFrame:
    """Fetch daily OHLCV bars via yfinance and return a DataFrame."""
    return fetch_bars(symbols, start, end, interval="1d", batch_size=batch_size)


# ── Alpaca trading & account ────────────────────────────────

from alpaca.trading import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce, QueryOrderStatus
from alpaca.common.exceptions import APIError

_trading_client: Optional[TradingClient] = None


def _get_api_keys() -> tuple[str, str]:
    key = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "") or key
    if not key:
        raise RuntimeError("APCA_API_KEY_ID environment variable must be set")
    return key, secret


def get_trading_client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        key, secret = _get_api_keys()
        _trading_client = TradingClient(api_key=key, secret_key=secret, paper=True)
    return _trading_client


def _to_dict(obj) -> dict:
    """Convert an Alpaca model to a dict, handling both _raw and pydantic models."""
    try:
        return obj._raw
    except AttributeError:
        pass
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    result = {}
    for attr in dir(obj):
        if attr.startswith("_"):
            continue
        try:
            val = getattr(obj, attr)
            if callable(val):
                continue
            if hasattr(val, "value"):
                val = val.value
            result[attr] = val
        except Exception:
            pass
    return result


def submit_paper_order(
    symbol: str, qty: int, side: OrderSide,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.DAY,
    limit_price: Optional[float] = None,
    stop_price: Optional[float] = None,
) -> dict:
    """Submit a paper trading order via Alpaca.

    Uses the alpaca-py SDK's request-object pattern: creates a
    LimitOrderRequest or MarketOrderRequest and passes it as
    ``order_data`` to ``submit_order()``.
    """
    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest

    common = dict(
        symbol=symbol,
        qty=qty,
        side=side,
        time_in_force=time_in_force,
    )

    if order_type == OrderType.LIMIT and limit_price is not None:
        order_data = LimitOrderRequest(
            **common,
            type=OrderType.LIMIT,
            limit_price=limit_price,
        )
    else:
        order_data = MarketOrderRequest(
            **common,
            type=OrderType.MARKET,
        )

    return _to_dict(get_trading_client().submit_order(order_data=order_data))


def get_account() -> dict:
    return _to_dict(get_trading_client().get_account())


def get_positions() -> list[dict]:
    return [_to_dict(p) for p in get_trading_client().get_all_positions()]


def get_orders(status: QueryOrderStatus = QueryOrderStatus.ALL, limit: int = 100) -> list[dict]:
    request = GetOrdersRequest(status=status, limit=limit)
    return [_to_dict(o) for o in get_trading_client().get_orders(filter=request)]


def get_open_position(symbol: str) -> dict | None:
    try:
        return _to_dict(get_trading_client().get_open_position(symbol))
    except APIError:
        return None