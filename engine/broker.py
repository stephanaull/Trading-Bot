"""Simulated broker: order execution with commissions, slippage, and stop/target fills."""

import logging
from typing import Optional

import pandas as pd

from engine.order import Order, Trade
from engine.position import Position

logger = logging.getLogger(__name__)


class SimulatedBroker:
    """Simulates order execution with realistic fills.

    Fill logic (matching TradingView defaults):
    - Market orders fill at the bar's open price + slippage
    - Stop-loss checked against bar low (long) or bar high (short)
    - Take-profit checked against bar high (long) or bar low (short)
    - Intrabar fill order: Open -> nearest of High/Low to Open -> other -> Close
    """

    def __init__(self, commission_rate: float = 0.001, slippage_rate: float = 0.0005):
        """
        Args:
            commission_rate: Per-trade commission as fraction of trade value (0.001 = 0.1%)
            slippage_rate: Slippage as fraction of price (0.0005 = 0.05%)
        """
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate

    def execute_market_order(self, order: Order, fill_bar: pd.Series) -> Trade:
        """Execute a market order at the fill bar's open price + slippage.

        Args:
            order: The order to execute
            fill_bar: The bar at which the order fills (next bar after signal)

        Returns:
            A Trade representing the executed entry
        """
        base_price = fill_bar["open"]
        slippage = self.calculate_slippage(base_price, order.direction)
        fill_price = base_price + slippage

        commission = self.calculate_commission(order.quantity, fill_price)

        trade = Trade(
            entry_time=fill_bar.name if isinstance(fill_bar.name, pd.Timestamp)
                       else pd.Timestamp(fill_bar.name),
            ticker=order.ticker,
            direction=order.direction,
            quantity=order.quantity,
            entry_price=fill_price,
            commission=commission,
            slippage=abs(slippage) * order.quantity,
        )

        logger.debug(f"Filled {order.direction} {order.quantity} {order.ticker} "
                      f"@ {fill_price:.4f} (slippage: {slippage:.4f}, commission: {commission:.2f})")
        return trade

    def check_stops_and_targets(self, position: Position, bar: pd.Series) -> Optional[dict]:
        """Check if stop-loss or take-profit is hit within the current bar.

        Uses TradingView's intrabar assumption:
        1. Open price is evaluated first
        2. Whichever of High/Low is closer to Open is evaluated next
        3. Then the other
        4. Close is evaluated last

        Returns:
            dict with 'price', 'reason' if hit, None otherwise
        """
        bar_open = bar["open"]
        bar_high = bar["high"]
        bar_low = bar["low"]

        stop_hit = position.is_stop_hit(bar_low, bar_high)
        target_hit = position.is_target_hit(bar_low, bar_high)

        if not stop_hit and not target_hit:
            return None

        # Both hit in same bar -- determine which was hit first using TradingView logic
        if stop_hit and target_hit:
            return self._resolve_both_hit(position, bar_open, bar_high, bar_low)

        if stop_hit:
            stop_price = position.get_stop_fill_price()
            return {"price": stop_price, "reason": "stop_loss"}

        # target_hit
        target_price = position.get_target_fill_price()
        return {"price": target_price, "reason": "take_profit"}

    def _resolve_both_hit(self, position: Position, bar_open: float,
                          bar_high: float, bar_low: float) -> dict:
        """When both stop and target are hit in the same bar, determine which was first.

        TradingView assumption: the price that is closer to open is hit first.
        """
        stop_price = position.get_stop_fill_price()
        target_price = position.get_target_fill_price()

        if position.direction == "long":
            # For long: stop is below, target is above
            dist_to_stop = abs(bar_open - stop_price) if stop_price else float("inf")
            dist_to_target = abs(bar_open - target_price) if target_price else float("inf")
        else:
            # For short: stop is above, target is below
            dist_to_stop = abs(bar_open - stop_price) if stop_price else float("inf")
            dist_to_target = abs(bar_open - target_price) if target_price else float("inf")

        if dist_to_stop <= dist_to_target:
            return {"price": stop_price, "reason": "stop_loss"}
        else:
            return {"price": target_price, "reason": "take_profit"}

    def execute_exit(self, position: Position, exit_bar: pd.Series,
                     exit_price: float, exit_reason: str) -> Trade:
        """Execute an exit (close a position) at the given price.

        Args:
            position: The position to close
            exit_bar: The bar at which the exit occurs
            exit_price: The fill price for the exit
            exit_reason: Why the position was closed

        Returns:
            The closed Trade with PnL computed
        """
        slippage = self.calculate_slippage(exit_price,
                                           "short" if position.direction == "long" else "long")
        fill_price = exit_price + slippage
        commission = self.calculate_commission(position.quantity, fill_price)

        exit_time = exit_bar.name if isinstance(exit_bar.name, pd.Timestamp) \
                    else pd.Timestamp(exit_bar.name)

        position.trade.close(
            exit_time=exit_time,
            exit_price=fill_price,
            exit_commission=commission,
            exit_slippage=abs(slippage) * position.quantity,
            exit_reason=exit_reason,
        )

        logger.debug(f"Closed {position.direction} {position.ticker} "
                      f"@ {fill_price:.4f} ({exit_reason}) PnL: {position.trade.pnl:.2f}")
        return position.trade

    def calculate_slippage(self, price: float, direction: str) -> float:
        """Calculate slippage amount (adverse price movement).

        For buys (long entry, short exit): price increases
        For sells (short entry, long exit): price decreases
        """
        if self.slippage_rate == 0:
            return 0.0
        amount = price * self.slippage_rate
        if direction == "long":
            return amount    # Higher fill for buys
        else:
            return -amount   # Lower fill for sells

    def calculate_commission(self, quantity: float, price: float) -> float:
        """Calculate commission cost for a trade."""
        return abs(quantity * price * self.commission_rate)
