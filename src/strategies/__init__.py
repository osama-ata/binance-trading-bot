from strategies.base import BaseStrategy, Signal
from strategies.donchian_ensemble import DonchianEnsemble
from strategies.ema_pullback import EmaPullback
from strategies.opening_range import OpeningRangeBreakout
from strategies.squeeze_breakout import SqueezeBreakout
from strategies.vwap_reversion import VwapReversion

STRATEGIES: dict[str, type[BaseStrategy]] = {
    s.name: s for s in (EmaPullback, VwapReversion, SqueezeBreakout, OpeningRangeBreakout, DonchianEnsemble)
}

__all__ = ["STRATEGIES", "BaseStrategy", "Signal"]
