"""Tests for performance metrics calculations."""

import sys
import os
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.metrics import Metrics
from engine.order import Trade


def _make_trade(pnl, direction="long", bars_held=5):
    """Helper to create a closed trade with a specific PnL."""
    t = Trade(
        entry_time=pd.Timestamp("2023-01-01"),
        ticker="TEST", direction=direction,
        quantity=10, entry_price=100,
    )
    t.close(
        exit_time=pd.Timestamp("2023-01-06"),
        exit_price=100 + (pnl / 10) if direction == "long" else 100 - (pnl / 10),
        bars_held=bars_held,
    )
    # Override PnL for precision
    t.pnl = pnl
    t.pnl_pct = (pnl / (100 * 10)) * 100
    return t


def _make_equity_curve(values, start_date="2023-01-01"):
    """Helper to create an equity curve Series."""
    dates = pd.date_range(start_date, periods=len(values), freq="D")
    return pd.Series(values, index=dates, name="equity")


class TestMetricsBasic:
    def test_net_profit(self):
        trades = [_make_trade(100), _make_trade(-50), _make_trade(200)]
        equity = _make_equity_curve([100000, 100100, 100050, 100250])
        m = Metrics(trades, equity, initial_capital=100000)
        assert m.net_profit() == 250.0

    def test_gross_profit_and_loss(self):
        trades = [_make_trade(100), _make_trade(-50), _make_trade(200)]
        equity = _make_equity_curve([100000, 100100, 100050, 100250])
        m = Metrics(trades, equity, initial_capital=100000)
        assert m.gross_profit() == 300.0
        assert m.gross_loss() == -50.0

    def test_win_rate(self):
        trades = [_make_trade(100), _make_trade(-50), _make_trade(200)]
        equity = _make_equity_curve([100000, 100100, 100050, 100250])
        m = Metrics(trades, equity, initial_capital=100000)
        assert abs(m.win_rate() - 66.67) < 0.1

    def test_profit_factor(self):
        trades = [_make_trade(100), _make_trade(-50), _make_trade(200)]
        equity = _make_equity_curve([100000, 100100, 100050, 100250])
        m = Metrics(trades, equity, initial_capital=100000)
        assert abs(m.profit_factor() - 6.0) < 0.01  # 300 / 50

    def test_total_trades(self):
        trades = [_make_trade(100), _make_trade(-50)]
        equity = _make_equity_curve([100000, 100100, 100050])
        m = Metrics(trades, equity, initial_capital=100000)
        assert m.total_trades() == 2
        assert m.winning_trades() == 1
        assert m.losing_trades() == 1


class TestMetricsDrawdown:
    def test_max_drawdown(self):
        equity = _make_equity_curve([100000, 105000, 103000, 101000, 106000])
        m = Metrics([], equity, initial_capital=100000)
        # Peak at 105000, lowest after peak at 101000 = -4000
        assert m.max_drawdown() == -4000.0

    def test_max_drawdown_pct(self):
        equity = _make_equity_curve([100000, 105000, 103000, 101000, 106000])
        m = Metrics([], equity, initial_capital=100000)
        # -4000 / 105000 * 100 = -3.81%
        assert abs(m.max_drawdown_pct() - (-4000 / 105000 * 100)) < 0.01

    def test_no_drawdown(self):
        equity = _make_equity_curve([100000, 101000, 102000, 103000])
        m = Metrics([], equity, initial_capital=100000)
        assert m.max_drawdown() == 0.0


class TestMetricsStreaks:
    def test_consecutive_wins(self):
        trades = [_make_trade(100), _make_trade(50), _make_trade(75),
                  _make_trade(-30), _make_trade(60)]
        equity = _make_equity_curve([100000] * 6)
        m = Metrics(trades, equity, initial_capital=100000)
        assert m.max_consecutive_wins() == 3

    def test_consecutive_losses(self):
        trades = [_make_trade(100), _make_trade(-50), _make_trade(-30),
                  _make_trade(-20), _make_trade(60)]
        equity = _make_equity_curve([100000] * 6)
        m = Metrics(trades, equity, initial_capital=100000)
        assert m.max_consecutive_losses() == 3

    def test_no_trades(self):
        equity = _make_equity_curve([100000])
        m = Metrics([], equity, initial_capital=100000)
        assert m.total_trades() == 0
        assert m.win_rate() == 0.0
        assert m.max_consecutive_wins() == 0


class TestMetricsRatios:
    def test_risk_reward(self):
        trades = [_make_trade(200), _make_trade(-100), _make_trade(300), _make_trade(-100)]
        equity = _make_equity_curve([100000] * 5)
        m = Metrics(trades, equity, initial_capital=100000)
        # avg win = 250, avg loss = -100, R:R = 250/100 = 2.5
        assert abs(m.risk_reward_ratio() - 2.5) < 0.01

    def test_expectancy(self):
        trades = [_make_trade(200), _make_trade(-100), _make_trade(300), _make_trade(-100)]
        equity = _make_equity_curve([100000] * 5)
        m = Metrics(trades, equity, initial_capital=100000)
        # win_rate=50%, avg_win=250, avg_loss=-100
        # expectancy = 0.5 * 250 + 0.5 * (-100) = 75
        assert abs(m.expectancy() - 75.0) < 0.01

    def test_profit_factor_no_losses(self):
        trades = [_make_trade(100), _make_trade(200)]
        equity = _make_equity_curve([100000, 100100, 100300])
        m = Metrics(trades, equity, initial_capital=100000)
        assert m.profit_factor() == float("inf")

    def test_calculate_all_returns_dict(self):
        trades = [_make_trade(100), _make_trade(-50)]
        equity = _make_equity_curve([100000, 100100, 100050])
        m = Metrics(trades, equity, initial_capital=100000)
        result = m.calculate_all()
        assert isinstance(result, dict)
        assert "net_profit" in result
        assert "sharpe_ratio" in result
        assert "win_rate_pct" in result
