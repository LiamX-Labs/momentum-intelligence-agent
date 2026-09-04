"""
Trade Journal — persistent audit log.

Records every candidate evaluation and every trade (entry + exit) as
structured JSON so the system's behavior is fully auditable.

The journal is append-only.  Records are written to a JSON file in
the project root for simplicity during the hackathon.
"""

import json
import logging
import math
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from database import state_manager

log = logging.getLogger(__name__)

JOURNAL_PATH = Path(__file__).resolve().parent.parent / "trade_journal.json"

# BUG FIX (thread safety): _load()/_save() previously did an
# unsynchronized read-modify-write of the whole JSON file. Two writers
# racing (scheduler thread mid-cycle + a dashboard-triggered manual
# close + a chunked order journaling a fill) could clobber each
# other's writes since the second writer's _load() wouldn't see the
# first writer's not-yet-flushed _save(). This journal remains the
# audit trail for the AI candidate/report history (dashboard reads it
# directly); the state-changing Orders/OpenPositions/ClosedPositions
# ledger now also lives in database/state_manager.py's SQLite store,
# which is the authoritative, race-free source of truth for what's
# actually open/closed/in-flight (see record_entry/record_exit below).
_journal_lock = threading.Lock()


def _load() -> dict:
    if JOURNAL_PATH.exists():
        with open(JOURNAL_PATH) as f:
            return json.load(f)
    return {"candidates": [], "trades": []}


