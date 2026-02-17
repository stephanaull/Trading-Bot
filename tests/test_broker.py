"""Tests for the simulated broker module."""

import sys
import os
import pytest
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.broker import SimulatedBroker
from engine.order import Order, Trade
from engine.position import Position


class TestSimulatedBroker:
    def setup_method(self):
        self.broker = SimulatedBroker(commission_rate=0.001, slippage_rate=0.0005)

    def _make_bar(self, open=100, high=105, low=95, close=102, volume=10000):
        return pd.Series({
            "open": open, "high": high, "low": low,
            "close": close, "volume": volume,
        }, name=pd.Timestamp("2023-06-01"))

    def _make_order(self, direction="long", quantity=100, stop_loss=None, take_profit=None):
        return Order(
            timestamp=pd.Timestamp("2023-05-31"),
            ticker="TEST",
            direction=direction,
            order_type="market",
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def test_market_order_fills_at_open(self):
        bar = self._make_bar(open=100)
        order = self._make_order(direction="long", quantity=10)
        trade = self.broker.execute_market_order(order, bar)

        # Should fill near open price (with slippage)
        assert trade.entry_price > 100  # Long = adverse slippage up
        assert trade.quantity == 10
        assert trade.direction == "long"
        assert trade.commission > 0

    def test_slippage_direction(self):
        bar = self._make_bar(open=100)

        # Long: price goes up (adverse)
        long_order = self._make_order(direction="long")
        long_trade = self.broker.execute_market_order(long_order, bar)
        assert long_trade.entry_price > 100

        # Short: price goes down (adverse)
        short_order = self._make_order(direction="short")
        short_trade = self.broker.execute_market_order(short_order, bar)
        assert short_trade.entry_price < 100

    def test_commission_calculation(self):
        commission = self.broker.calculate_commission(100, 150.0)
        expected = 100 * 150.0 * 0.001  # = 15.0
        assert abs(commission - expected) < 0.01

    def test_zero_slippage(self):
        broker = SimulatedBroker(commission_rate=0.001, slippage_rate=0.0)
        slippage = broker.calculate_slippage(100.0, "long")
        assert slippage == 0.0

    def test_stop_loss_hit_long(self):
        trade = Trade(
            entry_time=pd.Timestamp("2023-06-01"),
            ticker="TEST", direction="long",
            quantity=10, entry_price=100,
        )
        position = Position(trade=trade, stop_loss=95.0)

        # Bar where low goes below stop
        bar = self._make_bar(open=99, high=100, low=94, close=96)
        result = self.broker.check_stops_and_targets(position, bar)

        assert result is not None
        assert result["reason"] == "stop_loss"
        assert result["price"] == 95.0

    def test_take_profit_hit_long(self):
        trade = Trade(
            entry_time=pd.Timestamp("2023-06-01"),
            ticker="TEST", direction="long",
            quantity=10, entry_price=100,
        )
        position = Position(trade=trade, take_profit=110.0)

        # Bar where high goes above target
        bar = self._make_bar(open=105, high=112, low=104, close=111)
        result = self.broker.check_stops_and_targets(position, bar)

        assert result is not None
        assert result["reason"] == "take_profit"
        assert result["price"] == 110.0

    def test_no_stop_or_target_hit(self):
        trade = Trade(
            entry_time=pd.Timestamp("2023-06-01"),
            ticker="TEST", direction="long",
            quantity=10, entry_price=100,
        )
        position = Position(trade=trade, stop_loss=90.0, take_profit=120.0)

        # Normal bar, no extremes
        bar = self._make_bar(open=101, high=105, low=98, close=103)
        result = self.broker.check_stops_and_targets(position, bar)

        assert result is None
