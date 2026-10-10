"""Position sizing, trade management rules and account-level circuit breakers.

Shared by the backtester and the live engine so both apply identical risk logic.
"""
from dataclasses import dataclass, field
from datetime import date, datetime


def position_size(equity: float, entry: float, stop: float, risk_pct: float, max_position_pct: float) -> float:
    """Units to buy so that hitting the stop loses `risk_pct` of equity, capped at `max_position_pct` notional."""
    risk_per_unit = entry - stop
    if risk_per_unit <= 0 or entry <= 0 or equity <= 0:
        return 0.0
    qty = equity * risk_pct / risk_per_unit
    return min(qty, equity * max_position_pct / entry)


@dataclass
class Position:
    symbol: str
    qty: float
    entry: float
    stop: float
    target: float
    initial_stop: float
    opened_at: datetime
    strategy: str
    reason: str = ""
    bars_held: int = 0
    fee_paid: float = 0.0
    exit_order_list_id: int | None = None
    db_id: int | None = None

    @property
    def initial_risk(self) -> float:
        return self.entry - self.initial_stop


def breakeven_level(entry: float, fee_rate: float, slippage: float = 0.0, tick: float = 0.0) -> float:
    """Lowest stop price at which a stop-out still nets >= 0 after both fees and exit slippage.

    PnL = q*(exit - entry) - fee*q*entry - fee*q*exit >= 0  <=>  exit >= entry*(1+fee)/(1-fee),
    and a stop fills at stop*(1-slippage). One tick is added so rounding to the tick grid can't undercut it.
    """
    return entry * (1 + fee_rate) / ((1 - fee_rate) * (1 - slippage)) + tick


def breakeven_stop(entry: float, stop: float, initial_risk: float, bar_high: float, breakeven_at_r: float,
                   fee_rate: float, slippage: float = 0.0, tick: float = 0.0) -> float:
    """Stop after applying the break-even rule: once price has travelled `breakeven_at_r` R in our favour,
    raise the stop to the fee-adjusted break-even level (never lower it)."""
    if breakeven_at_r <= 0 or bar_high < entry + breakeven_at_r * initial_risk:
        return stop
    return max(stop, breakeven_level(entry, fee_rate, slippage, tick))


def updated_stop(pos: Position, bar_high: float, breakeven_at_r: float, fee_rate: float = 0.0,
                 slippage: float = 0.0, tick: float = 0.0) -> float:
    return breakeven_stop(pos.entry, pos.stop, pos.initial_risk, bar_high, breakeven_at_r, fee_rate, slippage, tick)


def bar_exit(pos: Position, high: float, low: float) -> tuple[str, float] | None:
    """Check a closed bar against stop/target. If both are touched, assume the stop (conservative)."""
    if low <= pos.stop:
        return "stop", pos.stop
    if high >= pos.target:
        return "target", pos.target
    return None


@dataclass
class RiskManager:
    risk_per_trade: float = 0.005
    max_position_pct: float = 0.25
    daily_loss_limit: float = 0.02
    max_trades_per_day: int = 10
    max_open_positions: int = 2
    loss_streak_cooldown: int = 3
    cooldown_bars: int = 12

    _day: date | None = field(default=None, init=False)
    _day_start_equity: float = field(default=0.0, init=False)
    _trades_today: int = field(default=0, init=False)
    _loss_streak: int = field(default=0, init=False)
    _cooldown_left: int = field(default=0, init=False)
    halted: bool = field(default=False, init=False)

    @classmethod
    def from_settings(cls, s) -> "RiskManager":
        return cls(
            risk_per_trade=s.risk_per_trade,
            max_position_pct=s.max_position_pct,
            daily_loss_limit=s.daily_loss_limit,
            max_trades_per_day=s.max_trades_per_day,
            max_open_positions=s.max_open_positions,
            loss_streak_cooldown=s.loss_streak_cooldown,
            cooldown_bars=s.cooldown_bars,
        )

    def on_bar(self, now: datetime, equity: float) -> None:
        """Call once per closed bar (per account, not per symbol) before evaluating entries."""
        if self._day != now.date():
            self._day = now.date()
            self._day_start_equity = equity
            self._trades_today = 0
            self.halted = False
        if self._cooldown_left > 0:
            self._cooldown_left -= 1
        if self._day_start_equity and equity <= self._day_start_equity * (1 - self.daily_loss_limit):
            self.halted = True

    def can_open(self, open_positions: int) -> tuple[bool, str]:
        if self.halted:
            return False, "daily loss limit hit"
        if self._trades_today >= self.max_trades_per_day:
            return False, "max trades per day"
        if open_positions >= self.max_open_positions:
            return False, "max open positions"
        if self._cooldown_left > 0:
            return False, f"cooldown ({self._cooldown_left} bars)"
        return True, ""

    def size(self, equity: float, entry: float, stop: float) -> float:
        return position_size(equity, entry, stop, self.risk_per_trade, self.max_position_pct)

    def on_open(self) -> None:
        self._trades_today += 1

    def on_close(self, pnl: float) -> None:
        self._loss_streak = self._loss_streak + 1 if pnl < 0 else 0
        if self.loss_streak_cooldown and self._loss_streak >= self.loss_streak_cooldown:
            self._cooldown_left = self.cooldown_bars
            self._loss_streak = 0
