"""MSTR Stochastic RSI + EMA Strategy v1 (5m).

Combines Stochastic oscillator with RSI and EMA trend for
high-probability entries in both directions. Stochastic provides
overbought/oversold + crossover signals, RSI confirms momentum,
EMA confirms trend. Tight stops, 2.3x targets.

Trades long AND short aggressively.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR Stoch RSI"
    version = "v1"
    description = "Stochastic + RSI + EMA trend, tight stops 2.3x R:R (5m)"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "stoch", "params": {"k": 14, "d": 3, "smooth_k": 3}, "var": "stoch"},
        {"name": "rsi", "params": {"length": 9}, "var": "rsi_val"},
        {"name": "ema", "params": {"length": 9}, "var": "fast_ema"},
        {"name": "ema", "params": {"length": 21}, "var": "slow_ema"},
        {"name": "atr", "params": {"length": 10}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "STOCHk crosses above STOCHd and STOCHk < 30 and rsi_val > 40 and close > slow_ema",
        "short_entry": "STOCHk crosses below STOCHd and STOCHk > 70 and rsi_val < 60 and close < slow_ema",
    }

    def __init__(self, params=None):
        defaults = {
            "stoch_k": 14,
            "stoch_d": 3,
            "stoch_smooth": 3,
            "stoch_oversold": 25,
            "stoch_overbought": 75,
            "rsi_length": 9,
            "fast_ema": 9,
            "slow_ema": 21,
            "atr_length": 10,
            "atr_stop_mult": 1.0,      # Tight stop
            "atr_target_mult": 2.3,    # 2.3x R:R minimum
            "volume_lookback": 12,
            "volume_mult": 0.9,
            "session_start_hour": 14,
            "session_start_minute": 35,
            "session_end_hour": 19,
            "session_end_minute": 45,
        }
        super().__init__({**defaults, **(params or {})})
        self._prev_k = None
        self._prev_d = None

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "stoch", k=self.params["stoch_k"],
                           d=self.params["stoch_d"],
                           smooth_k=self.params["stoch_smooth"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "ema", length=self.params["fast_ema"])
        df = Indicators.add(df, "ema", length=self.params["slow_ema"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])

        lb = self.params["volume_lookback"]
        df[f"VOL_SMA_{lb}"] = df["volume"].rolling(window=lb).mean()
        return df

    def _in_session(self, ts) -> bool:
        sh = self.params["session_start_hour"]
        sm = self.params["session_start_minute"]
        eh = self.params["session_end_hour"]
        em = self.params["session_end_minute"]
        t_min = sh * 60 + sm
        t_max = eh * 60 + em
        cur = ts.hour * 60 + ts.minute
        return t_min <= cur <= t_max

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        k_col = f"STOCHk_{self.params['stoch_k']}_{self.params['stoch_d']}_{self.params['stoch_smooth']}"
        d_col = f"STOCHd_{self.params['stoch_k']}_{self.params['stoch_d']}_{self.params['stoch_smooth']}"
        rsi_col = f"RSI_{self.params['rsi_length']}"
        fast_col = f"EMA_{self.params['fast_ema']}"
        slow_col = f"EMA_{self.params['slow_ema']}"
        atr_col = f"ATR_{self.params['atr_length']}"
        vol_col = f"VOL_SMA_{self.params['volume_lookback']}"

        if pd.isna(row.get(k_col)) or pd.isna(row.get(atr_col)) or pd.isna(row.get(slow_col)):
            return None

        ts = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)

        if not self._in_session(ts):
            if position is not None:
                direction = "close_long" if position.direction == "long" else "close_short"
                return Signal(direction=direction, reason="End of session")
            return None

        k = row[k_col]
        d = row[d_col]
        rsi = row[rsi_col]
        fast = row[fast_col]
        slow = row[slow_col]
        atr = row[atr_col]
        close = row["close"]
        volume = row["volume"]
        avg_vol = row.get(vol_col, 0)

        if atr <= 0:
            return None

        # Detect stoch crossovers
        k_crossed_up = self._prev_k is not None and self._prev_d is not None \
                        and self._prev_k <= self._prev_d and k > d
        k_crossed_down = self._prev_k is not None and self._prev_d is not None \
                          and self._prev_k >= self._prev_d and k < d
        self._prev_k = k
        self._prev_d = d

        vol_ok = avg_vol > 0 and volume >= avg_vol * self.params["volume_mult"]
        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        if position is None:
            # === LONG: Stoch crosses up from oversold, RSI bullish, EMA trend up ===
            if k_crossed_up and k < self.params["stoch_overbought"]:
                was_oversold = self._prev_k is not None and k < 40  # recently oversold zone
                trend_up = close > slow  # or fast > slow
                rsi_ok = rsi > 40 and rsi < 75

                if trend_up and rsi_ok and vol_ok:
                    stop = close - stop_dist
                    target = close + target_dist
                    return Signal(
                        direction="long",
                        stop_loss=stop,
                        take_profit=target,
                        reason=f"Stoch cross up K={k:.0f}, RSI {rsi:.0f}"
                    )

            # === SHORT: Stoch crosses down from overbought, RSI bearish, EMA trend down ===
            if k_crossed_down and k > self.params["stoch_oversold"]:
                was_overbought = k > 60
                trend_down = close < slow
                rsi_ok = rsi < 60 and rsi > 25

                if trend_down and rsi_ok and vol_ok:
                    stop = close + stop_dist
                    target = close - target_dist
                    return Signal(
                        direction="short",
                        stop_loss=stop,
                        take_profit=target,
                        reason=f"Stoch cross down K={k:.0f}, RSI {rsi:.0f}"
                    )

        # Exit on extreme stoch
        if position is not None:
            if position.direction == "long" and k_crossed_down and k > 80:
                return Signal(direction="close_long", reason=f"Stoch overbought cross down K={k:.0f}")
            if position.direction == "short" and k_crossed_up and k < 20:
                return Signal(direction="close_short", reason=f"Stoch oversold cross up K={k:.0f}")

        return None
