"""Message formatting for trade alerts, summaries, and errors.

All methods return (subject, body) tuples.
Body is plain text — the email notifier wraps it in HTML.
"""

from datetime import datetime
from typing import Optional


class Formatter:
    """Format notification messages for trades, summaries, and alerts."""

    def trade_entry(self, ticker: str, direction: str, quantity: float,
                    price: float, stop_loss: Optional[float] = None,
                    take_profit: Optional[float] = None,
                    reason: str = "") -> tuple[str, str]:
        """Format a trade entry notification."""
        arrow = "LONG" if direction == "long" else "SHORT"
        subject = f"[Trade] {arrow} {ticker} @ ${price:.2f}"

        lines = [
            f"TRADE ENTRY — {arrow} {ticker}",
            f"{'='*40}",
            f"  Time:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Direction: {arrow}",
            f"  Ticker:    {ticker}",
            f"  Quantity:  {quantity:.0f} shares",
            f"  Price:     ${price:.2f}",
            f"  Value:     ${quantity * price:,.2f}",
        ]

        if stop_loss:
            risk = abs(price - stop_loss) * quantity
            lines.append(f"  Stop Loss: ${stop_loss:.2f} (risk: ${risk:,.2f})")
        if take_profit:
            reward = abs(take_profit - price) * quantity
            lines.append(f"  Target:    ${take_profit:.2f} (reward: ${reward:,.2f})")
        if stop_loss and take_profit:
            rr = abs(take_profit - price) / abs(price - stop_loss) if abs(price - stop_loss) > 0 else 0
            lines.append(f"  R:R Ratio: {rr:.1f}:1")
        if reason:
            lines.append(f"  Reason:    {reason}")

        lines.append(f"{'='*40}")
        return subject, "\n".join(lines)

    def trade_exit(self, ticker: str, direction: str, quantity: float,
                   entry_price: float, exit_price: float,
                   pnl: float, pnl_pct: float,
                   exit_reason: str = "") -> tuple[str, str]:
        """Format a trade exit notification."""
        result = "WIN" if pnl >= 0 else "LOSS"
        sign = "+" if pnl >= 0 else ""
        subject = f"[{result}] {ticker} {sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%)"

        arrow = "LONG" if direction == "long" else "SHORT"
        lines = [
            f"TRADE EXIT — {result} — {arrow} {ticker}",
            f"{'='*40}",
            f"  Time:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Direction:  {arrow}",
            f"  Ticker:     {ticker}",
            f"  Quantity:   {quantity:.0f} shares",
            f"  Entry:      ${entry_price:.2f}",
            f"  Exit:       ${exit_price:.2f}",
            f"  P&L:        {sign}${pnl:,.2f} ({sign}{pnl_pct:.1f}%)",
            f"  Exit Reason:{exit_reason}",
            f"{'='*40}",
        ]

        return subject, "\n".join(lines)

    def daily_summary(self, date: str, total_pnl: float,
                      trades_taken: int, wins: int, losses: int,
                      equity: float,
                      positions: list[dict] = None) -> tuple[str, str]:
        """Format end-of-day summary."""
        sign = "+" if total_pnl >= 0 else ""
        subject = f"[Daily] {date} — {sign}${total_pnl:,.2f}"

        win_rate = (wins / trades_taken * 100) if trades_taken > 0 else 0

        lines = [
            f"DAILY SUMMARY — {date}",
            f"{'='*40}",
            f"  Total P&L:  {sign}${total_pnl:,.2f}",
            f"  Trades:     {trades_taken}",
            f"  Wins:       {wins}",
            f"  Losses:     {losses}",
            f"  Win Rate:   {win_rate:.1f}%",
            f"  Equity:     ${equity:,.2f}",
        ]

        if positions:
            lines.append(f"\n  Open Positions ({len(positions)}):")
            for p in positions:
                pnl_sign = "+" if p.get("unrealized_pnl", 0) >= 0 else ""
                lines.append(
                    f"    {p['ticker']}: {p['side']} {p['qty']:.0f} "
                    f"@ ${p['avg_price']:.2f} "
                    f"({pnl_sign}${p.get('unrealized_pnl', 0):.2f})"
                )
        else:
            lines.append(f"\n  No open positions.")

        lines.append(f"{'='*40}")
        return subject, "\n".join(lines)

    def error_alert(self, error_msg: str,
                    severity: str = "ERROR") -> tuple[str, str]:
        """Format an error/warning notification."""
        subject = f"[{severity}] Trading Bot Alert"

        lines = [
            f"{severity} ALERT",
            f"{'='*40}",
            f"  Time:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Severity: {severity}",
            f"  Message:  {error_msg}",
            f"{'='*40}",
        ]

        return subject, "\n".join(lines)

    def status_message(self, message: str) -> str:
        """Format a bot status message."""
        lines = [
            f"BOT STATUS",
            f"{'='*40}",
            f"  Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Status:  {message}",
            f"{'='*40}",
        ]
        return "\n".join(lines)

    def risk_alert(self, alert_type: str,
                   details: str) -> tuple[str, str]:
        """Format a risk management alert."""
        subject = f"[RISK] {alert_type}"

        lines = [
            f"RISK MANAGEMENT ALERT",
            f"{'='*40}",
            f"  Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Type:    {alert_type}",
            f"  Details: {details}",
            f"",
            f"  ACTION: Trading paused. Manual review required.",
            f"{'='*40}",
        ]

        return subject, "\n".join(lines)
