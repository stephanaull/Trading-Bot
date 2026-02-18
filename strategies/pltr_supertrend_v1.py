"""PLTR SuperTrend + ADX + RSI Strategy v1 (10m).

SuperTrend for direction, ADX for trend strength, RSI for momentum.
Adapted for 10m bars. Tight stops, 2.5x targets. Long AND short.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR SuperTrend Momentum"
    version = "v1"
    description = "SuperTrend + ADX + RSI, 1x ATR stop / 2.5x target (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "supertrend", "params": {"length": 7, "multiplier": 2.5}, "var": "st"},
        {"name": "adx", "params": {"length": 14}, "var": "adx_val"},
        {"name": "rsi", "params": {"length": 9}, "var": "rsi_val"},
        {"name": "atr", "params": {"length": 10}, "var": "atr_val"},
        {"name": "ema", "params": {"length": 50}, "var": "trend_ema"},
    ]
    pine_conditions = {
        "long_entry": "SUPERTd > 0 and ADX > 20 and rsi_val > 50",
        "short_entry": "SUPERTd < 0 and ADX > 20 and rsi_val < 50",
    }

    def __init__(self, params=None):
        defaults = {
            "st_length": 7,
            "st_multiplier": 2.5,
            "adx_length": 14,
            "adx_min": 20,
            "rsi_length": 9,
            "atr_length": 10,
            "trend_ema": 50,
            "atr_stop_mult": 1.0,
            "atr_target_mult": 2.5,
            "session_start_hour": 14,
            "session_start_minute": 40,
            "session_end_hour": 19,
            "session_end_minute": 50,
        }
        super().__init__({**defaults, **(params or {})})
        self._prev_st_dir = None

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "supertrend", length=self.params["st_length"],
                           multiplier=self.params["st_multiplier"])
        df = Indicators.add(df, "adx", length=self.params["adx_length"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        df = Indicators.add(df, "ema", length=self.params["trend_ema"])
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
        st_dir_col = f"SUPERTd_{self.params['st_length']}_{self.params['st_multiplier']}"
        adx_col = f"ADX_{self.params['adx_length']}"
        rsi_col = f"RSI_{self.params['rsi_length']}"
        atr_col = f"ATR_{self.params['atr_length']}"
        ema_col = f"EMA_{self.params['trend_ema']}"

        if pd.isna(row.get(st_dir_col)) or pd.isna(row.get(adx_col)) or pd.isna(row.get(atr_col)):
            return None

        ts = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)

        if not self._in_session(ts):
            if position is not None:
                direction = "close_long" if position.direction == "long" else "close_short"
                return Signal(direction=direction, reason="End of session")
            return None

        st_dir = row[st_dir_col]
        adx = row[adx_col]
        rsi = row[rsi_col]
        atr = row[atr_col]
        ema_trend = row.get(ema_col, None)
        close = row["close"]
        open_p = row["open"]

        if atr <= 0:
            return None

        st_flipped_bull = self._prev_st_dir is not None and self._prev_st_dir <= 0 and st_dir > 0
        st_flipped_bear = self._prev_st_dir is not None and self._prev_st_dir >= 0 and st_dir < 0
        self._prev_st_dir = st_dir

        trending = adx > self.params["adx_min"]
        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        if position is None:
            trend_up = ema_trend is not None and not pd.isna(ema_trend) and close > ema_trend
            if st_dir > 0 and trending and rsi > 50 and (st_flipped_bull or close > open_p):
                if trend_up or st_flipped_bull:
                    return Signal(
                        direction="long",
                        stop_loss=close - stop_dist,
                        take_profit=close + target_dist,
                        reason=f"SuperTrend bull, ADX {adx:.0f}, RSI {rsi:.0f}"
                    )

            trend_down = ema_trend is not None and not pd.isna(ema_trend) and close < ema_trend
            if st_dir < 0 and trending and rsi < 50 and (st_flipped_bear or close < open_p):
                if trend_down or st_flipped_bear:
                    return Signal(
                        direction="short",
                        stop_loss=close + stop_dist,
                        take_profit=close - target_dist,
                        reason=f"SuperTrend bear, ADX {adx:.0f}, RSI {rsi:.0f}"
                    )

        if position is not None:
            if position.direction == "long" and st_dir < 0:
                return Signal(direction="close_long", reason="SuperTrend flipped bearish")
            if position.direction == "short" and st_dir > 0:
                return Signal(direction="close_short", reason="SuperTrend flipped bullish")

        return None
