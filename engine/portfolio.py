"""Portfolio state tracking: positions, cash, equity curve, and trade history."""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from engine.order import Trade
from engine.position import Position

logger = logging.getLogger(__name__)


class Portfolio:
    """Tracks portfolio state throughout the backtest."""

    def __init__(self, initial_capital: float = 100_000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position: Optional[Position] = None  # Single position at a time
        self.closed_trades: list[Trade] = []
        self.equity_curve: list[float] = []
        self.timestamps: list[pd.Timestamp] = []
        self.peak_equity = initial_capital
        self._bar_count = 0

    @property
    def has_position(self) -> bool:
        return self.position is not None

    @property
    def current_direction(self) -> Optional[str]:
        return self.position.direction if self.position else None

    def open_position(self, trade: Trade, stop_loss: Optional[float] = None,
                      take_profit: Optional[float] = None,
                      trailing_stop_distance: Optional[float] = None) -> Position:
        """Open a new position from a filled trade.

        Args:
            trade: The executed entry trade
            stop_loss: Stop-loss price level
            take_profit: Take-profit price level
            trailing_stop_distance: Distance for trailing stop

        Returns:
            The created Position
        """
        if self.has_position:
            raise RuntimeError("Cannot open position while another is open. "
                               "Close existing position first.")

        # Deduct entry cost from cash
        cost = trade.entry_price * trade.quantity + trade.commission
        if trade.direction == "long":
            self.cash -= cost
        else:  # short: receive cash from short sale, but still deduct commission
            self.cash += trade.entry_price * trade.quantity - trade.commission

        self.position = Position(
            trade=trade,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop_distance=trailing_stop_distance,
        )

        logger.debug(f"Opened {trade.direction} position: {trade.quantity} @ {trade.entry_price}")
        return self.position

    def close_position(self, closed_trade: Trade) -> float:
        """Close the current position and record the completed trade.

        Args:
            closed_trade: The trade with exit information filled in

        Returns:
            The realized PnL
        """
        if not self.has_position:
            raise RuntimeError("No position to close.")

        # Return capital + PnL to cash
        if closed_trade.direction == "long":
            self.cash += closed_trade.exit_price * closed_trade.quantity - closed_trade.exit_commission
        else:  # short
            self.cash -= closed_trade.exit_price * closed_trade.quantity + closed_trade.exit_commission

        pnl = closed_trade.pnl
        self.closed_trades.append(closed_trade)
        self.position = None

        logger.debug(f"Closed position. PnL: {pnl:.2f}. Cash: {self.cash:.2f}")
        return pnl

    def update_equity(self, timestamp: pd.Timestamp, current_price: float) -> float:
        """Update equity curve at the current bar.

        Args:
            timestamp: Current bar timestamp
            current_price: Current close price for unrealized PnL

        Returns:
            Current total equity
        """
        equity = self.cash
        if self.has_position:
            # Add unrealized PnL
            unrealized = self.position.unrealized_pnl(current_price)
            if self.position.direction == "long":
                equity += self.position.entry_price * self.position.quantity + unrealized
            else:
                equity -= self.position.entry_price * self.position.quantity - unrealized

        self.equity_curve.append(equity)
        self.timestamps.append(timestamp)

        if equity > self.peak_equity:
            self.peak_equity = equity

        self._bar_count += 1
        return equity

    def get_current_equity(self, current_price: float) -> float:
        """Get current equity without recording to the curve."""
        equity = self.cash
        if self.has_position:
            unrealized = self.position.unrealized_pnl(current_price)
            if self.position.direction == "long":
                equity += self.position.entry_price * self.position.quantity + unrealized
            else:
                equity -= self.position.entry_price * self.position.quantity - unrealized
        return equity

    def get_drawdown(self, current_price: float) -> float:
        """Get current drawdown from peak equity."""
        equity = self.get_current_equity(current_price)
        if self.peak_equity == 0:
            return 0.0
        return (equity - self.peak_equity) / self.peak_equity * 100

    def get_equity_series(self) -> pd.Series:
        """Return the equity curve as a pandas Series."""
        return pd.Series(self.equity_curve, index=self.timestamps, name="equity")

    def get_trade_log(self) -> pd.DataFrame:
        """Return all closed trades as a DataFrame."""
        if not self.closed_trades:
            return pd.DataFrame()

        records = []
        for t in self.closed_trades:
            records.append({
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "ticker": t.ticker,
                "direction": t.direction,
                "quantity": t.quantity,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "commission": t.commission + t.exit_commission,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "bars_held": t.bars_held,
                "exit_reason": t.exit_reason,
            })
        return pd.DataFrame(records)

    def calculate_position_size(self, price: float, method: str = "fixed",
                                fixed_amount: float = 10_000.0,
                                pct_equity: float = 0.10,
                                risk_pct: float = 0.02,
                                stop_distance: float = None) -> float:
        """Calculate position size based on method.

        Args:
            price: Current price
            method: "fixed", "percent", or "risk_based"
            fixed_amount: Dollar amount for fixed sizing
            pct_equity: Fraction of equity for percent sizing
            risk_pct: Fraction of equity to risk for risk-based sizing
            stop_distance: Distance to stop-loss for risk-based sizing

        Returns:
            Number of shares/contracts to trade
        """
        equity = self.cash  # Use cash since we may have a position

        if method == "fixed":
            return max(1, int(fixed_amount / price))
        elif method == "percent":
            amount = equity * pct_equity
            return max(1, int(amount / price))
        elif method == "risk_based":
            if stop_distance is None or stop_distance <= 0:
                # Fall back to percent method
                amount = equity * risk_pct
                return max(1, int(amount / price))
            risk_amount = equity * risk_pct
            return max(1, int(risk_amount / stop_distance))
        else:
            raise ValueError(f"Unknown position sizing method: {method}")
