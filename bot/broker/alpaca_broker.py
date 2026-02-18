"""Alpaca broker implementation using alpaca-py SDK.

Supports both paper and live trading via Alpaca's API.
Maps engine Order/Trade dataclasses to Alpaca's native order format.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    TimeInForce,
    OrderStatus,
    QueryOrderStatus,
)
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed

from engine.order import Order, Trade
from bot.broker.base import BaseBroker, OrderRejectedException

logger = logging.getLogger(__name__)

# Map timeframe strings to Alpaca TimeFrame objects
_TIMEFRAME_MAP = {
    "1m": TimeFrame(1, TimeFrameUnit.Minute),
    "2m": TimeFrame(2, TimeFrameUnit.Minute),
    "5m": TimeFrame(5, TimeFrameUnit.Minute),
    "10m": TimeFrame(10, TimeFrameUnit.Minute),
    "15m": TimeFrame(15, TimeFrameUnit.Minute),
    "30m": TimeFrame(30, TimeFrameUnit.Minute),
    "1h": TimeFrame(1, TimeFrameUnit.Hour),
    "1d": TimeFrame(1, TimeFrameUnit.Day),
}


class AlpacaBroker(BaseBroker):
    """Alpaca broker for paper and live trading.

    Uses alpaca-py SDK:
    - TradingClient for orders, positions, account
    - StockHistoricalDataClient for historical bars
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self._api_key = api_key
        self._secret_key = secret_key
        self._paper = paper
        self._trading_client: Optional[TradingClient] = None
        self._data_client: Optional[StockHistoricalDataClient] = None
        self._connected = False

    async def connect(self) -> None:
        """Initialize Alpaca clients."""
        self._trading_client = TradingClient(
            api_key=self._api_key,
            secret_key=self._secret_key,
            paper=self._paper,
        )
        self._data_client = StockHistoricalDataClient(
            api_key=self._api_key,
            secret_key=self._secret_key,
        )
        self._connected = True

        # Verify connection by fetching account
        account = self._trading_client.get_account()
        mode = "PAPER" if self._paper else "LIVE"
        logger.info(
            f"Connected to Alpaca ({mode}). "
            f"Equity: ${float(account.equity):,.2f}, "
            f"Cash: ${float(account.cash):,.2f}, "
            f"Buying Power: ${float(account.buying_power):,.2f}"
        )

    async def disconnect(self) -> None:
        """Close Alpaca connection (no persistent connection to close)."""
        self._connected = False
        logger.info("Disconnected from Alpaca.")

    async def submit_order(self, order: Order) -> Trade:
        """Submit a market order to Alpaca.

        Maps engine Order → Alpaca MarketOrderRequest, then maps
        the fill response back to engine Trade.
        """
        self._ensure_connected()

        # Map direction to Alpaca OrderSide
        if order.direction == "long":
            side = OrderSide.BUY
        elif order.direction == "short":
            side = OrderSide.SELL
        elif order.direction in ("close_long", "close_short", "flat"):
            # Close position via the close_position method instead
            trade = await self.close_position(order.ticker)
            if trade is None:
                raise OrderRejectedException(
                    f"No position to close for {order.ticker}", order
                )
            return trade
        else:
            raise OrderRejectedException(
                f"Unknown direction: {order.direction}", order
            )

        # Submit market order
        request = MarketOrderRequest(
            symbol=order.ticker,
            qty=order.quantity,
            side=side,
            time_in_force=TimeInForce.DAY,
        )

        try:
            alpaca_order = self._trading_client.submit_order(request)
        except Exception as e:
            raise OrderRejectedException(str(e), order)

        # Wait for fill by polling (market orders fill nearly instantly)
        filled_order = self._wait_for_fill(alpaca_order.id)

        fill_price = float(filled_order.filled_avg_price or 0)
        fill_qty = float(filled_order.filled_qty or order.quantity)
        fill_time = filled_order.filled_at or datetime.utcnow()

        if isinstance(fill_time, str):
            fill_time = pd.Timestamp(fill_time)
        else:
            fill_time = pd.Timestamp(fill_time)

        trade = Trade(
            entry_time=fill_time,
            ticker=order.ticker,
            direction=order.direction,
            quantity=fill_qty,
            entry_price=fill_price,
            commission=0.0,  # Alpaca is commission-free for stocks
            slippage=0.0,    # Real slippage is baked into fill_price
        )

        logger.info(
            f"Order filled: {order.direction} {fill_qty} {order.ticker} "
            f"@ ${fill_price:.2f} (ID: {alpaca_order.id})"
        )
        return trade

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        self._ensure_connected()
        try:
            self._trading_client.cancel_order_by_id(order_id)
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    async def cancel_all(self, ticker: Optional[str] = None) -> int:
        """Cancel all open orders."""
        self._ensure_connected()
        try:
            if ticker:
                # Get open orders for this ticker and cancel each
                request = GetOrdersRequest(
                    status=QueryOrderStatus.OPEN,
                    symbols=[ticker],
                )
                orders = self._trading_client.get_orders(request)
                for o in orders:
                    self._trading_client.cancel_order_by_id(o.id)
                return len(orders)
            else:
                statuses = self._trading_client.cancel_orders()
                return len(statuses)
        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")
            return 0

    async def close_position(self, ticker: str) -> Optional[Trade]:
        """Close the entire position for a ticker."""
        self._ensure_connected()
        try:
            alpaca_order = self._trading_client.close_position(ticker)
        except Exception as e:
            logger.warning(f"No position to close for {ticker}: {e}")
            return None

        filled_order = self._wait_for_fill(alpaca_order.id)
        fill_price = float(filled_order.filled_avg_price or 0)
        fill_qty = float(filled_order.filled_qty or 0)
        fill_time = filled_order.filled_at or datetime.utcnow()

        if not isinstance(fill_time, pd.Timestamp):
            fill_time = pd.Timestamp(fill_time)

        # Determine direction based on the closing order side
        direction = "close_long" if filled_order.side == OrderSide.SELL else "close_short"

        trade = Trade(
            entry_time=fill_time,
            ticker=ticker,
            direction=direction,
            quantity=fill_qty,
            entry_price=fill_price,
            commission=0.0,
        )

        logger.info(f"Closed position: {ticker} {fill_qty} @ ${fill_price:.2f}")
        return trade

    async def get_position(self, ticker: str) -> Optional[dict]:
        """Get current position for a ticker."""
        self._ensure_connected()
        try:
            pos = self._trading_client.get_open_position(ticker)
        except Exception:
            return None

        return {
            "ticker": pos.symbol,
            "qty": abs(float(pos.qty)),
            "avg_price": float(pos.avg_entry_price),
            "side": "long" if float(pos.qty) > 0 else "short",
            "unrealized_pnl": float(pos.unrealized_pl),
            "market_value": abs(float(pos.market_value)),
            "current_price": float(pos.current_price),
        }

    async def get_positions(self) -> list[dict]:
        """Get all open positions."""
        self._ensure_connected()
        positions = self._trading_client.get_all_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": abs(float(p.qty)),
                "avg_price": float(p.avg_entry_price),
                "side": "long" if float(p.qty) > 0 else "short",
                "unrealized_pnl": float(p.unrealized_pl),
                "market_value": abs(float(p.market_value)),
                "current_price": float(p.current_price),
            }
            for p in positions
        ]

    async def get_account(self) -> dict:
        """Get account information including day trading fields."""
        self._ensure_connected()
        account = self._trading_client.get_account()

        # Day trading buying power (4x for PDT accounts, 0 for non-PDT)
        dt_bp = float(account.daytrading_buying_power or 0)
        regt_bp = float(account.regt_buying_power or account.buying_power or 0)

        return {
            "cash": float(account.cash),
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
            "regt_buying_power": regt_bp,
            "daytrading_buying_power": dt_bp,
            "non_marginable_buying_power": float(
                account.non_marginable_buying_power or account.cash
            ),
            "initial_capital": float(account.last_equity),
            "daytrade_count": getattr(account, "daytrade_count", 0) or 0,
            "pattern_day_trader": getattr(account, "pattern_day_trader", False),
            "multiplier": int(account.multiplier or 1),
            "trading_blocked": getattr(account, "trading_blocked", False),
            "currency": account.currency,
            "status": account.status.value if account.status else "unknown",
        }

    async def get_bars(self, ticker: str, timeframe: str,
                       limit: int = 200) -> pd.DataFrame:
        """Fetch historical bars from Alpaca.

        Returns DataFrame matching the engine's expected format:
        columns: open, high, low, close, volume
        index: pd.DatetimeIndex named 'date'
        """
        self._ensure_connected()

        tf = _TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            raise ValueError(
                f"Unsupported timeframe: {timeframe}. "
                f"Supported: {list(_TIMEFRAME_MAP.keys())}"
            )

        # Calculate start date to get enough bars
        # Overshoot to account for market closed hours/days
        if "m" in timeframe:
            minutes = int(timeframe.replace("m", ""))
            days_needed = max(5, (limit * minutes) // (390) + 3)  # 390 min/trading day
        elif timeframe == "1h":
            days_needed = max(5, (limit // 7) + 3)
        else:
            days_needed = limit + 10

        end = datetime.utcnow()
        start = end - timedelta(days=days_needed)

        request = StockBarsRequest(
            symbol_or_symbols=ticker,
            timeframe=tf,
            start=start,
            end=end,
            limit=limit,
            feed=DataFeed.IEX,
        )

        bars = self._data_client.get_stock_bars(request)

        # Convert to DataFrame
        records = []
        for bar in bars[ticker]:
            records.append({
                "date": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            })

        if not records:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.set_index("date").sort_index()

        # Trim to requested limit
        if len(df) > limit:
            df = df.iloc[-limit:]

        return df

    async def is_market_open(self) -> bool:
        """Check if the US stock market is currently open."""
        self._ensure_connected()
        clock = self._trading_client.get_clock()
        return clock.is_open

    @property
    def is_paper(self) -> bool:
        return self._paper

    @property
    def is_connected(self) -> bool:
        return self._connected

    # --- Private helpers ---

    def _ensure_connected(self) -> None:
        if not self._connected or self._trading_client is None:
            raise ConnectionError("Broker not connected. Call connect() first.")

    def _wait_for_fill(self, order_id: str, max_attempts: int = 30) -> object:
        """Poll until order is filled (market orders fill almost instantly).

        Args:
            order_id: Alpaca order ID
            max_attempts: Max polling attempts (each ~0.5s for total ~15s)

        Returns:
            Filled Alpaca order object
        """
        import time

        for _ in range(max_attempts):
            order = self._trading_client.get_order_by_id(order_id)
            if order.status == OrderStatus.FILLED:
                return order
            if order.status in (
                OrderStatus.CANCELED,
                OrderStatus.EXPIRED,
                OrderStatus.REJECTED,
            ):
                raise OrderRejectedException(
                    f"Order {order_id} was {order.status.value}"
                )
            time.sleep(0.5)

        raise OrderRejectedException(
            f"Order {order_id} not filled after {max_attempts * 0.5}s"
        )
