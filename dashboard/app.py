"""
Momentum Intelligence Agent — Web Dashboard.

Flask app serving:
  - Portfolio header (equity, daily P&L, total P&L, positions, win rate)
  - Candidate rankings with scores and AI decisions
  - Trade history with full thesis and exit reasons
  - Open positions with monitoring status
  - Live position marks/delta and a manual "Close Position" action,
    consumed by the Next.js dashboard (web/) via CORS.

Run:  python -m dashboard.app

Environment variables:
  AUTO_START_SCHEDULER  — "true" (default) starts the autonomous trading
                           daemon on boot; set "false" to disable.
"""

import json
import logging
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from flask import Flask, render_template, jsonify, request

from config import load_config
from database.repository import (
    get_open_trades,
    get_trade_history,
    get_performance_summary,
    record_exit,
    record_order_fill,
    _load as load_journal,
)
from database import state_manager
from options.greeks import approximate_delta
from trading.positions import liquidate_position

log = logging.getLogger(__name__)

# yfinance logs auth errors at ERROR level even though it falls back
# and works fine — suppress this noise in container environments.
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)

app = Flask(__name__)
app.secret_key = "momentum-intelligence-agent"

# The Next.js dashboard (web/) runs on a different origin (localhost:3000)
# and fetches live position data / triggers manual closes from the
# browser, so it needs CORS on the JSON API routes. Kept permissive
# (this is a local paper-trading demo dashboard, not a public API).
try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
except ImportError:
    @app.after_request
    def _add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response


# ── Auto-start autonomous scheduler on module load ──
# Railway / gunicorn imports the app object directly and never calls
# run(), so the scheduler must be started at module level.
_log_configured = False


def _maybe_start_scheduler():
    global _log_configured
    if not _log_configured:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
        _log_configured = True

    if os.environ.get("AUTO_START_SCHEDULER", "true").lower() not in ("1", "true", "yes"):
        return

    cfg = load_config()
    interval = cfg.get("scheduler", {}).get("interval_minutes", 15) * 60
    enabled = cfg.get("scheduler", {}).get("enabled_on_start", True)

    from scheduler import start, get_status
    start(interval_seconds=interval, enabled=enabled)
    status = get_status()
    log.info(
        "Scheduler auto-started: interval=%dmin enabled=%s thread=%s",
        interval // 60, enabled, status.get("running"),
    )


# Defer to a short timer so the import completes fully before any
# scheduler code tries to import from main (which imports heavy deps).
def _deferred_start():
    import time
    time.sleep(2)
    _maybe_start_scheduler()


_start_thread = threading.Thread(target=_deferred_start, daemon=True)
_start_thread.start()


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _format_pnl(val: float | None) -> str:
    if val is None:
        return "—"
    return f"${val:+,.2f}"


def _format_pct(val: float | None) -> str:
    if val is None:
        return "—"
    return f"{val:+.1%}"


_OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def _parse_occ_symbol(option_symbol: str) -> dict | None:
    """Parse a standard OCC option symbol, e.g. 'MRNA260101P00147000'.

    Returns {underlying, expiration (date), contract_type, strike} or
    None if it doesn't match the expected format.
    """
    m = _OCC_RE.match(option_symbol)
    if not m:
        return None
    underlying, exp_raw, cp, strike_raw = m.groups()
    try:
        expiration = datetime.strptime(exp_raw, "%y%m%d").date()
    except ValueError:
        return None
    return {
        "underlying": underlying,
        "expiration": expiration,
        "contract_type": "CALL" if cp == "C" else "PUT",
        "strike": int(strike_raw) / 1000.0,
    }


def _underlying_last_price(symbol: str) -> float | None:
    """Best-effort live underlying price for delta approximation.

    Uses yfinance (already a project dependency) rather than the
    Alpaca data client to keep this endpoint fast and side-effect
    free; failures here should never break the positions endpoint,
    only degrade it (delta omitted).
    """
    try:
        import yfinance as yf
        fast = yf.Ticker(symbol).fast_info
        price = fast.get("lastPrice") or fast.get("last_price")
        return float(price) if price else None
    except Exception:
        return None


# ── Routes ──────────────────────────────────────────────────────────


