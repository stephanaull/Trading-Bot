"""Main entry point for the trading bot.

Phase 1: Connect to Alpaca, verify account, test order flow.
Phase 2+: Will add LiveEngine, data feeds, risk management.
"""

import asyncio
import logging
import sys
from pathlib import Path

from bot.config.settings import BotConfig
from bot.broker.alpaca_broker import AlpacaBroker

logger = logging.getLogger(__name__)


def setup_logging(config: BotConfig) -> None:
    """Configure logging to console and file."""
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    # Ensure log directory exists
    log_path = Path(config.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Root logger
    root = logging.getLogger()
    root.setLevel(log_level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console.setFormatter(console_fmt)
    root.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(config.log_file)
    file_handler.setLevel(log_level)
    file_fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)
    root.addHandler(file_handler)


async def run_bot(config: BotConfig) -> None:
    """Main bot loop.

    Phase 1: Connect, print account info, verify broker works.
    Phase 2+: Start data feeds, run LiveEngine per ticker.
    """
    mode = "PAPER" if config.paper_trading else "LIVE"
    logger.info(f"=== Trading Bot Starting ({mode} mode) ===")

    if not config.alpaca_api_key or not config.alpaca_secret_key:
        logger.error(
            "Alpaca API keys not set. Set ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY environment variables."
        )
        return

    # Initialize broker
    broker = AlpacaBroker(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key,
        paper=config.paper_trading,
    )

    try:
        await broker.connect()

        # Print account summary
        account = await broker.get_account()
        print(f"\n{'='*50}")
        print(f"  Trading Bot — {mode} Mode")
        print(f"{'='*50}")
        print(f"  Equity:       ${account['equity']:>12,.2f}")
        print(f"  Cash:         ${account['cash']:>12,.2f}")
        print(f"  Buying Power: ${account['buying_power']:>12,.2f}")
        print(f"  Status:       {account['status']}")
        print(f"{'='*50}")

        # Show configured strategies
        enabled = {
            t: s for t, s in config.strategies.items() if s.enabled
        }
        if enabled:
            print(f"\n  Configured Strategies ({len(enabled)}):")
            for ticker, strat in enabled.items():
                print(f"    {ticker}: {strat.file} ({strat.timeframe})")
                if strat.params:
                    print(f"      params: {strat.params}")
        else:
            print("\n  No strategies configured. Edit bot/config/default.toml")

        # Check market status
        market_open = await broker.is_market_open()
        print(f"\n  Market: {'OPEN' if market_open else 'CLOSED'}")

        # Show open positions
        positions = await broker.get_positions()
        if positions:
            print(f"\n  Open Positions ({len(positions)}):")
            for p in positions:
                pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
                print(
                    f"    {p['ticker']}: {p['side']} {p['qty']:.0f} "
                    f"@ ${p['avg_price']:.2f} "
                    f"(P&L: {pnl_sign}${p['unrealized_pnl']:.2f})"
                )
        else:
            print("\n  No open positions.")

        print(f"\n{'='*50}")
        print("  Phase 1 complete. Broker connection verified.")
        print("  Phase 2 (LiveEngine + data feeds) coming next.")
        print(f"{'='*50}\n")

    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
    finally:
        await broker.disconnect()


async def test_order(config: BotConfig, ticker: str = "AAPL",
                     qty: float = 1) -> None:
    """Submit a test market order (paper mode only) and immediately cancel/close.

    This verifies the full order flow works end-to-end.
    """
    if not config.paper_trading:
        logger.error("Test orders only allowed in paper mode!")
        return

    broker = AlpacaBroker(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key,
        paper=True,
    )

    try:
        await broker.connect()

        from engine.order import Order
        import pandas as pd

        order = Order(
            timestamp=pd.Timestamp.now(tz="UTC"),
            ticker=ticker,
            direction="long",
            order_type="market",
            quantity=qty,
            reason="test_order",
        )

        print(f"\nSubmitting test order: BUY {qty} {ticker}...")
        trade = await broker.submit_order(order)
        print(
            f"  Filled: {trade.quantity:.0f} {trade.ticker} "
            f"@ ${trade.entry_price:.2f}"
        )

        # Immediately close
        print(f"  Closing test position...")
        close_trade = await broker.close_position(ticker)
        if close_trade:
            print(f"  Closed @ ${close_trade.entry_price:.2f}")
        print("  Test order flow complete!\n")

    except Exception as e:
        logger.error(f"Test order failed: {e}", exc_info=True)
    finally:
        await broker.disconnect()
