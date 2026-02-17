"""Order and Trade dataclasses for the backtesting engine."""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class Order:
    """Represents a pending order to be executed by the broker."""
    timestamp: pd.Timestamp
    ticker: str
    direction: str          # "long" or "short"
    order_type: str         # "market", "limit", "stop"
    quantity: float
    price: Optional[float] = None  # limit/stop price (None for market)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reason: str = ""


@dataclass
class Trade:
    """Represents an executed trade (entry or exit)."""
    entry_time: pd.Timestamp
    ticker: str
    direction: str          # "long" or "short"
    quantity: float
    entry_price: float
    commission: float = 0.0
    slippage: float = 0.0
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_commission: float = 0.0
    exit_slippage: float = 0.0
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    bars_held: int = 0
    exit_reason: str = ""

    def close(self, exit_time: pd.Timestamp, exit_price: float,
              exit_commission: float = 0.0, exit_slippage: float = 0.0,
              bars_held: int = 0, exit_reason: str = "") -> None:
        """Close this trade and compute PnL."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_commission = exit_commission
        self.exit_slippage = exit_slippage
        self.bars_held = bars_held
        self.exit_reason = exit_reason

        total_commission = self.commission + self.exit_commission
        if self.direction == "long":
            self.pnl = (self.exit_price - self.entry_price) * self.quantity - total_commission
        else:  # short
            self.pnl = (self.entry_price - self.exit_price) * self.quantity - total_commission

        cost_basis = self.entry_price * self.quantity
        self.pnl_pct = (self.pnl / cost_basis) * 100 if cost_basis > 0 else 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    @property
    def is_winner(self) -> bool:
        return self.pnl is not None and self.pnl > 0

    @property
    def is_loser(self) -> bool:
        return self.pnl is not None and self.pnl < 0
