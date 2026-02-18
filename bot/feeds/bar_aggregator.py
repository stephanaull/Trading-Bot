"""Bar aggregator: combines 1-minute bars into higher timeframes.

Alpaca WebSocket streams 1-minute bars natively. This module aggregates
them into 5m, 10m, etc. — aligned to clock boundaries (:00, :05, :10...).

Example: For 5m bars, 1m bars at :01, :02, :03, :04, :05 are combined
into a single 5m bar timestamped at :05 (or :00 depending on convention).
"""

import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

BarCallback = Callable[[str, pd.Series], Awaitable[None]]


class BarAggregator:
    """Aggregate 1-minute bars into N-minute bars aligned to clock boundaries.

    Usage:
        agg = BarAggregator(timeframe_minutes=5, callback=on_aggregated_bar)
        # Feed 1m bars:
        await agg.on_minute_bar("MSTR", bar_series)
    """

    def __init__(self, timeframe_minutes: int, callback: BarCallback):
        """
        Args:
            timeframe_minutes: Target timeframe in minutes (1, 2, 5, 10, 15, 30, 60)
            callback: Async function called with (ticker, aggregated_bar) when
                      a complete N-minute bar is ready
        """
        if timeframe_minutes < 1:
            raise ValueError("Timeframe must be >= 1 minute")

        self.tf_minutes = timeframe_minutes
        self.callback = callback

        # Buffer of 1m bars per ticker, keyed by the window start time
        # {ticker: {"window_start": datetime, "bars": [series, ...]}}
        self._buffers: dict[str, dict] = {}

    async def on_minute_bar(self, ticker: str, bar: pd.Series) -> None:
        """Process an incoming 1-minute bar.

        If this bar completes an N-minute window, the aggregated bar
        is emitted via the callback.

        Args:
            ticker: Symbol (e.g., "MSTR")
            bar: pd.Series with open, high, low, close, volume.
                 bar.name should be a pd.Timestamp (UTC).
        """
        # Passthrough for 1m timeframe
        if self.tf_minutes == 1:
            await self.callback(ticker, bar)
            return

        ts = bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp(bar.name)

        # Determine which N-minute window this bar belongs to
        window_start = self._get_window_start(ts)
        window_end = window_start + pd.Timedelta(minutes=self.tf_minutes)

        # Get or create buffer for this ticker
        if ticker not in self._buffers:
            self._buffers[ticker] = {"window_start": window_start, "bars": []}

        buf = self._buffers[ticker]

        # If this bar belongs to a new window, emit the previous window first
        if window_start != buf["window_start"]:
            if buf["bars"]:
                aggregated = self._aggregate(buf["bars"], buf["window_start"])
                await self.callback(ticker, aggregated)
            # Start new window
            buf["window_start"] = window_start
            buf["bars"] = []

        buf["bars"].append(bar)

        # Check if this is the last minute of the window
        # (the bar at minute N-1 of the window completes it)
        bar_minute_in_window = (ts.minute % self.tf_minutes) + 1
        if bar_minute_in_window >= self.tf_minutes:
            if buf["bars"]:
                aggregated = self._aggregate(buf["bars"], buf["window_start"])
                await self.callback(ticker, aggregated)
                buf["bars"] = []
                # Advance window
                buf["window_start"] = window_end

    async def flush(self, ticker: Optional[str] = None) -> None:
        """Emit any partially accumulated bars (e.g., at market close).

        Args:
            ticker: If provided, only flush this ticker. Otherwise flush all.
        """
        tickers = [ticker] if ticker else list(self._buffers.keys())
        for t in tickers:
            buf = self._buffers.get(t)
            if buf and buf["bars"]:
                aggregated = self._aggregate(buf["bars"], buf["window_start"])
                await self.callback(t, aggregated)
                buf["bars"] = []

    def _get_window_start(self, ts: pd.Timestamp) -> pd.Timestamp:
        """Get the start of the N-minute window this timestamp belongs to.

        Aligns to clock boundaries:
            5m:  :00, :05, :10, :15, ...
            10m: :00, :10, :20, :30, ...
        """
        floored_minute = (ts.minute // self.tf_minutes) * self.tf_minutes
        return ts.replace(minute=floored_minute, second=0, microsecond=0)

    def _aggregate(self, bars: list[pd.Series],
                   window_start: pd.Timestamp) -> pd.Series:
        """Combine multiple 1m bars into a single OHLCV bar.

        Args:
            bars: List of 1m bar Series (each with open, high, low, close, volume)
            window_start: Timestamp for the aggregated bar

        Returns:
            pd.Series with open, high, low, close, volume. name = window_start
        """
        agg = pd.Series({
            "open": bars[0]["open"],
            "high": max(b["high"] for b in bars),
            "low": min(b["low"] for b in bars),
            "close": bars[-1]["close"],
            "volume": sum(b["volume"] for b in bars),
        }, name=window_start)

        return agg
