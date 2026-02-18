"""Live trading engine — mirrors BacktestEngine._process_bar() against a real broker.

For each new bar:
1. Append bar to rolling DataFrame
2. Recompute indicators via strategy.setup()
3. Check stop/target levels (locally — broker also has stops as safety net)
4. Call strategy.on_bar() — identical to backtest
5. If Signal returned: validate via risk manager, submit to broker
6. Log trade, update daily report

Single position per ticker (matching backtest behavior).
"""

import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from strategies.base_strategy import BaseStrategy, Signal
from engine.order import Order, Trade
from engine.position import Position

from bot.broker.base import BaseBroker, OrderRejectedException
from bot.engine.reconciler import Reconciler
from bot.notifications.daily_report import DailyReport

logger = logging.getLogger(__name__)

# Max DataFrame rows to keep (prevents unbounded growth)
MAX_BARS = 500


class LiveEngine:
    """Live trading engine for a single ticker.

    One LiveEngine per ticker. Each receives aggregated bars from the feed
    and runs the assigned strategy against a shared broker.
    """

    def __init__(
        self,
        ticker: str,
        strategy: BaseStrategy,
        broker: BaseBroker,
        daily_report: DailyReport,
        initial_df: pd.DataFrame,
        position_sizing: str = "percent",
        pct_equity: float = 0.90,
        fixed_size: float = 10_000.0,
        risk_pct: float = 0.02,
    ):
        """
        Args:
            ticker: Symbol this engine manages (e.g., "MSTR")
            strategy: Warmed-up strategy instance
            broker: Connected broker for order execution
            daily_report: Shared daily report for logging trades
            initial_df: DataFrame from warmup (indicators already computed)
            position_sizing: "fixed", "percent", "risk_based"
            pct_equity: Fraction of equity for percent sizing
            fixed_size: Dollar amount for fixed sizing
            risk_pct: Fraction of equity to risk for risk_based sizing
        """
        self.ticker = ticker
        self.strategy = strategy
        self.broker = broker
        self.daily_report = daily_report
        self._df = initial_df.copy()
        self._position: Optional[Position] = None
        self._bar_count = 0
        self._reconciler = Reconciler()

        # Position sizing config
        self._sizing_method = position_sizing
        self._pct_equity = pct_equity
        self._fixed_size = fixed_size
        self._risk_pct = risk_pct

        # Track if we're actively trading
        self.active = True

    async def on_bar(self, ticker: str, bar: pd.Series) -> None:
        """Process a new aggregated bar. Called by the data feed.

        This is the core loop — mirrors BacktestEngine._process_bar().

        Args:
            ticker: Symbol (should match self.ticker)
            bar: OHLCV pd.Series with name=pd.Timestamp
        """
        if not self.active:
            return

        if ticker != self.ticker:
            return

        self._bar_count += 1

        # Step 1: Append bar to rolling DataFrame
        self._df = pd.concat([self._df, bar.to_frame().T])
        self._df.index.name = "date"

        # Trim to prevent unbounded growth
        if len(self._df) > MAX_BARS:
            self._df = self._df.iloc[-MAX_BARS:]

        # Step 2: Recompute indicators
        try:
            self._df = self.strategy.setup(self._df)
        except Exception as e:
            logger.error(f"[{self.ticker}] Indicator error: {e}")
            return

        # Current bar index (last row)
        idx = len(self._df) - 1
        row = self._df.iloc[-1]

        # Step 3: Check stops and targets locally
        if self._position is not None:
            await self._check_stops(row)

        # Step 4: Update trailing stop
        if self._position is not None:
            self._position.update_trailing_stop(row["close"])

        # Step 5: Call strategy
        try:
            signal = self.strategy.on_bar(idx, row, position=self._position)
        except Exception as e:
            logger.error(f"[{self.ticker}] Strategy error on bar {idx}: {e}")
            self.daily_report.log_error(f"{self.ticker}: Strategy error — {e}")
            return

        # Step 6: Execute signal
        if signal is not None:
            await self._execute_signal(signal, row)

        # Log heartbeat every 10 bars
        if self._bar_count % 10 == 0:
            pos_str = (
                f"{self._position.direction} {self._position.quantity:.0f} "
                f"@ ${self._position.entry_price:.2f}"
                if self._position else "flat"
            )
            logger.info(
                f"[{self.ticker}] Bar {self._bar_count}: "
                f"close=${row['close']:.2f}, position={pos_str}"
            )

    async def _execute_signal(self, signal: Signal, row: pd.Series) -> None:
        """Execute a trading signal via the broker."""
        if signal.direction in ("long", "short"):
            await self._open_position(signal, row)
        elif signal.direction in ("close_long", "close_short", "flat"):
            await self._close_position(signal, row)

    async def _open_position(self, signal: Signal, row: pd.Series) -> None:
        """Open a new position."""
        if self._position is not None:
            logger.debug(f"[{self.ticker}] Already in position, ignoring entry signal")
            return

        price = row["close"]
        quantity = await self._calculate_quantity(price, signal)

        if quantity <= 0:
            logger.warning(f"[{self.ticker}] Calculated quantity = 0, skipping")
            return

        order = Order(
            timestamp=pd.Timestamp.now(tz="UTC"),
            ticker=self.ticker,
            direction=signal.direction,
            order_type="market",
            quantity=quantity,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
        )

        try:
            trade = await self.broker.submit_order(order)
        except OrderRejectedException as e:
            logger.error(f"[{self.ticker}] Order rejected: {e.reason}")
            self.daily_report.log_error(f"{self.ticker}: Order rejected — {e.reason}")
            return
        except Exception as e:
            logger.error(f"[{self.ticker}] Order submission failed: {e}")
            self.daily_report.log_error(f"{self.ticker}: Order error — {e}")
            return

        # Create local position to track
        self._position = Position(
            trade=trade,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            trailing_stop_distance=signal.trailing_stop_distance,
        )

        logger.info(
            f"[{self.ticker}] ENTRY: {signal.direction} {trade.quantity:.0f} "
            f"@ ${trade.entry_price:.2f} "
            f"(SL: ${signal.stop_loss:.2f if signal.stop_loss else 0}, "
            f"TP: ${signal.take_profit:.2f if signal.take_profit else 0}) "
            f"— {signal.reason}"
        )

        self.daily_report.log_trade_entry(
            ticker=self.ticker,
            direction=signal.direction,
            quantity=trade.quantity,
            price=trade.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=signal.reason,
        )

    async def _close_position(self, signal: Signal, row: pd.Series) -> None:
        """Close the current position."""
        if self._position is None:
            return

        try:
            close_result = await self.broker.close_position(self.ticker)
        except Exception as e:
            logger.error(f"[{self.ticker}] Failed to close position: {e}")
            self.daily_report.log_error(f"{self.ticker}: Close failed — {e}")
            return

        if close_result is None:
            logger.warning(f"[{self.ticker}] Broker says no position to close")
            self._position = None
            return

        # Compute P&L
        exit_price = close_result.entry_price  # The close fill price
        entry_price = self._position.entry_price
        quantity = self._position.quantity

        if self._position.direction == "long":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity

        pnl_pct = (pnl / (entry_price * quantity)) * 100 if entry_price > 0 else 0
        result = "WIN" if pnl >= 0 else "LOSS"
        reason = signal.reason or "strategy_exit"

        logger.info(
            f"[{self.ticker}] EXIT ({result}): {self._position.direction} "
            f"{quantity:.0f} @ ${exit_price:.2f} "
            f"(entry: ${entry_price:.2f}, P&L: {'+' if pnl >= 0 else ''}${pnl:,.2f}) "
            f"— {reason}"
        )

        self.daily_report.log_trade_exit(
            ticker=self.ticker,
            direction=self._position.direction,
            quantity=quantity,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
        )

        # Notify strategy
        self._position.trade.close(
            exit_time=pd.Timestamp.now(tz="UTC"),
            exit_price=exit_price,
            exit_reason=reason,
        )
        self.strategy.on_trade_closed(self._position.trade)
        self._position = None

    async def _check_stops(self, row: pd.Series) -> None:
        """Check if stop-loss or take-profit was hit.

        The broker also tracks stops (as safety net), but we check locally
        to maintain identical behavior to the backtest engine.
        """
        if self._position is None:
            return

        bar_high = row["high"]
        bar_low = row["low"]

        stop_hit = self._position.is_stop_hit(bar_low, bar_high)
        target_hit = self._position.is_target_hit(bar_low, bar_high)

        if stop_hit:
            logger.info(f"[{self.ticker}] Stop loss hit")
            await self._close_position(
                Signal(direction=f"close_{self._position.direction}",
                       reason="stop_loss"),
                row,
            )
        elif target_hit:
            logger.info(f"[{self.ticker}] Take profit hit")
            await self._close_position(
                Signal(direction=f"close_{self._position.direction}",
                       reason="take_profit"),
                row,
            )

    async def _calculate_quantity(self, price: float,
                                  signal: Signal) -> float:
        """Calculate position size based on config and account equity."""
        try:
            account = await self.broker.get_account()
            equity = account["equity"]
        except Exception:
            equity = 60_000  # Fallback

        if self._sizing_method == "fixed":
            return max(1, int(self._fixed_size / price))
        elif self._sizing_method == "percent":
            amount = equity * self._pct_equity
            return max(1, int(amount / price))
        elif self._sizing_method == "risk_based":
            if signal.stop_loss:
                stop_dist = abs(price - signal.stop_loss)
                if stop_dist > 0:
                    risk_amount = equity * self._risk_pct
                    return max(1, int(risk_amount / stop_dist))
            amount = equity * self._risk_pct
            return max(1, int(amount / price))
        else:
            return max(1, int(self._pct_equity * equity / price))

    async def reconcile(self) -> dict:
        """Reconcile local position with broker."""
        result = await self._reconciler.reconcile(
            self.ticker, self._position, self.broker
        )

        if not result["match"]:
            logger.warning(f"[{self.ticker}] Reconciliation: {result['details']}")
            self.daily_report.log_error(
                f"Reconciliation: {result['details']}"
            )

            if result["action"] == "adopt_broker":
                self._position = self._reconciler.adopt_broker_position(
                    result["broker_position"], self.ticker
                )
            elif result["action"] == "clear_local":
                self._position = None

        return result

    def pause(self) -> None:
        """Pause trading (risk limit hit, etc.)."""
        self.active = False
        logger.warning(f"[{self.ticker}] Trading PAUSED")

    def resume(self) -> None:
        """Resume trading."""
        self.active = True
        logger.info(f"[{self.ticker}] Trading RESUMED")
