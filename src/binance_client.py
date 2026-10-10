"""Thin adapter over Binance's official Python SDK (binance-sdk-spot).

Market data always comes from Binance's public market-data endpoints (no keys needed).
Order endpoints point at prod / testnet / demo depending on BINANCE_ENV.
"""
import asyncio
import logging
import uuid
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any, Awaitable, Callable

import pandas as pd
from binance_common.configuration import ConfigurationRestAPI, ConfigurationWebSocketStreams
from binance_common.constants import (
    SPOT_REST_API_DEMO_URL,
    SPOT_REST_API_MARKET_URL,
    SPOT_REST_API_PROD_URL,
    SPOT_REST_API_TESTNET_URL,
    SPOT_WS_STREAMS_MARKET_URL,
)
from binance_sdk_spot.rest_api.models import (
    KlinesIntervalEnum,
    NewOrderNewOrderRespTypeEnum,
    NewOrderSideEnum,
    NewOrderTypeEnum,
    OrderListOcoAboveTypeEnum,
    OrderListOcoBelowTypeEnum,
    OrderListOcoSideEnum,
)
from binance_sdk_spot.spot import Spot
from binance_sdk_spot.websocket_streams.models import KlineIntervalEnum

log = logging.getLogger(__name__)

REST_URLS = {
    "prod": SPOT_REST_API_PROD_URL,
    "testnet": SPOT_REST_API_TESTNET_URL,
    "demo": SPOT_REST_API_DEMO_URL,
}

KLINE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal

    def round_qty(self, qty: float) -> float:
        q = (Decimal(str(qty)) / self.step_size).to_integral_value(ROUND_DOWN) * self.step_size
        return float(q)

    def round_price(self, price: float) -> float:
        p = (Decimal(str(price)) / self.tick_size).to_integral_value(ROUND_DOWN) * self.tick_size
        return float(p)

    def is_tradeable(self, qty: float, price: float) -> bool:
        return Decimal(str(qty)) >= self.min_qty and Decimal(str(qty)) * Decimal(str(price)) >= self.min_notional


def interval_to_timedelta(interval: str) -> pd.Timedelta:
    units = {"s": "s", "m": "min", "h": "h", "d": "D", "w": "W"}
    return pd.Timedelta(int(interval[:-1]), unit=units[interval[-1]])


def klines_to_df(rows: list[list[Any]]) -> pd.DataFrame:
    """Convert raw Binance kline rows into a float OHLCV frame indexed by UTC open time."""
    df = pd.DataFrame([r[:6] for r in rows], columns=["open_time", *KLINE_COLUMNS])
    ts = df["open_time"].astype("int64")
    # data.binance.vision spot files use microseconds since 2025; REST uses milliseconds
    unit = "us" if ts.max() > 10**14 else "ms"
    df.index = pd.to_datetime(ts, unit=unit, utc=True)
    df.index.name = "time"
    return df[KLINE_COLUMNS].astype(float)


