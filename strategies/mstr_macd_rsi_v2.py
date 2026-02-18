"""MSTR MACD + RSI Momentum Strategy v2 (5m).

V2 improvements over v1:
- Stronger trend alignment filters (require both EMAs aligned + candle direction)
- Widen target to 3x ATR (from 2.5x) to capture bigger moves
- Keep stop at 1x ATR (tight)
- Minimum ATR threshold to avoid choppy low-volatility periods
- Reduced trade frequency = less commission drag
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR MACD RSI v2"
    version = "v2"
    description = "MACD hist + RSI + dual EMA trend, stronger filters, 1x/3x ATR (5m)"
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
        "long_entry": "MACDh > 0 and MACDh > MACDh[1] and rsi_val > 55 and close > fast_ema and fast_ema > slow_ema and close > open",
        "short_entry": "MACDh < 0 and MACDh < MACDh[1] and rsi_val < 45 and close < fast_ema and fast_ema < slow_ema and close < open",
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
            "atr_stop_mult": 1.0,
            "atr_target_mult": 3.0,      # Wider target for bigger wins
            "min_atr_pct": 0.003,         # Min ATR as % of price (avoid chop)
            "rsi_long_min": 55,           # Stronger momentum required
            "rsi_short_max": 45,
            "volume_lookback": 12,
            "volume_mult": 1.0,           # Require at least average volume
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
        return (sh * 60 + sm) <= (ts.hour * 60 + ts.minute) <= (eh * 60 + em)

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        f, s, sg = self.params["macd_fast"], self.params["macd_slow"], self.params["macd_signal"]
        hist_col = f"MACDh_{f}_{s}_{sg}"
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

        # Minimum volatility filter
        atr_pct = atr / close
        if atr_pct < self.params["min_atr_pct"]:
            self._prev_hist = hist
            return None

        hist_rising = self._prev_hist is not None and hist > self._prev_hist
        hist_falling = self._prev_hist is not None and hist < self._prev_hist
        hist_crossed_up = self._prev_hist is not None and self._prev_hist <= 0 and hist > 0
        hist_crossed_down = self._prev_hist is not None and self._prev_hist >= 0 and hist < 0
        self._prev_hist = hist

        vol_ok = avg_vol > 0 and volume >= avg_vol * self.params["volume_mult"]
        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        if position is None:
            # LONG: histogram positive + rising (or zero cross), strong RSI, all EMAs aligned, bullish candle
            macd_bull = (hist > 0 and hist_rising) or hist_crossed_up
            trend_bull = close > fast_ema and fast_ema > slow_ema
            rsi_bull = rsi > self.params["rsi_long_min"]
            candle_bull = close > open_p

            if macd_bull and trend_bull and rsi_bull and candle_bull and vol_ok:
                return Signal(
                    direction="long",
                    stop_loss=close - stop_dist,
                    take_profit=close + target_dist,
                    reason=f"MACD bull v2: RSI {rsi:.0f}"
                )

            # SHORT: histogram negative + falling (or zero cross), weak RSI, EMAs aligned down, bearish candle
            macd_bear = (hist < 0 and hist_falling) or hist_crossed_down
            trend_bear = close < fast_ema and fast_ema < slow_ema
            rsi_bear = rsi < self.params["rsi_short_max"]
            candle_bear = close < open_p

            if macd_bear and trend_bear and rsi_bear and candle_bear and vol_ok:
                return Signal(
                    direction="short",
                    stop_loss=close + stop_dist,
                    take_profit=close - target_dist,
                    reason=f"MACD bear v2: RSI {rsi:.0f}"
                )

        # Tighter exit: only exit on actual histogram zero-cross against position
        if position is not None:
            if position.direction == "long" and hist_crossed_down:
                return Signal(direction="close_long", reason="MACD crossed zero bearish")
            if position.direction == "short" and hist_crossed_up:
                return Signal(direction="close_short", reason="MACD crossed zero bullish")

        return None
