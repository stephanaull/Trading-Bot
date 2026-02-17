"""PLTR Overbought Reversal Strategy v1 (10m).

Shorts overbought conditions when momentum fades.
RSI(7) > 75 + upper Bollinger Band touch + bearish candle.
ATR-based stops. 10m bars give cleaner signals than 5m.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR Overbought Reversal"
    version = "v1"
    description = "Short overbought: RSI > 75 + BB upper + bearish candle (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "rsi", "params": {"length": 7}, "var": "rsi_fast"},
        {"name": "bbands", "params": {"length": 20, "std": 2}, "var": "bb"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "short_entry": "rsi_fast > 75 and high > bb_upper and close < open",
        "short_exit": "rsi_fast < 50",
    }

    def __init__(self, params=None):
        defaults = {
            "rsi_length": 7,
            "rsi_overbought": 75,
            "rsi_exit": 50,
            "bb_length": 20,
            "bb_std": 2.0,
            "atr_length": 14,
            "atr_stop_mult": 2.0,
            "atr_target_mult": 3.0,
            "require_bearish_candle": True,
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
        bbu_col = f"BBU_{self.params['bb_length']}_{self.params['bb_std']}"
        atr_col = f"ATR_{self.params['atr_length']}"

        if pd.isna(row.get(rsi_col)) or pd.isna(row.get(bbu_col)) or pd.isna(row.get(atr_col)):
            return None

        rsi = row[rsi_col]
        bb_upper = row[bbu_col]
        atr = row[atr_col]
        close = row["close"]
        open_price = row["open"]
        high = row["high"]

        if position is None:
            is_overbought = rsi > self.params["rsi_overbought"]
            touched_bb = high >= bb_upper if self.params["require_bb_touch"] else True
            is_bearish = close < open_price if self.params["require_bearish_candle"] else True

            if is_overbought and touched_bb and is_bearish:
                stop = close + (atr * self.params["atr_stop_mult"])
                target = close - (atr * self.params["atr_target_mult"])
                return Signal(
                    direction="short",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"OB reversal: RSI {rsi:.0f}, high {high:.2f} >= BB {bb_upper:.2f}"
                )

        if position is not None and position.direction == "short":
            if rsi < self.params["rsi_exit"]:
                return Signal(direction="close_short",
                              reason=f"RSI neutral ({rsi:.0f})")
            if close > bb_upper:
                return Signal(direction="close_short",
                              reason=f"Price above BB upper ({close:.2f})")

        return None
