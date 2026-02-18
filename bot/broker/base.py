"""Abstract broker interface.

All broker implementations (Alpaca, IBKR, etc.) must implement this interface.
The interface mirrors the data types from engine/order.py (Order, Trade) so that
strategies and the live engine work identically to the backtest engine.
"""

from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd

from engine.order import Order, Trade


class BaseBroker(ABC):
    """Abstract broker for live order execution."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker API."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close broker connection."""
        ...

    @abstractmethod
    async def submit_order(self, order: Order) -> Trade:
        """Submit an order and return the resulting Trade.

        For market orders, this should block until the order is filled (or raise).
        Maps the engine's Order dataclass to the broker's native order format,
        and maps the fill response back to the engine's Trade dataclass.

        Args:
            order: Order with direction, quantity, ticker, stop_loss, take_profit

        Returns:
            Trade with entry_time, entry_price, quantity, commission filled in

        Raises:
            OrderRejectedException: If the broker rejects the order
            ConnectionError: If the broker connection is lost
        """
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order by ID.

        Returns:
            True if successfully cancelled, False if already filled or not found
        """
        ...

    @abstractmethod
    async def cancel_all(self, ticker: Optional[str] = None) -> int:
        """Cancel all open orders, optionally filtered by ticker.

        Returns:
            Number of orders cancelled
        """
        ...

    @abstractmethod
    async def close_position(self, ticker: str) -> Optional[Trade]:
        """Close the entire position for a ticker via market order.

        Returns:
            Trade representing the closing fill, or None if no position exists
        """
        ...

    @abstractmethod
    async def get_position(self, ticker: str) -> Optional[dict]:
        """Get current position for a ticker.

        Returns:
            dict with keys: qty, avg_price, side ('long'/'short'),
            unrealized_pnl, market_value, current_price
            Or None if no position exists
        """
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict]:
        """Get all open positions.

        Returns:
            List of position dicts (same format as get_position)
        """
        ...

    @abstractmethod
    async def get_account(self) -> dict:
        """Get account information.

        Returns:
            dict with keys: cash, equity, buying_power, initial_capital,
            day_trades_remaining, currency
        """
        ...

    @abstractmethod
    async def get_bars(self, ticker: str, timeframe: str,
                       limit: int = 200) -> pd.DataFrame:
        """Fetch historical bars for warmup.

        Args:
            ticker: Symbol (e.g., "MSTR")
            timeframe: Bar size (e.g., "1m", "5m", "10m", "1h", "1d")
            limit: Number of bars to fetch

        Returns:
            DataFrame with columns: open, high, low, close, volume
            Index: pd.DatetimeIndex (UTC)
        """
        ...

    @abstractmethod
    async def is_market_open(self) -> bool:
        """Check if the market is currently open for trading."""
        ...

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        """Whether this broker is in paper trading mode."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the broker connection is active."""
        ...


class OrderRejectedException(Exception):
    """Raised when the broker rejects an order."""

    def __init__(self, reason: str, order: Optional[Order] = None):
        self.reason = reason
        self.order = order
        super().__init__(f"Order rejected: {reason}")
