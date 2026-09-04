"""
Thread-safe state manager (SQLite).

Implements the three tracking models required by the trading engine:

  - Orders: every broker order submitted, including individual
    sub-orders produced by chunking a large fill (trading/execution.py,
    trading/positions.py).
  - OpenPositions: currently-held option positions with live mark
    price / unrealized P&L / delta.
  - ClosedPositions: fully closed positions with realized P&L and
    exit reason.

Why this exists: ``database/repository.py`` previously stored
everything as one big JSON file that was read-modify-written *whole*
on every call, with no locking. Two writers racing (the scheduler
thread running a cycle, a dashboard request triggering a manual
close, a partially-filled chunked order journaling itself) could
clobber each other's writes. SQLite + WAL mode + a single serializing
write lock gives real atomic, thread-safe writes; concurrent readers
are safe under WAL without any locking at all.

``database/repository.py`` remains the audit trail for AI candidate
evaluations and cycle reports (the dashboard reads trade_journal.json
directly), and now also writes through to this module so Orders /
OpenPositions / ClosedPositions are always the authoritative,
race-free record of what's actually open, closed, or in flight.
"""

import logging
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "state.db"

log = logging.getLogger(__name__)

_lock = threading.Lock()
_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        import sqlite3
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _init_schema(conn)
        _conn = conn
    return _conn


