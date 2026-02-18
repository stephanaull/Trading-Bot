"""Technical indicator wrapper with Pine Script name mapping.

Provides a clean facade over pandas-ta with consistent naming
and bidirectional mapping to Pine Script ta.xxx() functions.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# Try to import pandas_ta; provide fallback implementations if not available
try:
    import pandas_ta as ta
    HAS_PANDAS_TA = True
except ImportError:
    HAS_PANDAS_TA = False
    logger.warning("pandas-ta not installed. Using built-in indicator implementations. "
                    "Install with: pip install pandas-ta")


# Indicator registry: maps our names to pandas-ta and Pine Script equivalents
INDICATOR_MAP = {
    "sma":    {"pine": "ta.sma",    "params": ["length"]},
    "ema":    {"pine": "ta.ema",    "params": ["length"]},
    "wma":    {"pine": "ta.wma",    "params": ["length"]},
    "rma":    {"pine": "ta.rma",    "params": ["length"]},
    "rsi":    {"pine": "ta.rsi",    "params": ["length"]},
    "macd":   {"pine": "ta.macd",   "params": ["fast", "slow", "signal"]},
    "bbands": {"pine": "ta.bb",     "params": ["length", "std"]},
    "atr":    {"pine": "ta.atr",    "params": ["length"]},
    "adx":    {"pine": "ta.adx",    "params": ["length"]},
    "stoch":  {"pine": "ta.stoch",  "params": ["k", "d", "smooth_k"]},
    "cci":    {"pine": "ta.cci",    "params": ["length"]},
    "mfi":    {"pine": "ta.mfi",    "params": ["length"]},
    "obv":    {"pine": "ta.obv",    "params": []},
    "vwap":   {"pine": "ta.vwap",   "params": []},
    "supertrend": {"pine": "ta.supertrend", "params": ["length", "multiplier"]},
    "ichimoku":   {"pine": "ta.ichimoku",   "params": ["tenkan", "kijun", "senkou"]},
    "psar":   {"pine": "ta.sar",    "params": ["af", "max_af"]},
    "willr":  {"pine": "ta.wpr",    "params": ["length"]},
    "roc":    {"pine": "ta.roc",    "params": ["length"]},
    "mom":    {"pine": "ta.mom",    "params": ["length"]},
    "trix":   {"pine": "ta.trix",   "params": ["length"]},
    "keltner": {"pine": "ta.kc",    "params": ["length", "multiplier"]},
    "donchian": {"pine": "ta.donchian", "params": ["length"]},
    "cmf":    {"pine": "ta.cmf",    "params": ["length"]},
    "dmi":    {"pine": "ta.dmi",    "params": ["length"]},
    "ao":     {"pine": "ta.ao",     "params": []},
}


class Indicators:
    """Facade over pandas-ta with Pine Script name mapping."""

    @staticmethod
    def add(df: pd.DataFrame, name: str, **params) -> pd.DataFrame:
        """Add indicator columns to DataFrame.

        Args:
            df: DataFrame with OHLCV data
            name: Indicator name (e.g., 'ema', 'rsi', 'macd')
            **params: Indicator parameters (e.g., length=14)

        Returns:
            DataFrame with indicator columns added

        Example:
            df = Indicators.add(df, 'ema', length=20)
            df = Indicators.add(df, 'rsi', length=14)
            df = Indicators.add(df, 'macd', fast=12, slow=26, signal=9)
            df = Indicators.add(df, 'bbands', length=20, std=2)
        """
        name = name.lower()

        if HAS_PANDAS_TA:
            df = Indicators._add_with_pandas_ta(df, name, **params)
        else:
            df = Indicators._add_builtin(df, name, **params)

        return df

    @staticmethod
    def _add_with_pandas_ta(df: pd.DataFrame, name: str, **params) -> pd.DataFrame:
        """Add indicator using pandas-ta library."""
        try:
            if name == "sma":
                length = params.get("length", 20)
                result = ta.sma(df["close"], length=length)
                df[f"SMA_{length}"] = result

            elif name == "ema":
                length = params.get("length", 20)
                result = ta.ema(df["close"], length=length)
                df[f"EMA_{length}"] = result

            elif name == "wma":
                length = params.get("length", 20)
                result = ta.wma(df["close"], length=length)
                df[f"WMA_{length}"] = result

            elif name == "rsi":
                length = params.get("length", 14)
                result = ta.rsi(df["close"], length=length)
                df[f"RSI_{length}"] = result

            elif name == "macd":
                fast = params.get("fast", 12)
                slow = params.get("slow", 26)
                signal = params.get("signal", 9)
                result = ta.macd(df["close"], fast=fast, slow=slow, signal=signal)
                if result is not None:
                    df[f"MACD_{fast}_{slow}_{signal}"] = result.iloc[:, 0]
                    df[f"MACDh_{fast}_{slow}_{signal}"] = result.iloc[:, 1]
                    df[f"MACDs_{fast}_{slow}_{signal}"] = result.iloc[:, 2]

            elif name == "bbands":
                length = params.get("length", 20)
                std = params.get("std", 2.0)
                result = ta.bbands(df["close"], length=length, std=std)
                if result is not None:
                    df[f"BBL_{length}_{std}"] = result.iloc[:, 0]
                    df[f"BBM_{length}_{std}"] = result.iloc[:, 1]
                    df[f"BBU_{length}_{std}"] = result.iloc[:, 2]
                    df[f"BBB_{length}_{std}"] = result.iloc[:, 3]
                    df[f"BBP_{length}_{std}"] = result.iloc[:, 4]

            elif name == "atr":
                length = params.get("length", 14)
                result = ta.atr(df["high"], df["low"], df["close"], length=length)
                df[f"ATR_{length}"] = result

            elif name == "adx":
                length = params.get("length", 14)
                result = ta.adx(df["high"], df["low"], df["close"], length=length)
                if result is not None:
                    df[f"ADX_{length}"] = result.iloc[:, 0]
                    df[f"DMP_{length}"] = result.iloc[:, 1]
                    df[f"DMN_{length}"] = result.iloc[:, 2]

            elif name == "stoch":
                k = params.get("k", 14)
                d = params.get("d", 3)
                smooth_k = params.get("smooth_k", 3)
                result = ta.stoch(df["high"], df["low"], df["close"],
                                  k=k, d=d, smooth_k=smooth_k)
                if result is not None:
                    df[f"STOCHk_{k}_{d}_{smooth_k}"] = result.iloc[:, 0]
                    df[f"STOCHd_{k}_{d}_{smooth_k}"] = result.iloc[:, 1]

            elif name == "cci":
                length = params.get("length", 20)
                result = ta.cci(df["high"], df["low"], df["close"], length=length)
                df[f"CCI_{length}"] = result

            elif name == "mfi":
                length = params.get("length", 14)
                result = ta.mfi(df["high"], df["low"], df["close"], df["volume"], length=length)
                df[f"MFI_{length}"] = result

            elif name == "obv":
                result = ta.obv(df["close"], df["volume"])
                df["OBV"] = result

            elif name == "vwap":
                result = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
                df["VWAP"] = result

            elif name == "supertrend":
                length = params.get("length", 7)
                multiplier = params.get("multiplier", 3.0)
                result = ta.supertrend(df["high"], df["low"], df["close"],
                                        length=length, multiplier=multiplier)
                if result is not None:
                    df[f"SUPERT_{length}_{multiplier}"] = result.iloc[:, 0]
                    df[f"SUPERTd_{length}_{multiplier}"] = result.iloc[:, 1]

            elif name == "psar":
                af = params.get("af", 0.02)
                max_af = params.get("max_af", 0.2)
                result = ta.psar(df["high"], df["low"], af0=af, af=af, max_af=max_af)
                if result is not None:
                    df["PSAR_long"] = result.iloc[:, 0]
                    df["PSAR_short"] = result.iloc[:, 1]
                    df["PSAR_af"] = result.iloc[:, 2]
                    df["PSAR_reversal"] = result.iloc[:, 3]

            elif name == "willr":
                length = params.get("length", 14)
                result = ta.willr(df["high"], df["low"], df["close"], length=length)
                df[f"WILLR_{length}"] = result

            elif name == "roc":
                length = params.get("length", 10)
                result = ta.roc(df["close"], length=length)
                df[f"ROC_{length}"] = result

            elif name == "mom":
                length = params.get("length", 10)
                result = ta.mom(df["close"], length=length)
                df[f"MOM_{length}"] = result

            elif name == "donchian":
                length = params.get("length", 20)
                result = ta.donchian(df["high"], df["low"], lower_length=length, upper_length=length)
                if result is not None:
                    df[f"DCL_{length}"] = result.iloc[:, 0]
                    df[f"DCM_{length}"] = result.iloc[:, 1]
                    df[f"DCU_{length}"] = result.iloc[:, 2]

            elif name == "cmf":
                length = params.get("length", 20)
                result = ta.cmf(df["high"], df["low"], df["close"], df["volume"], length=length)
                df[f"CMF_{length}"] = result

            else:
                logger.warning(f"Unknown indicator: {name}. Attempting pandas-ta generic call.")
                result = df.ta.__getattribute__(name)(**params)
                if result is not None:
                    if isinstance(result, pd.DataFrame):
                        df = pd.concat([df, result], axis=1)
                    else:
                        df[f"{name.upper()}"] = result

        except Exception as e:
            logger.error(f"Failed to compute indicator {name}: {e}")
            raise

        return df

    @staticmethod
    def _add_builtin(df: pd.DataFrame, name: str, **params) -> pd.DataFrame:
        """Built-in indicator implementations when pandas-ta is not available."""
        if name == "sma":
            length = params.get("length", 20)
            df[f"SMA_{length}"] = df["close"].rolling(window=length).mean()

        elif name == "ema":
            length = params.get("length", 20)
            df[f"EMA_{length}"] = df["close"].ewm(span=length, adjust=False).mean()

        elif name == "rsi":
            length = params.get("length", 14)
            delta = df["close"].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
            rs = avg_gain / avg_loss
            df[f"RSI_{length}"] = 100 - (100 / (1 + rs))

        elif name == "macd":
            fast = params.get("fast", 12)
            slow = params.get("slow", 26)
            signal = params.get("signal", 9)
            ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
            ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=signal, adjust=False).mean()
            histogram = macd_line - signal_line
            df[f"MACD_{fast}_{slow}_{signal}"] = macd_line
            df[f"MACDh_{fast}_{slow}_{signal}"] = histogram
            df[f"MACDs_{fast}_{slow}_{signal}"] = signal_line

        elif name == "bbands":
            length = params.get("length", 20)
            std = params.get("std", 2.0)
            sma = df["close"].rolling(window=length).mean()
            std_dev = df["close"].rolling(window=length).std()
            df[f"BBL_{length}_{std}"] = sma - std * std_dev
            df[f"BBM_{length}_{std}"] = sma
            df[f"BBU_{length}_{std}"] = sma + std * std_dev

        elif name == "atr":
            length = params.get("length", 14)
            high = df["high"]
            low = df["low"]
            close = df["close"].shift(1)
            tr = pd.concat([
                high - low,
                (high - close).abs(),
                (low - close).abs()
            ], axis=1).max(axis=1)
            df[f"ATR_{length}"] = tr.ewm(alpha=1/length, min_periods=length, adjust=False).mean()

        elif name == "obv":
            obv = [0]
            for i in range(1, len(df)):
                if df["close"].iloc[i] > df["close"].iloc[i-1]:
                    obv.append(obv[-1] + df["volume"].iloc[i])
                elif df["close"].iloc[i] < df["close"].iloc[i-1]:
                    obv.append(obv[-1] - df["volume"].iloc[i])
                else:
                    obv.append(obv[-1])
            df["OBV"] = obv

        elif name == "stoch":
            k = params.get("k", 14)
            d = params.get("d", 3)
            smooth_k = params.get("smooth_k", 3)
            low_min = df["low"].rolling(window=k).min()
            high_max = df["high"].rolling(window=k).max()
            raw_k = 100 * (df["close"] - low_min) / (high_max - low_min)
            stoch_k = raw_k.rolling(window=smooth_k).mean()
            stoch_d = stoch_k.rolling(window=d).mean()
            df[f"STOCHk_{k}_{d}_{smooth_k}"] = stoch_k
            df[f"STOCHd_{k}_{d}_{smooth_k}"] = stoch_d

        elif name == "adx":
            length = params.get("length", 14)
            high = df["high"]
            low = df["low"]
            close = df["close"]
            # True Range
            prev_close = close.shift(1)
            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs()
            ], axis=1).max(axis=1)
            # Directional Movement
            up_move = high - high.shift(1)
            down_move = low.shift(1) - low
            plus_dm = pd.Series(0.0, index=df.index)
            minus_dm = pd.Series(0.0, index=df.index)
            plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
            minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
            # Smoothed averages (Wilder's smoothing = EWM with alpha=1/length)
            atr_sm = tr.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
            plus_dm_sm = plus_dm.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
            minus_dm_sm = minus_dm.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
            # DI+ and DI-
            plus_di = 100 * plus_dm_sm / atr_sm
            minus_di = 100 * minus_dm_sm / atr_sm
            # DX and ADX
            dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
            adx_val = dx.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
            df[f"ADX_{length}"] = adx_val
            df[f"DMP_{length}"] = plus_di
            df[f"DMN_{length}"] = minus_di

        elif name == "supertrend":
            length = params.get("length", 7)
            multiplier = params.get("multiplier", 3.0)
            close_s = df["close"].values.astype(float)
            high_s = df["high"].values.astype(float)
            low_s = df["low"].values.astype(float)
            n = len(df)

            # ATR calculation
            hl2 = (high_s + low_s) / 2.0
            tr = np.zeros(n)
            for i in range(1, n):
                tr[i] = max(high_s[i] - low_s[i],
                            abs(high_s[i] - close_s[i-1]),
                            abs(low_s[i] - close_s[i-1]))
            tr[0] = high_s[0] - low_s[0]

            # Wilder's smoothed ATR
            atr_arr = np.full(n, np.nan)
            atr_arr[length-1] = np.mean(tr[:length])
            for i in range(length, n):
                atr_arr[i] = (atr_arr[i-1] * (length - 1) + tr[i]) / length

            basic_ub = hl2 + multiplier * atr_arr
            basic_lb = hl2 - multiplier * atr_arr

            final_ub = np.full(n, np.nan)
            final_lb = np.full(n, np.nan)
            st_dir = np.ones(n)
            st_vals = np.full(n, np.nan)

            # Initialize at the first valid ATR bar
            start = length - 1
            final_ub[start] = basic_ub[start]
            final_lb[start] = basic_lb[start]
            # Determine initial direction
            if close_s[start] > basic_ub[start]:
                st_dir[start] = 1
                st_vals[start] = final_lb[start]
            else:
                st_dir[start] = -1
                st_vals[start] = final_ub[start]

            for i in range(start + 1, n):
                if np.isnan(basic_lb[i]) or np.isnan(basic_ub[i]):
                    final_lb[i] = final_lb[i-1]
                    final_ub[i] = final_ub[i-1]
                    st_dir[i] = st_dir[i-1]
                    st_vals[i] = st_vals[i-1]
                    continue

                # Final lower band: ratchet up only when price is above it
                if basic_lb[i] > final_lb[i-1] or close_s[i-1] < final_lb[i-1]:
                    final_lb[i] = basic_lb[i]
                else:
                    final_lb[i] = final_lb[i-1]

                # Final upper band: ratchet down only when price is below it
                if basic_ub[i] < final_ub[i-1] or close_s[i-1] > final_ub[i-1]:
                    final_ub[i] = basic_ub[i]
                else:
                    final_ub[i] = final_ub[i-1]

                # Direction
                prev_dir = st_dir[i-1]
                if prev_dir == 1:  # was bullish
                    if close_s[i] < final_lb[i]:
                        st_dir[i] = -1
                        st_vals[i] = final_ub[i]
                    else:
                        st_dir[i] = 1
                        st_vals[i] = final_lb[i]
                else:  # was bearish
                    if close_s[i] > final_ub[i]:
                        st_dir[i] = 1
                        st_vals[i] = final_lb[i]
                    else:
                        st_dir[i] = -1
                        st_vals[i] = final_ub[i]

            df[f"SUPERT_{length}_{multiplier}"] = st_vals
            df[f"SUPERTd_{length}_{multiplier}"] = st_dir

        else:
            raise ValueError(f"Built-in implementation not available for '{name}'. "
                             f"Install pandas-ta: pip install pandas-ta")

        return df

    @staticmethod
    def crossover(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
        """Returns boolean Series where series_a crosses above series_b.

        Equivalent to Pine Script's ta.crossover(a, b).
        """
        prev_a = series_a.shift(1)
        prev_b = series_b.shift(1)
        return (prev_a <= prev_b) & (series_a > series_b)

    @staticmethod
    def crossunder(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
        """Returns boolean Series where series_a crosses below series_b.

        Equivalent to Pine Script's ta.crossunder(a, b).
        """
        prev_a = series_a.shift(1)
        prev_b = series_b.shift(1)
        return (prev_a >= prev_b) & (series_a < series_b)

    @staticmethod
    def available() -> list:
        """List all available indicator names."""
        return sorted(INDICATOR_MAP.keys())

    @staticmethod
    def pine_name(indicator: str) -> str:
        """Get the Pine Script function name for an indicator."""
        info = INDICATOR_MAP.get(indicator.lower())
        if info:
            return info["pine"]
        return f"ta.{indicator.lower()}"

    @staticmethod
    def get_info(indicator: str) -> Optional[dict]:
        """Get full indicator info including Pine Script mapping."""
        return INDICATOR_MAP.get(indicator.lower())
