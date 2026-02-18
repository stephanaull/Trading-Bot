"""Multi-timeframe engine — runs the same strategy on multiple timeframes
for a single ticker and picks the best one to trade.

Architecture:
- One MultiTimeframeEngine per ticker
- Contains N LiveEngines (one per timeframe), all in "advisory" mode
- Each LiveEngine processes bars and generates signals independently
- When signals appear, the MTF engine scores them and executes the best one
- Only ONE position per ticker at any time (shared across all timeframes)

Signal scoring (higher = better):
1. ADX strength — stronger trend = higher conviction
2. Risk:Reward — tighter stop (lower TF) with same target = better R:R
3. Signal agreement — bonus if multiple TFs agree on direction
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
from bot.risk.manager import RiskManager
from bot.storage.database import Database

logger = logging.getLogger(__name__)

MAX_BARS = 500


class _TimeframeSlot:
    """One timeframe's state for a ticker: strategy + DataFrame + signal buffer."""

    def __init__(self, timeframe: str, strategy: BaseStrategy,
                 initial_df: pd.DataFrame):
        self.timeframe = timeframe
        self.tf_minutes = int(timeframe.replace("m", ""))
        self.strategy = strategy
        self.df = initial_df.copy()
        self.bar_count = 0
        self.last_signal: Optional[Signal] = None
        self.last_signal_row: Optional[pd.Series] = None
        self.last_signal_time: Optional[datetime] = None


