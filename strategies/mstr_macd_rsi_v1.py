"""MSTR MACD + RSI Divergence Strategy v1 (5m).

MACD histogram momentum with RSI confirmation and EMA trend filter.
Enters on MACD histogram crossover (zero or signal), confirmed by
RSI direction and EMA alignment. Tight stops with 2.3x+ targets.

Designed for aggressive momentum capture on high-volatility stocks.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR MACD RSI Momentum"
    version = "v1"
    description = "MACD histogram + RSI momentum + EMA trend, 1x ATR stop / 2.5x target (5m)"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "macd", "params": {"fast": 8, "slow": 21, "signal": 5}, "var": "macd"},
        {"name": "rsi", "params": {"length": 9}, "var": "rsi_val"},
        {"name": "ema", "params": {"length": 13}, "var": "fast_ema"},
        {"name": "ema", "params": {"length": 34}, "var": "slow_ema"},
        {"name": "atr", "params": {"length": 10}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "MACDh > 0 and MACDh > MACDh[1] and rsi_val > 50 and close > fast_ema",
        "short_entry": "MACDh < 0 and MACDh < MACDh[1] and rsi_val < 50 and close < fast_ema",
    }

    def __init__(self, params=None):
        defaults = {
            "macd_fast": 8,
            "macd_slow": 21,
            "macd_signal": 5,
            "rsi_length": 9,
            "fast_ema": 13,
            "slow_ema": 34,
            "atr_length": 10,
            "atr_stop_mult": 1.0,     # Tight stop
            "atr_target_mult": 2.5,   # 2.5x R:R
            "volume_lookback": 12,
            "volume_mult": 0.9,       # Slight volume filter
            "session_start_hour": 14,
            "session_start_minute": 35,
            "session_end_hour": 19,
            "session_end_minute": 45,
        }
        super().__init__({**defaults, **(params or {})})
        self._prev_hist = None

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "macd", fast=self.params["macd_fast"],
                           slow=self.params["macd_slow"],
                           signal=self.params["macd_signal"])
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
        f, s, sg = self.params["macd_fast"], self.params["macd_slow"], self.params["macd_signal"]
        hist_col = f"MACDh_{f}_{s}_{sg}"
        macd_col = f"MACD_{f}_{s}_{sg}"
        signal_col = f"MACDs_{f}_{s}_{sg}"
        rsi_col = f"RSI_{self.params['rsi_length']}"
        fast_col = f"EMA_{self.params['fast_ema']}"
        slow_col = f"EMA_{self.params['slow_ema']}"
        atr_col = f"ATR_{self.params['atr_length']}"
        vol_col = f"VOL_SMA_{self.params['volume_lookback']}"

        if pd.isna(row.get(hist_col)) or pd.isna(row.get(atr_col)) or pd.isna(row.get(slow_col)):
            return None

        ts = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)

        if not self._in_session(ts):
            if position is not None:
                direction = "close_long" if position.direction == "long" else "close_short"
                return Signal(direction=direction, reason="End of session")
            return None

        hist = row[hist_col]
        macd_val = row[macd_col]
        rsi = row[rsi_col]
        fast_ema = row[fast_col]
        slow_ema = row[slow_col]
        atr = row[atr_col]
        close = row["close"]
        open_p = row["open"]
        volume = row["volume"]
        avg_vol = row.get(vol_col, 0)

        if atr <= 0:
            return None

        # Track histogram direction
        hist_rising = self._prev_hist is not None and hist > self._prev_hist
        hist_falling = self._prev_hist is not None and hist < self._prev_hist
        hist_crossed_up = self._prev_hist is not None and self._prev_hist <= 0 and hist > 0
        hist_crossed_down = self._prev_hist is not None and self._prev_hist >= 0 and hist < 0
        self._prev_hist = hist

        vol_ok = avg_vol > 0 and volume >= avg_vol * self.params["volume_mult"]
        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        if position is None:
            # === LONG ===
            # MACD histogram positive and rising (or just crossed zero)
            # RSI > 50 (bullish momentum)
            # Price above fast EMA (short-term uptrend)
            # Fast EMA > Slow EMA (medium-term uptrend)
            macd_bull = (hist > 0 and hist_rising) or hist_crossed_up
            trend_bull = close > fast_ema and fast_ema > slow_ema
            rsi_bull = rsi > 50

            if macd_bull and trend_bull and rsi_bull and vol_ok:
                stop = close - stop_dist
                target = close + target_dist
                return Signal(
                    direction="long",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"MACD bull hist, RSI {rsi:.0f}, EMA aligned"
                )

            # === SHORT ===
            macd_bear = (hist < 0 and hist_falling) or hist_crossed_down
            trend_bear = close < fast_ema and fast_ema < slow_ema
            rsi_bear = rsi < 50

            if macd_bear and trend_bear and rsi_bear and vol_ok:
                stop = close + stop_dist
                target = close - target_dist
                return Signal(
                    direction="short",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"MACD bear hist, RSI {rsi:.0f}, EMA aligned"
                )

        # Exit on histogram reversal or EMA cross against
        if position is not None:
            if position.direction == "long":
                if hist_crossed_down or (close < slow_ema):
                    return Signal(direction="close_long",
                                 reason=f"MACD histogram flipped bearish")
            if position.direction == "short":
                if hist_crossed_up or (close > slow_ema):
                    return Signal(direction="close_short",
                                 reason=f"MACD histogram flipped bullish")

        return None
