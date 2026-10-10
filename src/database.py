"""Postgres persistence: fills, positions (so the bot can restart mid-trade) and equity snapshots."""
import datetime as dt
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Column, DateTime, Engine, Float, Integer, String, create_engine, inspect, text
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
