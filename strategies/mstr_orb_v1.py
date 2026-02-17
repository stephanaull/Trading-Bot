"""MSTR Opening Range Breakout (ORB) Strategy v1.

Classic day trading strategy:
1. Define the opening range from the first N bars of the session (first 15 min = 3 bars @ 5m)
2. Go long on breakout above the opening range high
3. Go short on breakout below the opening range low
4. Stop-loss at the opposite side of the range
5. Take-profit at 2x the range width

Session detection: uses typical US market hours (14:30-21:00 UTC / 9:30-4:00 ET).
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR Opening Range Breakout"
    version = "v1"
    description = "ORB: breakout above/below first 15min range with range-based stops"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "close > orb_high and barstate.isconfirmed",
        "short_entry": "close < orb_low and barstate.isconfirmed",
    }

    def __init__(self, params=None):
        defaults = {
            "orb_bars": 3,              # First 3 bars = 15 min opening range at 5m
            "target_mult": 2.0,         # Take profit at 2x range width
            "stop_buffer_pct": 0.001,   # Small buffer beyond OR for stop
            "atr_length": 14,
            "min_range_pct": 0.003,     # Min range width 0.3% to avoid tiny ranges
            "max_range_pct": 0.03,      # Max range width 3% to avoid extreme volatility
            "session_start_hour": 14,   # 14:30 UTC = 9:30 ET
            "session_start_minute": 30,
            "session_end_hour": 20,     # 20:00 UTC = 3:00 PM ET (stop trading)
            "max_trades_per_day": 2,    # Limit to 2 ORB trades per session
        }
        super().__init__({**defaults, **(params or {})})

        # Session state
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
        """Check if this bar is the first bar of the trading session."""
        return (timestamp.hour == self.params["session_start_hour"] and
                timestamp.minute >= self.params["session_start_minute"] and
                timestamp.minute < self.params["session_start_minute"] + 5)

    def _is_within_trading_hours(self, timestamp: pd.Timestamp) -> bool:
        """Check if current time is within allowed trading window."""
        if timestamp.hour < self.params["session_start_hour"]:
            return False
        if (timestamp.hour == self.params["session_start_hour"] and
                timestamp.minute < self.params["session_start_minute"]):
            return False
        if timestamp.hour >= self.params["session_end_hour"]:
            return False
        return True

    def _reset_session(self):
        """Reset ORB state for a new session."""
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
        close = row["close"]
        high = row["high"]
        low = row["low"]
        atr = row[atr_col]

        # Detect new trading day
        bar_date = timestamp.date()
        if self._current_date != bar_date:
            self._current_date = bar_date
            self._reset_session()

        # Build opening range during first N bars of session
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

                # Validate range
                if range_pct < self.params["min_range_pct"] or range_pct > self.params["max_range_pct"]:
                    self._orb_set = False  # Invalid range, skip this day
                    self._orb_high = None

            return None  # Don't trade during OR building

        # No valid ORB for today
        if not self._orb_set or self._orb_high is None:
            return None

        # Outside trading hours -- close any open position
        if not self._is_within_trading_hours(timestamp):
            if position is not None:
                if position.direction == "long":
                    return Signal(direction="close_long", reason="End of trading window")
                else:
                    return Signal(direction="close_short", reason="End of trading window")
            return None

        range_width = self._orb_high - self._orb_low
        buffer = self._orb_high * self.params["stop_buffer_pct"]
        target_dist = range_width * self.params["target_mult"]

        # Max trades per day check
        if self._trades_today >= self.params["max_trades_per_day"]:
            # Only allow exits, not new entries
            if position is not None:
                if position.direction == "long" and close < self._orb_low:
                    return Signal(direction="close_long", reason="Price fell below OR low")
                if position.direction == "short" and close > self._orb_high:
                    return Signal(direction="close_short", reason="Price broke above OR high")
            return None

        # LONG BREAKOUT: close above opening range high
        if position is None and close > self._orb_high + buffer:
            self._trades_today += 1
            return Signal(
                direction="long",
                stop_loss=self._orb_low - buffer,
                take_profit=close + target_dist,
                reason=f"ORB long breakout: close {close:.2f} > OR high {self._orb_high:.2f} (range: {range_width:.2f})"
            )

        # SHORT BREAKOUT: close below opening range low
        if position is None and close < self._orb_low - buffer:
            self._trades_today += 1
            return Signal(
                direction="short",
                stop_loss=self._orb_high + buffer,
                take_profit=close - target_dist,
                reason=f"ORB short breakout: close {close:.2f} < OR low {self._orb_low:.2f} (range: {range_width:.2f})"
            )

        return None

    def on_trade_closed(self, trade) -> None:
        """Track trades for daily limit."""
        pass  # Already tracked in on_bar
