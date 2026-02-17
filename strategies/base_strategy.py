"""Abstract base class for all trading strategies.

Every strategy must subclass BaseStrategy and implement:
- setup(df): Add required indicators to the DataFrame
- on_bar(idx, row, position): Return a Signal or None for each bar

The class inside every strategy file must be named 'Strategy' for dynamic loading.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class Signal:
    """A trading signal emitted by a strategy.

    Attributes:
        direction: "long", "short", "close_long", "close_short", or "flat"
        strength: Signal strength 0.0-1.0 (can be used for position sizing)
        stop_loss: Absolute stop-loss price level
        take_profit: Absolute take-profit price level
        trailing_stop_distance: Distance for trailing stop (in price units)
        reason: Human-readable reason for the signal
    """
    direction: str
    strength: float = 1.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop_distance: Optional[float] = None
    reason: str = ""


class BaseStrategy(ABC):
    """Abstract base class that all strategies must inherit from.

    Example:
        class Strategy(BaseStrategy):
            name = "My EMA Strategy"
            version = "v1"

            def setup(self, df):
                from engine.indicators import Indicators
                df = Indicators.add(df, 'ema', length=9)
                df = Indicators.add(df, 'ema', length=21)
                return df

            def on_bar(self, idx, row, position):
                if position is None and row['EMA_9'] > row['EMA_21']:
                    return Signal(direction='long', stop_loss=row['close'] * 0.95)
                elif position is not None and row['EMA_9'] < row['EMA_21']:
                    return Signal(direction='close_long', reason='EMA crossunder')
                return None
    """

    # Metadata -- override in each strategy
    name: str = "Unnamed Strategy"
    version: str = "v1"
    description: str = ""
    ticker: str = ""
    timeframe: str = "1d"

    # Pine Script export metadata
    pine_indicators: list = []
    pine_conditions: dict = {}

    def __init__(self, params: dict = None):
        """Initialize with optional parameter overrides.

        Args:
            params: Dictionary of strategy parameters (overrides defaults)
        """
        self.params = params or {}

    @abstractmethod
    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add required indicators to the DataFrame. Called once before backtest.

        Must return the modified DataFrame with indicator columns added.
        Use engine.indicators.Indicators.add() to add indicators.

        Args:
            df: DataFrame with OHLCV data (columns: open, high, low, close, volume)

        Returns:
            DataFrame with indicator columns added
        """
        ...

    @abstractmethod
    def on_bar(self, idx: int, row: pd.Series,
               position: Optional[object] = None) -> Optional[Signal]:
        """Called for each bar during the backtest.

        This is where your strategy logic lives. Evaluate the current bar's
        data (OHLCV + indicators) and decide whether to enter, exit, or do nothing.

        IMPORTANT: Only use data from the current row. The engine ensures
        no future data is available (no look-ahead bias).

        Args:
            idx: Current bar index (0-based)
            row: Current bar's data (OHLCV + all indicator columns)
            position: Current open Position object, or None if flat

        Returns:
            Signal to act on, or None to do nothing
        """
        ...

    def on_trade_closed(self, trade) -> None:
        """Optional callback when a trade closes. Override for adaptive strategies.

        Args:
            trade: The closed Trade object with PnL information
        """
        pass

    def get_pine_metadata(self) -> dict:
        """Return metadata needed for Pine Script export.

        Returns:
            Dictionary with name, version, indicators, conditions, and params
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "ticker": self.ticker,
            "timeframe": self.timeframe,
            "indicators": self.pine_indicators,
            "conditions": self.pine_conditions,
            "params": self.params,
        }
