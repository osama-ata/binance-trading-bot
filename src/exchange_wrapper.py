import ccxt
import pandas as pd
import uuid
from datetime import datetime
from typing import Optional, Dict, List, Any

class ExchangeWrapper:
    """
    Wrapper class for interactions with the Binance exchange via CCXT.
    Supports both LIVE and VIRTUAL (paper trading) modes.
    """
    def __init__(self, mode: str = 'VIRTUAL', api_key: Optional[str] = None, secret: Optional[str] = None):
        self.mode = mode
        
        # Public data connection (No keys needed for fetch_ticker/ohlcv on Binance)
        self.public_client = ccxt.binance()
        
        if self.mode == 'LIVE':
            self.private_client = ccxt.binance({
                'apiKey': api_key,
                'secret': secret,
                'options': {'defaultType': 'spot'}
            })
        else:
            # Paper Trading State
            self.balance: Dict[str, float] = {'USDT': 10000.0, 'BTC': 0.0, 'ETH': 0.0} # Fake Money
            self.orders: List[Dict[str, Any]] = []

    def fetch_price(self, symbol: str) -> float:
        """
        Fetches the current price for a symbol using the public API.
        Does not require login.
        """
        ticker = self.public_client.fetch_ticker(symbol)
        return float(ticker['last'])

    def fetch_ohlcv(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> List[List[float]]:
        """
        Fetches raw OHLCV data from the public API.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '1h', '15m')
            limit: Number of candles to fetch
            
        Returns:
            List of lists containing [timestamp, open, high, low, close, volume]
        """
        return self.public_client.fetch_ohlcv(symbol, timeframe, limit=limit)

    def fetch_ohlcv_df(self, symbol: str, timeframe: str = '1h', limit: int = 100) -> pd.DataFrame:
        """
        Fetches OHLCV data and returns it as a formatted Pandas DataFrame.
        Useful for backtesting.
        """
        data = self.fetch_ohlcv(symbol, timeframe, limit)
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df

    def get_balance(self) -> Dict[str, float]:
        """
        Returns the current wallet balance.
        In LIVE mode, fetches from exchange. In VIRTUAL mode, returns local state.
        """
        if self.mode == 'LIVE':
            bal = self.private_client.fetch_balance()
            return {k: v['free'] for k, v in bal.items() if v['free'] > 0}
        else:
            return self.balance

    def place_order(self, symbol: str, side: str, amount: float) -> Optional[Dict[str, Any]]:
        """
        Places a market order.
        In VIRTUAL mode, simulates the trade and updates local balance.
        """
        price = self.fetch_price(symbol)
        
        if self.mode == 'LIVE':
            # Real Execution
            return self.private_client.create_order(symbol, 'market', side, amount)
        else:
            # Virtual Execution (Simulation)
            base_currency = symbol.split('/')[0] # BTC
            quote_currency = symbol.split('/')[1] # USDT
            cost = price * amount
            status = 'FAILED'

            if side == 'BUY':
                if self.balance.get(quote_currency, 0) >= cost:
                    self.balance[quote_currency] -= cost
                    self.balance[base_currency] = self.balance.get(base_currency, 0) + amount
                    status = 'FILLED'
                else:
                    print("❌ VIRTUAL: Insufficient Funds")
                    return None
            
            elif side == 'SELL':
                if self.balance.get(base_currency, 0) >= amount:
                    self.balance[base_currency] -= amount
                    self.balance[quote_currency] = self.balance.get(quote_currency, 0) + cost
                    status = 'FILLED'
                else:
                    print("❌ VIRTUAL: Insufficient Asset")
                    return None

            # Create a fake order receipt similar to CCXT response
            order = {
                'id': str(uuid.uuid4()),
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'price': price,
                'status': status,
                'timestamp': datetime.utcnow().isoformat()
            }
            self.orders.append(order)
            return order