class BinanceClient:
    def __init__(
        self,
        env: str = "testnet",
        api_key: str | None = None,
        api_secret: str | None = None,
        private_key: str | None = None,
    ):
        if env not in REST_URLS:
            raise ValueError(f"BINANCE_ENV must be one of {list(REST_URLS)}, got {env!r}")
        self.env = env
        # The SDK retries with backoff on network errors (retries=3, backoff=1000ms by default).
        self._market = Spot(config_rest_api=ConfigurationRestAPI(base_path=SPOT_REST_API_MARKET_URL, timeout=5000))
        self._trading: Spot | None = None
        if api_key:
            self._trading = Spot(
                config_rest_api=ConfigurationRestAPI(
                    api_key=api_key,
                    api_secret=None if private_key else api_secret,
                    private_key=private_key,
                    base_path=REST_URLS[env],
                    timeout=5000,
                )
            )
        self._filters: dict[str, SymbolFilters] = {}

    # ---------- market data (public) ----------
    def get_klines(
        self, symbol: str, interval: str, limit: int = 1000, start_ms: int | None = None, end_ms: int | None = None
    ) -> pd.DataFrame:
        resp = self._market.rest_api.klines(
            symbol=symbol,
            interval=KlinesIntervalEnum(interval).value,
            start_time=start_ms,
            end_time=end_ms,
            limit=limit,
        )
        rows = resp.data()
        return klines_to_df(rows) if rows else pd.DataFrame(columns=KLINE_COLUMNS)

    def get_book_ticker(self, symbol: str) -> tuple[float, float]:
        d = self._market.rest_api.ticker_book_ticker(symbol=symbol).data().to_dict()
        return float(d["bidPrice"]), float(d["askPrice"])

    def exchange_filters(self, symbol: str) -> SymbolFilters:
        if symbol not in self._filters:
            info = self._market.rest_api.exchange_info(symbol=symbol).data()
            s = info.symbols[0]
            f = {x.to_dict()["filterType"]: x.to_dict() for x in s.filters}
            self._filters[symbol] = SymbolFilters(
                symbol=symbol,
                base_asset=s.base_asset,
                quote_asset=s.quote_asset,
                tick_size=Decimal(f["PRICE_FILTER"]["tickSize"]).normalize(),
                step_size=Decimal(f["LOT_SIZE"]["stepSize"]).normalize(),
                min_qty=Decimal(f["LOT_SIZE"]["minQty"]),
                min_notional=Decimal(f.get("NOTIONAL", {}).get("minNotional", "0")),
            )
        return self._filters[symbol]

    async def stream_closed_klines(
        self, symbols: list[str], interval: str, on_bar: Callable[[str, pd.Timestamp, dict], Awaitable[None]],
        on_update: Callable[[str, dict], Awaitable[None]] | None = None,
    ) -> None:
        """Subscribe to kline streams; call on_bar for every *closed* candle and on_update for every tick."""
        client = Spot(config_ws_streams=ConfigurationWebSocketStreams(stream_url=SPOT_WS_STREAMS_MARKET_URL))
        conn = await client.websocket_streams.create_connection()
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        for sym in symbols:
            stream = await conn.kline(symbol=sym.lower(), interval=KlineIntervalEnum(interval).value)
            stream.on("message", lambda msg: loop.call_soon_threadsafe(queue.put_nowait, msg.to_dict()))
        log.info("Subscribed to %s %s klines", symbols, interval)
        try:
            while True:
                msg = await queue.get()
                k = msg["k"]
                bar = {
                    "Open": float(k["o"]), "High": float(k["h"]), "Low": float(k["l"]),
                    "Close": float(k["c"]), "Volume": float(k["v"]),
                }
                if on_update:
                    await on_update(k["s"], bar)
                if k["x"]:
                    await on_bar(k["s"], pd.Timestamp(k["t"], unit="ms", tz="UTC"), bar)
        finally:
            await conn.close_connection(close_session=True)

    # ---------- trading (signed) ----------
    @property
    def trading(self) -> Spot:
        if self._trading is None:
            raise RuntimeError("BINANCE_API_KEY is required for LIVE trading")
        return self._trading

    def market_buy(self, symbol: str, qty: float) -> dict:
        """Market buy; returns {'order_id', 'qty', 'avg_price', 'fee', 'fee_asset'} from the FULL response."""
        resp = self.trading.rest_api.new_order(
            symbol=symbol,
            side=NewOrderSideEnum.BUY.value,
            type=NewOrderTypeEnum.MARKET.value,
            quantity=qty,
            new_client_order_id=f"bot-{uuid.uuid4().hex[:20]}",
            new_order_resp_type=NewOrderNewOrderRespTypeEnum.FULL.value,
        ).data().to_dict()
        return self._summarise_fills(resp)

    def market_sell(self, symbol: str, qty: float) -> dict:
        resp = self.trading.rest_api.new_order(
            symbol=symbol,
            side=NewOrderSideEnum.SELL.value,
            type=NewOrderTypeEnum.MARKET.value,
            quantity=qty,
            new_order_resp_type=NewOrderNewOrderRespTypeEnum.FULL.value,
        ).data().to_dict()
        return self._summarise_fills(resp)

    def place_exit_oco(self, symbol: str, qty: float, take_profit: float, stop: float) -> int:
        """Exchange-side protection for a long: LIMIT_MAKER take-profit above, STOP_LOSS (market) below."""
        f = self.exchange_filters(symbol)
        resp = self.trading.rest_api.order_list_oco(
            symbol=symbol,
            side=OrderListOcoSideEnum.SELL.value,
            quantity=f.round_qty(qty),
            above_type=OrderListOcoAboveTypeEnum.LIMIT_MAKER.value,
            above_price=f.round_price(take_profit),
            below_type=OrderListOcoBelowTypeEnum.STOP_LOSS.value,
            below_stop_price=f.round_price(stop),
        ).data().to_dict()
        return int(resp["orderListId"])

    def get_order_list_status(self, order_list_id: int) -> dict:
        return self.trading.rest_api.get_order_list(order_list_id=order_list_id).data().to_dict()

    def cancel_order_list(self, symbol: str, order_list_id: int) -> None:
        self.trading.rest_api.delete_order_list(symbol=symbol, order_list_id=order_list_id)

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self.trading.rest_api.get_order(symbol=symbol, order_id=order_id).data().to_dict()

    def get_free_balance(self, asset: str) -> float:
        acct = self.trading.rest_api.get_account(omit_zero_balances=True).data().to_dict()
        return next((float(b["free"]) for b in acct.get("balances", []) if b["asset"] == asset), 0.0)

    @staticmethod
    def _summarise_fills(resp: dict) -> dict:
        fills = resp.get("fills") or []
        qty = sum(float(f["qty"]) for f in fills) or float(resp.get("executedQty", 0))
        quote = sum(float(f["price"]) * float(f["qty"]) for f in fills) or float(resp.get("cummulativeQuoteQty", 0))
        return {
            "order_id": str(resp.get("orderId")),
            "status": resp.get("status"),
            "qty": qty,
            "avg_price": quote / qty if qty else 0.0,
            "fee": sum(float(f["commission"]) for f in fills),
            "fee_asset": fills[0]["commissionAsset"] if fills else None,
        }
