"""
Autonomous Cycle Scheduler.

Runs ``run_cycle()`` on a configurable interval in a background daemon
thread.  Writes a small status file so the dashboard can display the
schedule without needing a WebSocket.

Start:
    python main.py --autonomous        # run forever
    python main.py --once              # single cycle (same as no flag)

Config in config.yaml:
    scheduler:
      interval_seconds: 900            # 15 min default
      enabled_on_start: true
"""

import json
import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

STATUS_PATH = Path(__file__).resolve().parent / ".scheduler_status.json"


class SchedulerState:
    """Thread-safe holder for the scheduler's current state."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.enabled = False
        self.running = False
        self.cycle_count = 0
        self.last_run: Optional[datetime] = None
        self.last_result: str = ""
        self.next_run: Optional[datetime] = None
        self.interval_seconds = 900
        self.current_phase: str = "idle"
        self.error: Optional[str] = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "enabled": self.enabled,
                "running": self.running,
                "cycle_count": self.cycle_count,
                "last_run": self.last_run.isoformat() if self.last_run else None,
                "last_result": self.last_result,
                "next_run": self.next_run.isoformat() if self.next_run else None,
                "interval_seconds": self.interval_seconds,
                "current_phase": self.current_phase,
                "error": self.error,
                "updated": datetime.now().isoformat(),
            }

    def write_status(self) -> None:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(STATUS_PATH, "w") as f:
            json.dump(self.snapshot(), f, indent=2)


_state = SchedulerState()
_shutdown = threading.Event()


def _run_one_cycle(state: SchedulerState) -> None:
    """Run a single trading cycle and update state."""
    from main import run_cycle

    with state.lock:
        state.running = True
        state.error = None
        state.current_phase = "Phase A: momentum screening"
    state.write_status()

    try:
        result = run_cycle(lookback_days=30)
        with state.lock:
            state.last_run = datetime.now()
            state.cycle_count += 1
            state.current_phase = "idle"
            if result:
                executed = result.get("executed_trades", [])
                executed_count = sum(1 for t in executed if t.get("executed"))
                exited = result.get("exited_positions", [])
                state.last_result = f"OK — {executed_count} executed, {len(exited)} exited"
            else:
                state.last_result = "OK — no trades"
    except Exception as exc:
        with state.lock:
            state.last_run = datetime.now()
            state.cycle_count += 1
            state.error = str(exc)
            state.last_result = f"FAILED: {exc}"
            state.current_phase = "idle"
        log.exception("Autonomous cycle failed")
    finally:
        with state.lock:
            state.running = False
    state.write_status()


def _scheduler_loop(state: SchedulerState) -> None:
    """Main loop — wait for interval, then run cycle, repeat."""
    log.info("Autonomous scheduler loop started")

    while not _shutdown.is_set():
        with state.lock:
            if not state.enabled:
                state.next_run = None
        state.write_status()

        # Wait until enabled or shutdown
        while not _shutdown.is_set():
            with state.lock:
                if state.enabled:
                    break
            time.sleep(1)

        if _shutdown.is_set():
            break

        # Wait for the interval, checking every second for shutdown/settings
        with state.lock:
            interval = state.interval_seconds
            state.next_run = datetime.now() + timedelta(seconds=interval)

        while not _shutdown.is_set():
            with state.lock:
                if not state.enabled:
                    break
                remaining = (state.next_run - datetime.now()).total_seconds() if state.next_run else 0
            if isinstance(remaining, (int, float)) and remaining <= 0:
                break
            time.sleep(min(1, max(0, remaining) if isinstance(remaining, (int, float)) else 1))

        if _shutdown.is_set():
            break

        with state.lock:
            if not state.enabled:
                continue

        _run_one_cycle(state)

    log.info("Autonomous scheduler loop stopped")


_thread: Optional[threading.Thread] = None


def start(interval_seconds: int = 900, enabled: bool = True) -> None:
    """Start the autonomous scheduler in a background daemon thread."""
    global _thread

    if _thread and _thread.is_alive():
        log.warning("Scheduler already running")
        return

    with _state.lock:
        _state.interval_seconds = interval_seconds
        _state.enabled = enabled

    _state.write_status()

    _thread = threading.Thread(target=_scheduler_loop, args=(_state,), daemon=True)
    _thread.start()

    def _handle_sigterm(signum: int, frame: object) -> None:
        log.info("Shutdown signal received")
        stop()

    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)


def stop() -> None:
    """Signal the scheduler to stop after any in-flight cycle completes."""
    with _state.lock:
        _state.enabled = False
    _shutdown.set()
    _state.write_status()
    log.info("Scheduler stop requested")


def enable() -> None:
    with _state.lock:
        _state.enabled = True
    _state.write_status()
    log.info("Scheduler enabled — next cycle will start after interval")


def disable() -> None:
    with _state.lock:
        _state.enabled = False
    _state.write_status()
    log.info("Scheduler disabled")


def trigger_now() -> None:
    """Immediately run a cycle (non-blocking — fires in a thread)."""
    t = threading.Thread(target=_run_one_cycle, args=(_state,), daemon=True)
    t.start()
    log.info("Manual cycle triggered")


def get_status() -> dict:
    """Return current scheduler state for API/dashboard consumption."""
    return _state.snapshot()


def read_status() -> dict:
    """Read the on-disk status file (for the dashboard without importing scheduler)."""
    if STATUS_PATH.exists():
        try:
            with open(STATUS_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"enabled": False, "running": False, "cycle_count": 0, "error": None}