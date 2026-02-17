"""Main BacktestEngine: bar-by-bar event loop orchestrating the backtest.

This is the central file that ties together the broker, portfolio, strategy,
and metrics to run a complete trading strategy backtest.
"""

import logging
from typing import Optional
from dataclasses import dataclass

import pandas as pd
import numpy as np

from engine.broker import SimulatedBroker
from engine.portfolio import Portfolio
from engine.order import Order, Trade
from engine.position import Position
from engine.metrics import Metrics
from strategies.base_strategy import BaseStrategy, Signal

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Container for backtest results."""
    strategy_name: str
    metrics: dict
    equity_curve: pd.Series
    trades: list
    trade_log: pd.DataFrame
    data: pd.DataFrame

    def print_summary(self) -> None:
        """Print formatted performance summary."""
        m = Metrics(
            self.trades,
            self.equity_curve,
            initial_capital=self.equity_curve.iloc[0] if len(self.equity_curve) > 0 else 100000,
        )
        m.print_summary(self.strategy_name)


class BacktestEngine:
    """Main backtesting engine using bar-by-bar iteration.

    The engine processes each bar sequentially:
    1. Check if pending stop-loss or take-profit is hit
    2. Update trailing stops
    3. Call strategy.on_bar() to get a signal
    4. Execute any resulting orders via the broker
    5. Update portfolio equity

    Anti-lookahead guarantee: at bar index i, the strategy only sees
    data from index 0 through i.
    """

    def __init__(self, data: pd.DataFrame, strategy: BaseStrategy,
                 initial_capital: float = 100_000.0,
                 commission: float = 0.001,
                 slippage: float = 0.0005,
                 position_sizing: str = "fixed",
                 fixed_size: float = 10_000.0,
                 pct_equity: float = 0.10,
                 risk_pct: float = 0.02,
                 fill_on_close: bool = False):
        """
        Args:
            data: OHLCV DataFrame with datetime index
            strategy: Strategy instance (must subclass BaseStrategy)
            initial_capital: Starting capital in dollars
            commission: Commission rate (0.001 = 0.1%)
            slippage: Slippage rate (0.0005 = 0.05%)
            position_sizing: "fixed", "percent", or "risk_based"
            fixed_size: Dollar amount for fixed position sizing
            pct_equity: Fraction of equity for percent sizing
            risk_pct: Fraction of equity to risk for risk-based sizing
            fill_on_close: If True, fill on same bar's close (TradingView default).
                          If False, fill on next bar's open (more realistic).
        """
        self.data = data.copy()
        self.strategy = strategy
        self.initial_capital = initial_capital
        self.position_sizing = position_sizing
        self.fixed_size = fixed_size
        self.pct_equity = pct_equity
        self.risk_pct = risk_pct
        self.fill_on_close = fill_on_close

        self.broker = SimulatedBroker(
            commission_rate=commission,
            slippage_rate=slippage,
        )
        self.portfolio = Portfolio(initial_capital=initial_capital)

        # Pending signal to execute on next bar (when fill_on_close=False)
        self._pending_signal: Optional[Signal] = None
        self._pending_bar_idx: Optional[int] = None

    def run(self) -> BacktestResult:
        """Run the backtest.

        Returns:
            BacktestResult with metrics, equity curve, trades, and trade log
        """
        logger.info(f"Starting backtest: {self.strategy.name} {self.strategy.version}")
        logger.info(f"Capital: ${self.initial_capital:,.0f} | "
                     f"Commission: {self.broker.commission_rate*100:.2f}% | "
                     f"Slippage: {self.broker.slippage_rate*100:.3f}%")

        # Phase 1: Setup - add indicators to data
        self.data = self.strategy.setup(self.data)

        # Phase 2: Bar-by-bar iteration
        for idx in range(len(self.data)):
            bar = self.data.iloc[idx]
            self._process_bar(idx, bar)

        # Phase 3: Force close any open position at the last bar
        if self.portfolio.has_position:
            last_bar = self.data.iloc[-1]
            self._force_close(last_bar, "end_of_data")

        # Phase 4: Compute metrics
        equity_series = self.portfolio.get_equity_series()
        metrics_calc = Metrics(
            self.portfolio.closed_trades,
            equity_series,
            initial_capital=self.initial_capital,
        )
        metrics = metrics_calc.calculate_all()

        logger.info(f"Backtest complete. {metrics['total_trades']} trades, "
                     f"Net: ${metrics['net_profit']:,.2f} ({metrics['net_profit_pct']:.2f}%)")

        return BacktestResult(
            strategy_name=f"{self.strategy.name} {self.strategy.version}",
            metrics=metrics,
            equity_curve=equity_series,
            trades=self.portfolio.closed_trades,
            trade_log=self.portfolio.get_trade_log(),
            data=self.data,
        )

    def _process_bar(self, idx: int, bar: pd.Series) -> None:
        """Process a single bar in the backtest loop.

        Order of operations:
        1. Execute pending order from previous bar (if fill_on_close=False)
        2. Check stop-loss / take-profit on current bar
        3. Update trailing stop
        4. Call strategy.on_bar()
        5. Process the returned signal
        6. Update equity
        """
        # Step 1: Execute pending signal from previous bar
        if self._pending_signal is not None and not self.fill_on_close:
            self._execute_signal(self._pending_signal, bar, idx)
            self._pending_signal = None

        # Step 2: Check stops and targets
        if self.portfolio.has_position:
            exit_info = self.broker.check_stops_and_targets(
                self.portfolio.position, bar
            )
            if exit_info:
                self._close_position(bar, exit_info["price"], exit_info["reason"], idx)

        # Step 3: Update trailing stop
        if self.portfolio.has_position:
            self.portfolio.position.update_trailing_stop(bar["close"])

        # Step 4: Call strategy
        signal = self.strategy.on_bar(
            idx, bar,
            position=self.portfolio.position,
        )

        # Step 5: Process signal
        if signal is not None:
            if self.fill_on_close:
                # Fill immediately at this bar's close
                self._execute_signal_at_close(signal, bar, idx)
            else:
                # Queue for next bar's open
                self._pending_signal = signal
                self._pending_bar_idx = idx

        # Step 6: Update equity
        timestamp = bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp(bar.name)
        self.portfolio.update_equity(timestamp, bar["close"])

    def _execute_signal(self, signal: Signal, fill_bar: pd.Series, bar_idx: int) -> None:
        """Execute a signal at the fill bar's open price."""
        if signal.direction in ("long", "short"):
            self._open_position(signal, fill_bar, bar_idx)
        elif signal.direction in ("close_long", "close_short", "flat"):
            if self.portfolio.has_position:
                exit_price = fill_bar["open"]
                slippage = self.broker.calculate_slippage(
                    exit_price,
                    "short" if self.portfolio.position.direction == "long" else "long"
                )
                self._close_position(
                    fill_bar, exit_price + slippage,
                    signal.reason or "strategy_exit", bar_idx
                )

    def _execute_signal_at_close(self, signal: Signal, bar: pd.Series, bar_idx: int) -> None:
        """Execute a signal at the current bar's close price."""
        if signal.direction in ("long", "short"):
            self._open_position_at_close(signal, bar, bar_idx)
        elif signal.direction in ("close_long", "close_short", "flat"):
            if self.portfolio.has_position:
                self._close_position(bar, bar["close"], signal.reason or "strategy_exit", bar_idx)

    def _open_position(self, signal: Signal, fill_bar: pd.Series, bar_idx: int) -> None:
        """Open a new position at the fill bar's open."""
        if self.portfolio.has_position:
            return  # Already have a position

        price = fill_bar["open"]
        quantity = self._calculate_quantity(price, signal)

        order = Order(
            timestamp=fill_bar.name if isinstance(fill_bar.name, pd.Timestamp)
                      else pd.Timestamp(fill_bar.name),
            ticker=self.strategy.ticker or "UNKNOWN",
            direction=signal.direction,
            order_type="market",
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
        )

        trade = self.broker.execute_market_order(order, fill_bar)
        self.portfolio.open_position(
            trade,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            trailing_stop_distance=signal.trailing_stop_distance,
        )

    def _open_position_at_close(self, signal: Signal, bar: pd.Series, bar_idx: int) -> None:
        """Open a new position at the bar's close."""
        if self.portfolio.has_position:
            return

        price = bar["close"]
        quantity = self._calculate_quantity(price, signal)
        slippage = self.broker.calculate_slippage(price, signal.direction)
        fill_price = price + slippage
        commission = self.broker.calculate_commission(quantity, fill_price)

        timestamp = bar.name if isinstance(bar.name, pd.Timestamp) else pd.Timestamp(bar.name)

        trade = Trade(
            entry_time=timestamp,
            ticker=self.strategy.ticker or "UNKNOWN",
            direction=signal.direction,
            quantity=quantity,
            entry_price=fill_price,
            commission=commission,
            slippage=abs(slippage) * quantity,
        )

        self.portfolio.open_position(
            trade,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            trailing_stop_distance=signal.trailing_stop_distance,
        )

    def _close_position(self, bar: pd.Series, exit_price: float,
                        reason: str, bar_idx: int = 0) -> None:
        """Close the current position at the given price."""
        if not self.portfolio.has_position:
            return

        position = self.portfolio.position
        entry_idx = self._find_entry_bar_idx(position.trade.entry_time)
        bars_held = bar_idx - entry_idx if entry_idx is not None else 0

        position.trade.bars_held = bars_held
        closed_trade = self.broker.execute_exit(position, bar, exit_price, reason)
        self.portfolio.close_position(closed_trade)

        # Notify strategy
        self.strategy.on_trade_closed(closed_trade)

    def _force_close(self, bar: pd.Series, reason: str) -> None:
        """Force close position at bar's close price."""
        if self.portfolio.has_position:
            self._close_position(bar, bar["close"], reason, len(self.data) - 1)

    def _calculate_quantity(self, price: float, signal: Signal) -> float:
        """Calculate position size based on the configured method."""
        stop_distance = None
        if signal.stop_loss is not None:
            stop_distance = abs(price - signal.stop_loss)

        return self.portfolio.calculate_position_size(
            price=price,
            method=self.position_sizing,
            fixed_amount=self.fixed_size,
            pct_equity=self.pct_equity,
            risk_pct=self.risk_pct,
            stop_distance=stop_distance,
        )

    def _find_entry_bar_idx(self, entry_time: pd.Timestamp) -> Optional[int]:
        """Find the bar index for a given entry timestamp."""
        try:
            return self.data.index.get_loc(entry_time)
        except KeyError:
            # Entry time might not match exactly; find nearest
            idx = self.data.index.searchsorted(entry_time)
            return int(idx) if idx < len(self.data) else None
