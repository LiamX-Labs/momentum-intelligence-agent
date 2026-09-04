"""
Regression tests for the bug fixes in this task:

  1. Options selection algorithm (delta / strike proximity / liquidity)
  2. Order chunking for sizes > 500 contracts
  3. PUT P&L sign fix (monitor.py + repository.py)

Run with:  pip install pytest --break-system-packages && pytest tests/ -v

(No network / broker credentials required -- everything here is
mocked or uses synthetic OptionContract data, per the task's
"Verification & Testing Plan".)
"""

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config

load_config(str(Path(__file__).resolve().parent.parent / "config" / "config.yaml"))

from options.chain import OptionContract
from options.greeks import approximate_delta
from options.selector import select_contract
import trading.execution as execution_mod
import trading.positions as positions_mod


# ── 1. Options selection algorithm ──────────────────────────────────

def test_delta_approximation_is_bounded_and_correctly_signed():
    """Deep OTM contracts must approach 0, not overshoot into the wrong sign."""
    assert 0.0 <= approximate_delta(40, 148, "PUT", 14) < 0.05
    assert -0.05 < approximate_delta(220, 148, "CALL", 14) < 0.05
    assert approximate_delta(148, 148, "PUT", 14) < 0
    assert approximate_delta(148, 148, "CALL", 14) > 0
    assert approximate_delta(250, 148, "PUT", 14) <= -0.95
    assert approximate_delta(74, 148, "CALL", 14) >= 0.95


def test_selector_rejects_the_reported_junk_contract():
    """The exact bug report scenario: $40 strike put on a $148 stock,
    $0.00 bid / $0.03 ask, must never be selected."""
    exp = date.today() + timedelta(days=14)
    junk = OptionContract(
        symbol="MRNA_JUNK_40P", underlying="MRNA", strike_price=40.0,
        expiration_date=exp, contract_type="PUT", style="american",
        bid_price=0.0, ask_price=0.03, bid_size=1, ask_size=5,
        open_interest=12, dte=14,
    )
    result = select_contract([junk], underlying_price=148.0)
    assert result.selected is None
    assert "40P" not in (result.selected.symbol if result.selected else "")


def test_selector_picks_a_realistic_near_atm_contract_over_junk():
    exp = date.today() + timedelta(days=14)
    junk = OptionContract(
        symbol="MRNA_JUNK_40P", underlying="MRNA", strike_price=40.0,
        expiration_date=exp, contract_type="PUT", style="american",
        bid_price=0.0, ask_price=0.03, bid_size=1, ask_size=5,
        open_interest=12, dte=14,
    )
    good = OptionContract(
        symbol="MRNA_GOOD_147P", underlying="MRNA", strike_price=147.0,
        expiration_date=exp, contract_type="PUT", style="american",
        bid_price=4.60, ask_price=4.75, bid_size=50, ask_size=60,
        open_interest=340, dte=14,
    )
    result = select_contract([junk, good], underlying_price=148.0)
    assert result.selected is not None
    assert result.selected.symbol == "MRNA_GOOD_147P"


def test_selector_enforces_min_open_interest():
    exp = date.today() + timedelta(days=14)
    thin = OptionContract(
        symbol="THIN", underlying="XYZ", strike_price=100.0,
        expiration_date=exp, contract_type="CALL", style="american",
        bid_price=2.0, ask_price=2.10, bid_size=10, ask_size=10,
        open_interest=5, dte=14,  # below min_open_interest (100)
    )
    result = select_contract([thin], underlying_price=100.0)
    assert result.selected is None


def test_selector_enforces_strike_proximity():
    exp = date.today() + timedelta(days=14)
    far = OptionContract(
        symbol="FAR", underlying="XYZ", strike_price=130.0,  # 30% OTM
        expiration_date=exp, contract_type="CALL", style="american",
        bid_price=0.50, ask_price=0.55, bid_size=200, ask_size=200,
        open_interest=1000, dte=14,
    )
    result = select_contract([far], underlying_price=100.0)
    assert result.selected is None


