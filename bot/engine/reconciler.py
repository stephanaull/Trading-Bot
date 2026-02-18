"""Position reconciliation between local state and broker.

The reconciler ensures the bot's internal position tracking matches
what the broker actually reports. This handles:
- Missed fills (network issues)
- Manual trades (user trades outside the bot)
- Bot restart (recover open positions)
- Order rejections not yet reflected locally
"""

import logging
from typing import Optional

from bot.broker.base import BaseBroker
from engine.position import Position
from engine.order import Trade

import pandas as pd

logger = logging.getLogger(__name__)


class Reconciler:
    """Synchronize local position state with broker positions."""

    async def reconcile(
        self,
        ticker: str,
        local_position: Optional[Position],
        broker: BaseBroker,
    ) -> dict:
        """Compare local position with broker and report discrepancies.

        Args:
            ticker: Symbol to reconcile
            local_position: Our tracked position (or None if flat)
            broker: Connected broker to query

        Returns:
            dict with:
                "match": bool — whether local and broker agree
                "broker_position": dict or None — broker's view
                "local_position": Position or None — our view
                "action": str — "none", "adopt_broker", "clear_local", "mismatch"
                "details": str — human-readable description
        """
        broker_pos = await broker.get_position(ticker)

        has_local = local_position is not None
        has_broker = broker_pos is not None

        # Case 1: Both agree — no position
        if not has_local and not has_broker:
            return {
                "match": True,
                "broker_position": None,
                "local_position": None,
                "action": "none",
                "details": f"{ticker}: Flat (agreed)",
            }

        # Case 2: Both have a position — check they agree
        if has_local and has_broker:
            local_dir = local_position.direction
            broker_dir = broker_pos["side"]
            local_qty = local_position.quantity
            broker_qty = broker_pos["qty"]

            if local_dir == broker_dir and abs(local_qty - broker_qty) < 0.01:
                return {
                    "match": True,
                    "broker_position": broker_pos,
                    "local_position": local_position,
                    "action": "none",
                    "details": (
                        f"{ticker}: {local_dir} {local_qty:.0f} (agreed)"
                    ),
                }
            else:
                return {
                    "match": False,
                    "broker_position": broker_pos,
                    "local_position": local_position,
                    "action": "mismatch",
                    "details": (
                        f"{ticker}: MISMATCH — "
                        f"local={local_dir} {local_qty:.0f}, "
                        f"broker={broker_dir} {broker_qty:.0f}"
                    ),
                }

        # Case 3: Broker has position, we don't — adopt it
        if has_broker and not has_local:
            return {
                "match": False,
                "broker_position": broker_pos,
                "local_position": None,
                "action": "adopt_broker",
                "details": (
                    f"{ticker}: Broker has {broker_pos['side']} "
                    f"{broker_pos['qty']:.0f} @ ${broker_pos['avg_price']:.2f} "
                    f"— local is flat. Adopting broker position."
                ),
            }

        # Case 4: We have position, broker doesn't — clear local
        if has_local and not has_broker:
            return {
                "match": False,
                "broker_position": None,
                "local_position": local_position,
                "action": "clear_local",
                "details": (
                    f"{ticker}: Local has {local_position.direction} "
                    f"{local_position.quantity:.0f} — broker is flat. "
                    f"Clearing local state."
                ),
            }

        # Should never reach here
        return {
            "match": False,
            "broker_position": broker_pos,
            "local_position": local_position,
            "action": "unknown",
            "details": f"{ticker}: Unknown reconciliation state",
        }

    def adopt_broker_position(self, broker_pos: dict, ticker: str) -> Position:
        """Create a local Position from broker data.

        Used when the broker has a position we don't know about
        (e.g., after bot restart, manual trade).

        Args:
            broker_pos: dict from broker.get_position()
            ticker: Symbol

        Returns:
            Position object tracking this position locally
        """
        trade = Trade(
            entry_time=pd.Timestamp.now(tz="UTC"),
            ticker=ticker,
            direction=broker_pos["side"],
            quantity=broker_pos["qty"],
            entry_price=broker_pos["avg_price"],
            commission=0.0,
        )

        position = Position(
            trade=trade,
            stop_loss=None,     # Unknown — strategy will manage on next bar
            take_profit=None,
        )

        logger.info(
            f"Adopted broker position: {broker_pos['side']} "
            f"{broker_pos['qty']:.0f} {ticker} @ ${broker_pos['avg_price']:.2f}"
        )
        return position