@app.route("/")
def index():
    cfg = load_config()
    journal = load_journal()

    # ── Portfolio header ───────────────────────────────────────
    perf = get_performance_summary()
    open_trades = get_open_trades()
    history = get_trade_history()

    try:
        from market.alpaca_data import get_account, get_positions as alpaca_positions
        account = get_account()
        equity = _safe_float(account.get("equity", 100000), 100000)
        cash = _safe_float(account.get("cash", 100000), 100000)
    except Exception:
        equity = 100000.0
        cash = 100000.0

    total_pnl = perf["total_pnl"]
    current_equity = equity + total_pnl if equity == 100000 and cash == 0 else equity

    # Daily P&L from today's trades
    today_str = date.today().isoformat()
    todays_trades = [
        t for t in history
        if t.get("entry_time", "").startswith(today_str) or t.get("exit_time", "").startswith(today_str)
    ]
    daily_pnl = sum(_safe_float(t.get("pnl", 0)) for t in todays_trades)

    # ── Candidate evaluations ───────────────────────────────────
    candidates = journal.get("candidates", [])[-50:]  # Last 50
    candidates.reverse()  # Most recent first

    candidates_by_run: dict[str, list] = {}
    for c in candidates:
        ts = c.get("timestamp", "")[:16]
        candidates_by_run.setdefault(ts, []).append(c)

    # ── AI stats ────────────────────────────────────────────────
    approved_candidates = [c for c in candidates if c.get("approved")]
    avg_k2_conf = sum(c.get("k2_confidence", 0) for c in candidates) / max(len(candidates), 1)
    avg_qwen_conf = sum(c.get("qwen_confidence", 0) for c in candidates) / max(len(candidates), 1)
    approve_rate = len(approved_candidates) / max(len(candidates), 1)

    # ── Trade stats ─────────────────────────────────────────────
    winning_trades = [t for t in history if _safe_float(t.get("pnl", 0)) > 0]
    losing_trades = [t for t in history if _safe_float(t.get("pnl", 0)) <= 0]
    avg_winner = sum(_safe_float(t.get("pnl", 0)) for t in winning_trades) / max(len(winning_trades), 1)
    avg_loser = sum(_safe_float(t.get("pnl", 0)) for t in losing_trades) / max(len(losing_trades), 1)

    # ── Market regime ───────────────────────────────────────────
    regime_info = {"regime": "UNKNOWN", "description": "Run a cycle to determine regime"}
    # Try to infer from recent candidates
    if candidates:
        regime_info["regime"] = candidates[0].get("regime", "UNKNOWN")

    return render_template(
        "index.html",
        equity=current_equity,
        cash=cash,
        daily_pnl=daily_pnl,
        total_pnl=total_pnl,
        open_positions=len(open_trades),
        win_rate=perf["win_rate"],
        avg_trade=perf["avg_pnl"],
        total_trades=perf["total_trades"],
        avg_k2_conf=avg_k2_conf,
        avg_qwen_conf=avg_qwen_conf,
        approve_rate=approve_rate,
        candidates=candidates,
        candidates_by_run=candidates_by_run,
        open_trades=open_trades,
        history=history[-30:],
        todays_trades=todays_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        avg_winner=avg_winner,
        avg_loser=avg_loser,
        regime=regime_info,
        config=cfg,
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        format_pnl=_format_pnl,
        format_pct=_format_pct,
        safe_float=_safe_float,
    )


@app.route("/api/portfolio")
def api_portfolio():
    perf = get_performance_summary()
    return jsonify(perf)


@app.route("/api/candidates")
def api_candidates():
    journal = load_journal()
    return jsonify(journal.get("candidates", [])[-100:])


@app.route("/api/trades")
def api_trades():
    return jsonify({
        "open": get_open_trades(),
        "history": get_trade_history(),
        "performance": get_performance_summary(),
    })


