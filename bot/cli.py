"""Bot CLI — command-line interface for the trading bot.

Usage:
    python -m bot.cli start [--config PATH] [--live]
    python -m bot.cli account
    python -m bot.cli trades [--today] [--limit N]
    python -m bot.cli stats
    python -m bot.cli bars TICKER [--timeframe 5m] [--limit 20]
    python -m bot.cli test-order [--ticker AAPL] [--qty 1]
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
    """Show account details and open positions."""
    config = get_config(args)

    async def _show():
        from bot.broker.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            paper=config.paper_trading,
        )
        await broker.connect()
        account = await broker.get_account()
        positions = await broker.get_positions()
        market_open = await broker.is_market_open()
        await broker.disconnect()

        mode = "PAPER" if config.paper_trading else "LIVE"
        print(f"\n{'='*50}")
        print(f"  Account — {mode} Mode")
        print(f"{'='*50}")
        print(f"  Equity:       ${account['equity']:>12,.2f}")
        print(f"  Cash:         ${account['cash']:>12,.2f}")
        print(f"  Buying Power: ${account['buying_power']:>12,.2f}")
        print(f"  Status:       {account['status']}")
        print(f"  Market:       {'OPEN' if market_open else 'CLOSED'}")

        if positions:
            print(f"\n  Open Positions ({len(positions)}):")
            for p in positions:
                pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
                print(
                    f"    {p['ticker']}: {p['side'].upper()} {p['qty']:.0f} "
                    f"@ ${p['avg_price']:.2f} → ${p['current_price']:.2f} "
                    f"({pnl_sign}${p['unrealized_pnl']:.2f})"
                )
        else:
            print(f"\n  No open positions.")
        print(f"{'='*50}\n")

    asyncio.run(_show())


def cmd_trades(args):
    """Show trade history from the database."""
    config = get_config(args)
    from bot.storage.database import Database

    db = Database(db_path=config.db_path)
    db.connect()

    if args.today:
        trades = db.get_trades_today()
        title = "Today's Trades"
    else:
        trades = db.get_trade_history(limit=args.limit)
        title = f"Recent Trades (last {args.limit})"

    db.close()

    if not trades:
        print(f"\n  {title}: No trades found.\n")
        return

    print(f"\n  {title} ({len(trades)} trades)")
    print(f"  {'='*80}")
    print(f"  {'Time':<20} {'Ticker':<6} {'Dir':<6} {'Qty':>6} "
          f"{'Entry':>10} {'Exit':>10} {'P&L':>12} {'Reason'}")
    print(f"  {'-'*80}")

    total_pnl = 0
    for t in trades:
        direction = t.get("direction", "?")[:5].upper()
        entry = f"${t['entry_price']:.2f}" if t.get("entry_price") else "—"
        exit_p = f"${t['exit_price']:.2f}" if t.get("exit_price") else "open"
        if t.get("pnl") is not None:
            pnl = t["pnl"]
            total_pnl += pnl
            sign = "+" if pnl >= 0 else ""
            pnl_str = f"{sign}${pnl:,.2f}"
        else:
            pnl_str = "—"
        reason = t.get("exit_reason", "") or t.get("signal_reason", "")
        time_str = t.get("entry_time", "")[:19]

        print(f"  {time_str:<20} {t['ticker']:<6} {direction:<6} "
              f"{t['quantity']:>6.0f} {entry:>10} {exit_p:>10} "
              f"{pnl_str:>12} {reason}")

    sign = "+" if total_pnl >= 0 else ""
    print(f"  {'-'*80}")
    print(f"  {'Total P&L':>64} {sign}${total_pnl:,.2f}")
    print()


def cmd_stats(args):
    """Show aggregate trade statistics from the database."""
    config = get_config(args)
    from bot.storage.database import Database

    db = Database(db_path=config.db_path)
    db.connect()

    stats = db.get_trade_stats()
    daily = db.get_daily_pnl_history(days=10)
    db.close()

    total = stats["total_trades"]
    wins = stats["wins"] or 0
    losses = stats["losses"] or 0
    win_rate = (wins / total * 100) if total > 0 else 0

    print(f"\n{'='*50}")
    print(f"  Trade Statistics (All Time)")
    print(f"{'='*50}")
    print(f"  Total Trades:  {total}")
    print(f"  Wins:          {wins}")
    print(f"  Losses:        {losses}")
    print(f"  Win Rate:      {win_rate:.1f}%")
    sign = "+" if stats["total_pnl"] >= 0 else ""
    print(f"  Total P&L:     {sign}${stats['total_pnl']:,.2f}")
    print(f"  Avg P&L:       ${stats['avg_pnl']:,.2f}")
    print(f"  Best Trade:    +${stats['best_trade']:,.2f}")
    print(f"  Worst Trade:   ${stats['worst_trade']:,.2f}")

    if daily:
        print(f"\n  Daily P&L (Last {len(daily)} days):")
        print(f"  {'Date':<12} {'P&L':>12} {'Trades':>8} {'W/L':>8}")
        print(f"  {'-'*44}")
        for d in daily:
            sign = "+" if d["realized_pnl"] >= 0 else ""
            wl = f"{d['wins'] or 0}W/{d['losses'] or 0}L"
            print(f"  {d['date']:<12} {sign}${d['realized_pnl']:>10,.2f} "
                  f"{d['trades_taken'] or 0:>8} {wl:>8}")
    print(f"{'='*50}\n")


def cmd_bars(args):
    """Fetch and display recent bars for a ticker."""
    config = get_config(args)

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
    p_start.add_argument("--live", action="store_true",
                         help="Use live trading (default: paper)")
    p_start.set_defaults(func=cmd_start)

    # account
    p_account = subparsers.add_parser("account",
                                       help="Show account info and positions")
    p_account.set_defaults(func=cmd_account)

    # trades
    p_trades = subparsers.add_parser("trades", help="Show trade history")
    p_trades.add_argument("--today", action="store_true",
                          help="Show only today's trades")
    p_trades.add_argument("--limit", "-n", type=int, default=50,
                          help="Number of trades to show (default: 50)")
    p_trades.set_defaults(func=cmd_trades)

    # stats
    p_stats = subparsers.add_parser("stats",
                                     help="Show aggregate trade statistics")
    p_stats.set_defaults(func=cmd_stats)

    # bars
    p_bars = subparsers.add_parser("bars",
                                    help="Fetch recent bars for a ticker")
    p_bars.add_argument("ticker", help="Ticker symbol (e.g., MSTR)")
    p_bars.add_argument("--timeframe", "-tf", default="5m",
                        help="Timeframe (default: 5m)")
    p_bars.add_argument("--limit", "-n", type=int, default=20,
                        help="Number of bars (default: 20)")
    p_bars.set_defaults(func=cmd_bars)

    # test-order
    p_test = subparsers.add_parser("test-order",
                                    help="Submit a test order (paper only)")
    p_test.add_argument("--ticker", "-t", default="AAPL",
                        help="Ticker to test (default: AAPL)")
    p_test.add_argument("--qty", "-q", type=float, default=1,
                        help="Quantity (default: 1)")
    p_test.set_defaults(func=cmd_test_order)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    load_env()
    args.func(args)


if __name__ == "__main__":
    main()
