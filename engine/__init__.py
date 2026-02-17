"""Trading Backtest Engine - Core Package.

Usage:
    from engine.backtest import BacktestEngine
    from engine.data_loader import DataLoader
    from engine.indicators import Indicators
    from engine.metrics import Metrics
"""

from engine.backtest import BacktestEngine, BacktestResult
from engine.data_loader import DataLoader
from engine.indicators import Indicators
from engine.metrics import Metrics
from engine.portfolio import Portfolio
from engine.broker import SimulatedBroker

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "DataLoader",
    "Indicators",
    "Metrics",
    "Portfolio",
    "SimulatedBroker",
]
