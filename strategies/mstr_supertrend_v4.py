"""MSTR SuperTrend + ADX Strategy v4 (5m) — Quality + Volume.

Learnings from v1/v2/v3:
- v1: Most profit ($62k) but low win rate (46%) and 93 stop-outs
- v2: Best win rate (58%) and PF (3.6x) but too few trades ($35k)
- v3: Trailing stops hurt — caused premature exits, more stop-outs

v4 approach: Keep v2's PROVEN quality filters, but ADD a second entry
type: CONTINUATION entries within an established trend. This gives us
more trades without lowering quality.

Entry Type 1 (FLIP): Same as v2 — enter on SuperTrend direction change
Entry Type 2 (CONTINUATION): If already in a ST bullish/bearish trend for 5+ bars,
    enter on RSI pullback + bounce (RSI dips then recovers above threshold).
    This catches the "2nd wave" moves that v2 was missing.

Also: Remove trailing stop (v3 proved it hurts). Use wider session (v1 proved late trades
can work). Keep ATR floor + candle body + stricter RSI from v2.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR SuperTrend Momentum v4"
    version = "v4"
    description = "v2 quality filters + continuation entries for more trades (5m)"
    ticker = "MSTR"
    timeframe = "5m"

    def __init__(self, params=None):
        defaults = {
            "st_length": 7,
            "st_multiplier": 2.5,
            "adx_length": 14,
            "adx_min": 22,              # Slightly above v1's 20 but below v2's 25
            "rsi_length": 9,
            "atr_length": 10,
            "trend_ema": 50,
            "atr_stop_mult": 1.5,
            "atr_target_mult": 3.5,
            "rsi_long_min": 53,         # Slightly above 50 (was 55 in v2)
            "rsi_short_max": 47,        # Slightly below 50 (was 45 in v2)
            "session_start_hour": 14,
            "session_start_minute": 35,
            "session_end_hour": 19,     # Back to v1's wider window
            "session_end_minute": 0,
            # Quality filters (from v2)
            "candle_body_pct": 0.35,    # Slightly relaxed from 0.40
            "use_atr_floor": True,
            "atr_floor_len": 20,
            # Continuation entry params
            "use_continuation": True,
            "cont_st_hold_min": 5,      # ST direction must hold 5+ bars for continuation
            "cont_rsi_dip": 5,          # RSI must have dipped at least 5 points recently
        }
        super().__init__({**defaults, **(params or {})})
        self._prev_st_dir = None
        self._st_dir_count = 0
        self._prev_rsi = None
        self._rsi_recent_low = None     # Track RSI dip for continuation
        self._bars_since_entry = 0      # Avoid rapid re-entry
        self._in_trade = False

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "supertrend", length=self.params["st_length"],
                           multiplier=self.params["st_multiplier"])
        df = Indicators.add(df, "adx", length=self.params["adx_length"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        df = Indicators.add(df, "ema", length=self.params["trend_ema"])
        # ATR SMA for floor
        atr_col = f"ATR_{self.params['atr_length']}"
        atr_sma_col = f"ATR_SMA_{self.params['atr_floor_len']}"
        if atr_col in df.columns:
            df[atr_sma_col] = df[atr_col].rolling(self.params["atr_floor_len"]).mean()
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

    def on_trade_closed(self, trade) -> None:
        """Track when trades close for re-entry timing."""
        self._in_trade = False
        self._bars_since_entry = 0

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        st_dir_col = f"SUPERTd_{self.params['st_length']}_{self.params['st_multiplier']}"
        adx_col = f"ADX_{self.params['adx_length']}"
        rsi_col = f"RSI_{self.params['rsi_length']}"
        atr_col = f"ATR_{self.params['atr_length']}"
        ema_col = f"EMA_{self.params['trend_ema']}"
        atr_sma_col = f"ATR_SMA_{self.params['atr_floor_len']}"

        if pd.isna(row.get(st_dir_col)) or pd.isna(row.get(adx_col)) or pd.isna(row.get(atr_col)):
            return None

        ts = row.name if isinstance(row.name, pd.Timestamp) else pd.Timestamp(row.name)

        if not self._in_session(ts):
            if position is not None:
                self._in_trade = False
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
        high = row["high"]
        low = row["low"]

        if atr <= 0:
            return None

        # ── Track SuperTrend direction duration ──
        if self._prev_st_dir is not None and st_dir == self._prev_st_dir:
            self._st_dir_count += 1
        else:
            self._st_dir_count = 1
            self._rsi_recent_low = rsi  # Reset RSI tracking on direction change

        st_flipped_bull = self._prev_st_dir is not None and self._prev_st_dir <= 0 and st_dir > 0
        st_flipped_bear = self._prev_st_dir is not None and self._prev_st_dir >= 0 and st_dir < 0
        self._prev_st_dir = st_dir

        # Track RSI for pullback detection
        if self._rsi_recent_low is None:
            self._rsi_recent_low = rsi
        if st_dir > 0:  # Bullish trend: track RSI lows
            if rsi < self._rsi_recent_low:
                self._rsi_recent_low = rsi
        elif st_dir < 0:  # Bearish trend: track RSI highs
            if rsi > self._rsi_recent_low:
                self._rsi_recent_low = rsi

        self._prev_rsi = rsi

        if position is not None:
            self._bars_since_entry += 1

        # ── EXIT LOGIC ──
        if position is not None:
            if position.direction == "long" and st_dir < 0:
                self._in_trade = False
                return Signal(direction="close_long", reason="SuperTrend flipped bearish")
            if position.direction == "short" and st_dir > 0:
                self._in_trade = False
                return Signal(direction="close_short", reason="SuperTrend flipped bullish")
            return None

        # ══════════════════════════════════════════════════════
        # ENTRY LOGIC
        # ══════════════════════════════════════════════════════

        # Shared quality filters
        trending = adx > self.params["adx_min"]
        if not trending:
            return None

        # ATR floor
        if self.params["use_atr_floor"]:
            atr_sma = row.get(atr_sma_col, None)
            if atr_sma is not None and not pd.isna(atr_sma) and atr < atr_sma * 0.85:
                # Slightly relaxed: only reject if ATR < 85% of average (v2 was < 100%)
                return None

        # Candle body filter
        candle_range = high - low
        candle_body = abs(close - open_p)
        if candle_range > 0:
            body_pct = candle_body / candle_range
            if body_pct < self.params["candle_body_pct"]:
                return None

        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        trend_up = ema_trend is not None and not pd.isna(ema_trend) and close > ema_trend
        trend_down = ema_trend is not None and not pd.isna(ema_trend) and close < ema_trend

        # ── ENTRY TYPE 1: FLIP ENTRY (like v1/v2) ──
        # On SuperTrend flip + momentum confirmation
        if st_dir > 0 and rsi > self.params["rsi_long_min"]:
            if (close > open_p or st_flipped_bull) and (trend_up or st_flipped_bull):
                stop = close - stop_dist
                target = close + target_dist
                self._in_trade = True
                self._bars_since_entry = 0
                self._rsi_recent_low = rsi  # Reset for next continuation
                return Signal(
                    direction="long",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"v4 Flip Long: ADX {adx:.0f}, RSI {rsi:.0f}"
                )

        if st_dir < 0 and rsi < self.params["rsi_short_max"]:
            if (close < open_p or st_flipped_bear) and (trend_down or st_flipped_bear):
                stop = close + stop_dist
                target = close - target_dist
                self._in_trade = True
                self._bars_since_entry = 0
                self._rsi_recent_low = rsi
                return Signal(
                    direction="short",
                    stop_loss=stop,
                    take_profit=target,
                    reason=f"v4 Flip Short: ADX {adx:.0f}, RSI {rsi:.0f}"
                )

        # ── ENTRY TYPE 2: CONTINUATION ENTRY (new in v4) ──
        # After SuperTrend has been in one direction for N+ bars,
        # enter on RSI pullback recovery (second wave)
        if self.params["use_continuation"] and self._st_dir_count >= self.params["cont_st_hold_min"]:
            rsi_dip_threshold = self.params["cont_rsi_dip"]

            # LONG continuation: RSI dipped then recovered above threshold
            if st_dir > 0 and trend_up and close > open_p:
                rsi_dipped = (self._rsi_recent_low is not None and
                             rsi - self._rsi_recent_low >= rsi_dip_threshold)
                if rsi_dipped and rsi > self.params["rsi_long_min"]:
                    stop = close - stop_dist
                    target = close + target_dist
                    self._in_trade = True
                    self._bars_since_entry = 0
                    self._rsi_recent_low = rsi  # Reset for next wave
                    return Signal(
                        direction="long",
                        stop_loss=stop,
                        take_profit=target,
                        reason=f"v4 Cont Long: RSI bounce from {self._rsi_recent_low:.0f} to {rsi:.0f}"
                    )

            # SHORT continuation: RSI spiked then dropped back below threshold
            if st_dir < 0 and trend_down and close < open_p:
                rsi_spiked = (self._rsi_recent_low is not None and
                             self._rsi_recent_low - rsi >= rsi_dip_threshold)
                if rsi_spiked and rsi < self.params["rsi_short_max"]:
                    stop = close + stop_dist
                    target = close - target_dist
                    self._in_trade = True
                    self._bars_since_entry = 0
                    self._rsi_recent_low = rsi
                    return Signal(
                        direction="short",
                        stop_loss=stop,
                        take_profit=target,
                        reason=f"v4 Cont Short: RSI drop from {self._rsi_recent_low:.0f} to {rsi:.0f}"
                    )

        return None
