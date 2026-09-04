"""
Auto-exit execution engine.

Handles closing positions through Alpaca paper trading when any
exit condition is triggered by the monitoring agent.

Exits are deterministic — the LLM never authorizes closing trades.

BUG FIX: liquidate_position() previously called Alpaca's
close_position() once with the *entire* position quantity in a single
broker call. That's exactly what tripped "options order qty must be
<= 1000" when trying to exit a large MRNA position: Alpaca's paper
API rejects any single option order above 1000 contracts. This now
looks up the actual held quantity and closes it via chunked
sell-to-close orders (same max-500-per-chunk chunking as the entry
side in trading/execution.py), journaling each chunk's fill
immediately via the optional ``on_fill`` callback.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from market.alpaca_data import get_trading_client, get_open_position
from config import get_config

log = logging.getLogger(__name__)

DEFAULT_MAX_CHUNK_SIZE = 500


@dataclass
class ExitResult:
    """Result of an auto-exit operation."""

    symbol: str
    option_symbol: str
    order_id: str = ""
    status: str = ""
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    error: Optional[str] = None
    # One entry per broker sub-order used to close the position.
    sub_orders: list[dict] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status not in ("", "REJECTED", "ERROR") and self.error is None


def _chunk_quantity(quantity: int, max_chunk_size: int) -> list[int]:
    if quantity <= max_chunk_size:
        return [quantity]
    chunks = []
    remaining = quantity
    while remaining > 0:
        chunk = min(max_chunk_size, remaining)
        chunks.append(chunk)
        remaining -= chunk
    return chunks


def liquidate_position(
    option_symbol: str,
    exit_reason: str = "",
    on_fill: Optional[Callable[[dict], None]] = None,
) -> ExitResult:
    """
    Close an open position through Alpaca, chunking the close into
    sub-500-contract sell orders when the position is large.

    Args:
        option_symbol: Full option symbol (e.g. 'CRM260911P00175000')
        exit_reason: Human-readable reason for exit
        on_fill: optional callback invoked immediately after each
            chunk's fill (before the next chunk is submitted), so the
            journal is never left out of sync with a partially-closed
            position.

    Returns:
        ExitResult with aggregated order details or error information.
    """
    result = ExitResult(
        symbol="",
        option_symbol=option_symbol,
        exit_reason=exit_reason,
    )

    # Check position exists and get its actual held quantity.
    pos = get_open_position(option_symbol)
    if pos is None:
        result.error = f"No open position found for {option_symbol}"
        log.warning(result.error)
        return result

    result.symbol = pos.get("symbol", "")

    try:
        held_qty = abs(int(float(pos.get("qty", 0))))
    except (TypeError, ValueError):
        held_qty = 0

    if held_qty <= 0:
        result.error = f"Position {option_symbol} has no positive quantity to close"
        log.warning(result.error)
        return result

    cfg = get_config()
    max_chunk_size = cfg.get("execution", {}).get("max_order_chunk_size", DEFAULT_MAX_CHUNK_SIZE)
    chunk_sizes = _chunk_quantity(held_qty, max_chunk_size)

    if len(chunk_sizes) > 1:
        log.info(
            f"  Chunking exit: {option_symbol} qty={held_qty} -> "
            f"{len(chunk_sizes)} sub-orders {chunk_sizes} (max_chunk={max_chunk_size})"
        )

    sub_orders: list[dict] = []
    total_filled_qty = 0.0
    total_filled_notional = 0.0
    first_order_id = ""
    last_status = "UNKNOWN"
    fatal_error: Optional[str] = None

    for idx, chunk_qty in enumerate(chunk_sizes):
        single = submit_exit_order(option_symbol, chunk_qty, exit_reason=exit_reason)

        chunk_record = {
            "order_id": single.order_id,
            "status": single.status or ("ERROR" if single.error else "UNKNOWN"),
            "chunk_qty": chunk_qty,
            "filled_qty": chunk_qty if single.succeeded else 0,
            "filled_avg_price": single.exit_price,
            "error": single.error,
        }
        sub_orders.append(chunk_record)

        if single.succeeded:
            if not first_order_id:
                first_order_id = single.order_id
            last_status = single.status
            total_filled_qty += chunk_qty
            if single.exit_price:
                total_filled_notional += chunk_qty * single.exit_price
        else:
            fatal_error = single.error or f"Exit chunk {idx + 1} failed"

        # ── Journal this chunk's fill immediately, before the next
        # chunk is submitted (same rationale as trading/execution.py).
        if on_fill is not None:
            try:
                on_fill({
                    "symbol": result.symbol,
                    "option_symbol": option_symbol,
                    "chunk_index": idx,
                    "chunk_count": len(chunk_sizes),
                    "exit_reason": exit_reason,
                    **chunk_record,
                })
            except Exception as e:
                log.error(f"  Journaling callback failed for exit chunk {idx + 1}: {e}")

        if fatal_error:
            log.error(f"  Exit failed for {option_symbol} (chunk {idx + 1}/{len(chunk_sizes)}): {fatal_error}")
            break

    avg_exit_price = (total_filled_notional / total_filled_qty) if total_filled_qty else None

    result.order_id = first_order_id
    result.exit_price = avg_exit_price
    result.exit_time = datetime.now()
    result.sub_orders = sub_orders

    if fatal_error and total_filled_qty == 0:
        result.status = "ERROR"
        result.error = fatal_error
    elif fatal_error:
        result.status = "PARTIALLY_FILLED"
        result.error = fatal_error
    else:
        result.status = "FILLED" if all(so["status"] == "FILLED" or not so["error"] for so in sub_orders) else last_status

    log.info(
        f"  Exit complete: {option_symbol} status={result.status} "
        f"filled={total_filled_qty}/{held_qty} avg_price={avg_exit_price} "
        f"reason={exit_reason[:60]}"
    )

    return result


def submit_exit_order(
    option_symbol: str,
    quantity: int,
    exit_reason: str = "",
) -> ExitResult:
    """
    Submit a single sell-to-close order for a specific option contract
    and quantity. This is the low-level primitive that liquidate_position()
    calls (possibly multiple times) to chunk a large close.
    """
    tc = get_trading_client()
    result = ExitResult(
        symbol="",
        option_symbol=option_symbol,
        exit_reason=exit_reason,
    )

    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    try:
        order_data = MarketOrderRequest(
            symbol=option_symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = tc.submit_order(order_data)

        if isinstance(order, dict):
            result.order_id = order.get("id", "")
            result.status = order.get("status", "UNKNOWN")
            fap = order.get("filled_avg_price")
            result.exit_price = float(fap) if fap else None
        else:
            result.order_id = order.id if hasattr(order, "id") else ""
            result.status = order.status.value if hasattr(order, "status") else str(order.status)
            fap = getattr(order, "filled_avg_price", None)
            result.exit_price = float(fap) if fap else None

        result.exit_time = datetime.now()
        log.info(f"  Exit submitted: {option_symbol} qty={quantity} "
                 f"order={result.order_id} status={result.status}")

    except Exception as e:
        result.error = str(e)
        log.error(f"  Exit failed for {option_symbol}: {e}")

    return result
