"""MSTR Oversold Reversal Strategy v1.

Detects oversold conditions and enters LONG when buying pressure emerges.
Multi-confirmation approach:
1. RSI < 25 (oversold)
2. Price touches or dips below lower Bollinger Band
3. Bullish candle confirmation (close > open = green candle)
4. Optional: volume spike confirms capitulation/reversal

Exits on RSI recovering to neutral (> 50) or stop-loss hit.
ATR-based stops for volatility adaptation.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR Oversold Reversal"
    version = "v1"
    description = "Long oversold reversals: RSI < 25 + BB lower touch + bullish candle"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "rsi", "params": {"length": 7}, "var": "rsi_fast"},
        {"name": "bbands", "params": {"length": 20, "std": 2}, "var": "bb"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
        {"name": "ema", "params": {"length": 50}, "var": "trend_ema"},
    ]
    pine_conditions = {
        "long_entry": "rsi_fast < 25 and low < bb_lower and close > open",
        "long_exit": "rsi_fast > 50",
    }

    def __init__(self, params=None):
        defaults = {
            "rsi_length": 7,            # Fast RSI for quicker OS detection
            "rsi_oversold": 25,
            "rsi_exit": 50,             # Exit when RSI returns to neutral
            "rsi_deep_exit": 70,        # Take profit when RSI reaches overbought
            "bb_length": 20,
            "bb_std": 2.0,
            "atr_length": 14,
            "atr_stop_mult": 2.0,       # Stop at 2x ATR below entry
            "atr_target_mult": 3.0,     # Target at 3x ATR above entry
            "require_bullish_candle": True,
            "require_bb_touch": True,
            "volume_spike_mult": 1.5,   # Volume must be 1.5x average
            "volume_lookback": 20,
            "require_volume_spike": False,  # Optional volume filter
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "bbands", length=self.params["bb_length"],
                            std=self.params["bb_std"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        df = Indicators.add(df, "ema", length=50)

        # Volume moving average for spike detection
        lb = self.params["volume_lookback"]
        df[f"VOL_SMA_{lb}"] = df["volume"].rolling(window=lb).mean()

        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        rsi_col = f"RSI_{self.params['rsi_length']}"
        bbl_col = f"BBL_{self.params['bb_length']}_{self.params['bb_std']}"
        bbm_col = f"BBM_{self.params['bb_length']}_{self.params['bb_std']}"
        atr_col = f"ATR_{self.params['atr_length']}"
        vol_col = f"VOL_SMA_{self.params['volume_lookback']}"

        if pd.isna(row.get(rsi_col)) or pd.isna(row.get(bbl_col)) or pd.isna(row.get(atr_col)):
            return None

        rsi = row[rsi_col]
        bb_lower = row[bbl_col]
        bb_mid = row[bbm_col]
        atr = row[atr_col]
        close = row["close"]
        open_price = row["open"]
        low = row["low"]
        volume = row["volume"]
        avg_volume = row.get(vol_col, 0)

        # ── ENTRY: Long oversold reversal ──
        if position is None:
            # Condition 1: RSI oversold
            is_oversold = rsi < self.params["rsi_oversold"]

            # Condition 2: Price touched lower Bollinger Band
            touched_bb = low <= bb_lower if self.params["require_bb_touch"] else True

            # Condition 3: Bullish candle (close > open = buyers stepping in)
            is_bullish = close > open_price if self.params["require_bullish_candle"] else True

            # Condition 4 (optional): Volume spike = capitulation
            if self.params["require_volume_spike"]:
                vol_ok = avg_volume > 0 and volume > avg_volume * self.params["volume_spike_mult"]
            else:
                vol_ok = True

            if is_oversold and touched_bb and is_bullish and vol_ok:
                stop = close - (atr * self.params["atr_stop_mult"])
                target = close + (atr * self.params["atr_target_mult"])
                return Signal(
                    direction="long",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"OS reversal: RSI {rsi:.0f}, low {low:.2f} <= BB {bb_lower:.2f}, bullish candle"
                )

        # ── EXIT: RSI returns to neutral or reversal fails ──
        if position is not None and position.direction == "long":
            # Exit when RSI rises to neutral (momentum recovered)
            if rsi > self.params["rsi_exit"]:
                return Signal(
                    direction="close_long",
                    reason=f"RSI returned to neutral ({rsi:.0f} > {self.params['rsi_exit']})"
                )

            # Also exit if price falls below BB lower again (reversal failed)
            if close < bb_lower:
                return Signal(
                    direction="close_long",
                    reason=f"Price broke below BB lower again ({close:.2f} < {bb_lower:.2f})"
                )

        return None