def _sanitize(obj: object) -> object:
    """Recursively replace NaN/Infinity with None for valid JSON output."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}  # type: ignore[union-attr]
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]  # type: ignore[union-attr]
    return obj


def _save(data: dict) -> None:
    data = _sanitize(data)
    with open(JOURNAL_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)


def record_candidate(
    symbol: str,
    momentum_score: float,
    direction: str,
    k2_confidence: float,
    qwen_recommendation: str,
    qwen_confidence: float,
    final_score: float,
    approved: bool,
    thesis: str = "",
    regime: str = "",
    timestamp: Optional[datetime] = None,
    run_id: Optional[str] = None,
    reject_reason: Optional[str] = None,
    # ── Full AI debate payload (no truncation) ──────────────────
    k2: Optional[dict] = None,
    qwen: Optional[dict] = None,
    gates: Optional[list] = None,
    evidence: Optional[dict] = None,
    reused: bool = False,
) -> None:
    """Record a candidate evaluation in the journal.

    ``k2`` / ``qwen`` should be the full structured-output dicts from the
    respective agents (e.g. ``K2AnalystOutput.model_dump()``) so the
    dashboard can render the complete adversarial debate and thesis with
    zero truncation.  ``gates`` is the list of deterministic risk-gate
    tuples ``(name, passed, detail)`` from the risk validator, if the
    candidate reached Phase D.  ``evidence`` carries the raw momentum /
    fundamental / earnings / catalyst dicts shown to both agents.
    """
    ts = timestamp or datetime.now()
    with _journal_lock:
        journal = _load()
        journal["candidates"].append({
            "timestamp": ts.isoformat(),
            "run_id": run_id or ts.strftime("%Y-%m-%dT%H:%M"),
            "symbol": symbol,
            "momentum_score": round(momentum_score, 1),
            "direction": direction,
            "k2_confidence": round(k2_confidence, 3),
            "qwen_recommendation": qwen_recommendation,
            "qwen_confidence": round(qwen_confidence, 3),
            "final_score": round(final_score, 3),
            "approved": approved,
            "reject_reason": reject_reason,
            "thesis": thesis,
            "regime": regime,
            "k2": k2,
            "qwen": qwen,
            "gates": gates or [],
            "evidence": evidence,
            "reused": reused,
        })
        _save(journal)


def record_entry(
    symbol: str,
    option_symbol: str,
    direction: str,
    quantity: int,
    entry_price: float,
    thesis: str,
    invalidation: str,
    confidence: float,
    expected_holding_days: int,
    max_holding_days: int,
    momentum_rank: int,
    underlying_close: float,
    order_id: str = "",
    entry_time: Optional[datetime] = None,
) -> None:
    """Record a trade entry in the journal.

    Also write-through to the SQLite state manager's open_positions
    table (the authoritative, thread-safe ledger -- see
    database/state_manager.py) so the position is tracked there too.
    """
    entry_time = entry_time or datetime.now()
    with _journal_lock:
        journal = _load()
        journal["trades"].append({
            "trade_id": f"TRADE_{entry_time.strftime('%Y%m%d_%H%M%S')}_{symbol}",
            "symbol": symbol,
            "option_symbol": option_symbol,
            "direction": direction,
            "entry_time": entry_time.isoformat(),
            "entry_price": entry_price,
            "quantity": quantity,
            "thesis": thesis,
            "invalidation": invalidation,
            "confidence": round(confidence, 3),
            "expected_holding_days": expected_holding_days,
            "max_holding_days": max_holding_days,
            "entry_momentum_rank": momentum_rank,
            "entry_close": underlying_close,
            "order_id": order_id,
            "exit_time": None,
            "exit_price": None,
            "exit_reason": "",
            "pnl": None,
        })
        _save(journal)

    try:
        state_manager.upsert_open_position(
            option_symbol=option_symbol,
            underlying_symbol=symbol,
            direction=direction,
            qty=quantity,
            avg_entry_price=entry_price,
            entry_timestamp=entry_time,
        )
    except Exception as e:
        log.error(f"state_manager.upsert_open_position failed for {option_symbol}: {e}")


def record_order_fill(
    order_id: str,
    symbol: str,
    option_symbol: str,
    side: str,
    chunk_qty: int,
    status: str,
    filled_qty: float,
    filled_avg_price: Optional[float],
    chunk_index: int = 0,
    chunk_count: int = 1,
) -> None:
    """
    Journal a single order chunk's fill IMMEDIATELY (called as the
    ``on_fill`` callback from trading/execution.py and
    trading/positions.py). This is the fix for "unjournaled position"
    errors: every chunk that fills is written to the Orders table the
    moment it fills, before the next chunk is even submitted, so a
    crash mid-way through a multi-chunk order never leaves an
    un-recorded fill sitting in the broker account.
    """
    try:
        state_manager.record_order(
            order_id=order_id,
            symbol=symbol,
            option_symbol=option_symbol,
            side=side,
            qty=chunk_qty,
            status=status,
            filled_qty=int(filled_qty),
            limit_price=filled_avg_price,
            chunk_index=chunk_index,
            chunk_count=chunk_count,
        )
    except Exception as e:
        log.error(f"state_manager.record_order failed for {order_id}: {e}")


def record_exit(
    option_symbol: str,
    exit_price: Optional[float],
    exit_reason: str,
    exit_time: Optional[datetime] = None,
) -> None:
    """Record a trade exit in the journal (updates the latest matching trade).

    Also write-through to the SQLite state manager, moving the
    position from open_positions to closed_positions with realized
    P&L (see database/state_manager.close_position).
    """
    exit_time = exit_time or datetime.now()

    with _journal_lock:
        journal = _load()

        # Find the matching trade (latest open trade for this symbol)
        for trade in reversed(journal["trades"]):
            if trade["option_symbol"] == option_symbol and trade.get("exit_time") is None:
                trade["exit_time"] = exit_time.isoformat()
                trade["exit_price"] = exit_price
                trade["exit_reason"] = exit_reason

                if exit_price is not None and trade["entry_price"] and trade["entry_price"] > 0:
                    # BUG FIX: this used to flip the sign for PUT trades
                    # (as if entry_price/exit_price were the underlying's
                    # price rather than the option premium). Realized P&L
                    # on a long option position -- call or put -- is
                    # always (exit_premium - entry_premium) * qty * 100;
                    # see agents/monitor.py for the matching fix and full
                    # explanation of why puts don't need a sign flip here.
                    trade["pnl"] = round(
                        (exit_price - trade["entry_price"]) * trade["quantity"] * 100, 2
                    )

                trade["holding_days"] = (
                    exit_time - datetime.fromisoformat(trade["entry_time"])
                ).days
                break

        _save(journal)

    try:
        state_manager.close_position(
            option_symbol=option_symbol,
            avg_exit_price=exit_price,
            exit_reason=exit_reason,
            closed_timestamp=exit_time,
        )
    except Exception as e:
        log.error(f"state_manager.close_position failed for {option_symbol}: {e}")


def get_open_trades() -> list[dict]:
    """Return all trades that haven't been exited yet."""
    with _journal_lock:
        journal = _load()
    return [t for t in journal["trades"] if t.get("exit_time") is None]


