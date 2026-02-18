"""Daily Single Trade [SMRT Algo] - Opening Range Breakout Strategy.

Replicates the TradingView "Daily Single Trade [SMRT Algo]" indicator:
- At market open, captures the high and low of the first candle
- Goes LONG if price breaks above first candle high
- Goes SHORT if price breaks below first candle low
- One trade per day maximum
- Fixed R:R based stop/target from the breakout level
- No indicators — pure price action

Originally by SMRTAlgo on TradingView, re-implemented for backtesting.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal


class Strategy(BaseStrategy):
    name = "Daily Single Trade (SMRT Algo)"
    version = "v1"
    description = "Opening range breakout: first candle H/L, one trade per day, fixed R:R"
    ticker = "ANY"
    timeframe = "5m"

    pine_indicators = []  # No indicators — pure price action
    pine_conditions = {
        "long_entry": "close > candle1High and not tradeExecuted",
        "short_entry": "close < candle1Low and not tradeExecuted",
    }

    def __init__(self, params=None):
        defaults = {
            "pip_offset": 0.0,      # Offset value for SL (matches Pine 'Pip' input)
            "rr_ratio": 2,          # Risk-reward ratio (default 2:1)
            # Open candle detection: provide a list of (hour, minute) candidates
            # The strategy will use the FIRST bar of each day that matches any of these
            # NYSE 9:30 AM ET = 14:30 UTC or 09:30 local
            "open_times": [(14, 30), (9, 30)],
            # Session end — close any open position after this time
            "session_end_hour": 20,   # 20:00 UTC = 4:00 PM ET
            "session_end_minute": 0,
            "use_session_end": True,
        }
        super().__init__({**defaults, **(params or {})})

        # State tracking (reset each day)
        self._candle1_high = None
        self._candle1_low = None
        self._trade_executed_today = False
        self._current_day = None
        self._found_open_candle = False
        self._open_candle_bar_idx = None

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        """No indicators needed — pure price action strategy."""
        return df

    def _get_day(self, ts):
        """Get the day for tracking one-trade-per-day."""
        if hasattr(ts, 'date'):
            return ts.date()
        return ts

    def _is_open_candle(self, ts) -> bool:
        """Check if this bar matches any of the configured open times."""
        if not hasattr(ts, 'hour'):
            return False
        h, m = ts.hour, ts.minute
        for target_h, target_m in self.params["open_times"]:
            if h == target_h and m == target_m:
                return True
        return False

    def _is_weekend(self, ts) -> bool:
        """Check if the day is Saturday or Sunday."""
        if hasattr(ts, 'weekday'):
            return ts.weekday() >= 5
        return False

    def _past_session_end(self, ts) -> bool:
        """Check if we're past the session end time."""
        if not self.params.get("use_session_end", False):
            return False
        if not hasattr(ts, 'hour'):
            return False
        h, m = ts.hour, ts.minute
        end_h = self.params["session_end_hour"]
        end_m = self.params["session_end_minute"]
        return (h * 60 + m) >= (end_h * 60 + end_m)

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        ts = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)

        # Skip weekends
        if self._is_weekend(ts):
            return None

        # Detect new day — reset state
        current_day = self._get_day(ts)
        if current_day != self._current_day:
            self._current_day = current_day
            self._trade_executed_today = False
            self._candle1_high = None
            self._candle1_low = None
            self._found_open_candle = False
            self._open_candle_bar_idx = None

        close = row["close"]
        high = row["high"]
        low = row["low"]

        # End of session — close any open position
        if self._past_session_end(ts) and position is not None:
            if position.direction == "long":
                return Signal(direction="close_long", reason="End of session")
            else:
                return Signal(direction="close_short", reason="End of session")

        # Step 1: Capture the open candle's high/low (first match per day)
        if self._is_open_candle(ts) and not self._found_open_candle and not self._trade_executed_today:
            self._candle1_high = high
            self._candle1_low = low
            self._found_open_candle = True
            self._open_candle_bar_idx = idx
            return None  # Don't trade on the open candle itself

        # Step 2: After open candle, look for breakout (only one trade per day)
        if (self._found_open_candle and
                not self._trade_executed_today and
                self._candle1_high is not None and
                idx > (self._open_candle_bar_idx or 0)):

            pip = self.params["pip_offset"]
            rr = self.params["rr_ratio"]

            # LONG breakout: close > first candle high
            if close > self._candle1_high:
                stop_loss = self._candle1_low - pip
                risk = close - stop_loss
                if risk <= 0:
                    return None
                take_profit = close + risk * rr

                self._trade_executed_today = True
                return Signal(
                    direction="long",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    reason=f"ORB Long: break {self._candle1_high:.2f}, SL {stop_loss:.2f}, TP {take_profit:.2f}"
                )

            # SHORT breakout: close < first candle low
            if close < self._candle1_low:
                stop_loss = self._candle1_high + pip
                risk = stop_loss - close
                if risk <= 0:
                    return None
                take_profit = close - risk * rr

                self._trade_executed_today = True
                return Signal(
                    direction="short",
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    reason=f"ORB Short: break {self._candle1_low:.2f}, SL {stop_loss:.2f}, TP {take_profit:.2f}"
                )

        # No additional exit signals — the broker handles SL/TP fills
        return None
