"""Daily report generator — saves markdown reports to reports/daily/.

No external services needed. Reports are plain markdown files
committed to the repo, one per trading day.

Each report includes:
- Account snapshot (equity, cash, buying power)
- Trades executed that day (entries + exits with P&L)
- Open positions at end of day
- Running totals (cumulative P&L, win rate)
- Risk events (if any)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("reports/daily")


class DailyReport:
    """Accumulates events during the day and writes a markdown report."""

    def __init__(self, date: Optional[str] = None):
        """Initialize for a trading day.

        Args:
            date: Date string YYYY-MM-DD. Defaults to today.
        """
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self.trades: list[dict] = []          # All trades (entries + exits)
        self.risk_events: list[str] = []      # Risk alerts
        self.errors: list[str] = []           # Errors encountered
        self.status_log: list[str] = []       # Bot status messages
        self._account_start: Optional[dict] = None
        self._account_end: Optional[dict] = None
        self._positions_end: list[dict] = []

    def set_account_start(self, account: dict) -> None:
        """Record account state at start of day."""
        self._account_start = account

    def set_account_end(self, account: dict, positions: list[dict] = None) -> None:
        """Record account state at end of day."""
        self._account_end = account
        self._positions_end = positions or []

    def log_trade_entry(self, ticker: str, direction: str, quantity: float,
                        price: float, stop_loss: float = None,
                        take_profit: float = None, reason: str = "") -> None:
        """Log a trade entry."""
        self.trades.append({
            "type": "entry",
            "time": datetime.now().strftime("%H:%M:%S"),
            "ticker": ticker,
            "direction": direction,
            "quantity": quantity,
            "price": price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reason": reason,
        })

    def log_trade_exit(self, ticker: str, direction: str, quantity: float,
                       entry_price: float, exit_price: float,
                       pnl: float, pnl_pct: float,
                       exit_reason: str = "") -> None:
        """Log a trade exit."""
        self.trades.append({
            "type": "exit",
            "time": datetime.now().strftime("%H:%M:%S"),
            "ticker": ticker,
            "direction": direction,
            "quantity": quantity,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": exit_reason,
        })

    def log_risk_event(self, message: str) -> None:
        """Log a risk management event."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.risk_events.append(f"{timestamp} — {message}")

    def log_error(self, message: str) -> None:
        """Log an error."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.errors.append(f"{timestamp} — {message}")

    def log_status(self, message: str) -> None:
        """Log a bot status message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_log.append(f"{timestamp} — {message}")

    def save(self) -> Path:
        """Write the daily report to reports/daily/YYYY-MM-DD.md.

        Returns:
            Path to the written report file
        """
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = REPORTS_DIR / f"{self.date}.md"

        content = self._render()

        filepath.write_text(content)
        logger.info(f"Daily report saved: {filepath}")
        return filepath

    def _render(self) -> str:
        """Render the full markdown report."""
        lines = []

        # Header
        lines.append(f"# Daily Trading Report — {self.date}")
        lines.append("")

        # Account snapshot
        lines.append("## Account")
        lines.append("")
        if self._account_start or self._account_end:
            lines.append("| Metric | Start of Day | End of Day |")
            lines.append("|--------|-------------|------------|")
            start = self._account_start or {}
            end = self._account_end or {}
            for key in ["equity", "cash", "buying_power"]:
                s_val = f"${start.get(key, 0):,.2f}" if start else "—"
                e_val = f"${end.get(key, 0):,.2f}" if end else "—"
                lines.append(f"| {key.replace('_', ' ').title()} | {s_val} | {e_val} |")

            if start and end:
                day_pnl = end.get("equity", 0) - start.get("equity", 0)
                sign = "+" if day_pnl >= 0 else ""
                lines.append(f"| **Day P&L** | | **{sign}${day_pnl:,.2f}** |")
            lines.append("")
        else:
            lines.append("*No account data recorded.*")
            lines.append("")

        # Trades
        entries = [t for t in self.trades if t["type"] == "entry"]
        exits = [t for t in self.trades if t["type"] == "exit"]

        lines.append("## Trades")
        lines.append("")

        if not self.trades:
            lines.append("*No trades today.*")
            lines.append("")
        else:
            # Summary
            total_pnl = sum(t.get("pnl", 0) for t in exits)
            wins = sum(1 for t in exits if t.get("pnl", 0) > 0)
            losses = sum(1 for t in exits if t.get("pnl", 0) < 0)
            win_rate = (wins / len(exits) * 100) if exits else 0
            sign = "+" if total_pnl >= 0 else ""

            lines.append(f"**{len(entries)} entries, {len(exits)} exits** — "
                         f"P&L: {sign}${total_pnl:,.2f} — "
                         f"Win Rate: {win_rate:.0f}% ({wins}W / {losses}L)")
            lines.append("")

            # Entries table
            if entries:
                lines.append("### Entries")
                lines.append("")
                lines.append("| Time | Ticker | Dir | Qty | Price | Stop | Target | Reason |")
                lines.append("|------|--------|-----|-----|-------|------|--------|--------|")
                for t in entries:
                    d = "LONG" if t["direction"] == "long" else "SHORT"
                    sl = f"${t['stop_loss']:.2f}" if t.get("stop_loss") else "—"
                    tp = f"${t['take_profit']:.2f}" if t.get("take_profit") else "—"
                    lines.append(
                        f"| {t['time']} | {t['ticker']} | {d} | "
                        f"{t['quantity']:.0f} | ${t['price']:.2f} | "
                        f"{sl} | {tp} | {t.get('reason', '')} |"
                    )
                lines.append("")

            # Exits table
            if exits:
                lines.append("### Exits")
                lines.append("")
                lines.append("| Time | Ticker | Dir | Qty | Entry | Exit | P&L | P&L % | Reason |")
                lines.append("|------|--------|-----|-----|-------|------|-----|-------|--------|")
                for t in exits:
                    d = "LONG" if t["direction"] == "long" else "SHORT"
                    pnl_sign = "+" if t["pnl"] >= 0 else ""
                    result = "W" if t["pnl"] >= 0 else "L"
                    lines.append(
                        f"| {t['time']} | {t['ticker']} | {d} | "
                        f"{t['quantity']:.0f} | ${t['entry_price']:.2f} | "
                        f"${t['exit_price']:.2f} | "
                        f"{pnl_sign}${t['pnl']:,.2f} ({result}) | "
                        f"{pnl_sign}{t['pnl_pct']:.1f}% | {t.get('exit_reason', '')} |"
                    )
                lines.append("")

        # Open positions
        lines.append("## Open Positions")
        lines.append("")
        if self._positions_end:
            lines.append("| Ticker | Side | Qty | Avg Price | Current | Unrealized P&L |")
            lines.append("|--------|------|-----|-----------|---------|----------------|")
            for p in self._positions_end:
                pnl_sign = "+" if p.get("unrealized_pnl", 0) >= 0 else ""
                lines.append(
                    f"| {p['ticker']} | {p['side'].upper()} | "
                    f"{p['qty']:.0f} | ${p['avg_price']:.2f} | "
                    f"${p.get('current_price', 0):.2f} | "
                    f"{pnl_sign}${p.get('unrealized_pnl', 0):,.2f} |"
                )
            lines.append("")
        else:
            lines.append("*Flat — no open positions.*")
            lines.append("")

        # Risk events
        if self.risk_events:
            lines.append("## Risk Events")
            lines.append("")
            for event in self.risk_events:
                lines.append(f"- {event}")
            lines.append("")

        # Errors
        if self.errors:
            lines.append("## Errors")
            lines.append("")
            for error in self.errors:
                lines.append(f"- {error}")
            lines.append("")

        # Status log
        if self.status_log:
            lines.append("## Bot Log")
            lines.append("")
            for entry in self.status_log:
                lines.append(f"- {entry}")
            lines.append("")

        # Footer
        lines.append("---")
        lines.append(f"*Generated by Trading Bot at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("")

        return "\n".join(lines)