def get_trade_history() -> list[dict]:
    """Return all completed trades."""
    with _journal_lock:
        journal = _load()
    return [t for t in journal["trades"] if t.get("exit_time") is not None]


def get_performance_summary() -> dict:
    """Return high-level performance metrics."""
    with _journal_lock:
        trades = [t for t in _load()["trades"] if t.get("exit_time") is not None]
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
        }
    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    return {
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 3),
        "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
        "avg_pnl": round(sum(t.get("pnl", 0) for t in trades) / len(trades), 2),
    }


def update_candidate_gates(
    symbol: str,
    run_id: str,
    gates: list,
    risk_approved: Optional[bool] = None,
    risk_reason: Optional[str] = None,
    position_size: Optional[dict] = None,
) -> None:
    """Attach Phase D deterministic risk-gate results to a candidate record.

    Candidates are recorded during Phase C (before risk validation runs),
    so this backfills the gate-by-gate breakdown once Phase D completes —
    letting the dashboard show the complete decision trail: momentum →
    K2 thesis → Qwen critique → risk gates → execution.
    """
    with _journal_lock:
        journal = _load()
        for c in reversed(journal.get("candidates", [])):
            if c.get("symbol") == symbol and c.get("run_id") == run_id:
                c["gates"] = gates
                if risk_approved is not None:
                    c["risk_approved"] = risk_approved
                if risk_reason is not None:
                    c["risk_reason"] = risk_reason
                if position_size is not None:
                    c["position_size"] = position_size
                break
        _save(journal)


def record_cycle_report(
    run_id: str,
    cycle_number: int,
    regime: str,
    total_candidates: int,
    total_approved: int,
    total_rejected: int,
    summary: str,
    verdicts: list[dict],
    timestamp: Optional[datetime] = None,
) -> None:
    """Record a cycle reporter summary in the journal.

    This is written to the ``reports`` array so the dashboard can show
    the human-readable cycle narrative alongside the detailed debates.
    """
    with _journal_lock:
        journal = _load()
        if "reports" not in journal:
            journal["reports"] = []
        ts = timestamp or datetime.now()
        journal["reports"].append({
            "timestamp": ts.isoformat(),
            "run_id": run_id,
            "cycle_number": cycle_number,
            "regime": regime,
            "total_candidates": total_candidates,
            "total_approved": total_approved,
            "total_rejected": total_rejected,
            "summary": summary,
            "verdicts": verdicts,
        })
        _save(journal)


def get_recent_candidate_for_symbol(
    symbol: str,
    within_cycles: int = 3,
) -> dict | None:
    """Return the most recent candidate evaluation for a symbol.

    Used to skip re-processing symbols whose decision hasn't changed.
    Only considers candidates from the last ``within_cycles`` runs.
    """
    with _journal_lock:
        journal = _load()
    candidates = journal.get("candidates", [])
    if not candidates:
        return None

    # Get unique run_ids, most recent first
    seen_run_ids = []
    unique_runs = []
    for c in reversed(candidates):
        rid = c.get("run_id", "")
        if rid and rid not in seen_run_ids:
            seen_run_ids.append(rid)
            unique_runs.append(rid)
        if len(unique_runs) >= within_cycles:
            break

    # Find the most recent evaluation for this symbol within those runs
    for c in reversed(candidates):
        if c.get("symbol") == symbol and c.get("run_id") in unique_runs:
            return c
    return None


def get_cycle_count() -> int:
    """Return the number of unique runs (cycles) in the journal."""
    journal = _load()
    run_ids = set()
    for c in journal.get("candidates", []):
        rid = c.get("run_id", "")
        if rid:
            run_ids.add(rid)
    return len(run_ids) or 1