"""PLTR SMA Crossover Strategy v1 (10m).

SMA 10/30 crossover with RSI filter.
Volume confirmation slightly relaxed for 10m bars (1.0x avg instead of 1.2x).
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR SMA Cross"
    version = "v1"
    description = "SMA 10/30 crossover with RSI filter and volume confirmation (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "sma", "params": {"length": 10}, "var": "fast_sma"},
        {"name": "sma", "params": {"length": 30}, "var": "slow_sma"},
        {"name": "rsi", "params": {"length": 14}, "var": "rsi_val"},
    ]
    pine_conditions = {
        "long_entry": "ta.crossover(fast_sma, slow_sma) and rsi_val < 70",
        "short_entry": "ta.crossunder(fast_sma, slow_sma) and rsi_val > 30",
        "long_exit": "ta.crossunder(fast_sma, slow_sma) or rsi_val > 80",
        "short_exit": "ta.crossover(fast_sma, slow_sma) or rsi_val < 20",
    }

    def __init__(self, params=None):
        defaults = {
            "fast_period": 10,
            "slow_period": 30,
            "rsi_length": 14,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "rsi_exit_ob": 80,
            "rsi_exit_os": 20,
            "stop_loss_pct": 0.015,
            "take_profit_pct": 0.03,
            "volume_mult": 1.0,
            "volume_lookback": 20,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "sma", length=self.params["fast_period"])
        df = Indicators.add(df, "sma", length=self.params["slow_period"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        lb = self.params["volume_lookback"]
        df[f"VOL_SMA_{lb}"] = df["volume"].rolling(window=lb).mean()
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        fast_col = f"SMA_{self.params['fast_period']}"
        slow_col = f"SMA_{self.params['slow_period']}"
        rsi_col = f"RSI_{self.params['rsi_length']}"
        vol_col = f"VOL_SMA_{self.params['volume_lookback']}"

        if pd.isna(row.get(slow_col)) or pd.isna(row.get(rsi_col)):
            return None

        fast = row[fast_col]
        slow = row[slow_col]
        rsi = row[rsi_col]
        close = row["close"]
        volume = row["volume"]
        avg_volume = row.get(vol_col, 0)

        if not hasattr(self, "_prev_fast"):
            self._prev_fast = fast
            self._prev_slow = slow
            return None

        cross_above = self._prev_fast <= self._prev_slow and fast > slow
        cross_below = self._prev_fast >= self._prev_slow and fast < slow

        self._prev_fast = fast
        self._prev_slow = slow

        vol_ok = avg_volume > 0 and volume >= avg_volume * self.params["volume_mult"]

        if position is None and cross_above and rsi < self.params["rsi_overbought"] and vol_ok:
            return Signal(
                direction="long",
                stop_loss=close * (1 - self.params["stop_loss_pct"]),
                take_profit=close * (1 + self.params["take_profit_pct"]),
                reason=f"SMA bullish cross, RSI {rsi:.0f}"
            )

        if position is None and cross_below and rsi > self.params["rsi_oversold"] and vol_ok:
            return Signal(
                direction="short",
                stop_loss=close * (1 + self.params["stop_loss_pct"]),
                take_profit=close * (1 - self.params["take_profit_pct"]),
                reason=f"SMA bearish cross, RSI {rsi:.0f}"
            )

        if position is not None and position.direction == "long":
            if cross_below or rsi > self.params["rsi_exit_ob"]:
                return Signal(direction="close_long", reason=f"SMA bearish cross or RSI {rsi:.0f}")

        if position is not None and position.direction == "short":
            if cross_above or rsi < self.params["rsi_exit_os"]:
                return Signal(direction="close_short", reason=f"SMA bullish cross or RSI {rsi:.0f}")

        return None
