"""Abstract data feed interface.

All feed implementations (Alpaca, IBKR, etc.) must implement this interface.
Feeds deliver OHLCV bars via async callbacks.
"""

from abc import ABC, abstractmethod
from typing import Callable, Awaitable, Optional

import pandas as pd


# Callback type: async function receiving (ticker, bar_as_series)
BarCallback = Callable[[str, pd.Series], Awaitable[None]]


class BaseFeed(ABC):
    """Abstract data feed for real-time bar delivery."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the data connection."""
        ...

    @abstractmethod
    async def subscribe(self, tickers: list[str]) -> None:
        """Subscribe to bar data for the given tickers.

        Args:
            tickers: List of symbols to subscribe to (e.g., ["MSTR", "PLTR"])
        """
        ...

    @abstractmethod
    def on_bar(self, callback: BarCallback) -> None:
        """Register a callback for new aggregated bars.

        The callback receives (ticker, bar_series) where bar_series
        is a pd.Series with index=['open','high','low','close','volume']
        and name=pd.Timestamp (UTC).

        Args:
            callback: Async function to call when a new bar is ready
        """
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the feed is connected and streaming."""
        ...
