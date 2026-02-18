"""Bot CLI — command-line interface for the trading bot.

Usage:
    python -m bot.cli start [--config PATH] [--live]
    python -m bot.cli status [--config PATH]
    python -m bot.cli test-order [--ticker AAPL] [--qty 1]
    python -m bot.cli account [--config PATH]
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is on path
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def load_env():
    """Load .env file if it exists."""
    env_file = Path(project_root) / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass  # python-dotenv not installed, rely on real env vars


def get_config(args):
    """Load config from CLI args."""
    from bot.config.settings import BotConfig

    config_path = getattr(args, "config", None) or "bot/config/default.toml"
    config = BotConfig.load(config_path)

    # CLI overrides
    if getattr(args, "live", False):
        config.paper_trading = False

    return config


def cmd_start(args):
    """Start the trading bot."""
    config = get_config(args)
    from bot.main import run_bot, setup_logging
    setup_logging(config)
    asyncio.run(run_bot(config))


def cmd_test_order(args):
    """Submit a test order (paper mode only)."""
    config = get_config(args)
    config.paper_trading = True  # Force paper mode for test
    from bot.main import test_order, setup_logging
    setup_logging(config)
    asyncio.run(test_order(config, ticker=args.ticker, qty=args.qty))


def cmd_account(args):
    """Show account details."""
    config = get_config(args)
    from bot.main import run_bot, setup_logging
    setup_logging(config)
    asyncio.run(run_bot(config))


def cmd_bars(args):
    """Fetch and display recent bars for a ticker."""
    config = get_config(args)
    from bot.main import setup_logging
    setup_logging(config)

    async def _fetch():
        from bot.broker.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            paper=config.paper_trading,
        )
        await broker.connect()
        df = await broker.get_bars(args.ticker, args.timeframe, limit=args.limit)
        await broker.disconnect()

        print(f"\n  {args.ticker} — Last {len(df)} bars ({args.timeframe})\n")
        print(df.tail(args.limit).to_string())
        print()

    asyncio.run(_fetch())


def main():
    parser = argparse.ArgumentParser(
        prog="bot",
        description="Trading Bot CLI",
    )
    parser.add_argument(
        "--config", "-c",
        default="bot/config/default.toml",
        help="Path to TOML config file (default: bot/config/default.toml)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # start
    p_start = subparsers.add_parser("start", help="Start the trading bot")
    p_start.add_argument("--live", action="store_true", help="Use live trading (default: paper)")
    p_start.set_defaults(func=cmd_start)

    # test-order
    p_test = subparsers.add_parser("test-order", help="Submit a test order (paper only)")
    p_test.add_argument("--ticker", "-t", default="AAPL", help="Ticker to test (default: AAPL)")
    p_test.add_argument("--qty", "-q", type=float, default=1, help="Quantity (default: 1)")
    p_test.set_defaults(func=cmd_test_order)

    # account
    p_account = subparsers.add_parser("account", help="Show account info")
    p_account.set_defaults(func=cmd_account)

    # bars
    p_bars = subparsers.add_parser("bars", help="Fetch recent bars for a ticker")
    p_bars.add_argument("ticker", help="Ticker symbol (e.g., MSTR)")
    p_bars.add_argument("--timeframe", "-tf", default="5m", help="Timeframe (default: 5m)")
    p_bars.add_argument("--limit", "-n", type=int, default=20, help="Number of bars (default: 20)")
    p_bars.set_defaults(func=cmd_bars)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    load_env()
    args.func(args)


if __name__ == "__main__":
    main()
