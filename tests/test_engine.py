from brokers import PaperBroker, Store
from database import PositionRow, init_db, session_scope
from engine import TradingEngine
from risk import RiskManager
from strategies import BaseStrategy


class AlwaysLong(BaseStrategy):
    name = "always_long"
    defaults = {"stop_atr": 1.0, "rr": 1.0, "breakeven_at_r": 0.0, "max_bars": 3, "atr_tf": None,
                "min_stop_fee_mult": 0.0, "min_target_fee_mult": 0.0}

    def indicator_warmup(self, bar) -> int:
        return 20

    def indicators(self, df):
        return {}

    def entry(self, row, prev):
        return "always"


def _engine(ohlcv, factory=None):
    broker = PaperBroker(Store(factory, "VIRTUAL"), cash=10_000, fee_rate=0.001, slippage_bps=0)
    eng = TradingEngine(client=None, broker=broker, strategy=AlwaysLong(), risk=RiskManager(),
                        symbols=["BTCUSDT"], interval="5m")
    eng.frames["BTCUSDT"] = ohlcv.iloc[:100].copy()
    return eng


def _feed(eng, ohlcv, i):
    t = ohlcv.index[i]
    eng._process_bar("BTCUSDT", t, ohlcv.iloc[i].to_dict())


def test_engine_enters_then_exits_and_persists(ohlcv):
    factory = init_db("sqlite://")
    eng = _engine(ohlcv, factory)
    _feed(eng, ohlcv, 100)
    assert "BTCUSDT" in eng.broker.positions  # entered on the closed bar
    for i in range(101, 110):
        _feed(eng, ohlcv, i)
        if "BTCUSDT" not in eng.broker.positions:
            break
    with session_scope(factory) as s:
        closed = s.query(PositionRow).filter_by(status="CLOSED").all()
    assert closed and closed[0].exit_reason in {"stop", "target", "time stop"}
    assert len(eng.frames["BTCUSDT"]) <= eng.keep_bars


def test_engine_respects_max_trades_per_day(ohlcv):
    eng = _engine(ohlcv)
    eng.risk.max_trades_per_day = 1
    for i in range(100, 160):
        _feed(eng, ohlcv, i)
    assert ohlcv.index[100].date() == ohlcv.index[159].date()
    assert eng.risk._trades_today == 1


def test_time_stop(ohlcv):
    eng = _engine(ohlcv)
    _feed(eng, ohlcv, 100)
    pos = eng.broker.positions["BTCUSDT"]
    pos.stop, pos.target = 0.01, 10**9  # unreachable: only the time stop (max_bars=3) can exit
    for i in range(101, 104):
        _feed(eng, ohlcv, i)
    assert "BTCUSDT" not in eng.broker.positions
    assert eng.risk._trades_today == 1
