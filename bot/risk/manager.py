"""Risk management: daily loss limits, drawdown circuit breaker, position sizing.

The RiskManager sits between the strategy signal and the broker. Every order
must pass through check_new_order() before submission. If any limit is breached,
the order is blocked and trading pauses.

Limits enforced:
- Trading blocked by broker  → pauses immediately
- Equity below PDT threshold → pauses (risk of day trade restrictions)
- Max daily loss ($)         → pauses all trading for the day
- Max drawdown (%)           → circuit breaker, manual review needed
- Max position value (%)     → prevents over-sizing
- Max positions per ticker   → 1 (matching backtest behavior)
- Max total positions        → limits concurrent open positions
- Total exposure cap         → limits total $ at risk across all tickers
- Buying power validation    → checks Reg-T buying power to avoid margin calls
- Session time filter        → blocks trades outside market hours
"""

import logging
from datetime import datetime, date
from typing import Optional

from bot.config.settings import RiskConfig
from bot.risk.session_filter import SessionFilter
from strategies.base_strategy import Signal

logger = logging.getLogger(__name__)


class RiskManager:
    """Account-level risk management layer."""

    def __init__(self, config: RiskConfig, initial_equity: float = 60_000.0):
        self.config = config
        self.initial_equity = initial_equity
        self.peak_equity = initial_equity

        # Daily tracking
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._daily_wins: int = 0
        self._daily_losses: int = 0
        self._current_date: date = date.today()

        # State
        self.is_paused: bool = False
        self.pause_reason: str = ""

        # Open positions per ticker (ticker -> estimated position value)
        self._open_positions: dict[str, float] = {}

        # Session filter
        self._session_filter = SessionFilter()

    def check_new_order(
        self,
        signal: Signal,
        ticker: str,
        price: float,
        equity: float,
        buying_power: float,
        account: Optional[dict] = None,
    ) -> tuple[bool, str]:
        """Validate an order against all risk limits.

        Called after strategy.on_bar() returns a Signal, before broker submission.

        Args:
            signal: The trading signal to validate
            ticker: Symbol
            price: Current price
            equity: Current account equity
            buying_power: Available buying power
            account: Full account dict from broker (optional, enables PDT/BP checks)

        Returns:
            (allowed: bool, reason: str)
            If allowed=False, the order should be blocked.
        """
        # Reset daily counters if new day
        self._check_day_rollover()

        # Allow close signals always (we always want to be able to exit)
        if signal.direction in ("close_long", "close_short", "flat"):
            return True, "exit_allowed"

        # Check 1: Is trading paused?
        if self.is_paused:
            return False, f"Trading paused: {self.pause_reason}"

        # Check 2: Trading blocked by broker
        if account and account.get("trading_blocked"):
            self._pause("Trading blocked by broker")
            return False, self.pause_reason

        # Check 3: Equity below PDT threshold ($25k)
        min_equity = self.config.min_equity_for_trading
        if min_equity > 0 and equity < min_equity:
            self._pause(
                f"Equity ${equity:,.2f} below minimum ${min_equity:,.2f} "
                f"(PDT threshold — risk of day trade restrictions)"
            )
            return False, self.pause_reason

        # Check 4: Daily loss limit
        if abs(self._daily_pnl) > 0 and self._daily_pnl <= -self.config.max_daily_loss:
            self._pause(f"Daily loss limit hit: ${self._daily_pnl:,.2f}")
            return False, self.pause_reason

        # Check 5: Drawdown circuit breaker
        if equity > self.peak_equity:
            self.peak_equity = equity
        drawdown_pct = ((self.peak_equity - equity) / self.peak_equity) * 100
        if drawdown_pct >= self.config.max_drawdown_pct:
            self._pause(
                f"Drawdown circuit breaker: {drawdown_pct:.1f}% "
                f"(limit: {self.config.max_drawdown_pct}%)"
            )
            return False, self.pause_reason

        # Check 6: Max position per ticker
        if ticker in self._open_positions:
            return False, f"Already in position for {ticker}"

        # Check 7: Max total positions across all tickers
        total_open = len(self._open_positions)
        if total_open >= self.config.max_total_positions:
            open_tickers = ", ".join(self._open_positions.keys())
            return False, (
                f"Max total positions reached: {total_open}/"
                f"{self.config.max_total_positions} ({open_tickers})"
            )

        # Check 8: Total exposure check
        current_exposure = sum(self._open_positions.values())
        max_total_exposure = equity * self.config.max_total_exposure_pct
        remaining_capacity = max_total_exposure - current_exposure
        if remaining_capacity <= 0:
            return False, (
                f"Max total exposure reached: ${current_exposure:,.0f} / "
                f"${max_total_exposure:,.0f} "
                f"({self.config.max_total_exposure_pct*100:.0f}% of equity)"
            )

        # Check 9: Position size vs equity
        max_value = equity * self.config.max_position_value_pct
        # Rough estimate — actual quantity is calculated later
        if price > max_value:
            return False, (
                f"Single share (${price:.2f}) exceeds max position value "
                f"(${max_value:,.2f})"
            )

        # Check 10: Buying power validation
        # Use Reg-T buying power (2x for overnight holds). Ensures we don't
        # exceed what Alpaca actually allows and trigger a margin call.
        if self.config.enforce_buying_power and account:
            regt_bp = account.get("regt_buying_power", buying_power)
            available_bp = regt_bp - current_exposure
            if available_bp <= 0:
                return False, (
                    f"Insufficient buying power: Reg-T BP ${regt_bp:,.0f}, "
                    f"current exposure ${current_exposure:,.0f}, "
                    f"available ${available_bp:,.0f}"
                )

        # Check 11: Session filter (market hours)
        if not self._session_filter.is_market_hours():
            return False, "Outside market hours"

        return True, "approved"

    def record_trade_opened(self, ticker: str, position_value: float = 0.0) -> None:
        """Track that a position was opened.

        Args:
            ticker: Symbol
            position_value: Estimated $ value of the position (qty * price)
        """
        self._open_positions[ticker] = position_value
        self._daily_trades += 1
        total_open = len(self._open_positions)
        total_exposure = sum(self._open_positions.values())
        logger.info(
            f"[Risk] Position opened: {ticker} (${position_value:,.0f}). "
            f"Total: {total_open} positions, ${total_exposure:,.0f} exposure"
        )

    def record_trade_closed(self, ticker: str, pnl: float) -> None:
        """Update daily P&L and position tracking after a trade closes."""
        self._check_day_rollover()
        self._open_positions.pop(ticker, None)
        self._daily_pnl += pnl

        if pnl >= 0:
            self._daily_wins += 1
        else:
            self._daily_losses += 1

        logger.info(
            f"[Risk] Trade closed: {ticker} P&L=${pnl:,.2f}. "
            f"Daily total: ${self._daily_pnl:,.2f} "
            f"({self._daily_wins}W/{self._daily_losses}L)"
        )

        # Check if daily loss limit is now breached
        if self._daily_pnl <= -self.config.max_daily_loss:
            self._pause(
                f"Daily loss limit hit: ${self._daily_pnl:,.2f} "
                f"(limit: -${self.config.max_daily_loss:,.2f})"
            )

    def get_remaining_capacity(self, equity: float) -> float:
        """Get remaining $ capacity for new positions based on total exposure limit.

        Used by engines to scale position sizes when other positions are open.

        Args:
            equity: Current account equity

        Returns:
            Remaining $ capacity (always >= 0)
        """
        max_total_exposure = equity * self.config.max_total_exposure_pct
        current_exposure = sum(self._open_positions.values())
        return max(0.0, max_total_exposure - current_exposure)

    def get_open_position_count(self) -> int:
        """Get number of currently open positions across all tickers."""
        return len(self._open_positions)

    def get_daily_stats(self) -> dict:
        """Get current daily trading statistics."""
        self._check_day_rollover()
        return {
            "date": self._current_date.isoformat(),
            "daily_pnl": self._daily_pnl,
            "trades": self._daily_trades,
            "wins": self._daily_wins,
            "losses": self._daily_losses,
            "is_paused": self.is_paused,
            "pause_reason": self.pause_reason,
        }

    def resume(self) -> None:
        """Manually resume trading after a pause.

        Only call this after reviewing the situation.
        """
        if self.is_paused:
            logger.info(f"[Risk] Trading RESUMED (was paused: {self.pause_reason})")
            self.is_paused = False
            self.pause_reason = ""

    def _pause(self, reason: str) -> None:
        """Pause all new entries."""
        if not self.is_paused:
            self.is_paused = True
            self.pause_reason = reason
            logger.warning(f"[Risk] Trading PAUSED: {reason}")

    def _check_day_rollover(self) -> None:
        """Reset daily counters at the start of a new trading day."""
        today = date.today()
        if today != self._current_date:
            logger.info(
                f"[Risk] New trading day: {today}. "
                f"Previous day P&L: ${self._daily_pnl:,.2f}"
            )
            self._daily_pnl = 0.0
            self._daily_trades = 0
            self._daily_wins = 0
            self._daily_losses = 0
            self._current_date = today

            # Auto-resume on new day (daily loss pause only)
            if self.is_paused and "Daily loss" in self.pause_reason:
                self.resume()
