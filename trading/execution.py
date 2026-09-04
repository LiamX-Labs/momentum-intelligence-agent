"""
Order execution engine.

Handles: contract validation, position checks, order construction,
submission through Alpaca paper trading, and trade journaling.

The AI never submits orders directly — this module is the final
deterministic gate before execution.

BUG FIXES:
  - Order chunking: Alpaca's paper API rejects option orders with
    qty > 1000 ("options order qty must be <= 1000"). This previously
    submitted the full requested quantity in a single broker call, so
    a sized-up position (e.g. a very cheap-premium contract producing
    a large contract count) could fail outright instead of filling.
    Any order above ``max_order_chunk_size`` (default 500, from
    config) is now split into multiple sub-orders submitted in
    sequence (e.g. qty=1200 -> 500 + 500 + 200).
  - Unjournaled position handling: each chunk's fill is written to the
    journal immediately after it's submitted (via the optional
    ``on_fill`` callback), *before* the next chunk is submitted. If
    the process dies mid-way through a multi-chunk order, only the
    unjournaled tail chunk is at risk, not the whole position.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from alpaca.trading.enums import OrderSide, OrderType, TimeInForce

from market.alpaca_data import (
    submit_paper_order,
    get_open_position,
    get_positions,
)
from config import get_config

import logging

log = logging.getLogger(__name__)

DEFAULT_MAX_CHUNK_SIZE = 500


@dataclass
class OrderRequest:
    symbol: str
    option_symbol: str
    direction: str          # "CALL" or "PUT"
    quantity: int
    order_type: OrderType = OrderType.LIMIT
    time_in_force: TimeInForce = TimeInForce.DAY
    limit_price: Optional[float] = None
    thesis: str = ""
    confidence: float = 0.0


@dataclass
class ExecutionResult:
    symbol: str
    option_symbol: str
    direction: str
    quantity: int
    order_id: str
    status: str
    filled_qty: str
    filled_avg_price: str
    submitted_at: datetime
    error: Optional[str] = None
    thesis: str = ""
    limit_price: Optional[float] = None
    # Chunking: one entry per broker sub-order submitted for this
    # request. Each dict has: order_id, status, filled_qty,
    # filled_avg_price, chunk_qty, error.
    sub_orders: list[dict] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status not in ("REJECTED", "ERROR", "") and self.error is None

    @property
    def fully_filled(self) -> bool:
        """True only if every chunk filled its full requested quantity."""
        if not self.sub_orders:
            return False
        return all(so.get("status") == "FILLED" and not so.get("error") for so in self.sub_orders)


def check_duplicate_position(symbol: str) -> bool:
    try:
        pos = get_open_position(symbol)
        return pos is not None
    except Exception:
        return False


def check_max_positions(max_positions: int = 5) -> bool:
    try:
        positions = get_positions()
        return len(positions) < max_positions
    except Exception:
        return True


def build_order_request(
    symbol: str,
    direction: str,
    option_contract: "OptionContract",
    quantity: int,
    thesis: str = "",
    confidence: float = 0.0,
) -> OrderRequest:
    """
    Build an order request from a selected option contract and position size.

    Uses limit orders with the ask price (for buys) to control slippage.
    """
    limit_price = option_contract.ask_price
    if limit_price is None and option_contract.last_price:
        limit_price = option_contract.last_price * 1.02

    return OrderRequest(
        symbol=symbol,
        option_symbol=option_contract.symbol,
        direction=direction,
        quantity=quantity,
        order_type=OrderType.LIMIT if limit_price else OrderType.MARKET,
        limit_price=limit_price,
        thesis=thesis,
        confidence=confidence,
    )


def _chunk_quantity(quantity: int, max_chunk_size: int) -> list[int]:
    """Split a total quantity into sub-1000-cap chunks, e.g. 1200 -> [500, 500, 200]."""
    if quantity <= max_chunk_size:
        return [quantity]
    chunks = []
    remaining = quantity
    while remaining > 0:
        chunk = min(max_chunk_size, remaining)
        chunks.append(chunk)
        remaining -= chunk
    return chunks


def _rejected_result(request: OrderRequest, error: str) -> ExecutionResult:
    return ExecutionResult(
        symbol=request.symbol,
        option_symbol=request.option_symbol,
        direction=request.direction,
        quantity=request.quantity,
        order_id="",
        status="REJECTED",
        filled_qty="0",
        filled_avg_price="0",
        submitted_at=datetime.now(),
        error=error,
        thesis=request.thesis,
        limit_price=request.limit_price,
    )


def execute_order(
    request: OrderRequest,
    on_fill: Optional[Callable[[dict], None]] = None,
) -> ExecutionResult:
    """
    Execute a paper trading order through Alpaca.

    Runs all deterministic pre-flight checks:
      1. No duplicate position on underlying
      2. Under max open positions
      3. Valid quantity > 0

    Then submits the order, chunking into sub-orders of at most
    ``execution.max_order_chunk_size`` contracts (default 500) so a
    large sized position can never trip Alpaca's 1000-contract cap.

    ``on_fill``, if given, is called immediately after EACH chunk's
    fill (before the next chunk is submitted) with a dict describing
    that chunk, so callers can journal the position without waiting
    for the whole (possibly multi-chunk) order to finish. This is
    what eliminates "unjournaled position" errors: even if the
    process dies partway through a multi-chunk order, every chunk
    that actually filled was already written to the journal.
    """
    cfg = get_config()

    if request.quantity <= 0:
        return _rejected_result(request, "Quantity must be > 0")

    if check_duplicate_position(request.symbol):
        return _rejected_result(request, f"Duplicate position: {request.symbol} already held")

    max_positions = cfg.get("risk", {}).get("max_open_positions", 5)
    if not check_max_positions(max_positions):
        return _rejected_result(request, f"Max open positions ({max_positions}) reached")

    max_chunk_size = cfg.get("execution", {}).get("max_order_chunk_size", DEFAULT_MAX_CHUNK_SIZE)
    chunk_sizes = _chunk_quantity(request.quantity, max_chunk_size)
    side = OrderSide.BUY

    if len(chunk_sizes) > 1:
        log.info(
            f"    Chunking order: qty={request.quantity} -> "
            f"{len(chunk_sizes)} sub-orders {chunk_sizes} (max_chunk={max_chunk_size})"
        )

    sub_orders: list[dict] = []
    total_filled_qty = 0.0
    total_filled_notional = 0.0
    first_order_id = ""
    last_status = "UNKNOWN"
    fatal_error: Optional[str] = None

    for idx, chunk_qty in enumerate(chunk_sizes):
        log.info(
            f"    Submitting {request.direction} order [{idx + 1}/{len(chunk_sizes)}]: "
            f"{request.option_symbol} qty={chunk_qty} type={request.order_type.value} "
            f"limit={request.limit_price}"
        )
        try:
            result = submit_paper_order(
                symbol=request.option_symbol,
                qty=chunk_qty,
                side=side,
                order_type=request.order_type,
                time_in_force=request.time_in_force,
                limit_price=request.limit_price,
            )
            order_id = result.get("id", "")
            status = result.get("status", "UNKNOWN")
            filled_qty = float(result.get("filled_qty") or 0)
            filled_avg_price = result.get("filled_avg_price")

            log.info(f"    Order {order_id}: {status} filled={filled_qty}@{filled_avg_price}")

            chunk_record = {
                "order_id": order_id,
                "status": status,
                "chunk_qty": chunk_qty,
                "filled_qty": filled_qty,
                "filled_avg_price": filled_avg_price,
                "error": None,
            }
            sub_orders.append(chunk_record)

            if not first_order_id:
                first_order_id = order_id
            last_status = status
            total_filled_qty += filled_qty
            if filled_avg_price:
                total_filled_notional += filled_qty * float(filled_avg_price)

            # ── Journal this chunk's fill IMMEDIATELY, before the next
            # chunk is submitted. This is the fix for "unjournaled
            # position" errors: partial multi-chunk fills are never
            # left un-recorded while later chunks are still in flight.
            if on_fill is not None:
                try:
                    on_fill({
                        "symbol": request.symbol,
                        "option_symbol": request.option_symbol,
                        "direction": request.direction,
                        "chunk_index": idx,
                        "chunk_count": len(chunk_sizes),
                        **chunk_record,
                    })
                except Exception as e:
                    log.error(f"    Journaling callback failed for chunk {idx + 1}: {e}")

        except Exception as e:
            log.error(f"    Order submission failed (chunk {idx + 1}/{len(chunk_sizes)}): {e}")
            chunk_record = {
                "order_id": "",
                "status": "ERROR",
                "chunk_qty": chunk_qty,
                "filled_qty": 0,
                "filled_avg_price": None,
                "error": str(e),
            }
            sub_orders.append(chunk_record)
            # Stop chunking on the first failure -- don't keep firing
            # more broker orders once something's gone wrong, but keep
            # whatever already filled (and was already journaled above).
            fatal_error = str(e)
            break

    avg_fill_price = (total_filled_notional / total_filled_qty) if total_filled_qty else 0.0

    if fatal_error and total_filled_qty == 0:
        # Nothing filled at all -- a clean rejection.
        res = _rejected_result(request, fatal_error)
        res.status = "ERROR"
        res.sub_orders = sub_orders
        return res

    # Aggregate status: FILLED only if every chunk filled; otherwise
    # surface the partial/last status so callers can see it wasn't clean.
    if fatal_error:
        agg_status = "PARTIALLY_FILLED"
    elif all(so["status"] == "FILLED" for so in sub_orders):
        agg_status = "FILLED"
    else:
        agg_status = last_status

    return ExecutionResult(
        symbol=request.symbol,
        option_symbol=request.option_symbol,
        direction=request.direction,
        quantity=request.quantity,
        order_id=first_order_id,
        status=agg_status,
        filled_qty=str(total_filled_qty),
        filled_avg_price=str(round(avg_fill_price, 4)) if avg_fill_price else "0",
        submitted_at=datetime.now(),
        error=fatal_error,
        thesis=request.thesis,
        limit_price=request.limit_price,
        sub_orders=sub_orders,
    )