# ── 2. Order chunking ────────────────────────────────────────────────

def test_chunk_quantity_matches_spec_example():
    from trading.execution import _chunk_quantity
    assert _chunk_quantity(1200, 500) == [500, 500, 200]
    assert _chunk_quantity(500, 500) == [500]
    assert _chunk_quantity(100, 500) == [100]


def test_execute_order_chunks_and_journals_before_next_submission():
    call_log = []

    def fake_submit(symbol, qty, side, order_type, time_in_force, limit_price):
        call_log.append(qty)
        return {"id": f"O{len(call_log)}", "status": "FILLED",
                "filled_qty": str(qty), "filled_avg_price": "4.75"}

    journaled_before_next_chunk = []

    def on_fill(chunk):
        journaled_before_next_chunk.append((chunk["chunk_index"], len(call_log)))

    with patch.object(execution_mod, "submit_paper_order", fake_submit), \
         patch.object(execution_mod, "check_duplicate_position", return_value=False), \
         patch.object(execution_mod, "check_max_positions", return_value=True):

        req = execution_mod.OrderRequest(
            symbol="MRNA", option_symbol="MRNA260101P00147000", direction="PUT",
            quantity=1200, limit_price=4.75, thesis="test",
        )
        result = execution_mod.execute_order(req, on_fill=on_fill)

    assert call_log == [500, 500, 200]
    assert result.status == "FILLED"
    assert float(result.filled_qty) == 1200
    # each chunk journaled immediately, before the next broker call
    assert journaled_before_next_chunk == [(0, 1), (1, 2), (2, 3)]


def test_liquidate_position_chunks_a_1200_contract_exit():
    """Reproduces the exact reported bug: closing a 1200-contract MRNA
    position must never submit a single >1000-qty order."""
    fake_position = {"symbol": "MRNA", "qty": "1200"}
    sell_calls = []

    class FakeStatus:
        value = "filled"

    class FakeOrder:
        def __init__(self, order_id, qty):
            self.id = order_id
            self.status = FakeStatus()
            self.filled_avg_price = "5.10"

    class FakeTradingClient:
        def submit_order(self, order_data):
            sell_calls.append(order_data.qty)
            return FakeOrder(f"E{len(sell_calls)}", order_data.qty)

    with patch.object(positions_mod, "get_open_position", return_value=fake_position), \
         patch.object(positions_mod, "get_trading_client", return_value=FakeTradingClient()):
        result = positions_mod.liquidate_position(
            option_symbol="MRNA260101P00147000",
            exit_reason="broker limit re-test",
        )

    assert sell_calls == [500, 500, 200]
    assert all(qty <= 1000 for qty in sell_calls)
    assert result.succeeded


# ── 3. PUT P&L sign fix ─────────────────────────────────────────────

def test_put_pnl_is_not_inverted(tmp_path):
    """A long put whose premium RISES (because the underlying fell)
    must show a POSITIVE realized P&L, not negative."""
    import database.repository as repo
    import database.state_manager as sm

    repo.JOURNAL_PATH = tmp_path / "journal.json"
    sm.DB_PATH = tmp_path / "state.db"
    sm._conn = None

    repo.record_entry(
        symbol="MRNA", option_symbol="MRNA260101P00147000", direction="PUT",
        quantity=10, entry_price=4.75, thesis="t", invalidation="i",
        confidence=0.7, expected_holding_days=5, max_holding_days=14,
        momentum_rank=1, underlying_close=148.0,
    )
    repo.record_exit(
        option_symbol="MRNA260101P00147000", exit_price=6.50, exit_reason="TAKE_PROFIT",
    )

    history = repo.get_trade_history()
    assert history[0]["pnl"] == pytest.approx(1750.0)  # (6.50-4.75)*10*100, NOT negative

    closed = sm.get_closed_positions()
    assert closed[0]["realized_pnl"] == pytest.approx(1750.0)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
