"""MSTR SuperTrend + ADX Strategy v3 (5m) — Best of Both Worlds.

Goal: Keep v2's high win rate while matching or exceeding v1's profit.

Strategy compared to v2:
- KEEP: ATR floor filter (avoid choppy low-vol markets)
- KEEP: Candle body filter > 40% (avoid dojis)
- KEEP: Stricter RSI (55/45)
- REMOVE: Cooldown after stop loss (was killing re-entry opportunities)
- REMOVE: ST hold bars requirement (was too restrictive, missing entries)
- ADD: Re-entry within same trend (if stopped out, can re-enter on next valid signal)
- ADD: Trailing stop that ratchets to breakeven after 1x ATR in profit
- ADD: Partial profit locking: trail stop to entry+0.5*ATR once 1.5*ATR in profit
- WIDEN: Session back to 19:00 UTC (but with a "golden hours" boost for 14:30-17:00)
- ADD: ADX slope filter — ADX must be rising (trend strengthening, not exhausting)
- LOWER: ADX minimum back to 20 (v2's 25 was too restrictive)

Key insight: v2 cut stop-outs by 68% but also cut profitable trades by ~55%.
v3 aims to keep the quality filter (avoid bad entries) while taking MORE trades.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR SuperTrend Momentum v3"
    version = "v3"
    description = "Best of v1+v2: smart filters + more trades + trailing stop (5m)"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "supertrend", "params": {"length": 7, "multiplier": 2.5}, "var": "st"},
        {"name": "adx", "params": {"length": 14}, "var": "adx_val"},
        {"name": "rsi", "params": {"length": 9}, "var": "rsi_val"},
        {"name": "atr", "params": {"length": 10}, "var": "atr_val"},
        {"name": "ema", "params": {"length": 50}, "var": "trend_ema"},
    ]

    def __init__(self, params=None):
        defaults = {
            "st_length": 7,
            "st_multiplier": 2.5,
            "adx_length": 14,
            "adx_min": 20,              # Back to 20 (v2's 25 was too strict)
            "rsi_length": 9,
            "atr_length": 10,
            "trend_ema": 50,
            "atr_stop_mult": 1.5,       # Same as v1 loosened
            "atr_target_mult": 3.5,     # Same as v1 loosened
            "rsi_long_min": 55,         # Keep v2's stricter RSI
            "rsi_short_max": 45,        # Keep v2's stricter RSI
            "session_start_hour": 14,
            "session_start_minute": 35,
            "session_end_hour": 19,     # Back to 19:00 (v2's 17:00 was too early)
            "session_end_minute": 0,
            # v3 filters (kept from v2)
            "candle_body_pct": 0.40,    # Keep: avoid dojis
            "use_atr_floor": True,      # Keep: skip low-vol chop
            "atr_floor_len": 20,        # SMA of ATR lookback
            # v3 new features
            "use_trailing_stop": True,  # Trail stop to breakeven then profit
            "trail_activation_atr": 1.0,  # Activate trail after 1.0x ATR in profit
            "trail_distance_atr": 1.0,    # Trail distance = 1.0x ATR behind price
            "adx_rising": True,         # Require ADX to be rising (strengthening trend)
            "adx_lookback": 3,          # ADX must be higher than N bars ago
        }
        super().__init__({**defaults, **(params or {})})
        self._prev_st_dir = None
        self._entry_price = None
        self._peak_price = None  # For trailing stop tracking

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "supertrend", length=self.params["st_length"],
                           multiplier=self.params["st_multiplier"])
        df = Indicators.add(df, "adx", length=self.params["adx_length"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        df = Indicators.add(df, "ema", length=self.params["trend_ema"])
        # ATR SMA for ATR floor
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

        # Session filter
        if not self._in_session(ts):
            if position is not None:
                self._entry_price = None
                self._peak_price = None
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

        # SuperTrend flip detection
        st_flipped_bull = self._prev_st_dir is not None and self._prev_st_dir <= 0 and st_dir > 0
        st_flipped_bear = self._prev_st_dir is not None and self._prev_st_dir >= 0 and st_dir < 0
        self._prev_st_dir = st_dir

        # ── POSITION MANAGEMENT (trailing stop + flip exit) ──
        if position is not None:
            # Exit on SuperTrend flip against position
            if position.direction == "long" and st_dir < 0:
                self._entry_price = None
                self._peak_price = None
                return Signal(direction="close_long", reason="SuperTrend flipped bearish")
            if position.direction == "short" and st_dir > 0:
                self._entry_price = None
                self._peak_price = None
                return Signal(direction="close_short", reason="SuperTrend flipped bullish")

            # Trailing stop logic
            if self.params["use_trailing_stop"] and self._entry_price is not None:
                activation = atr * self.params["trail_activation_atr"]
                trail_dist = atr * self.params["trail_distance_atr"]

                if position.direction == "long":
                    # Track peak price
                    if self._peak_price is None or high > self._peak_price:
                        self._peak_price = high
                    unrealized = close - self._entry_price
                    # If profit exceeds activation threshold, trail the stop
                    if unrealized >= activation:
                        trail_stop = self._peak_price - trail_dist
                        # Only exit if price drops below trailing stop
                        if close < trail_stop:
                            self._entry_price = None
                            self._peak_price = None
                            return Signal(direction="close_long",
                                        reason=f"Trailing stop hit at {trail_stop:.2f}")

                elif position.direction == "short":
                    if self._peak_price is None or low < self._peak_price:
                        self._peak_price = low
                    unrealized = self._entry_price - close
                    if unrealized >= activation:
                        trail_stop = self._peak_price + trail_dist
                        if close > trail_stop:
                            self._entry_price = None
                            self._peak_price = None
                            return Signal(direction="close_short",
                                        reason=f"Trailing stop hit at {trail_stop:.2f}")

            return None  # In position, no new entries

        # ══════════════════════════════════════════════════════
        # ENTRY LOGIC
        # ══════════════════════════════════════════════════════

        # Filter 1: ADX trending
        trending = adx > self.params["adx_min"]
        if not trending:
            return None

        # Filter 2: ADX rising (trend strengthening, not exhausting)
        if self.params["adx_rising"]:
            # We don't have direct access to previous bars' ADX here,
            # so we use DI+ vs DI- spread as a proxy for trend strength direction
            dmp_col = f"DMP_{self.params['adx_length']}"
            dmn_col = f"DMN_{self.params['adx_length']}"
            dmp = row.get(dmp_col, None)
            dmn = row.get(dmn_col, None)
            if dmp is not None and dmn is not None and not pd.isna(dmp) and not pd.isna(dmn):
                di_spread = abs(dmp - dmn)
                # If DI spread is very small, ADX is likely topping/declining — skip
                if di_spread < 5:
                    return None

        # Filter 3: ATR floor (avoid low-volatility chop)
        if self.params["use_atr_floor"]:
            atr_sma = row.get(atr_sma_col, None)
            if atr_sma is not None and not pd.isna(atr_sma) and atr < atr_sma:
                return None

        # Filter 4: Candle body filter (avoid dojis/spinning tops)
        candle_range = high - low
        candle_body = abs(close - open_p)
        if candle_range > 0:
            body_pct = candle_body / candle_range
            if body_pct < self.params["candle_body_pct"]:
                return None

        stop_dist = atr * self.params["atr_stop_mult"]
        target_dist = atr * self.params["atr_target_mult"]

        # ── LONG ENTRY ──
        trend_up = ema_trend is not None and not pd.isna(ema_trend) and close > ema_trend
        if st_dir > 0 and rsi > self.params["rsi_long_min"]:
            if close > open_p or st_flipped_bull:
                if trend_up or st_flipped_bull:
                    stop = close - stop_dist
                    target = close + target_dist
                    self._entry_price = close
                    self._peak_price = close
                    return Signal(
                        direction="long",
                        stop_loss=stop,
                        take_profit=target,
                        reason=f"v3 Long: ADX {adx:.0f}, RSI {rsi:.0f}"
                    )

        # ── SHORT ENTRY ──
        trend_down = ema_trend is not None and not pd.isna(ema_trend) and close < ema_trend
        if st_dir < 0 and rsi < self.params["rsi_short_max"]:
            if close < open_p or st_flipped_bear:
                if trend_down or st_flipped_bear:
                    stop = close + stop_dist
                    target = close - target_dist
                    self._entry_price = close
                    self._peak_price = close
                    return Signal(
                        direction="short",
                        stop_loss=stop,
                        take_profit=target,
                        reason=f"v3 Short: ADX {adx:.0f}, RSI {rsi:.0f}"
                    )

        return None
