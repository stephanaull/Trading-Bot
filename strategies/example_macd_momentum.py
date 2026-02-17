"""Example strategy: MACD Momentum.

Goes long when MACD histogram turns positive (momentum shift).
Exits when histogram turns negative.
Uses ATR-based stop-loss for volatility-adjusted risk management.
"""

from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MACD Momentum"
    version = "v1"
    description = "Long on MACD histogram positive crossover, ATR-based stops"
    ticker = ""
    timeframe = "1d"

    pine_indicators = [
        {"name": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}, "var": "macd"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "ta.crossover(macd_hist, 0)",
        "long_exit": "ta.crossunder(macd_hist, 0)",
    }

    def __init__(self, params=None):
        defaults = {
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "atr_length": 14,
            "atr_stop_mult": 2.0,    # Stop at 2x ATR below entry
            "atr_target_mult": 3.0,  # Target at 3x ATR above entry
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "macd",
                            fast=self.params["macd_fast"],
                            slow=self.params["macd_slow"],
                            signal=self.params["macd_signal"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        f, s, sig = self.params["macd_fast"], self.params["macd_slow"], self.params["macd_signal"]
        hist_col = f"MACDh_{f}_{s}_{sig}"
        atr_col = f"ATR_{self.params['atr_length']}"

        if pd.isna(row.get(hist_col)) or pd.isna(row.get(atr_col)):
            return None

        histogram = row[hist_col]
        atr = row[atr_col]
        close = row["close"]

        # Track previous histogram for crossover detection
        if not hasattr(self, "_prev_hist"):
            self._prev_hist = histogram
            return None

        prev_hist = self._prev_hist
        self._prev_hist = histogram

        # Entry: histogram crosses above zero (momentum turns bullish)
        if position is None and prev_hist <= 0 and histogram > 0:
            stop = close - (atr * self.params["atr_stop_mult"])
            target = close + (atr * self.params["atr_target_mult"])
            return Signal(
                direction="long",
                stop_loss=stop,
                take_profit=target,
                reason=f"MACD histogram crossed above zero (hist: {histogram:.4f})"
            )

        # Exit: histogram crosses below zero (momentum turns bearish)
        if position is not None and prev_hist >= 0 and histogram < 0:
            return Signal(
                direction="close_long",
                reason=f"MACD histogram crossed below zero (hist: {histogram:.4f})"
            )

        return None
