"""MSTR SuperTrend + RSI + ADX Strategy v1.1 (5m).

Improvements over v1 based on live trading losses:
1. ADX raised from 20 → 25 (filter weak trends)
2. RSI long min raised from 50 → 55 (require real momentum)
3. RSI overbought cap: skip longs when RSI > 80 (avoid chasing)
4. RSI oversold cap: skip shorts when RSI < 20
5. Anti-whipsaw: SuperTrend must hold 2+ bars (unless fresh flip)
6. ATR floor: skip when ATR < 20-bar SMA of ATR (choppy market)
7. Candle body filter: body must be > 40% of range (avoid dojis)
8. Cooldown: wait 3 bars after stop-loss before re-entry

Uses SuperTrend for trend direction, ADX for trend strength,
RSI for momentum, EMA for trend. Tighter filters = fewer but better trades.
"""

from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "MSTR SuperTrend Momentum"
    version = "v1.1"
    description = "SuperTrend + ADX(25) + RSI(55-80) + anti-whipsaw + ATR floor (5m)"
    ticker = "MSTR"
    timeframe = "5m"

    pine_indicators = [
        {"name": "supertrend", "params": {"length": 7, "multiplier": 2.5}, "var": "st"},
        {"name": "adx", "params": {"length": 14}, "var": "adx_val"},
        {"name": "rsi", "params": {"length": 9}, "var": "rsi_val"},
        {"name": "atr", "params": {"length": 10}, "var": "atr_val"},
        {"name": "ema", "params": {"length": 50}, "var": "trend_ema"},
    ]
    pine_conditions = {
        "long_entry": "SUPERTd > 0 and ADX > 25 and rsi_val > 55 and rsi_val < 80 and close > trend_ema",
        "short_entry": "SUPERTd < 0 and ADX > 25 and rsi_val < 45 and rsi_val > 20 and close < trend_ema",
    }

    def __init__(self, params=None):
        defaults = {
            "st_length": 7,
            "st_multiplier": 2.5,
            "adx_length": 14,
            "adx_min": 25,           # Raised from 20 → 25
            "rsi_length": 9,
            "atr_length": 10,
            "trend_ema": 50,
            "atr_stop_mult": 1.0,    # Tight stop (overridden to 1.5 in TOML)
            "atr_target_mult": 2.5,  # 2.5x R:R (overridden to 3.5 in TOML)
            "rsi_long_min": 55,      # Raised from 50 → 55
            "rsi_long_max": 80,      # NEW: skip overbought entries
            "rsi_short_max": 45,     # Lowered from 50 → 45
            "rsi_short_min": 20,     # NEW: skip oversold shorts
            "session_start_hour": 14,
            "session_start_minute": 35,
            "session_end_hour": 19,
            "session_end_minute": 45,
            # New v1.1 filters
            "st_hold_bars": 2,       # SuperTrend must hold for N bars
            "candle_body_pct": 0.40, # Body must be > 40% of H-L range
            "use_atr_floor": True,   # Skip when ATR < avg ATR
            "atr_floor_len": 20,     # SMA length for ATR floor
            "cooldown_bars": 3,      # Wait N bars after stop-out
        }
        super().__init__({**defaults, **(params or {})})
        self._prev_st_dir = None
        self._st_dir_count = 0
        self._cooldown_remaining = 0

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "supertrend", length=self.params["st_length"],
                           multiplier=self.params["st_multiplier"])
        df = Indicators.add(df, "adx", length=self.params["adx_length"])
        df = Indicators.add(df, "rsi", length=self.params["rsi_length"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])
        df = Indicators.add(df, "ema", length=self.params["trend_ema"])
        # ATR SMA for floor filter
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
        """After a stop loss, activate cooldown."""
        reason = getattr(trade, 'exit_reason', getattr(trade, 'reason', ''))
        if 'stop' in str(reason).lower():
            self._cooldown_remaining = self.params["cooldown_bars"]

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
                direction = "close_long" if position.direction == "long" else "close_short"
                return Signal(direction=direction, reason="End of session")
            return None

        st_dir = row[st_dir_col]   # 1 = bullish, -1 = bearish
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
            self._st_dir_count = 1  # Reset on direction change

        # Detect SuperTrend direction flip
        st_flipped_bull = self._prev_st_dir is not None and self._prev_st_dir <= 0 and st_dir > 0
        st_flipped_bear = self._prev_st_dir is not None and self._prev_st_dir >= 0 and st_dir < 0
        self._prev_st_dir = st_dir

        # ── Cooldown timer ──
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1

        # ── Exit on SuperTrend flip against position ──
        if position is not None:
            if position.direction == "long" and st_dir < 0:
                return Signal(direction="close_long", reason="SuperTrend flipped bearish")
            if position.direction == "short" and st_dir > 0:
                return Signal(direction="close_short", reason="SuperTrend flipped bullish")
            return None  # Already in a position, no new entries

        # ══════════════════════════════════════════════════════
        # ENTRY FILTERS (v1.1 improvements)
        # ══════════════════════════════════════════════════════

        # Filter 1: Cooldown after stop loss
        if self._cooldown_remaining > 0:
            return None

        # Filter 2: ADX trending (raised threshold)
        trending = adx > self.params["adx_min"]
        if not trending:
            return None

        # Filter 3: Anti-whipsaw — SuperTrend must hold for N bars (or be fresh flip)
        st_held = self._st_dir_count >= self.params["st_hold_bars"]

        # Filter 4: ATR floor — skip when volatility is below average (choppy market)
        if self.params["use_atr_floor"]:
            atr_sma = row.get(atr_sma_col, None)
            if atr_sma is not None and not pd.isna(atr_sma) and atr < atr_sma:
                return None

        # Filter 5: Candle body filter — avoid dojis/spinning tops
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
            # Filter 6: RSI overbought cap — skip chasing
            if rsi > self.params["rsi_long_max"]:
                return None
            # Bullish candle required (or fresh flip)
            if close > open_p or st_flipped_bull:
                # EMA filter (relaxed on flip)
                if trend_up or st_flipped_bull:
                    # Anti-whipsaw: must hold direction or be a fresh flip
                    if st_held or st_flipped_bull:
                        stop = close - stop_dist
                        target = close + target_dist
                        return Signal(
                            direction="long",
                            stop_loss=stop,
                            take_profit=target,
                            reason=f"SuperTrend bull, ADX {adx:.0f}, RSI {rsi:.0f}"
                        )

        # ── SHORT ENTRY ──
        trend_down = ema_trend is not None and not pd.isna(ema_trend) and close < ema_trend
        if st_dir < 0 and rsi < self.params["rsi_short_max"]:
            # Filter 6: RSI oversold cap — skip chasing
            if rsi < self.params["rsi_short_min"]:
                return None
            if close < open_p or st_flipped_bear:
                if trend_down or st_flipped_bear:
                    if st_held or st_flipped_bear:
                        stop = close + stop_dist
                        target = close - target_dist
                        return Signal(
                            direction="short",
                            stop_loss=stop,
                            take_profit=target,
                            reason=f"SuperTrend bear, ADX {adx:.0f}, RSI {rsi:.0f}"
                        )

        return None
