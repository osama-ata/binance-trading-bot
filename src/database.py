import os
import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import Any

Base = declarative_base()

class Trade(Base):
    """
    SQLAlchemy model representing a trade execution.
    """
    __tablename__ = 'trades'
    id = Column(Integer, primary_key=True)
    symbol = Column(String)
    side = Column(String) # BUY or SELL
    price = Column(Float)
    quantity = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

def get_engine() -> Engine:
    """
    Constructs and returns the SQLAlchemy Engine based on env vars.
    """
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    db = os.getenv("POSTGRES_DB", "tradingbot")
    host = os.getenv("POSTGRES_HOST", "localhost")
    return create_engine(f"postgresql://{user}:{password}@{host}:5432/{db}")

def init_db() -> sessionmaker[Session]:
    """
    Initializes the database, creates tables if they don't exist,
    and returns a sessionmaker factory.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)