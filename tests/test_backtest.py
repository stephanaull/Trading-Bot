"""Integration tests for the backtest engine."""

import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.backtest import BacktestEngine, BacktestResult
from engine.data_loader import DataLoader

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
SAMPLE_CSV = os.path.join(FIXTURES_DIR, "sample_ohlcv.csv")


def _load_ema_strategy():
    """Load the example EMA cross strategy."""
    import importlib.util
    strategy_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  "strategies", "example_ema_cross.py")
    spec = importlib.util.spec_from_file_location("ema_strat", strategy_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Strategy()


class TestBacktestEngine:
    def test_basic_run(self):
        """Test that a backtest runs and produces results."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()
        engine = BacktestEngine(data, strategy, initial_capital=100000)
        result = engine.run()

        assert isinstance(result, BacktestResult)
        assert result.strategy_name is not None
        assert len(result.equity_curve) > 0
        assert isinstance(result.metrics, dict)

    def test_equity_curve_length(self):
        """Equity curve should have one entry per bar."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()
        engine = BacktestEngine(data, strategy, initial_capital=100000)
        result = engine.run()

        assert len(result.equity_curve) == len(data)

    def test_initial_equity(self):
        """First equity value should be close to initial capital."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()
        engine = BacktestEngine(data, strategy, initial_capital=50000)
        result = engine.run()

        # First bar equity should be approximately initial capital
        first_equity = result.equity_curve.iloc[0]
        assert abs(first_equity - 50000) < 5000  # Within 10% (position might open bar 0)

    def test_metrics_populated(self):
        """All expected metric keys should be present."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()
        engine = BacktestEngine(data, strategy, initial_capital=100000)
        result = engine.run()

        expected_keys = [
            "net_profit", "net_profit_pct", "max_drawdown", "sharpe_ratio",
            "profit_factor", "win_rate_pct", "total_trades",
        ]
        for key in expected_keys:
            assert key in result.metrics, f"Missing metric: {key}"

    def test_trade_log(self):
        """Trade log should be a DataFrame with expected columns."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()
        engine = BacktestEngine(data, strategy, initial_capital=100000)
        result = engine.run()

        if len(result.trades) > 0:
            assert isinstance(result.trade_log, pd.DataFrame)
            assert "entry_time" in result.trade_log.columns
            assert "pnl" in result.trade_log.columns

    def test_no_negative_equity(self):
        """Equity should never go negative (with reasonable parameters)."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()
        engine = BacktestEngine(data, strategy, initial_capital=100000)
        result = engine.run()

        assert result.equity_curve.min() > 0

    def test_different_capital(self):
        """Different initial capital should produce different absolute results."""
        data = DataLoader.from_csv(SAMPLE_CSV)
        strategy = _load_ema_strategy()

        result_50k = BacktestEngine(data, strategy, initial_capital=50000).run()
        # Reload strategy to reset state
        strategy2 = _load_ema_strategy()
        result_100k = BacktestEngine(data, strategy2, initial_capital=100000).run()

        assert result_50k.equity_curve.iloc[0] != result_100k.equity_curve.iloc[0]
