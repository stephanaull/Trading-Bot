"""Async SQLite database for trade logs, daily P&L, and bot state.

Uses aiosqlite for non-blocking database access. All writes happen
asynchronously so they never block the trading engine.

Trade data persists across bot restarts for:
- Trade history and performance tracking
- Daily P&L tracking
- Bot state recovery (open positions, daily counters)
"""

import logging
import json
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from bot.storage.models import CREATE_TABLES

logger = logging.getLogger(__name__)


class Database:
    """Synchronous SQLite database (lightweight, no extra dependency).

    Uses standard sqlite3 module. For the bot's workload (a few writes per
    trade), synchronous SQLite is fast enough and avoids the aiosqlite dep.
    Writes happen in < 1ms — well within the 5-minute bar interval.
    """

    def __init__(self, db_path: str = "bot/data/trading.db"):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Open database connection and create tables if needed."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(CREATE_TABLES)
        self._conn.commit()
        logger.info(f"Database connected: {self.db_path}")

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Trades ---

    def save_trade_entry(self, ticker: str, direction: str,
                         quantity: float, entry_price: float,
                         stop_loss: float = None, take_profit: float = None,
                         signal_reason: str = "") -> int:
        """Save a trade entry. Returns the trade ID."""
        cursor = self._conn.execute(
            """INSERT INTO trades (entry_time, ticker, direction, quantity,
               entry_price, stop_loss, take_profit, signal_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                ticker, direction, quantity, entry_price,
                stop_loss, take_profit, signal_reason,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def save_trade_exit(self, trade_id: int, exit_price: float,
                        pnl: float, pnl_pct: float,
                        exit_reason: str = "") -> None:
        """Update a trade with exit information."""
        self._conn.execute(
            """UPDATE trades SET exit_time=?, exit_price=?, pnl=?,
               pnl_pct=?, exit_reason=? WHERE id=?""",
            (
                datetime.utcnow().isoformat(),
                exit_price, pnl, pnl_pct, exit_reason, trade_id,
            ),
        )
        self._conn.commit()

    def get_open_trades(self) -> list[dict]:
        """Get all trades that haven't been closed yet."""
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE exit_time IS NULL ORDER BY entry_time"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trades_today(self) -> list[dict]:
        """Get all trades from today."""
        today = date.today().isoformat()
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE entry_time >= ? ORDER BY entry_time",
            (today,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trades_by_ticker(self, ticker: str, limit: int = 50) -> list[dict]:
        """Get recent trades for a specific ticker."""
        rows = self._conn.execute(
            "SELECT * FROM trades WHERE ticker=? ORDER BY entry_time DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trade_history(self, limit: int = 100) -> list[dict]:
        """Get recent closed trades."""
        rows = self._conn.execute(
            """SELECT * FROM trades WHERE exit_time IS NOT NULL
               ORDER BY exit_time DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_trade_stats(self) -> dict:
        """Get aggregate trade statistics."""
        row = self._conn.execute(
            """SELECT
                COUNT(*) as total_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END) as breakeven,
                COALESCE(SUM(pnl), 0) as total_pnl,
                COALESCE(AVG(pnl), 0) as avg_pnl,
                COALESCE(MAX(pnl), 0) as best_trade,
                COALESCE(MIN(pnl), 0) as worst_trade
               FROM trades WHERE exit_time IS NOT NULL"""
        ).fetchone()
        return dict(row)

    # --- Daily P&L ---

    def save_daily_pnl(self, realized_pnl: float, trades: int,
                       wins: int, losses: int,
                       equity_start: float = None,
                       equity_end: float = None) -> None:
        """Save or update today's daily P&L record."""
        today = date.today().isoformat()
        self._conn.execute(
            """INSERT INTO daily_pnl (date, realized_pnl, trades_taken,
               wins, losses, equity_start, equity_end)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
               realized_pnl=?, trades_taken=?, wins=?, losses=?,
               equity_end=?""",
            (
                today, realized_pnl, trades, wins, losses,
                equity_start, equity_end,
                realized_pnl, trades, wins, losses, equity_end,
            ),
        )
        self._conn.commit()

    def get_daily_pnl_history(self, days: int = 30) -> list[dict]:
        """Get daily P&L for the last N days."""
        rows = self._conn.execute(
            "SELECT * FROM daily_pnl ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Bot State ---

    def save_state(self, key: str, value: any) -> None:
        """Save a key-value pair for bot state recovery."""
        self._conn.execute(
            """INSERT INTO bot_state (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?""",
            (
                key, json.dumps(value), datetime.utcnow().isoformat(),
                json.dumps(value), datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    def load_state(self, key: str, default=None) -> any:
        """Load a state value by key."""
        row = self._conn.execute(
            "SELECT value FROM bot_state WHERE key=?",
            (key,),
        ).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return default

    def clear_state(self, key: str) -> None:
        """Remove a state key."""
        self._conn.execute("DELETE FROM bot_state WHERE key=?", (key,))
        self._conn.commit()
