import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
from database import get_engine
from backtester import run_backtest
from exchange_wrapper import ExchangeWrapper

load_dotenv()

st.set_page_config(page_title="Crypto Commander", layout="wide")

# Initialize Exchange Wrapper for data fetching
exchange = ExchangeWrapper(mode='VIRTUAL')

# --- 1. SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Settings")

# Date Range Picker
start_date = st.sidebar.date_input("Start Date", value=pd.to_datetime("2023-01-01"))
end_date = st.sidebar.date_input("End Date", value=pd.to_datetime("today"))

# Fetch Data from DB for Trades/Monitor
engine = get_engine()
try:
    query = f"""
    SELECT * FROM trades 
    WHERE timestamp >= '{start_date}' AND timestamp <= '{end_date}'
    ORDER BY timestamp ASC
    """
    df = pd.read_sql(query, engine)
except Exception as e:
    st.error(f"Database Error: {e}")
    df = pd.DataFrame()

# Multi-Coin Selector for Monitor
available_coins = ['BTC/USDT', 'ETH/USDT'] # Default strings if DB empty
if not df.empty:
    available_coins = df['symbol'].unique()
    
selected_coins = st.sidebar.multiselect("Select Coins to Compare", available_coins, default=available_coins[:1] if len(available_coins) > 0 else None)

# Chart Type
chart_type = st.sidebar.radio("Chart Type", ["Line", "Candlestick", "Normalized (%)"])

# --- 2. MAIN TABS ---
tab1, tab2 = st.tabs(["📈 Market Overview", "🛠️ Strategy Backtester"])

with tab1:
    st.header("Market Comparison")
    
    if df.empty:
        st.warning("No trade data found in database. Start the bot to see live trades here.")
    elif selected_coins:
        filtered_df = df[df['symbol'].isin(selected_coins)]
        
        if chart_type == "Line":
            fig = px.line(filtered_df, x='timestamp', y='price', color='symbol', title="Price Comparison")
            
        elif chart_type == "Normalized (%)":
            # Normalize prices to start at 0% for fair comparison
            normalized_df = filtered_df.copy()
            for coin in selected_coins:
                coin_data = normalized_df[normalized_df['symbol'] == coin]
                if not coin_data.empty:
                    start_price = coin_data.iloc[0]['price']
                    normalized_df.loc[normalized_df['symbol'] == coin, 'price'] = (
                        (normalized_df['price'] - start_price) / start_price
                    ) * 100
                
            fig = px.line(normalized_df, x='timestamp', y='price', color='symbol', 
                          title="Relative Performance (%)", labels={'price': 'Return %'})

        elif chart_type == "Candlestick":
            # Note: Candlestick usually only makes sense for 1 coin at a time
            coin_to_plot = st.selectbox("Select Coin for Candle Chart", selected_coins)
            coin_data = df[df['symbol'] == coin_to_plot]
            
            # Creating a mock OHLC structure since our simple DB only has 'price'
            # In a real app, you would save Open/High/Low/Close in the DB
            fig = go.Figure(data=[go.Candlestick(x=coin_data['timestamp'],
                open=coin_data['price'], high=coin_data['price']*1.001,
                low=coin_data['price']*0.999, close=coin_data['price'])])
            fig.update_layout(title=f"{coin_to_plot} Candles")

        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.header("Strategy Backtester (SMA Cross)")
    st.write("Backtest strategies using historical market data from Binance.")
    
    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
    bt_coin = col_b1.selectbox("Select Coin", ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT'])
    bt_timeframe = col_b1.selectbox("Timeframe", ['1h', '4h', '1d'], index=0)
    fast_ma = col_b2.number_input("Fast MA", min_value=1, value=10)
    slow_ma = col_b3.number_input("Slow MA", min_value=2, value=20)
    initial_cash = col_b4.number_input("Initial Cash", min_value=1000, value=100000, step=1000)
    
    if st.button("Run Backtest"):
        with st.spinner(f'Fetching {bt_timeframe} data for {bt_coin} and Simulating...'):
            try:
                # 1. Fetch Real Historical Data
                bt_data = exchange.fetch_ohlcv_df(bt_coin, timeframe=bt_timeframe, limit=500)
                
                if bt_data.empty:
                    st.error("No data returned from exchange.")
                else:
                    # 2. Run Backtest
                    stats, bt_instance = run_backtest(bt_data, fast_ma, slow_ma, cash=initial_cash)
                    
                    # 3. Results
                    st.success(f"Return: {stats['Return [%]']:.2f}%")
                    
                    # Metrics Display
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Win Rate", f"{stats['Win Rate [%]']:.1f}%")
                    m2.metric("Max Drawdown", f"{stats['Max. Drawdown [%]']:.1f}%")
                    m3.metric("Sharpe Ratio", f"{stats['Sharpe Ratio']:.2f}")
                    
                    # Plot Equity Curve
                    st.subheader("Equity Curve")
                    equity_curve = stats['_equity_curve']
                    st.line_chart(equity_curve['Equity'])
                    
                    # Optional: Plot the trades on the chart
                    # bt_instance.plot() # Note: backtesting.py plot uses bokeh which might need extra setup in streamlit
            except Exception as e:
                st.error(f"Backtest failed: {e}")