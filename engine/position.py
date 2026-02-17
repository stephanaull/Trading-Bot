"""Position management with stop-loss, take-profit, and trailing stop tracking."""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from engine.order import Trade


@dataclass
class Position:
    """Represents an open position with attached stop/target levels."""
    trade: Trade
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing_stop: Optional[float] = None
    trailing_stop_distance: Optional[float] = None

    @property
    def direction(self) -> str:
        return self.trade.direction

    @property
    def entry_price(self) -> float:
        return self.trade.entry_price

    @property
    def quantity(self) -> float:
        return self.trade.quantity

    @property
    def ticker(self) -> str:
        return self.trade.ticker

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL at a given price."""
        if self.direction == "long":
            return (current_price - self.entry_price) * self.quantity
        else:
            return (self.entry_price - current_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: float) -> float:
        """Calculate unrealized PnL percentage."""
        cost_basis = self.entry_price * self.quantity
        if cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl(current_price) / cost_basis) * 100

    def update_trailing_stop(self, current_price: float) -> None:
        """Update trailing stop based on current price movement."""
        if self.trailing_stop_distance is None:
            return

        if self.direction == "long":
            new_stop = current_price - self.trailing_stop_distance
            if self.trailing_stop is None or new_stop > self.trailing_stop:
                self.trailing_stop = new_stop
        else:  # short
            new_stop = current_price + self.trailing_stop_distance
            if self.trailing_stop is None or new_stop < self.trailing_stop:
                self.trailing_stop = new_stop

    def is_stop_hit(self, bar_low: float, bar_high: float) -> bool:
        """Check if stop-loss or trailing stop is hit within the bar."""
        effective_stop = self._get_effective_stop()
        if effective_stop is None:
            return False

        if self.direction == "long":
            return bar_low <= effective_stop
        else:  # short
            return bar_high >= effective_stop

    def is_target_hit(self, bar_low: float, bar_high: float) -> bool:
        """Check if take-profit is hit within the bar."""
        if self.take_profit is None:
            return False

        if self.direction == "long":
            return bar_high >= self.take_profit
        else:  # short
            return bar_low <= self.take_profit

    def get_stop_fill_price(self) -> Optional[float]:
        """Get the price at which the stop would fill."""
        return self._get_effective_stop()

    def get_target_fill_price(self) -> Optional[float]:
        """Get the price at which the target would fill."""
        return self.take_profit

    def _get_effective_stop(self) -> Optional[float]:
        """Get the tighter of stop_loss and trailing_stop."""
        if self.stop_loss is not None and self.trailing_stop is not None:
            if self.direction == "long":
                return max(self.stop_loss, self.trailing_stop)
            else:
                return min(self.stop_loss, self.trailing_stop)
        return self.stop_loss or self.trailing_stop
