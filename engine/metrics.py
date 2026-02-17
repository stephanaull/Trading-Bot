"""Performance metrics matching TradingView's Strategy Tester.

Computes all standard metrics using TradingView-compatible formulas:
- Sharpe/Sortino use monthly return periods
- Max drawdown uses intrabar methodology
- Profit factor, win rate, expectancy, etc.
"""

import logging
from typing import Optional

import pandas as pd
import numpy as np

from engine.order import Trade

logger = logging.getLogger(__name__)


class Metrics:
    """Compute performance metrics from closed trades and equity curve."""

    def __init__(self, trades: list, equity_curve: pd.Series,
                 initial_capital: float = 100_000.0,
                 risk_free_rate: float = 0.02,
                 periods_per_year: int = 252):
        """
        Args:
            trades: List of closed Trade objects
            equity_curve: pd.Series with datetime index and equity values
            initial_capital: Starting capital
            risk_free_rate: Annual risk-free rate (default 2%)
            periods_per_year: Trading periods per year (252 for daily)
        """
        self.trades = trades
        self.equity_curve = equity_curve
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        self.periods_per_year = periods_per_year

        # Pre-compute trade arrays
        self._pnls = np.array([t.pnl for t in trades if t.pnl is not None])
        self._winners = self._pnls[self._pnls > 0]
        self._losers = self._pnls[self._pnls < 0]

    def calculate_all(self) -> dict:
        """Calculate all metrics and return as a dictionary."""
        return {
            # Overview
            "net_profit": self.net_profit(),
            "net_profit_pct": self.net_profit_pct(),
            "gross_profit": self.gross_profit(),
            "gross_loss": self.gross_loss(),
            "max_drawdown": self.max_drawdown(),
            "max_drawdown_pct": self.max_drawdown_pct(),
            "buy_and_hold_return_pct": self.buy_and_hold_return(),

            # Ratios
            "sharpe_ratio": self.sharpe_ratio(),
            "sortino_ratio": self.sortino_ratio(),
            "profit_factor": self.profit_factor(),
            "recovery_factor": self.recovery_factor(),
            "calmar_ratio": self.calmar_ratio(),
            "risk_reward_ratio": self.risk_reward_ratio(),
            "expectancy": self.expectancy(),

            # Trade stats
            "total_trades": self.total_trades(),
            "winning_trades": self.winning_trades(),
            "losing_trades": self.losing_trades(),
            "win_rate_pct": self.win_rate(),
            "avg_trade": self.avg_trade(),
            "avg_winning_trade": self.avg_winning_trade(),
            "avg_losing_trade": self.avg_losing_trade(),
            "largest_winning_trade": self.largest_winning_trade(),
            "largest_losing_trade": self.largest_losing_trade(),
            "avg_bars_in_trade": self.avg_bars_in_trade(),

            # Streaks
            "max_consecutive_wins": self.max_consecutive_wins(),
            "max_consecutive_losses": self.max_consecutive_losses(),
        }

    # ── Overview metrics ─────────────────────────────────────────

    def net_profit(self) -> float:
        if len(self._pnls) == 0:
            return 0.0
        return float(self._pnls.sum())

    def net_profit_pct(self) -> float:
        if self.initial_capital == 0:
            return 0.0
        return (self.net_profit() / self.initial_capital) * 100

    def gross_profit(self) -> float:
        if len(self._winners) == 0:
            return 0.0
        return float(self._winners.sum())

    def gross_loss(self) -> float:
        if len(self._losers) == 0:
            return 0.0
        return float(self._losers.sum())

    def max_drawdown(self) -> float:
        """Maximum drawdown in dollar terms (TradingView intrabar method)."""
        if len(self.equity_curve) == 0:
            return 0.0
        peak = self.equity_curve.expanding().max()
        drawdown = self.equity_curve - peak
        return float(drawdown.min())

    def max_drawdown_pct(self) -> float:
        """Maximum drawdown as percentage of peak equity."""
        if len(self.equity_curve) == 0:
            return 0.0
        peak = self.equity_curve.expanding().max()
        drawdown_pct = ((self.equity_curve - peak) / peak) * 100
        return float(drawdown_pct.min())

    def buy_and_hold_return(self) -> float:
        """Buy and hold return percentage over the backtest period."""
        if len(self.equity_curve) < 2:
            return 0.0
        # Approximate: use first and last equity values as if fully invested
        return ((self.equity_curve.iloc[-1] - self.initial_capital) /
                self.initial_capital * 100)

    # ── Ratio metrics ────────────────────────────────────────────

    def sharpe_ratio(self) -> float:
        """Sharpe Ratio using monthly returns (TradingView method).

        SR = (mean_monthly_return - monthly_rfr) / std_monthly_returns
        """
        if len(self.equity_curve) < 2:
            return 0.0

        # Compute monthly returns from equity curve
        monthly = self.equity_curve.resample("ME").last()
        if len(monthly) < 2:
            # Fall back to daily returns
            returns = self.equity_curve.pct_change().dropna()
            if len(returns) == 0 or returns.std() == 0:
                return 0.0
            daily_rfr = self.risk_free_rate / self.periods_per_year
            excess = returns.mean() - daily_rfr
            return float(excess / returns.std() * np.sqrt(self.periods_per_year))

        monthly_returns = monthly.pct_change().dropna()
        if len(monthly_returns) == 0 or monthly_returns.std() == 0:
            return 0.0

        monthly_rfr = self.risk_free_rate / 12
        excess_return = monthly_returns.mean() - monthly_rfr
        return float(excess_return / monthly_returns.std() * np.sqrt(12))

    def sortino_ratio(self) -> float:
        """Sortino Ratio: like Sharpe but only penalizes downside volatility."""
        if len(self.equity_curve) < 2:
            return 0.0

        monthly = self.equity_curve.resample("ME").last()
        if len(monthly) < 2:
            returns = self.equity_curve.pct_change().dropna()
            if len(returns) == 0:
                return 0.0
            daily_rfr = self.risk_free_rate / self.periods_per_year
            downside = returns[returns < 0]
            if len(downside) == 0 or downside.std() == 0:
                return float("inf") if returns.mean() > daily_rfr else 0.0
            excess = returns.mean() - daily_rfr
            return float(excess / downside.std() * np.sqrt(self.periods_per_year))

        monthly_returns = monthly.pct_change().dropna()
        if len(monthly_returns) == 0:
            return 0.0

        monthly_rfr = self.risk_free_rate / 12
        downside = monthly_returns[monthly_returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return float("inf") if monthly_returns.mean() > monthly_rfr else 0.0

        excess_return = monthly_returns.mean() - monthly_rfr
        return float(excess_return / downside.std() * np.sqrt(12))

    def profit_factor(self) -> float:
        """Profit Factor: gross_profit / abs(gross_loss)."""
        gp = self.gross_profit()
        gl = abs(self.gross_loss())
        if gl == 0:
            return float("inf") if gp > 0 else 0.0
        return gp / gl

    def recovery_factor(self) -> float:
        """Recovery Factor: net_profit / abs(max_drawdown)."""
        mdd = abs(self.max_drawdown())
        if mdd == 0:
            return 0.0
        return self.net_profit() / mdd

    def calmar_ratio(self) -> float:
        """Calmar Ratio: annualized return / abs(max_drawdown_pct)."""
        mdd_pct = abs(self.max_drawdown_pct())
        if mdd_pct == 0:
            return 0.0

        # Annualized return
        if len(self.equity_curve) < 2:
            return 0.0
        total_days = (self.equity_curve.index[-1] - self.equity_curve.index[0]).days
        if total_days <= 0:
            return 0.0
        total_return = self.equity_curve.iloc[-1] / self.initial_capital
        years = total_days / 365.25
        annualized = (total_return ** (1 / years) - 1) * 100
        return annualized / mdd_pct

    def risk_reward_ratio(self) -> float:
        """Average Risk/Reward ratio: avg_winning / abs(avg_losing)."""
        avg_win = self.avg_winning_trade()
        avg_loss = abs(self.avg_losing_trade())
        if avg_loss == 0:
            return float("inf") if avg_win > 0 else 0.0
        return avg_win / avg_loss

    def expectancy(self) -> float:
        """Expectancy per trade: (win_rate * avg_win) - (loss_rate * abs(avg_loss))."""
        if self.total_trades() == 0:
            return 0.0
        wr = self.win_rate() / 100
        lr = 1 - wr
        return wr * self.avg_winning_trade() + lr * self.avg_losing_trade()

    # ── Trade statistics ─────────────────────────────────────────

    def total_trades(self) -> int:
        return len(self._pnls)

    def winning_trades(self) -> int:
        return len(self._winners)

    def losing_trades(self) -> int:
        return len(self._losers)

    def win_rate(self) -> float:
        """Win rate as percentage."""
        if self.total_trades() == 0:
            return 0.0
        return (self.winning_trades() / self.total_trades()) * 100

    def avg_trade(self) -> float:
        if self.total_trades() == 0:
            return 0.0
        return float(self._pnls.mean())

    def avg_winning_trade(self) -> float:
        if len(self._winners) == 0:
            return 0.0
        return float(self._winners.mean())

    def avg_losing_trade(self) -> float:
        if len(self._losers) == 0:
            return 0.0
        return float(self._losers.mean())

    def largest_winning_trade(self) -> float:
        if len(self._winners) == 0:
            return 0.0
        return float(self._winners.max())

    def largest_losing_trade(self) -> float:
        if len(self._losers) == 0:
            return 0.0
        return float(self._losers.min())

    def avg_bars_in_trade(self) -> float:
        bars = [t.bars_held for t in self.trades if t.bars_held > 0]
        if not bars:
            return 0.0
        return sum(bars) / len(bars)

    # ── Streak metrics ───────────────────────────────────────────

    def max_consecutive_wins(self) -> int:
        return self._max_streak(winning=True)

    def max_consecutive_losses(self) -> int:
        return self._max_streak(winning=False)

    def _max_streak(self, winning: bool) -> int:
        if len(self._pnls) == 0:
            return 0
        max_streak = 0
        current = 0
        for pnl in self._pnls:
            if (winning and pnl > 0) or (not winning and pnl < 0):
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    # ── Output ───────────────────────────────────────────────────

    def print_summary(self, strategy_name: str = "Strategy") -> None:
        """Print formatted performance summary to console."""
        m = self.calculate_all()

        print(f"\n{'=' * 55}")
        print(f"  {strategy_name}")
        print(f"{'=' * 55}")

        if len(self.equity_curve) >= 2:
            start = self.equity_curve.index[0].strftime("%Y-%m-%d")
            end = self.equity_curve.index[-1].strftime("%Y-%m-%d")
            print(f"  Period: {start} to {end} ({len(self.equity_curve):,} bars)")
            print(f"{'─' * 55}")

        rows = [
            ("Net Profit", f"${m['net_profit']:,.2f} ({m['net_profit_pct']:.2f}%)"),
            ("Gross Profit", f"${m['gross_profit']:,.2f}"),
            ("Gross Loss", f"${m['gross_loss']:,.2f}"),
            ("Max Drawdown", f"${m['max_drawdown']:,.2f} ({m['max_drawdown_pct']:.2f}%)"),
            ("", ""),
            ("Sharpe Ratio", f"{m['sharpe_ratio']:.2f}"),
            ("Sortino Ratio", f"{m['sortino_ratio']:.2f}"),
            ("Profit Factor", f"{m['profit_factor']:.2f}"),
            ("Recovery Factor", f"{m['recovery_factor']:.2f}"),
            ("Risk/Reward", f"1:{m['risk_reward_ratio']:.2f}"),
            ("Expectancy", f"${m['expectancy']:,.2f}"),
            ("", ""),
            ("Total Trades", f"{m['total_trades']}"),
            ("Win Rate", f"{m['win_rate_pct']:.1f}% ({m['winning_trades']}/{m['total_trades']})"),
            ("Avg Trade", f"${m['avg_trade']:,.2f}"),
            ("Avg Win", f"${m['avg_winning_trade']:,.2f}"),
            ("Avg Loss", f"${m['avg_losing_trade']:,.2f}"),
            ("Largest Win", f"${m['largest_winning_trade']:,.2f}"),
            ("Largest Loss", f"${m['largest_losing_trade']:,.2f}"),
            ("Avg Bars/Trade", f"{m['avg_bars_in_trade']:.1f}"),
            ("", ""),
            ("Max Consec. Wins", f"{m['max_consecutive_wins']}"),
            ("Max Consec. Losses", f"{m['max_consecutive_losses']}"),
        ]

        for label, value in rows:
            if label == "":
                print(f"{'─' * 55}")
            else:
                print(f"  {label:<30} {value:>22}")

        print(f"{'=' * 55}\n")
