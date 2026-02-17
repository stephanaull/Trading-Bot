"""Example strategy: RSI Mean Reversion.

Buys when RSI is oversold (< 30), sells when overbought (> 70).
Includes EMA trend filter: only takes longs above 200 EMA.
Uses stop-loss and take-profit.
"""

from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "RSI Mean Reversion"
    version = "v1"
    description = "Buy RSI oversold with EMA trend filter, sell RSI overbought"
    ticker = ""
    timeframe = "1d"

    pine_indicators = [
        {"name": "rsi", "params": {"length": 14}, "var": "rsi_val"},
        {"name": "ema", "params": {"length": 200}, "var": "trend_ema"},
    ]
    pine_conditions = {
        "long_entry": "rsi_val < 30 and close > trend_ema",
        "long_exit": "rsi_val > 70",
    }

    def __init__(self, params=None):
        defaults = {
            "rsi_length": 14,
            "oversold": 30,
            "overbought": 70,
            "trend_ema_length": 200,
            "stop_loss_pct": 0.05,
            "take_profit_pct": 0.10,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "ema", length=self.params["trend_ema_length"])
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        rsi_col = f"RSI_{self.params['rsi_length']}"
        ema_col = f"EMA_{self.params['trend_ema_length']}"

        if pd.isna(row.get(rsi_col)) or pd.isna(row.get(ema_col)):
            return None

        rsi = row[rsi_col]
        ema = row[ema_col]
        close = row["close"]

        # Entry: RSI oversold AND price above trend EMA (bullish bias)
        if position is None and rsi < self.params["oversold"] and close > ema:
            return Signal(
                direction="long",
                stop_loss=close * (1 - self.params["stop_loss_pct"]),
                take_profit=close * (1 + self.params["take_profit_pct"]),
                reason=f"RSI oversold ({rsi:.1f}) above EMA {self.params['trend_ema_length']}"
            )

        # Exit: RSI overbought
        if position is not None and rsi > self.params["overbought"]:
            return Signal(
                direction="close_long",
                reason=f"RSI overbought ({rsi:.1f})"
            )

        return None
