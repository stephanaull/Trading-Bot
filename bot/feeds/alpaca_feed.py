"""Alpaca WebSocket data feed for real-time 1-minute bars.

Connects to Alpaca's real-time data stream and delivers bars
through the BarAggregator to produce the desired timeframe.

Includes automatic reconnection with exponential backoff.
"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed

from bot.feeds.base import BaseFeed, BarCallback
from bot.feeds.bar_aggregator import BarAggregator

logger = logging.getLogger(__name__)


class AlpacaFeed(BaseFeed):
    """Real-time bar feed from Alpaca WebSocket.

    Streams 1-minute bars and routes them through BarAggregators
    (one per ticker/timeframe) to produce the desired bar sizes.
    """

    def __init__(self, api_key: str, secret_key: str,
                 feed: str = "iex"):
        """
        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            feed: Data feed source. "iex" (free, 15min delayed for some)
                  or "sip" (real-time, requires paid subscription)
        """
        self._api_key = api_key
        self._secret_key = secret_key
        self._feed = DataFeed.IEX if feed == "iex" else DataFeed.SIP
        self._stream: Optional[StockDataStream] = None
        self._connected = False

        # Aggregators: {ticker: BarAggregator}
        self._aggregators: dict[str, BarAggregator] = {}

        # User callback for aggregated bars
        self._bar_callback: Optional[BarCallback] = None

        # Subscribed tickers
        self._tickers: list[str] = []

        # Reconnection settings
        self._max_reconnect_attempts = 10
        self._reconnect_delay = 3  # seconds, doubles each retry

    async def connect(self) -> None:
        """Create the WebSocket stream client."""
        self._stream = StockDataStream(
            api_key=self._api_key,
            secret_key=self._secret_key,
            feed=self._feed,
        )
        self._connected = True
        logger.info(f"Alpaca feed initialized (feed: {self._feed.value})")

    async def disconnect(self) -> None:
        """Stop the WebSocket stream."""
        if self._stream:
            try:
                await self._stream.stop_ws()
            except Exception:
                pass
        self._connected = False
        logger.info("Alpaca feed disconnected.")

    async def subscribe(self, tickers: list[str]) -> None:
        """Subscribe to 1-minute bars for the given tickers.

        Note: Actual timeframe aggregation is handled by BarAggregators
        registered via add_aggregator().
        """
        self._tickers = tickers
        if self._stream:
            self._stream.subscribe_bars(self._on_raw_bar, *tickers)
            logger.info(f"Subscribed to bars: {', '.join(tickers)}")

    def add_aggregator(self, ticker: str, timeframe_minutes: int) -> None:
        """Add a bar aggregator for a specific ticker/timeframe.

        Args:
            ticker: Symbol to aggregate
            timeframe_minutes: Target timeframe (5, 10, etc.)
        """
        async def _emit(t: str, bar: pd.Series):
            if self._bar_callback:
                await self._bar_callback(t, bar)

        self._aggregators[ticker] = BarAggregator(
            timeframe_minutes=timeframe_minutes,
            callback=_emit,
        )
        logger.info(f"Aggregator added: {ticker} → {timeframe_minutes}m bars")

    def on_bar(self, callback: BarCallback) -> None:
        """Register callback for aggregated bars."""
        self._bar_callback = callback

    async def run(self) -> None:
        """Start the WebSocket stream (blocking).

        This runs the Alpaca WebSocket event loop. Call this in an
        asyncio task — it blocks until disconnected.
        """
        if not self._stream:
            raise RuntimeError("Call connect() before run()")

        attempt = 0
        delay = self._reconnect_delay

        while attempt < self._max_reconnect_attempts:
            try:
                logger.info("Starting Alpaca WebSocket stream...")
                self._stream.run()  # Blocking
            except Exception as e:
                attempt += 1
                if attempt >= self._max_reconnect_attempts:
                    logger.error(
                        f"Max reconnection attempts ({self._max_reconnect_attempts}) "
                        f"reached. Giving up."
                    )
                    raise
                logger.warning(
                    f"WebSocket disconnected: {e}. "
                    f"Reconnecting in {delay}s (attempt {attempt})..."
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)  # Exponential backoff, max 60s

                # Recreate stream and resubscribe
                self._stream = StockDataStream(
                    api_key=self._api_key,
                    secret_key=self._secret_key,
                    feed=self._feed,
                )
                if self._tickers:
                    self._stream.subscribe_bars(self._on_raw_bar, *self._tickers)

    async def _on_raw_bar(self, bar) -> None:
        """Handle incoming 1-minute bar from Alpaca WebSocket.

        Converts to pd.Series and routes through the appropriate aggregator.
        """
        ticker = bar.symbol

        # Convert Alpaca Bar to pd.Series matching engine format
        ts = pd.Timestamp(bar.timestamp)
        bar_series = pd.Series({
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }, name=ts)

        # Route through aggregator if one exists
        aggregator = self._aggregators.get(ticker)
        if aggregator:
            await aggregator.on_minute_bar(ticker, bar_series)
        elif self._bar_callback:
            # No aggregator — pass through raw 1m bar
            await self._bar_callback(ticker, bar_series)

    async def flush_all(self) -> None:
        """Flush all aggregators (emit partial bars, e.g., at market close)."""
        for ticker, agg in self._aggregators.items():
            await agg.flush(ticker)

    @property
    def is_connected(self) -> bool:
        return self._connected
