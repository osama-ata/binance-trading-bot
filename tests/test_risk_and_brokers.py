from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from binance_client import SymbolFilters
from brokers import PaperBroker, Store
from database import EquitySnapshot, PositionRow, Trade, init_db, session_scope
from risk import Position, RiskManager, bar_exit, position_size, updated_stop
from strategies import Signal

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_position_size_risks_fixed_fraction():
    qty = position_size(equity=10_000, entry=100, stop=98, risk_pct=0.01, max_position_pct=1.0)
    assert qty == pytest.approx(50)  # 50 units * $2 risk = $100 = 1% of equity


def test_position_size_capped_by_notional():
    qty = position_size(equity=10_000, entry=100, stop=99.9, risk_pct=0.01, max_position_pct=0.25)
    assert qty * 100 == pytest.approx(2_500)


def test_position_size_invalid_stop():
    assert position_size(10_000, 100, 101, 0.01, 1.0) == 0


def test_symbol_filters_rounding():
    f = SymbolFilters("BTCUSDT", "BTC", "USDT", Decimal("0.01"), Decimal("0.00001"), Decimal("0.00001"), Decimal("5"))
    assert f.round_qty(0.123456789) == 0.12345
    assert f.round_price(82826.4789) == 82826.47
    assert not f.is_tradeable(0.00005, 82_000)  # $4.1 < $5 min notional
    assert f.is_tradeable(0.0001, 82_000)


def test_kill_switch_trips_on_daily_loss():
    rm = RiskManager(daily_loss_limit=0.02)
    rm.on_bar(T0, 10_000)
    assert rm.can_open(0)[0]
    rm.on_bar(T0 + timedelta(minutes=5), 9_790)
    assert rm.can_open(0) == (False, "daily loss limit hit")
    rm.on_bar(T0 + timedelta(days=1), 9_790)  # resets next UTC day
    assert rm.can_open(0)[0]


def test_trade_count_and_cooldown():
    rm = RiskManager(max_trades_per_day=2, loss_streak_cooldown=2, cooldown_bars=3)
    rm.on_bar(T0, 10_000)
    rm.on_open(); rm.on_open()
    assert rm.can_open(0) == (False, "max trades per day")
    rm.on_bar(T0 + timedelta(days=1), 10_000)
    rm.on_close(-1); rm.on_close(-1)
    assert not rm.can_open(0)[0]
    for k in range(3):
        rm.on_bar(T0 + timedelta(days=1, minutes=5 * (k + 1)), 10_000)
    assert rm.can_open(0)[0]


def _pos(**kw):
    base = dict(symbol="BTCUSDT", qty=1.0, entry=100.0, stop=98.0, target=104.0, initial_stop=98.0,
                opened_at=T0, strategy="test")
    return Position(**{**base, **kw})


def test_bar_exit_prefers_stop_when_both_touched():
    assert bar_exit(_pos(), high=105, low=97) == ("stop", 98.0)
    assert bar_exit(_pos(), high=105, low=99) == ("target", 104.0)
    assert bar_exit(_pos(), high=103, low=99) is None


def test_breakeven():
    p = _pos()
    assert updated_stop(p, bar_high=101.9, breakeven_at_r=1.0) == 98.0
    assert updated_stop(p, bar_high=102.0, breakeven_at_r=1.0) == 100.0


def test_paper_broker_applies_fees_slippage_and_persists():
    factory = init_db("sqlite://")
    store = Store(factory, "VIRTUAL")
    b = PaperBroker(store, cash=10_000, fee_rate=0.001, slippage_bps=10)
    sig = Signal(entry=100.0, stop=98.0, target=104.0, reason="test")
    pos = b.open("BTCUSDT", 10, sig, "test", T0)
    assert pos.entry == pytest.approx(100.1)  # 10 bps slippage
    assert b.cash() == pytest.approx(10_000 - 1001 - 1.001)

    # Restart: open position is restored from the DB
    b2 = PaperBroker(Store(factory, "VIRTUAL"), cash=10_000)
    assert "BTCUSDT" in b2.positions and b2.positions["BTCUSDT"].qty == 10

    pnl = b.check_exits("BTCUSDT", {"Open": 101, "High": 105, "Low": 100.5, "Close": 104.5}, T0)
    assert pnl == pytest.approx(10 * (104 - 100.1) - 1.001 - 1.04)  # target filled as maker at 104
    assert not b.positions
    with session_scope(factory) as s:
        row = s.query(PositionRow).one()
        assert row.status == "CLOSED" and row.exit_reason == "target"
        assert s.query(Trade).count() == 2


def test_paper_broker_stop_gap_fills_at_open():
    b = PaperBroker(Store(None, "VIRTUAL"), cash=10_000, fee_rate=0.0, slippage_bps=0)
    b.open("BTCUSDT", 1, Signal(100.0, 98.0, 104.0, "t"), "test", T0)
    pnl = b.check_exits("BTCUSDT", {"Open": 95, "High": 96, "Low": 94, "Close": 95}, T0)
    assert pnl == pytest.approx(-5)  # gapped through the 98 stop, filled at the 95 open


def test_paper_cash_restored_from_snapshot():
    factory = init_db("sqlite://")
    with session_scope(factory) as s:
        s.add(EquitySnapshot(timestamp=T0, mode="VIRTUAL", equity=12_000, cash=11_500))
    assert PaperBroker(Store(factory, "VIRTUAL"), cash=10_000).cash() == 11_500