class MultiTimeframeEngine:
    """Runs a strategy on multiple timeframes for a single ticker.

    Receives bars tagged with their timeframe, runs strategy logic on each,
    and when signals appear, picks the best timeframe to trade on.
    """

    def __init__(
        self,
        ticker: str,
        slots: list[_TimeframeSlot],
        broker: BaseBroker,
        daily_report: DailyReport,
        risk_manager: RiskManager = None,
        db: Database = None,
        position_sizing: str = "percent",
        pct_equity: float = 0.90,
        fixed_size: float = 10_000.0,
        risk_pct: float = 0.02,
        long_only: bool = False,
    ):
        self.ticker = ticker
        self.slots: dict[str, _TimeframeSlot] = {s.timeframe: s for s in slots}
        self.broker = broker
        self.daily_report = daily_report
        self.risk_manager = risk_manager
        self.db = db
        self._long_only = long_only

        # Position state — shared across all timeframes
        self._position: Optional[Position] = None
        self._active_tf: Optional[str] = None  # Which TF opened the position
        self._current_trade_db_id: Optional[int] = None

        # Position sizing
        self._sizing_method = position_sizing
        self._pct_equity = pct_equity
        self._fixed_size = fixed_size
        self._risk_pct = risk_pct

        # Reconciliation
        self._reconciler = Reconciler()
        self.active = True

        # Track total bars for heartbeat
        self._total_bars = 0

    async def on_bar(self, ticker: str, timeframe: str, bar: pd.Series) -> None:
        """Process a bar for a specific timeframe.

        Args:
            ticker: Symbol (must match self.ticker)
            timeframe: e.g., "2m", "5m", "10m"
            bar: OHLCV pd.Series
        """
        if not self.active or ticker != self.ticker:
            return

        slot = self.slots.get(timeframe)
        if not slot:
            return

        slot.bar_count += 1
        self._total_bars += 1

        # Step 1: Append bar
        slot.df = pd.concat([slot.df, bar.to_frame().T])
        slot.df.index.name = "date"
        if len(slot.df) > MAX_BARS:
            slot.df = slot.df.iloc[-MAX_BARS:]

        # Step 2: Recompute indicators
        try:
            slot.df = slot.strategy.setup(slot.df)
        except Exception as e:
            logger.error(f"[{self.ticker}/{timeframe}] Indicator error: {e}")
            return

        idx = len(slot.df) - 1
        row = slot.df.iloc[-1]

        # Step 3: If we have a position opened by THIS timeframe, check stops
        if self._position is not None and self._active_tf == timeframe:
            await self._check_stops(row, timeframe)

        # Step 4: Update trailing stop (from active TF only)
        if self._position is not None and self._active_tf == timeframe:
            self._position.update_trailing_stop(row["close"])

        # Step 5: Get strategy signal
        try:
            signal = slot.strategy.on_bar(idx, row, position=self._position)
        except Exception as e:
            logger.error(f"[{self.ticker}/{timeframe}] Strategy error: {e}")
            return

        if signal is not None:
            # Long-only filter
            if self._long_only and signal.direction in ("short", "close_short"):
                return

            if signal.direction in ("close_long", "close_short", "flat"):
                # Exit signals — execute immediately from any TF
                if self._position is not None:
                    await self._close_position(signal, row, timeframe)
            else:
                # Entry signal — buffer it, then decide
                slot.last_signal = signal
                slot.last_signal_row = row
                slot.last_signal_time = datetime.utcnow()
                await self._evaluate_entries(row)

        # Heartbeat
        if self._total_bars % 20 == 0:
            pos_str = (
                f"{self._position.direction} @ ${self._position.entry_price:.2f} "
                f"(via {self._active_tf})"
                if self._position else "flat"
            )
            logger.info(
                f"[{self.ticker}] Bar #{self._total_bars}: "
                f"close=${row['close']:.2f}, position={pos_str}"
            )

    async def _evaluate_entries(self, current_row: pd.Series) -> None:
        """Evaluate buffered signals across all timeframes and pick the best.

        Only called when at least one slot has a fresh signal.
        """
        if self._position is not None:
            # Already in a position — clear signals and skip
            for slot in self.slots.values():
                slot.last_signal = None
            return

        # Collect fresh signals (within last 60 seconds)
        now = datetime.utcnow()
        candidates: list[tuple[str, _TimeframeSlot]] = []

        for tf, slot in self.slots.items():
            if slot.last_signal and slot.last_signal_time:
                age = (now - slot.last_signal_time).total_seconds()
                if age < 120:  # Signal still fresh (within 2 min)
                    candidates.append((tf, slot))

        if not candidates:
            return

        # Score each candidate
        best_tf = None
        best_score = -999
        best_slot = None

        for tf, slot in candidates:
            score = self._score_signal(slot)
            logger.info(
                f"[{self.ticker}/{tf}] Signal: {slot.last_signal.direction} "
                f"(score: {score:.1f}, ADX: {self._get_adx(slot):.1f}, "
                f"reason: {slot.last_signal.reason})"
            )
            if score > best_score:
                best_score = score
                best_tf = tf
                best_slot = slot

        if best_slot and best_tf and best_score > 0:
            logger.info(
                f"[{self.ticker}] Best timeframe: {best_tf} "
                f"(score: {best_score:.1f})"
            )
            await self._open_position(
                best_slot.last_signal, best_slot.last_signal_row, best_tf
            )
        elif best_score <= 0:
            logger.info(
                f"[{self.ticker}] All signals blocked or below threshold "
                f"(best score: {best_score:.1f})"
            )

        # Clear all buffered signals after evaluation
        for slot in self.slots.values():
            slot.last_signal = None

    def _count_tf_agreement(self, signal: Signal) -> int:
        """Count how many timeframes have a fresh signal in the same direction."""
        count = 0
        now = datetime.utcnow()
        for tf, slot in self.slots.items():
            if slot.last_signal and slot.last_signal_time:
                age = (now - slot.last_signal_time).total_seconds()
                if age < 120 and slot.last_signal.direction == signal.direction:
                    count += 1
        return count

    def _score_signal(self, slot: _TimeframeSlot) -> float:
        """Score a signal based on multiple factors.

        Higher score = better entry.

        Factors:
        - ADX strength (0-100, weighted heavily)
        - Risk:Reward ratio from stop/target
        - Lower timeframe bonus (tighter stops, faster entries)
        - Signal agreement across timeframes (REQUIRED: minimum 2 TFs)
        - RSI extreme rejection (hard block RSI > 80 longs, RSI < 20 shorts)
        """
        score = 0.0
        row = slot.last_signal_row
        signal = slot.last_signal

        # ── HARD GATE: RSI extreme rejection ──
        # No scoring needed — these entries are categorically bad
        rsi = self._get_rsi(slot)
        if rsi is not None:
            if signal.direction == "long" and rsi > 80:
                logger.info(
                    f"[{self.ticker}/{slot.timeframe}] BLOCKED: RSI {rsi:.0f} > 80 "
                    f"(overbought — skipping long)"
                )
                return -999  # Hard block
            elif signal.direction == "short" and rsi < 20:
                logger.info(
                    f"[{self.ticker}/{slot.timeframe}] BLOCKED: RSI {rsi:.0f} < 20 "
                    f"(oversold — skipping short)"
                )
                return -999  # Hard block

        # ── HARD GATE: Require minimum 2 TFs in agreement ──
        # Lone 2m signals are noisy. Require at least one other TF to confirm.
        agreement_count = self._count_tf_agreement(signal)
        if agreement_count < 2:
            logger.info(
                f"[{self.ticker}/{slot.timeframe}] BLOCKED: Only {agreement_count}/2 "
                f"TFs agree on {signal.direction} — need at least 2"
            )
            return -999  # Hard block

        # 1. ADX strength (max ~40 points)
        adx = self._get_adx(slot)
        if adx > 25:
            score += min(adx * 1.0, 40)  # Strong trend
        elif adx > 20:
            score += adx * 0.5  # Moderate trend
        else:
            score += adx * 0.2  # Weak trend

        # 2. Risk:Reward ratio (max ~30 points)
        if signal.stop_loss and signal.take_profit and row is not None:
            price = row["close"]
            risk = abs(price - signal.stop_loss)
            reward = abs(signal.take_profit - price)
            if risk > 0:
                rr = reward / risk
                score += min(rr * 10, 30)  # Cap at 3:1 = 30 points

        # 3. Timeframe preference (lower TF = tighter stop = bonus)
        # 2m gets 15 pts, 5m gets 10 pts, 10m gets 5 pts
        tf_bonus = max(0, 20 - slot.tf_minutes * 1.5)
        score += tf_bonus

        # 4. Signal agreement bonus — more agreement = higher conviction
        # Already counted above, just add bonus points
        agreement_bonus = (agreement_count - 1) * 15  # 15 pts per extra TF
        score += agreement_bonus

        # 5. RSI quality zone (55-75 is the sweet spot for longs)
        if rsi is not None:
            if signal.direction == "long":
                if rsi < 70:
                    score += 10  # Sweet spot
                elif rsi < 75:
                    score += 5   # Acceptable
                else:
                    score -= 5   # Getting hot (70-80 range)
            elif signal.direction == "short":
                if rsi > 30:
                    score += 10
                elif rsi > 25:
                    score += 5
                else:
                    score -= 5

        return score

    def _get_adx(self, slot: _TimeframeSlot) -> float:
        """Get ADX value from slot's last row."""
        row = slot.last_signal_row
        if row is not None:
            for col in ["ADX_14", "ADX_10", "ADX_20"]:
                if col in row.index:
                    val = row[col]
                    if pd.notna(val):
                        return float(val)
        return 15.0  # Default: weak trend

    def _get_rsi(self, slot: _TimeframeSlot) -> Optional[float]:
        """Get RSI value from slot's last row."""
        row = slot.last_signal_row
        if row is not None:
            for col in ["RSI_9", "RSI_14", "RSI_7"]:
                if col in row.index:
                    val = row[col]
                    if pd.notna(val):
                        return float(val)
        return None

    async def _open_position(self, signal: Signal, row: pd.Series,
                             timeframe: str) -> None:
        """Open a position using the selected timeframe's signal."""
        if self._position is not None:
            return

        price = row["close"]

        # Risk check (pass full account dict for buying power + PDT validation)
        account = None
        if self.risk_manager:
            try:
                account = await self.broker.get_account()
                allowed, reason = self.risk_manager.check_new_order(
                    signal, self.ticker, price,
                    account["equity"], account["buying_power"],
                    account=account,
                )
                if not allowed:
                    logger.warning(
                        f"[{self.ticker}] Order blocked by risk manager: {reason}"
                    )
                    self.daily_report.log_risk_event(
                        f"{self.ticker}: Order blocked — {reason}"
                    )
                    return
            except Exception as e:
                logger.error(f"[{self.ticker}] Risk check failed: {e}")

        quantity = await self._calculate_quantity(price, signal, account=account)
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

        self._position = Position(
            trade=trade,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            trailing_stop_distance=signal.trailing_stop_distance,
        )
        self._active_tf = timeframe

        if self.risk_manager:
            position_value = trade.quantity * trade.entry_price
            self.risk_manager.record_trade_opened(self.ticker, position_value)

        if self.db:
            try:
                self._current_trade_db_id = self.db.save_trade_entry(
                    ticker=self.ticker,
                    direction=signal.direction,
                    quantity=trade.quantity,
                    entry_price=trade.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    signal_reason=f"[{timeframe}] {signal.reason}",
                )
            except Exception as e:
                logger.error(f"[{self.ticker}] DB save entry failed: {e}")

        sl_str = f"${signal.stop_loss:.2f}" if signal.stop_loss else "none"
        tp_str = f"${signal.take_profit:.2f}" if signal.take_profit else "none"
        logger.info(
            f"[{self.ticker}] ENTRY via {timeframe}: "
            f"{signal.direction} {trade.quantity:.0f} "
            f"@ ${trade.entry_price:.2f} "
            f"(SL: {sl_str}, TP: {tp_str}) "
            f"— {signal.reason}"
        )

        self.daily_report.log_trade_entry(
            ticker=self.ticker,
            direction=signal.direction,
            quantity=trade.quantity,
            price=trade.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            reason=f"[{timeframe}] {signal.reason}",
        )

    async def _close_position(self, signal: Signal, row: pd.Series,
                              timeframe: str) -> None:
        """Close the current position."""
        if self._position is None:
            return

        try:
            close_result = await self.broker.close_position(self.ticker)
        except Exception as e:
            logger.error(f"[{self.ticker}] Failed to close position: {e}")
            return

        if close_result is None:
            self._position = None
            self._active_tf = None
            return

        exit_price = close_result.entry_price
        entry_price = self._position.entry_price
        quantity = self._position.quantity

        if self._position.direction == "long":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity

        pnl_pct = (pnl / (entry_price * quantity)) * 100 if entry_price > 0 else 0
        result = "WIN" if pnl >= 0 else "LOSS"
        reason = signal.reason or "strategy_exit"

        if self.risk_manager:
            self.risk_manager.record_trade_closed(self.ticker, pnl)
            if self.risk_manager.is_paused:
                self.pause()
                self.daily_report.log_risk_event(
                    f"Trading paused: {self.risk_manager.pause_reason}"
                )

        if self.db and self._current_trade_db_id:
            try:
                self.db.save_trade_exit(
                    trade_id=self._current_trade_db_id,
                    exit_price=exit_price,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason=f"[{timeframe}] {reason}",
                )
                self._current_trade_db_id = None
            except Exception as e:
                logger.error(f"[{self.ticker}] DB save exit failed: {e}")

        logger.info(
            f"[{self.ticker}] EXIT ({result}) via {timeframe}: "
            f"{self._position.direction} {quantity:.0f} @ ${exit_price:.2f} "
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
            exit_reason=f"[{timeframe}] {reason}",
        )

        self._position.trade.close(
            exit_time=pd.Timestamp.now(tz="UTC"),
            exit_price=exit_price,
            exit_reason=reason,
        )
        # Notify all slot strategies about the closed trade
        for slot in self.slots.values():
            slot.strategy.on_trade_closed(self._position.trade)

        self._position = None
        self._active_tf = None

    async def _check_stops(self, row: pd.Series, timeframe: str) -> None:
        """Check stop-loss and take-profit."""
        if self._position is None:
            return

        stop_hit = self._position.is_stop_hit(row["low"], row["high"])
        target_hit = self._position.is_target_hit(row["low"], row["high"])

        if stop_hit:
            logger.info(f"[{self.ticker}/{timeframe}] Stop loss hit")
            await self._close_position(
                Signal(direction=f"close_{self._position.direction}",
                       reason="stop_loss"),
                row, timeframe,
            )
        elif target_hit:
            logger.info(f"[{self.ticker}/{timeframe}] Take profit hit")
            await self._close_position(
                Signal(direction=f"close_{self._position.direction}",
                       reason="take_profit"),
                row, timeframe,
            )

    async def _calculate_quantity(self, price: float, signal: Signal,
                                  account: dict = None) -> float:
        """Calculate position size, capped by exposure capacity and buying power."""
        if account is None:
            try:
                account = await self.broker.get_account()
            except Exception:
                account = {"equity": 60_000, "regt_buying_power": 60_000}

        equity = account.get("equity", 60_000)

        # Calculate base desired amount
        if self._sizing_method == "fixed":
            desired_value = self._fixed_size
        elif self._sizing_method == "percent":
            desired_value = equity * self._pct_equity
        elif self._sizing_method == "risk_based":
            if signal.stop_loss:
                stop_dist = abs(price - signal.stop_loss)
                if stop_dist > 0:
                    desired_value = (equity * self._risk_pct / stop_dist) * price
                else:
                    desired_value = equity * self._risk_pct
            else:
                desired_value = equity * self._risk_pct
        else:
            desired_value = equity * self._pct_equity

        # Cap by remaining exposure capacity (global limit)
        if self.risk_manager:
            remaining = self.risk_manager.get_remaining_capacity(equity)
            if desired_value > remaining:
                logger.info(
                    f"[{self.ticker}] Position sized down: "
                    f"${desired_value:,.0f} → ${remaining:,.0f} "
                    f"(exposure cap)"
                )
                desired_value = remaining

        # Cap by available Reg-T buying power (prevents margin violations)
        current_exposure = sum(self.risk_manager._open_positions.values()) if self.risk_manager else 0
        regt_bp = account.get("regt_buying_power", equity * 2)
        available_bp = regt_bp - current_exposure
        if desired_value > available_bp and available_bp > 0:
            logger.info(
                f"[{self.ticker}] Position sized down: "
                f"${desired_value:,.0f} → ${available_bp:,.0f} "
                f"(buying power cap, Reg-T BP: ${regt_bp:,.0f})"
            )
            desired_value = available_bp

        return max(1, int(desired_value / price))

    async def reconcile(self) -> dict:
        """Reconcile local position with broker."""
        result = await self._reconciler.reconcile(
            self.ticker, self._position, self.broker
        )
        if not result["match"]:
            logger.warning(f"[{self.ticker}] Reconciliation: {result['details']}")
            if result["action"] == "adopt_broker":
                self._position = self._reconciler.adopt_broker_position(
                    result["broker_position"], self.ticker
                )
                self._active_tf = "reconciled"
            elif result["action"] == "clear_local":
                self._position = None
                self._active_tf = None
        return result

    def pause(self) -> None:
        self.active = False
        logger.warning(f"[{self.ticker}] Trading PAUSED")

    def resume(self) -> None:
        self.active = True
        logger.info(f"[{self.ticker}] Trading RESUMED")
