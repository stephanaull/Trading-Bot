"""PLTR EMA Scalping Strategy v1 (10m).

Fast EMA 8/21 crossover with EMA 50 trend filter.
Adapted for 10-minute bars -- slightly slower EMAs than 5m version.
ATR-based dynamic stops.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR EMA Scalp"
    version = "v1"
    description = "EMA 8/21 crossover with EMA 50 trend filter, ATR stops (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "ema", "params": {"length": 8}, "var": "fast_ema"},
        {"name": "ema", "params": {"length": 21}, "var": "mid_ema"},
        {"name": "ema", "params": {"length": 50}, "var": "trend_ema"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "ta.crossover(fast_ema, mid_ema) and close > trend_ema",
        "short_entry": "ta.crossunder(fast_ema, mid_ema) and close < trend_ema",
        "long_exit": "ta.crossunder(fast_ema, mid_ema)",
        "short_exit": "ta.crossover(fast_ema, mid_ema)",
    }

    def __init__(self, params=None):
        defaults = {
            "fast_period": 8,
            "mid_period": 21,
            "trend_period": 50,
            "atr_length": 14,
            "atr_stop_mult": 1.5,
            "atr_target_mult": 2.5,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "ema", length=self.params["fast_period"])
        df = Indicators.add(df, "ema", length=self.params["mid_period"])
        df = Indicators.add(df, "ema", length=self.params["trend_period"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        fast_col = f"EMA_{self.params['fast_period']}"
        mid_col = f"EMA_{self.params['mid_period']}"
        trend_col = f"EMA_{self.params['trend_period']}"
        atr_col = f"ATR_{self.params['atr_length']}"

        if pd.isna(row.get(trend_col)) or pd.isna(row.get(atr_col)):
            return None

        fast = row[fast_col]
        mid = row[mid_col]
        trend = row[trend_col]
        atr = row[atr_col]
        close = row["close"]

        if not hasattr(self, "_prev_fast"):
            self._prev_fast = fast
            self._prev_mid = mid
            return None

        cross_above = self._prev_fast <= self._prev_mid and fast > mid
        cross_below = self._prev_fast >= self._prev_mid and fast < mid

        self._prev_fast = fast
        self._prev_mid = mid

        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        if position is None and cross_above and close > trend:
            return Signal(
                direction="long",
                stop_loss=close - stop_dist,
                take_profit=close + target_dist,
                reason=f"EMA bullish cross above trend"
            )

        if position is None and cross_below and close < trend:
            return Signal(
                direction="short",
                stop_loss=close + stop_dist,
                take_profit=close - target_dist,
                reason=f"EMA bearish cross below trend"
            )

        if position is not None and position.direction == "long" and cross_below:
            return Signal(direction="close_long", reason="EMA bearish crossunder")

        if position is not None and position.direction == "short" and cross_above:
            return Signal(direction="close_short", reason="EMA bullish crossover")

        return None
