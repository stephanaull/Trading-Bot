"""Example strategy: Bollinger Band Squeeze Breakout.

Detects when Bollinger Bands narrow (low volatility squeeze),
then enters on breakout above the upper band.
Uses the middle band as a trailing reference for exits.
"""

from typing import Optional

import pandas as pd
import numpy as np

from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators


class Strategy(BaseStrategy):
    name = "Bollinger Squeeze Breakout"
    version = "v1"
    description = "Enter on BB breakout after squeeze, exit on middle band cross"
    ticker = ""
    timeframe = "1d"

    pine_indicators = [
        {"name": "bbands", "params": {"length": 20, "std": 2}, "var": "bb"},
        {"name": "atr", "params": {"length": 14}, "var": "atr_val"},
    ]
    pine_conditions = {
        "long_entry": "close > bb_upper and bb_bandwidth < squeeze_threshold",
        "long_exit": "close < bb_mid",
    }

    def __init__(self, params=None):
        defaults = {
            "bb_length": 20,
            "bb_std": 2.0,
            "squeeze_percentile": 20,  # Bandwidth below 20th percentile = squeeze
            "squeeze_lookback": 120,   # Look back 120 bars for percentile calc
            "atr_length": 14,
            "stop_loss_atr_mult": 2.0,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        df = Indicators.add(df, "bbands",
                            length=self.params["bb_length"],
                            std=self.params["bb_std"])
        df = Indicators.add(df, "atr", length=self.params["atr_length"])

        # Calculate bandwidth (BBU - BBL) / BBM
        bbl = f"BBL_{self.params['bb_length']}_{self.params['bb_std']}"
        bbm = f"BBM_{self.params['bb_length']}_{self.params['bb_std']}"
        bbu = f"BBU_{self.params['bb_length']}_{self.params['bb_std']}"

        if bbl in df.columns and bbm in df.columns and bbu in df.columns:
            df["BB_bandwidth"] = (df[bbu] - df[bbl]) / df[bbm]

            # Rolling percentile of bandwidth to identify squeezes
            lookback = self.params["squeeze_lookback"]
            df["BB_bw_percentile"] = df["BB_bandwidth"].rolling(lookback).apply(
                lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100,
                raw=False
            )

        return df

    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        bbu = f"BBU_{self.params['bb_length']}_{self.params['bb_std']}"
        bbm = f"BBM_{self.params['bb_length']}_{self.params['bb_std']}"
        atr_col = f"ATR_{self.params['atr_length']}"

        if pd.isna(row.get(bbu)) or pd.isna(row.get("BB_bw_percentile")):
            return None

        close = row["close"]
        upper_band = row[bbu]
        middle_band = row[bbm]
        atr = row[atr_col]
        bw_percentile = row.get("BB_bw_percentile", 50)

        # Detect squeeze: bandwidth is below the threshold percentile
        is_squeeze = bw_percentile < self.params["squeeze_percentile"]

        # Track if we were in a squeeze recently (within last 5 bars)
        if not hasattr(self, "_squeeze_bars"):
            self._squeeze_bars = 0

        if is_squeeze:
            self._squeeze_bars = 5  # Remember squeeze for 5 bars
        elif self._squeeze_bars > 0:
            self._squeeze_bars -= 1

        # Entry: price breaks above upper band after a squeeze
        if position is None and close > upper_band and self._squeeze_bars > 0:
            stop = close - (atr * self.params["stop_loss_atr_mult"])
            return Signal(
                direction="long",
                stop_loss=stop,
                reason=f"BB breakout after squeeze (bandwidth pctl: {bw_percentile:.0f}%)"
            )

        # Exit: price crosses below middle band
        if position is not None and close < middle_band:
            return Signal(
                direction="close_long",
                reason=f"Price crossed below BB middle band ({middle_band:.2f})"
            )

        return None
