import time
import os
import sys
from dotenv import load_dotenv
from database import init_db, Trade
from exchange_wrapper import ExchangeWrapper 

# Load environment variables
load_dotenv()

# Configuration
MODE: str = os.getenv('TRADING_MODE', 'VIRTUAL') # Default to Virtual
API_KEY: str | None = os.getenv('BINANCE_API_KEY')
SECRET: str | None = os.getenv('BINANCE_SECRET')

# Initialize Wrapper
# If MODE is VIRTUAL, keys can be None/Empty
exchange = ExchangeWrapper(mode=MODE, api_key=API_KEY, secret=SECRET)

# Database Setup
try:
    Session = init_db()
    session = Session()
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    print("Ensure Docker is running and POSTGRES env vars are set.")
    sys.exit(1)

SYMBOLS: list[str] = ['BTC/USDT', 'ETH/USDT']

def trading_loop() -> None:
    """
    Main trading loop. 
    Fetches prices, checks strategy logic, and executes trades.
    """
    print(f"🚀 Starting Engine in {MODE} mode")
    
    while True:
        for symbol in SYMBOLS:
            try:
                # 1. Fetch Data (Public - works without login)
                price = exchange.fetch_price(symbol)
                balance = exchange.get_balance()
                print(f"[{symbol}] {price} (Bal: {balance})")

                # 2. Strategy Logic (Mock RSI)
                # In real life, use: candles = exchange.fetch_ohlcv(symbol)
                # For demo purposes, we buy if price ends in a small digit (random)
                should_buy = (price % 10 < 2) 
                
                if should_buy:
                    # 3. Execute (Virtual or Real handled automatically)
                    order = exchange.place_order(symbol, 'BUY', 0.0001)
                    
                    if order and order['status'] == 'FILLED':
                        # Log to DB
                        db_trade = Trade(
                            symbol=symbol,
                            side='BUY',
                            price=order['price'],
                            quantity=order['amount']
                        )
                        session.add(db_trade)
                        session.commit()
                        print(f"✅ ORDER EXECUTED: {symbol} @ {order['price']}")

            except Exception as e:
                print(f"⚠️ Error handling {symbol}: {e}")
        
        time.sleep(10)

if __name__ == "__main__":
    try:
        trading_loop()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    except Exception as e:
        print(f"🔥 Critical error: {e}")