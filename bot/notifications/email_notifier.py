"""Email notifications for trade alerts, daily summaries, and errors.

Uses Gmail SMTP with App Passwords (not your login password).
Setup: https://myaccount.google.com/apppasswords

All emails are sent asynchronously using asyncio to avoid blocking
the trading engine.
"""

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional

from bot.config.settings import BotConfig
from bot.notifications.formatter import Formatter

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send email notifications for trading events."""

    def __init__(self, config: BotConfig):
        self.enabled = config.email_enabled
        self.smtp_server = config.email_smtp_server
        self.smtp_port = config.email_smtp_port
        self.email_from = config.email_from
        self.email_to = config.email_to
        self.email_password = config.email_password
        self.formatter = Formatter()

        if self.enabled and not all([self.email_from, self.email_to, self.email_password]):
            logger.warning(
                "Email notifications enabled but credentials incomplete. "
                "Set EMAIL_FROM, EMAIL_TO, EMAIL_PASSWORD in .env"
            )
            self.enabled = False

    async def send_trade_entry(self, ticker: str, direction: str,
                               quantity: float, price: float,
                               stop_loss: Optional[float] = None,
                               take_profit: Optional[float] = None,
                               reason: str = "") -> None:
        """Notify on trade entry."""
        subject, body = self.formatter.trade_entry(
            ticker, direction, quantity, price, stop_loss, take_profit, reason
        )
        await self._send(subject, body)

    async def send_trade_exit(self, ticker: str, direction: str,
                              quantity: float, entry_price: float,
                              exit_price: float, pnl: float,
                              pnl_pct: float, exit_reason: str = "") -> None:
        """Notify on trade exit."""
        subject, body = self.formatter.trade_exit(
            ticker, direction, quantity, entry_price, exit_price,
            pnl, pnl_pct, exit_reason
        )
        await self._send(subject, body)

    async def send_daily_summary(self, date: str, total_pnl: float,
                                 trades_taken: int, wins: int, losses: int,
                                 equity: float,
                                 positions: list[dict] = None) -> None:
        """Send end-of-day summary."""
        subject, body = self.formatter.daily_summary(
            date, total_pnl, trades_taken, wins, losses, equity, positions
        )
        await self._send(subject, body)

    async def send_error(self, error_msg: str, severity: str = "ERROR") -> None:
        """Notify on errors or warnings."""
        subject, body = self.formatter.error_alert(error_msg, severity)
        await self._send(subject, body)

    async def send_status(self, message: str) -> None:
        """Send bot status update (started, stopped, etc.)."""
        subject = f"[Trading Bot] {message}"
        body = self.formatter.status_message(message)
        await self._send(subject, body)

    async def send_risk_alert(self, alert_type: str, details: str) -> None:
        """Notify on risk events (daily loss limit, circuit breaker, etc.)."""
        subject, body = self.formatter.risk_alert(alert_type, details)
        await self._send(subject, body)

    async def _send(self, subject: str, body: str) -> None:
        """Send an email asynchronously (runs SMTP in a thread to avoid blocking)."""
        if not self.enabled:
            logger.debug(f"Email disabled, skipping: {subject}")
            return

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, subject, body
            )
            logger.debug(f"Email sent: {subject}")
        except Exception as e:
            logger.error(f"Failed to send email '{subject}': {e}")

    def _send_sync(self, subject: str, body: str) -> None:
        """Synchronous email send via SMTP (called in thread executor)."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        # Send both plain text and HTML
        text_part = MIMEText(body, "plain")
        html_part = MIMEText(self._wrap_html(body), "html")
        msg.attach(text_part)
        msg.attach(html_part)

        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.email_from, self.email_password)
            server.send_message(msg)

    def _wrap_html(self, text: str) -> str:
        """Wrap plain text in a simple HTML template."""
        # Convert newlines to <br> and preserve formatting
        html_body = text.replace("\n", "<br>\n")
        return f"""
        <html>
        <body style="font-family: 'Courier New', monospace; font-size: 14px;
                     color: #222; background: #f9f9f9; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: white;
                        padding: 20px; border-radius: 8px;
                        border: 1px solid #ddd;">
                {html_body}
            </div>
            <p style="color: #999; font-size: 11px; text-align: center;
                      margin-top: 15px;">
                Trading Bot — Automated notification
            </p>
        </body>
        </html>
        """
