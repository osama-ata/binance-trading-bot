"""Postgres persistence: fills, positions (so the bot can restart mid-trade), equity snapshots and research runs."""
import datetime as dt
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import JSON, Column, DateTime, Engine, Float, Integer, String, create_engine, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import settings

Base = declarative_base()


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Trade(Base):
    """One fill (entry or exit)."""

    __tablename__ = "trades"
    id = Column(Integer, primary_key=True)
    symbol = Column(String)
    side = Column(String)  # BUY or SELL
    price = Column(Float)  # average fill price
    quantity = Column(Float)
    timestamp = Column(DateTime(timezone=True), default=utcnow)
    order_id = Column(String)
    strategy = Column(String)
    mode = Column(String)  # VIRTUAL / LIVE-testnet / LIVE-demo / LIVE-prod
    fee = Column(Float, default=0.0)  # in quote currency
    pnl = Column(Float)  # realised PnL on exits, net of both fees
    reason = Column(String)
    position_id = Column(Integer)


class PositionRow(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    mode = Column(String, index=True)
    strategy = Column(String)
    status = Column(String, default="OPEN", index=True)  # OPEN / CLOSED
    qty = Column(Float)
    entry_price = Column(Float)
    stop = Column(Float)
    initial_stop = Column(Float)
    target = Column(Float)
    opened_at = Column(DateTime(timezone=True), default=utcnow)
    bars_held = Column(Integer, default=0)
    entry_fee = Column(Float, default=0.0)
    exit_order_list_id = Column(Integer)
    closed_at = Column(DateTime(timezone=True))
    exit_price = Column(Float)
    exit_reason = Column(String)
    pnl = Column(Float)
    entry_reason = Column(String)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, index=True)
    mode = Column(String, index=True)
    equity = Column(Float)
    cash = Column(Float)


class ResearchRun(Base):
    """Headline numbers of one cached research run (walk-forward + overfitting stats).

    The files in data/research/<key>/ stay the source of truth (equity curve, folds); this table makes the runs
    queryable and feeds the dashboard's Research tab. Written by research_cache.save and scripts/research_db.py.
    """

    __tablename__ = "research_runs"
    key = Column(String, primary_key=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    code = Column(String, index=True)  # result-code fingerprint
    kind = Column(String)
    strategy = Column(String, index=True)
    symbol = Column(String, index=True)
    interval = Column(String)
    signal_tf = Column(String)
    start = Column(String)
    end = Column(String)
    train_days = Column(Integer)
    test_days = Column(Integer)
    fee = Column(Float)
    slippage_bps = Column(Float)
    params = Column(JSON)
    risk = Column(JSON)
    oos_return_pct = Column(Float)
    buy_hold_pct = Column(Float)
    oos_max_dd_pct = Column(Float)
    oos_trades = Column(Integer)
    folds = Column(Integer)
    oos_sharpe_ann = Column(Float)
    buy_hold_sharpe_ann = Column(Float)
    dsr = Column(Float)
    pbo = Column(Float)
    seconds = Column(Float)
    spec = Column(JSON)
    summary = Column(JSON)

    @classmethod
    def from_run(cls, key: str, spec: dict, summary: dict, created_at: dt.datetime | None = None) -> "ResearchRun":
        def num(k: str) -> float | None:
            v = summary.get(k)
            return None if v is None or v != v else float(v)  # NaN -> NULL

        return cls(
            key=key, created_at=created_at or utcnow(), code=spec.get("_code"), kind=spec.get("kind"),
            strategy=spec.get("strategy"), symbol=spec.get("symbol"), interval=spec.get("interval"),
            signal_tf=summary.get("signal_tf"), start=spec.get("start"), end=spec.get("end"),
            train_days=spec.get("train_days"), test_days=spec.get("test_days"), fee=spec.get("fee"),
            slippage_bps=spec.get("slippage_bps"), params=spec.get("params") or {}, risk=spec.get("risk") or {},
            oos_return_pct=num("oos_return_pct"), buy_hold_pct=num("buy_hold_pct"),
            oos_max_dd_pct=num("oos_max_dd_pct"), oos_trades=summary.get("oos_trades"), folds=summary.get("folds"),
            oos_sharpe_ann=num("oos_sharpe_ann"), buy_hold_sharpe_ann=num("buy_hold_sharpe_ann"), dsr=num("dsr"),
            pbo=num("pbo"), seconds=num("seconds"),
            spec=_jsonable(spec), summary=_jsonable(summary),
        )


def _jsonable(v):
    """JSON-safe copy: NaN/inf -> None, unknown types -> str (Postgres JSON rejects NaN)."""
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, float):
        return v if v == v and abs(v) != float("inf") else None
    if v is None or isinstance(v, (str, int, bool)):
        return v
    return str(v)


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or settings.database_url, pool_pre_ping=True)


def _migrate(engine: Engine) -> None:
    """Add columns introduced after the first version of the `trades` table (create_all won't alter tables)."""
    if engine.dialect.name != "postgresql":
        return
    existing = {c["name"] for c in inspect(engine).get_columns("trades")}
    with engine.begin() as conn:
        for col in Trade.__table__.columns:
            if col.name not in existing:
                conn.execute(text(f'ALTER TABLE trades ADD COLUMN IF NOT EXISTS "{col.name}" {col.type.compile(engine.dialect)}'))


def init_db(url: str | None = None) -> sessionmaker[Session]:
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    _migrate(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Short-lived session per unit of work: commit on success, roll back on error."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
