import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover
from backtesting.test import SMA
from typing import Tuple, Any

# 1. Define a standard Strategy Class
class SmaCross(Strategy):
    """
    Simple Moving Average Crossover Strategy.
    Buys when fast SMA crosses above slow SMA.
    Sells when fast SMA crosses below slow SMA.
    """
    n1: int = 10
    n2: int = 20

    def init(self):
        # Precompute the two moving averages
        self.sma1 = self.I(SMA, self.data.Close, self.n1)
        self.sma2 = self.I(SMA, self.data.Close, self.n2)

    def next(self):
        # If sma1 crosses above sma2, BUY
        if crossover(self.sma1, self.sma2):
            self.buy()
        # If sma1 crosses below sma2, SELL
        elif crossover(self.sma2, self.sma1):
            self.sell()

def run_backtest(df: pd.DataFrame, fast_ma: int, slow_ma: int, cash: float = 100000.0, commission: float = 0.002) -> Tuple[pd.Series, Any]:
    """
    Runs the backtest using the provided DataFrame and parameters.
    
    Args:
        df: Pandas DataFrame containing OHLCV data.
        fast_ma: Period for the fast moving average.
        slow_ma: Period for the slow moving average.
        cash: Initial capital.
        commission: Commission per trade (e.g., 0.002 = 0.2%).
        
    Returns:
        Tuple containing:
        - stats (pd.Series): Backtest statistics.
        - bt (Backtest): The Backtest instance.
    """
    # Map column names to what backtesting.py expects (Title Case)
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low', 
        'close': 'Close', 'volume': 'Volume'
    })
    
    # Ensure timestamp is the index
    if 'timestamp' in df.columns:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    # Configure strategy with user inputs
    class CustomStrategy(SmaCross):
        n1 = fast_ma
        n2 = slow_ma

    bt = Backtest(df, CustomStrategy, cash=cash, commission=commission)
    stats = bt.run()
    return stats, bt