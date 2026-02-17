"""PLTR Opening Range Breakout (ORB) Strategy v1 (10m).

Uses first 30 minutes (3 bars @ 10m) as the opening range.
10m bars produce a wider, more reliable range than 5m.
US market hours session filter.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR Opening Range Breakout"
    version = "v1"
    description = "ORB: breakout above/below first 30min range, range-based stops (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "close > orb_high",
        "short_entry": "close < orb_low",
    }

    def __init__(self, params=None):
        defaults = {
            "orb_bars": 3,              # First 3 bars @ 10m = 30 min opening range
            "target_mult": 2.0,
            "stop_buffer_pct": 0.001,
            "atr_length": 14,
            "min_range_pct": 0.003,
            "max_range_pct": 0.04,
            "session_start_hour": 14,
            "session_start_minute": 30,
            "session_end_hour": 20,
            "max_trades_per_day": 2,
        }
        super().__init__({**defaults, **(params or {})})

        self._orb_high = None
        self._orb_low = None
        self._orb_bars_count = 0
        self._orb_set = False
        self._current_date = None
        self._trades_today = 0

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        return df

    def _is_session_start(self, timestamp: pd.Timestamp) -> bool:
        return (timestamp.hour == self.params["session_start_hour"] and
                timestamp.minute >= self.params["session_start_minute"] and
                timestamp.minute < self.params["session_start_minute"] + 10)

    def _is_within_trading_hours(self, timestamp: pd.Timestamp) -> bool:
        if timestamp.hour < self.params["session_start_hour"]:
            return False
        if (timestamp.hour == self.params["session_start_hour"] and
                timestamp.minute < self.params["session_start_minute"]):
            return False
        if timestamp.hour >= self.params["session_end_hour"]:
            return False
        return True

    def _reset_session(self):
        self._orb_high = None
        self._orb_low = None
        self._orb_bars_count = 0
        self._orb_set = False
        self._trades_today = 0

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        atr_col = f"ATR_{self.params['atr_length']}"
        if pd.isna(row.get(atr_col)):
            return None

        timestamp = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)
        # Strip timezone if present
        if hasattr(timestamp, 'tz') and timestamp.tz is not None:
            timestamp = timestamp.tz_localize(None) if timestamp.tzinfo is None else timestamp

        close = row["close"]
        high = row["high"]
        low = row["low"]

        bar_date = timestamp.date() if hasattr(timestamp, 'date') else timestamp
        if self._current_date != bar_date:
            self._current_date = bar_date
            self._reset_session()

        if self._is_session_start(timestamp) and not self._orb_set:
            self._orb_bars_count = 0
            self._orb_high = high
            self._orb_low = low

        if not self._orb_set and self._orb_high is not None:
            self._orb_high = max(self._orb_high, high)
            self._orb_low = min(self._orb_low, low)
            self._orb_bars_count += 1

            if self._orb_bars_count >= self.params["orb_bars"]:
                self._orb_set = True
                range_width = self._orb_high - self._orb_low
                range_pct = range_width / self._orb_low if self._orb_low > 0 else 0

                if range_pct < self.params["min_range_pct"] or range_pct > self.params["max_range_pct"]:
                    self._orb_set = False
                    self._orb_high = None
            return None

        if not self._orb_set or self._orb_high is None:
            return None

        if not self._is_within_trading_hours(timestamp):
            if position is not None:
                direction = "close_long" if position.direction == "long" else "close_short"
                return Signal(direction=direction, reason="End of trading window")
            return None

        range_width = self._orb_high - self._orb_low
        buffer = self._orb_high * self.params["stop_buffer_pct"]
        target_dist = range_width * self.params["target_mult"]

        if self._trades_today >= self.params["max_trades_per_day"]:
            return None

        if position is None and close > self._orb_high + buffer:
            self._trades_today += 1
            return Signal(
                direction="long",
                stop_loss=self._orb_low - buffer,
                take_profit=close + target_dist,
                reason=f"ORB long: {close:.2f} > OR high {self._orb_high:.2f}"
            )

        if position is None and close < self._orb_low - buffer:
            self._trades_today += 1
            return Signal(
                direction="short",
                stop_loss=self._orb_high + buffer,
                take_profit=close - target_dist,
                reason=f"ORB short: {close:.2f} < OR low {self._orb_low:.2f}"
            )

        return None