def _init_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orders (
            order_id            TEXT PRIMARY KEY,
            symbol              TEXT NOT NULL,
            option_symbol       TEXT NOT NULL,
            side                TEXT NOT NULL,
            qty                 INTEGER NOT NULL,
            filled_qty          INTEGER NOT NULL DEFAULT 0,
            limit_price         REAL,
            status              TEXT NOT NULL,
            chunk_index         INTEGER NOT NULL DEFAULT 0,
            chunk_count         INTEGER NOT NULL DEFAULT 1,
            timestamp           TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS open_positions (
            position_id         TEXT PRIMARY KEY,
            option_symbol       TEXT NOT NULL UNIQUE,
            underlying_symbol   TEXT NOT NULL,
            direction            TEXT,
            qty                 INTEGER NOT NULL,
            avg_entry_price     REAL NOT NULL,
            current_mark_price  REAL,
            unrealized_pnl      REAL,
            unrealized_pnl_pct  REAL,
            delta               REAL,
            entry_timestamp     TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS closed_positions (
            position_id         TEXT PRIMARY KEY,
            option_symbol       TEXT NOT NULL,
            underlying_symbol   TEXT NOT NULL,
            direction            TEXT,
            qty                 INTEGER NOT NULL,
            avg_entry_price     REAL NOT NULL,
            avg_exit_price      REAL,
            realized_pnl        REAL,
            realized_pnl_pct    REAL,
            exit_reason         TEXT,
            closed_timestamp    TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_orders_option_symbol ON orders(option_symbol);
        CREATE INDEX IF NOT EXISTS idx_closed_option_symbol ON closed_positions(option_symbol);
        """
    )
    conn.commit()


# ── Orders ──────────────────────────────────────────────────────────

def record_order(
    order_id: str,
    symbol: str,
    option_symbol: str,
    side: str,
    qty: int,
    status: str,
    filled_qty: int = 0,
    limit_price: Optional[float] = None,
    chunk_index: int = 0,
    chunk_count: int = 1,
    timestamp: Optional[datetime] = None,
) -> None:
    """Record (or update, if order_id already exists) a single broker order."""
    ts = (timestamp or datetime.now()).isoformat()
    order_id = order_id or f"LOCAL_{uuid.uuid4().hex[:12]}"
    with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO orders (order_id, symbol, option_symbol, side, qty, filled_qty,
                                 limit_price, status, chunk_index, chunk_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(order_id) DO UPDATE SET
                filled_qty = excluded.filled_qty,
                status = excluded.status
            """,
            (order_id, symbol, option_symbol, side, qty, filled_qty,
             limit_price, status, chunk_index, chunk_count, ts),
        )
        conn.commit()


def get_orders(option_symbol: Optional[str] = None) -> list[dict]:
    with _lock:
        conn = _get_conn()
        if option_symbol:
            rows = conn.execute(
                "SELECT * FROM orders WHERE option_symbol = ? ORDER BY timestamp", (option_symbol,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM orders ORDER BY timestamp").fetchall()
        return [dict(r) for r in rows]


# ── Open positions ───────────────────────────────────────────────────

def upsert_open_position(
    option_symbol: str,
    underlying_symbol: str,
    direction: str,
    qty: int,
    avg_entry_price: float,
    entry_timestamp: Optional[datetime] = None,
    current_mark_price: Optional[float] = None,
    delta: Optional[float] = None,
) -> None:
    """Create or update an open position (e.g. as chunked entry fills accumulate)."""
    ts = (entry_timestamp or datetime.now()).isoformat()
    unrealized_pnl = None
    unrealized_pnl_pct = None
    if current_mark_price is not None and avg_entry_price:
        unrealized_pnl = (current_mark_price - avg_entry_price) * qty * 100
        unrealized_pnl_pct = (current_mark_price - avg_entry_price) / avg_entry_price

    with _lock:
        conn = _get_conn()
        existing = conn.execute(
            "SELECT position_id FROM open_positions WHERE option_symbol = ?", (option_symbol,)
        ).fetchone()
        position_id = existing["position_id"] if existing else f"POS_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO open_positions (position_id, option_symbol, underlying_symbol, direction,
                                         qty, avg_entry_price, current_mark_price,
                                         unrealized_pnl, unrealized_pnl_pct, delta, entry_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(option_symbol) DO UPDATE SET
                qty = excluded.qty,
                avg_entry_price = excluded.avg_entry_price,
                current_mark_price = COALESCE(excluded.current_mark_price, open_positions.current_mark_price),
                unrealized_pnl = COALESCE(excluded.unrealized_pnl, open_positions.unrealized_pnl),
                unrealized_pnl_pct = COALESCE(excluded.unrealized_pnl_pct, open_positions.unrealized_pnl_pct),
                delta = COALESCE(excluded.delta, open_positions.delta)
            """,
            (position_id, option_symbol, underlying_symbol, direction, qty, avg_entry_price,
             current_mark_price, unrealized_pnl, unrealized_pnl_pct, delta, ts),
        )
        conn.commit()


def update_position_mark(
    option_symbol: str,
    current_mark_price: float,
    delta: Optional[float] = None,
) -> None:
    """Update an open position's live mark price / unrealized P&L / delta."""
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT qty, avg_entry_price FROM open_positions WHERE option_symbol = ?",
            (option_symbol,),
        ).fetchone()
        if row is None:
            return
        qty, avg_entry_price = row["qty"], row["avg_entry_price"]
        unrealized_pnl = (current_mark_price - avg_entry_price) * qty * 100 if avg_entry_price else None
        unrealized_pnl_pct = (
            (current_mark_price - avg_entry_price) / avg_entry_price if avg_entry_price else None
        )
        conn.execute(
            """
            UPDATE open_positions
            SET current_mark_price = ?, unrealized_pnl = ?, unrealized_pnl_pct = ?,
                delta = COALESCE(?, delta)
            WHERE option_symbol = ?
            """,
            (current_mark_price, unrealized_pnl, unrealized_pnl_pct, delta, option_symbol),
        )
        conn.commit()


def get_open_positions() -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute("SELECT * FROM open_positions ORDER BY entry_timestamp DESC").fetchall()
        return [dict(r) for r in rows]


def get_open_position_by_symbol(option_symbol: str) -> Optional[dict]:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM open_positions WHERE option_symbol = ?", (option_symbol,)
        ).fetchone()
        return dict(row) if row else None


# ── Closed positions ─────────────────────────────────────────────────

def close_position(
    option_symbol: str,
    avg_exit_price: Optional[float],
    exit_reason: str,
    closed_timestamp: Optional[datetime] = None,
) -> None:
    """Move a position from open_positions to closed_positions with realized P&L.

    Realized P&L is always (exit_price - entry_price) * qty * 100 -- this
    system only ever holds long option positions (long calls or long
    puts), so there is no direction-based sign flip here (see the fix
    in agents/monitor.py for the same principle applied to unrealized
    P&L during monitoring).
    """
    ts = (closed_timestamp or datetime.now()).isoformat()
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM open_positions WHERE option_symbol = ?", (option_symbol,)
        ).fetchone()
        if row is None:
            log.warning(f"close_position: no open position found for {option_symbol}")
            return

        realized_pnl = None
        realized_pnl_pct = None
        if avg_exit_price is not None and row["avg_entry_price"]:
            realized_pnl = (avg_exit_price - row["avg_entry_price"]) * row["qty"] * 100
            realized_pnl_pct = (avg_exit_price - row["avg_entry_price"]) / row["avg_entry_price"]

        conn.execute(
            """
            INSERT INTO closed_positions (position_id, option_symbol, underlying_symbol, direction,
                                           qty, avg_entry_price, avg_exit_price, realized_pnl,
                                           realized_pnl_pct, exit_reason, closed_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (row["position_id"], option_symbol, row["underlying_symbol"], row["direction"],
             row["qty"], row["avg_entry_price"], avg_exit_price, realized_pnl,
             realized_pnl_pct, exit_reason, ts),
        )
        conn.execute("DELETE FROM open_positions WHERE option_symbol = ?", (option_symbol,))
        conn.commit()


def get_closed_positions() -> list[dict]:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM closed_positions ORDER BY closed_timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]
