"""PLTR VWAP Momentum Strategy v1 (10m).

Aggressive momentum strategy combining VWAP, EMA trend, RSI momentum,
and volume confirmation. Adapted for 10m bars on PLTR.
Tight ATR-based stops with 2.5x targets. Long AND short.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "PLTR VWAP Momentum"
    version = "v1"
    description = "VWAP + EMA trend + RSI momentum, tight stops 2.5x R:R (10m)"
    ticker = "PLTR"
    timeframe = "10m"

    pine_indicators = [
        {"name": "ema", "params": {"length": 9}, "var": "fast_ema"},
        {"name": "ema", "params": {"length": 21}, "var": "mid_ema"},
        {"name": "rsi", "params": {"length": 9}, "var": "rsi_val"},
        {"name": "atr", "params": {"length": 10}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "close > fast_ema and fast_ema > mid_ema and rsi_val > 50",
        "short_entry": "close < fast_ema and fast_ema < mid_ema and rsi_val < 50",
    }

    def __init__(self, params=None):
        defaults = {
            "fast_ema": 9,
            "mid_ema": 21,
            "rsi_length": 9,
            "atr_length": 10,
            "atr_stop_mult": 1.0,
            "atr_target_mult": 2.5,
            "rsi_long_min": 50,
            "rsi_long_max": 80,
            "rsi_short_min": 20,
            "rsi_short_max": 50,
            "volume_lookback": 15,
            "volume_mult": 1.0,
            "session_start_hour": 14,
            "session_start_minute": 40,
            "session_end_hour": 19,
            "session_end_minute": 50,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "ema", length=self.params["fast_ema"])
        df = Indicators.add(df, "ema", length=self.params["mid_ema"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])

        # VWAP
        df["_typical"] = (df["high"] + df["low"] + df["close"]) / 3
        prev_date = None
        cum_tp_vol = 0.0
        cum_vol = 0.0
        vwap_vals = []
        for i in range(len(df)):
            ts = df.index[i]
            cur_date = ts.date() if hasattr(ts, 'date') else ts
            if cur_date != prev_date:
                cum_tp_vol = 0.0
                cum_vol = 0.0
                prev_date = cur_date
            vol = df.iloc[i]["volume"]
            tp = df.iloc[i]["_typical"] if pd.notna(df.iloc[i]["_typical"]) else 0
            cum_tp_vol += tp * vol
            cum_vol += vol
            vwap_vals.append(cum_tp_vol / cum_vol if cum_vol > 0 else tp)
        df["VWAP"] = vwap_vals
        df.drop(columns=["_typical"], inplace=True, errors='ignore')

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
        fast_col = f"EMA_{self.params['fast_ema']}"
        mid_col = f"EMA_{self.params['mid_ema']}"
        rsi_col = f"RSI_{self.params['rsi_length']}"
        atr_col = f"ATR_{self.params['atr_length']}"
        vol_col = f"VOL_SMA_{self.params['volume_lookback']}"

        if pd.isna(row.get(mid_col)) or pd.isna(row.get(atr_col)) or pd.isna(row.get("VWAP")):
            return None

        ts = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)

        if not self._in_session(ts):
            if position is not None:
                direction = "close_long" if position.direction == "long" else "close_short"
                return Signal(direction=direction, reason="End of session")
            return None

        fast = row[fast_col]
        mid = row[mid_col]
        rsi = row[rsi_col]
        atr = row[atr_col]
        vwap = row["VWAP"]
        close = row["close"]
        open_p = row["open"]
        volume = row["volume"]
        avg_vol = row.get(vol_col, 0)

        if atr <= 0:
            return None

        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]
        vol_ok = avg_vol > 0 and volume >= avg_vol * self.params["volume_mult"]

        if position is None:
            # LONG
            uptrend = fast > mid and close > vwap
            rsi_ok = self.params["rsi_long_min"] < rsi < self.params["rsi_long_max"]
            bullish = close > open_p

            if uptrend and rsi_ok and bullish and vol_ok:
                return Signal(
                    direction="long",
                    stop_loss=close - stop_dist,
                    take_profit=close + target_dist,
                    reason=f"VWAP momentum long: RSI {rsi:.0f}"
                )

            # SHORT
            downtrend = fast < mid and close < vwap
            rsi_ok_s = self.params["rsi_short_min"] < rsi < self.params["rsi_short_max"]
            bearish = close < open_p

            if downtrend and rsi_ok_s and bearish and vol_ok:
                return Signal(
                    direction="short",
                    stop_loss=close + stop_dist,
                    take_profit=close - target_dist,
                    reason=f"VWAP momentum short: RSI {rsi:.0f}"
                )

        if position is not None:
            if position.direction == "long" and rsi > 82:
                return Signal(direction="close_long", reason=f"RSI overextended ({rsi:.0f})")
            if position.direction == "short" and rsi < 18:
                return Signal(direction="close_short", reason=f"RSI overextended ({rsi:.0f})")

        return None