@app.route("/api/positions/live")
def api_positions_live():
    """
    Live mark price, delta, and unrealized P&L for every open position —
    consumed by the Next.js dashboard's Open Positions view (which
    otherwise only has the static entry-time snapshot from
    trade_journal.json).

    Uses Alpaca's own live position data for price/P&L (Alpaca computes
    unrealized P&L directly from current market value vs. cost basis,
    so it's correct for both calls and puts with no custom sign logic
    needed here) and adds a best-effort approximated delta per contract.

    Also returns aggregate ``total_unrealized_pnl`` and
    ``total_open_exposure`` (sum of cost basis of open positions) for
    the dashboard's overview cards.
    """
    try:
        from market.alpaca_data import get_positions as alpaca_positions
        positions = alpaca_positions()
    except Exception as e:
        log.warning(f"api_positions_live: could not fetch Alpaca positions: {e}")
        return jsonify({"positions": [], "total_unrealized_pnl": 0.0,
                         "total_open_exposure": 0.0, "error": str(e)})

    open_trades_by_symbol = {t["option_symbol"]: t for t in get_open_trades()}

    enriched = []
    total_unrealized_pnl = 0.0
    total_open_exposure = 0.0

    for p in positions:
        option_symbol = p.get("symbol", "")
        qty = _safe_float(p.get("qty"))
        current_price = _safe_float(p.get("current_price")) or None
        avg_entry_price = _safe_float(p.get("avg_entry_price")) or None
        unrealized_pnl = _safe_float(p.get("unrealized_pl"))
        unrealized_pnl_pct = _safe_float(p.get("unrealized_plpc"))
        cost_basis = _safe_float(p.get("cost_basis")) or abs(qty) * (avg_entry_price or 0) * 100

        parsed = _parse_occ_symbol(option_symbol)
        delta = None
        if parsed and current_price:
            underlying_price = _underlying_last_price(parsed["underlying"])
            if underlying_price:
                dte = max((parsed["expiration"] - date.today()).days, 0)
                delta = approximate_delta(
                    strike_price=parsed["strike"],
                    underlying_price=underlying_price,
                    contract_type=parsed["contract_type"],
                    dte=dte,
                )

        # Best-effort live mark update to the SQLite ledger too, so it
        # stays in sync with what the dashboard is showing.
        try:
            if current_price is not None:
                state_manager.update_position_mark(option_symbol, current_price, delta)
        except Exception:
            pass

        journal_trade = open_trades_by_symbol.get(option_symbol, {})

        enriched.append({
            "option_symbol": option_symbol,
            "underlying_symbol": parsed["underlying"] if parsed else journal_trade.get("symbol"),
            "direction": parsed["contract_type"] if parsed else journal_trade.get("direction"),
            "qty": qty,
            "avg_entry_price": avg_entry_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "delta": delta,
            "cost_basis": cost_basis,
            "thesis": journal_trade.get("thesis"),
            "trade_id": journal_trade.get("trade_id"),
        })
        total_unrealized_pnl += unrealized_pnl
        total_open_exposure += cost_basis

    return jsonify({
        "positions": enriched,
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_open_exposure": round(total_open_exposure, 2),
    })


@app.route("/api/positions/<option_symbol>/close", methods=["POST"])
def api_close_position(option_symbol: str):
    """
    Manual "Close Position" action for emergency overrides from the
    dashboard. Chunks the close (trading/positions.liquidate_position)
    so it can't trip Alpaca's per-order contract cap, journals every
    chunk's fill immediately, then records the exit in the trade
    journal / SQLite ledger.
    """
    body = request.get_json(silent=True) or {}
    reason = body.get("reason") or "Manual close (dashboard)"

    def _on_fill(chunk):
        record_order_fill(
            order_id=chunk["order_id"],
            symbol=chunk["symbol"],
            option_symbol=chunk["option_symbol"],
            side="SELL",
            chunk_qty=chunk["chunk_qty"],
            status=chunk["status"],
            filled_qty=chunk["filled_qty"],
            filled_avg_price=chunk["filled_avg_price"],
            chunk_index=chunk["chunk_index"],
            chunk_count=chunk["chunk_count"],
        )

    result = liquidate_position(option_symbol, exit_reason=reason, on_fill=_on_fill)

    if not result.succeeded:
        return jsonify({
            "success": False,
            "error": result.error or "Close failed",
            "sub_orders": result.sub_orders,
        }), 400

    record_exit(
        option_symbol=option_symbol,
        exit_price=result.exit_price,
        exit_reason=reason,
        exit_time=result.exit_time,
    )

    return jsonify({
        "success": True,
        "order_id": result.order_id,
        "status": result.status,
        "exit_price": result.exit_price,
        "sub_orders": result.sub_orders,
    })


@app.route("/api/scheduler")
def api_scheduler():
    """Return the autonomous scheduler's current state."""
    try:
        from scheduler import get_status as scheduler_status
        return jsonify(scheduler_status())
    except Exception:
        return jsonify({"enabled": False, "running": False, "cycle_count": 0, "error": "scheduler not loaded"})


