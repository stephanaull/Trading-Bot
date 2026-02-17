"""Example strategy: EMA Crossover.

Goes long when fast EMA crosses above slow EMA.
Exits when fast EMA crosses below slow EMA.
Includes stop-loss and take-profit.
"""

from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "EMA Crossover"
    version = "v1"
    description = "Long when fast EMA crosses above slow EMA, exit on cross below"
    ticker = ""
    timeframe = "1d"

    pine_indicators = [
        {"name": "ema", "params": {"length": 9}, "var": "fast_ema"},
        {"name": "ema", "params": {"length": 21}, "var": "slow_ema"},
    ]
    pine_conditions = {
        "long_entry": "ta.crossover(fast_ema, slow_ema)",
        "long_exit": "ta.crossunder(fast_ema, slow_ema)",
    }

    def __init__(self, params=None):
        defaults = {
            "fast_period": 9,
            "slow_period": 21,
            "stop_loss_pct": 0.03,    # 3% stop-loss
            "take_profit_pct": 0.06,  # 6% take-profit
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "ema", length=self.params["fast_period"])
        df = Indicators.add(df, "ema", length=self.params["slow_period"])
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        fast_col = f"EMA_{self.params['fast_period']}"
        slow_col = f"EMA_{self.params['slow_period']}"

        # Skip if indicators not yet computed (NaN)
        if pd.isna(row.get(fast_col)) or pd.isna(row.get(slow_col)):
            return None

        fast_ema = row[fast_col]
        slow_ema = row[slow_col]
        close = row["close"]

        # Need previous bar data for crossover detection
        if idx < 1:
            return None

        # Store current values for crossover detection
        # We use a simple comparison since we process bar-by-bar
        if not hasattr(self, "_prev_fast"):
            self._prev_fast = fast_ema
            self._prev_slow = slow_ema
            return None

        # Detect crossover
        cross_above = self._prev_fast <= self._prev_slow and fast_ema > slow_ema
        cross_below = self._prev_fast >= self._prev_slow and fast_ema < slow_ema

        # Update previous values
        self._prev_fast = fast_ema
        self._prev_slow = slow_ema

        # Entry: fast EMA crosses above slow EMA (go long)
        if position is None and cross_above:
            return Signal(
                direction="long",
                stop_loss=close * (1 - self.params["stop_loss_pct"]),
                take_profit=close * (1 + self.params["take_profit_pct"]),
                reason=f"EMA crossover: {fast_col} crossed above {slow_col}"
            )

        # Exit: fast EMA crosses below slow EMA
        if position is not None and cross_below:
            return Signal(
                direction="close_long",
                reason=f"EMA crossunder: {fast_col} crossed below {slow_col}"
            )

        return None
