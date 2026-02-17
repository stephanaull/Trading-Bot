"""PLTR Oversold Reversal Strategy v1 (10m).

Buys oversold bounces when buying pressure emerges.
RSI(7) < 25 + lower Bollinger Band touch + bullish candle.
ATR-based stops. 10m bars give cleaner signals than 5m.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR Oversold Reversal"
    version = "v1"
    description = "Long oversold: RSI < 25 + BB lower + bullish candle (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "rsi", "params": {"length": 7}, "var": "rsi_fast"},
        {"name": "bbands", "params": {"length": 20, "std": 2}, "var": "bb"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "rsi_fast < 25 and low < bb_lower and close > open",
        "long_exit": "rsi_fast > 50",
    }

    def __init__(self, params=None):
        defaults = {
            "rsi_length": 7,
            "rsi_oversold": 25,
            "rsi_exit": 50,
            "bb_length": 20,
            "bb_std": 2.0,
            "atr_length": 14,
            "atr_stop_mult": 2.0,
            "atr_target_mult": 3.0,
            "require_bullish_candle": True,
            "require_bb_touch": True,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "bbands", length=self.params["bb_length"],
                            std=self.params["bb_std"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        rsi_col = f"RSI_{self.params['rsi_length']}"
        bbl_col = f"BBL_{self.params['bb_length']}_{self.params['bb_std']}"
        atr_col = f"ATR_{self.params['atr_length']}"

        if pd.isna(row.get(rsi_col)) or pd.isna(row.get(bbl_col)) or pd.isna(row.get(atr_col)):
            return None

        rsi = row[rsi_col]
        bb_lower = row[bbl_col]
        atr = row[atr_col]
        close = row["close"]
        open_price = row["open"]
        low = row["low"]

        if position is None:
            is_oversold = rsi < self.params["rsi_oversold"]
            touched_bb = low <= bb_lower if self.params["require_bb_touch"] else True
            is_bullish = close > open_price if self.params["require_bullish_candle"] else True

            if is_oversold and touched_bb and is_bullish:
                stop = close - (atr * self.params["atr_stop_mult"])
                target = close + (atr * self.params["atr_target_mult"])
                return Signal(
                    direction="long",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"OS reversal: RSI {rsi:.0f}, low {low:.2f} <= BB {bb_lower:.2f}"
                )

        if position is not None and position.direction == "long":
            if rsi > self.params["rsi_exit"]:
                return Signal(direction="close_long",
                              reason=f"RSI neutral ({rsi:.0f})")
            if close < bb_lower:
                return Signal(direction="close_long",
                              reason=f"Price below BB lower ({close:.2f})")

        return None