@app.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    """Start the autonomous scheduler daemon."""
    try:
        from scheduler import start, get_status
        start()
        status = get_status()
        return jsonify({"success": True, "status": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    """Stop the autonomous scheduler daemon."""
    try:
        from scheduler import stop, get_status
        stop()
        status = get_status()
        return jsonify({"success": True, "status": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/scheduler/trigger", methods=["POST"])
def api_scheduler_trigger():
    """Immediately trigger a single trading cycle (non-blocking)."""
    try:
        from scheduler import trigger_now, get_status
        trigger_now()
        status = get_status()
        return jsonify({"success": True, "message": "Cycle triggered", "status": status})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/account")
def api_account():
    """Live Alpaca paper account state — equity, cash, buying power, day P&L.

    Polled by the Next.js dashboard (useAlpacaAccount hook) every 15s so
    the Account Equity card reflects the broker's actual balance, not a
    synthetic journal-derived number.
    """
    try:
        from market.alpaca_data import get_account
        account = get_account()
        return jsonify({
            "equity": _safe_float(account.get("equity")),
            "cash": _safe_float(account.get("cash")),
            "buying_power": _safe_float(account.get("buying_power")),
            "portfolio_value": _safe_float(account.get("portfolio_value")),
            "long_market_value": _safe_float(account.get("long_market_value")),
            "short_market_value": _safe_float(account.get("short_market_value")),
            "daytrade_count": int(_safe_float(account.get("daytrade_count", 0))),
            "last_equity": _safe_float(account.get("last_equity")),
            "initial_margin": _safe_float(account.get("initial_margin")),
            "maintenance_margin": _safe_float(account.get("maintenance_margin")),
            "account_number": account.get("account_number", ""),
        })
    except Exception as e:
        log.warning(f"api_account: could not fetch Alpaca account: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/orders")
def api_orders():
    """Recent Alpaca order history — broker's real order trail.

    Polled by the Next.js dashboard to show orders independent of the
    trade journal (includes manual orders placed outside the system).
    """
    try:
        from market.alpaca_data import get_orders
        from alpaca.trading.enums import QueryOrderStatus
        orders = get_orders(status=QueryOrderStatus.ALL, limit=50)
        simplified = []
        for o in orders:
            simplified.append({
                "id": o.get("id"),
                "client_order_id": o.get("client_order_id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "type": o.get("type"),
                "qty": _safe_float(o.get("qty")),
                "filled_qty": _safe_float(o.get("filled_qty")),
                "filled_avg_price": _safe_float(o.get("filled_avg_price")) or None,
                "limit_price": _safe_float(o.get("limit_price")) or None,
                "stop_price": _safe_float(o.get("stop_price")) or None,
                "status": o.get("status"),
                "submitted_at": o.get("submitted_at"),
                "filled_at": o.get("filled_at"),
                "expired_at": o.get("expired_at"),
                "canceled_at": o.get("canceled_at"),
                "failed_at": o.get("failed_at"),
                "replaced_at": o.get("replaced_at"),
                "time_in_force": o.get("time_in_force"),
                "order_class": o.get("order_class"),
                "notional": _safe_float(o.get("notional")) or None,
            })
        return jsonify(simplified)
    except Exception as e:
        log.warning(f"api_orders: could not fetch Alpaca orders: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/trade/<trade_id>")
def trade_detail(trade_id: str):
    journal = load_journal()
    all_trades = journal.get("trades", [])
    trade = next((t for t in all_trades if t.get("trade_id") == trade_id), None)
    if not trade:
        trade = next((t for t in all_trades if t.get("option_symbol") == trade_id), None)

    if not trade:
        return render_template("trade_not_found.html", trade_id=trade_id), 404

    return render_template(
        "trade_detail.html",
        trade=trade,
        format_pnl=_format_pnl,
        format_pct=_format_pct,
        safe_float=_safe_float,
    )


def run(host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
    """Start the Flask dashboard and optionally the autonomous scheduler."""
    if os.environ.get("AUTO_START_SCHEDULER", "true").lower() in ("1", "true", "yes"):
        cfg = load_config()
        interval = cfg.get("scheduler", {}).get("interval_minutes", 15) * 60
        enabled = cfg.get("scheduler", {}).get("enabled_on_start", True)
        from scheduler import start
        start(interval_seconds=interval, enabled=enabled)
        log.info(f"Scheduler auto-started: interval={interval // 60}min, enabled={enabled}")

    port = int(os.environ.get("PORT", port))
    log.info(f"Dashboard starting at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run(debug=True)