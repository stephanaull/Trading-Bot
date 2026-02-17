"""MSTR Overbought Reversal Strategy v1.

Detects overbought conditions and enters SHORT when momentum fades.
Multi-confirmation approach:
1. RSI > 75 (overbought)
2. Price touches or exceeds upper Bollinger Band
3. Bearish candle confirmation (close < open = red candle)

Exits on RSI returning to neutral (< 50) or stop-loss hit.
ATR-based stops for volatility adaptation.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR Overbought Reversal"
    version = "v1"
    description = "Short overbought reversals: RSI > 75 + BB upper touch + bearish candle"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "rsi", "params": {"length": 7}, "var": "rsi_fast"},
        {"name": "bbands", "params": {"length": 20, "std": 2}, "var": "bb"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
        {"name": "ema", "params": {"length": 50}, "var": "trend_ema"},
    ]
    pine_conditions = {
        "short_entry": "rsi_fast > 75 and high > bb_upper and close < open",
        "short_exit": "rsi_fast < 50",
    }

    def __init__(self, params=None):
        defaults = {
            "rsi_length": 7,            # Fast RSI for quicker OB detection
            "rsi_overbought": 75,
            "rsi_exit": 50,             # Exit when RSI returns to neutral
            "rsi_deep_exit": 30,        # Take profit when RSI reaches oversold
            "bb_length": 20,
            "bb_std": 2.0,
            "atr_length": 14,
            "atr_stop_mult": 2.0,       # Stop at 2x ATR above entry
            "atr_target_mult": 3.0,     # Target at 3x ATR below entry
            "require_bearish_candle": True,
            "require_bb_touch": True,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "bbands", length=self.params["bb_length"],
                            std=self.params["bb_std"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        df = Indicators.add(df, "ema", length=50)
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        rsi_col = f"RSI_{self.params['rsi_length']}"
        bbu_col = f"BBU_{self.params['bb_length']}_{self.params['bb_std']}"
        bbm_col = f"BBM_{self.params['bb_length']}_{self.params['bb_std']}"
        atr_col = f"ATR_{self.params['atr_length']}"

        if pd.isna(row.get(rsi_col)) or pd.isna(row.get(bbu_col)) or pd.isna(row.get(atr_col)):
            return None

        rsi = row[rsi_col]
        bb_upper = row[bbu_col]
        bb_mid = row[bbm_col]
        atr = row[atr_col]
        close = row["close"]
        open_price = row["open"]
        high = row["high"]

        # ── ENTRY: Short overbought reversal ──
        if position is None:
            # Condition 1: RSI overbought
            is_overbought = rsi > self.params["rsi_overbought"]

            # Condition 2: Price touched upper Bollinger Band
            touched_bb = high >= bb_upper if self.params["require_bb_touch"] else True

            # Condition 3: Bearish candle (close < open = sellers stepping in)
            is_bearish = close < open_price if self.params["require_bearish_candle"] else True

            if is_overbought and touched_bb and is_bearish:
                stop = close + (atr * self.params["atr_stop_mult"])
                target = close - (atr * self.params["atr_target_mult"])
                return Signal(
                    direction="short",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"OB reversal: RSI {rsi:.0f}, high {high:.2f} >= BB {bb_upper:.2f}, bearish candle"
                )

        # ── EXIT: RSI returns to neutral or target zone ──
        if position is not None and position.direction == "short":
            # Exit when RSI drops to neutral (momentum exhausted)
            if rsi < self.params["rsi_exit"]:
                return Signal(
                    direction="close_short",
                    reason=f"RSI returned to neutral ({rsi:.0f} < {self.params['rsi_exit']})"
                )

            # Also exit if price crosses back above BB middle (reversal failed)
            if close > bb_upper:
                return Signal(
                    direction="close_short",
                    reason=f"Price broke above BB upper again ({close:.2f} > {bb_upper:.2f})"
                )

        return None
