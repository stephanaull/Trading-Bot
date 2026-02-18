"""Main entry point for the trading bot.

Wires together: Broker → Feed → Aggregator → Warmup → Engine → Reports.

Supports two modes per ticker:
- Single timeframe: one LiveEngine per ticker (legacy)
- Multi-timeframe: one MultiTimeframeEngine per ticker that runs
  the strategy on 2m, 5m, 10m (etc.) and picks the best entry.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from pathlib import Path

from bot.config.settings import BotConfig
from bot.broker.alpaca_broker import AlpacaBroker
from bot.feeds.alpaca_feed import AlpacaFeed
from bot.engine.warmup import warmup_strategy, load_strategy
from bot.engine.live_engine import LiveEngine
from bot.engine.multi_tf_engine import MultiTimeframeEngine, _TimeframeSlot
from bot.notifications.daily_report import DailyReport
from bot.risk.manager import RiskManager
from bot.storage.database import Database

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
    """Main bot loop: connect, warm up, stream bars, trade."""
    mode = "PAPER" if config.paper_trading else "LIVE"
    logger.info(f"=== Trading Bot Starting ({mode} mode) ===")

    if not config.alpaca_api_key or not config.alpaca_secret_key:
        logger.error(
            "Alpaca API keys not set. Set ALPACA_API_KEY and "
            "ALPACA_SECRET_KEY environment variables."
        )
        return

    # Get enabled strategies
    enabled = {t: s for t, s in config.strategies.items() if s.enabled}
    if not enabled:
        logger.error("No strategies enabled. Edit bot/config/default.toml")
        return

    # Initialize broker
    broker = AlpacaBroker(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key,
        paper=config.paper_trading,
    )

    # Initialize daily report
    daily_report = DailyReport()

    # Initialize data feed
    feed = AlpacaFeed(
        api_key=config.alpaca_api_key,
        secret_key=config.alpaca_secret_key,
        feed="iex",
    )

    # engines dict: ticker -> LiveEngine or MultiTimeframeEngine
    engines: dict = {}
    shutdown_event = asyncio.Event()

    try:
        # Step 1: Connect broker + initialize services
        await broker.connect()
        account = await broker.get_account()
        daily_report.set_account_start(account)
        daily_report.log_status(f"Bot started ({mode} mode)")

        _print_banner(mode, account, enabled)

        # Initialize risk manager
        risk_manager = RiskManager(
            config=config.risk,
            initial_equity=account["equity"],
        )

        # Initialize database
        db = Database(db_path=config.db_path)
        db.connect()

        # Step 2: Load strategies, warm up, create engines
        for ticker, strat_config in enabled.items():
            timeframes = strat_config.get_timeframes()
            is_multi_tf = len(timeframes) > 1

            if is_multi_tf:
                # Multi-timeframe mode
                logger.info(f"--- Setting up {ticker} (multi-TF: {', '.join(timeframes)}) ---")
                slots = []

                for tf in timeframes:
                    # Load a separate strategy instance per timeframe
                    strategy = load_strategy(strat_config.file, strat_config.params)

                    # Warm up with the specific timeframe
                    df = await warmup_strategy(strategy, broker, ticker, tf)

                    if df.empty:
                        logger.warning(f"Skipping {ticker}/{tf} — no historical data")
                        continue

                    slots.append(_TimeframeSlot(
                        timeframe=tf,
                        strategy=strategy,
                        initial_df=df,
                    ))

                if not slots:
                    logger.warning(f"Skipping {ticker} — no valid timeframes")
                    continue

                engine = MultiTimeframeEngine(
                    ticker=ticker,
                    slots=slots,
                    broker=broker,
                    daily_report=daily_report,
                    risk_manager=risk_manager,
                    db=db,
                    position_sizing=config.position_sizing,
                    pct_equity=config.pct_equity,
                    fixed_size=config.fixed_size,
                    risk_pct=config.risk_pct,
                    long_only=strat_config.long_only,
                )

                await engine.reconcile()
                engines[ticker] = engine

                daily_report.log_status(
                    f"Multi-TF strategy loaded: {slots[0].strategy.name} "
                    f"on {ticker} ({', '.join(timeframes)})"
                )

            else:
                # Single timeframe mode (legacy)
                tf = timeframes[0]
                logger.info(f"--- Setting up {ticker} ({tf}) ---")

                strategy = load_strategy(strat_config.file, strat_config.params)
                df = await warmup_strategy(strategy, broker, ticker, tf)

                if df.empty:
                    logger.warning(f"Skipping {ticker} — no historical data")
                    daily_report.log_error(f"{ticker}: No historical data for warmup")
                    continue

                engine = LiveEngine(
                    ticker=ticker,
                    strategy=strategy,
                    broker=broker,
                    daily_report=daily_report,
                    initial_df=df,
                    risk_manager=risk_manager,
                    db=db,
                    position_sizing=config.position_sizing,
                    pct_equity=config.pct_equity,
                    fixed_size=config.fixed_size,
                    risk_pct=config.risk_pct,
                    long_only=strat_config.long_only,
                )

                await engine.reconcile()
                engines[ticker] = engine
                daily_report.log_status(
                    f"Strategy loaded: {strategy.name} on {ticker} ({tf})"
                )

        if not engines:
            logger.error("No engines created. Check strategy files and data.")
            return

        # Step 3: Set up data feed with aggregators
        await feed.connect()

        for ticker, strat_config in enabled.items():
            if ticker in engines:
                for tf in strat_config.get_timeframes():
                    tf_minutes = int(tf.replace("m", ""))
                    feed.add_aggregator(ticker, tf_minutes)

        # Register bar callback — routes to the right engine
        async def _on_aggregated_bar(ticker: str, timeframe: str, bar):
            engine = engines.get(ticker)
            if engine is None:
                return
            if isinstance(engine, MultiTimeframeEngine):
                await engine.on_bar(ticker, timeframe, bar)
            elif isinstance(engine, LiveEngine):
                await engine.on_bar(ticker, bar)

        feed.on_bar(_on_aggregated_bar)

        # Subscribe to all tickers
        tickers = list(engines.keys())
        await feed.subscribe(tickers)

        # Step 4: Check market status
        market_open = await broker.is_market_open()
        if not market_open:
            logger.info("Market is CLOSED. Bot will stream bars when market opens.")
            daily_report.log_status("Market is closed. Waiting for open.")
        else:
            logger.info("Market is OPEN. Streaming live bars...")

        # Handle graceful shutdown
        def _signal_handler():
            logger.info("Shutdown signal received...")
            shutdown_event.set()

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

        print(f"\n  Bot running. Streaming bars for: {', '.join(tickers)}")
        print(f"  Press Ctrl+C to stop.\n")

        # Step 5: Run the feed (blocking) with periodic reconciliation
        feed_task = asyncio.create_task(_run_feed(feed))
        reconcile_task = asyncio.create_task(
            _periodic_reconcile(engines, interval=300)
        )

        await shutdown_event.wait()

        # --- Graceful shutdown sequence ---
        # 1. Deactivate all engines (prevents new trades during shutdown)
        logger.info("Deactivating engines...")
        for ticker, engine in engines.items():
            engine.active = False

        # 2. Cancel the feed and reconcile tasks
        feed_task.cancel()
        reconcile_task.cancel()

        # 3. Wait briefly for any in-flight bar processing to complete
        await asyncio.sleep(1)

        # 4. Cancel any pending orders on the broker
        try:
            await broker.cancel_all()
            logger.info("Cancelled all pending orders")
        except Exception as e:
            logger.warning(f"Could not cancel pending orders: {e}")

    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        daily_report.log_error(f"Fatal error: {e}")
    finally:
        logger.info("Shutting down...")
        daily_report.log_status("Bot stopped")

        end_account = None
        try:
            end_account = await broker.get_account()
            end_positions = await broker.get_positions()
            daily_report.set_account_end(end_account, end_positions)
        except Exception:
            pass

        try:
            stats = risk_manager.get_daily_stats()
            db.save_daily_pnl(
                realized_pnl=stats["daily_pnl"],
                trades=stats["trades"],
                wins=stats["wins"],
                losses=stats["losses"],
                equity_start=account.get("equity", 0),
                equity_end=end_account.get("equity", 0) if end_account else None,
            )
        except Exception:
            pass

        report_path = daily_report.save()
        logger.info(f"Daily report saved: {report_path}")

        # Close resources in correct order: DB last (engines might still reference it)
        await feed.disconnect()
        await broker.disconnect()
        db.close()

        print(f"\n  Bot stopped. Report: {report_path}\n")


async def _run_feed(feed: AlpacaFeed) -> None:
    """Run the feed in a task (catches cancellation)."""
    try:
        await asyncio.get_event_loop().run_in_executor(None, feed._stream.run)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Feed error: {e}")


async def _periodic_reconcile(engines: dict, interval: int = 300) -> None:
    """Periodically reconcile positions with broker."""
    try:
        while True:
            await asyncio.sleep(interval)
            for ticker, engine in engines.items():
                try:
                    await engine.reconcile()
                except Exception as e:
                    logger.error(f"Reconciliation error for {ticker}: {e}")
    except asyncio.CancelledError:
        pass


def _print_banner(mode: str, account: dict, strategies: dict) -> None:
    """Print startup banner with day trading info."""
    pdt = account.get("pattern_day_trader", False)
    dt_count = account.get("daytrade_count", 0)
    multiplier = account.get("multiplier", 1)
    regt_bp = account.get("regt_buying_power", account["buying_power"])
    dt_bp = account.get("daytrading_buying_power", 0)

    # Determine day trade status
    if pdt:
        dt_status = f"PDT — Unlimited day trades ({multiplier}x margin)"
    elif account["equity"] >= 25_000:
        dt_status = f"Above $25k — Unlimited day trades ({multiplier}x margin)"
    else:
        dt_remaining = max(0, 3 - dt_count)
        dt_status = f"{dt_remaining} day trades remaining (non-PDT, {dt_count}/3 used)"

    print(f"\n{'='*60}")
    print(f"  Trading Bot — {mode} Mode")
    print(f"{'='*60}")
    print(f"  Equity:           ${account['equity']:>12,.2f}")
    print(f"  Cash:             ${account['cash']:>12,.2f}")
    print(f"  Buying Power:     ${account['buying_power']:>12,.2f}")
    print(f"  Reg-T BP:         ${regt_bp:>12,.2f}")
    if dt_bp > 0:
        print(f"  Day Trade BP:     ${dt_bp:>12,.2f}")
    print(f"  Day Trades:       {dt_status}")
    print(f"  Status:           {account['status']}")
    print(f"{'='*60}")
    print(f"\n  Strategies ({len(strategies)}):")
    for ticker, strat in strategies.items():
        tfs = strat.get_timeframes()
        tf_str = ", ".join(tfs) if len(tfs) > 1 else tfs[0]
        flags = ""
        if strat.long_only:
            flags += " [LONG ONLY]"
        if len(tfs) > 1:
            flags += " [MULTI-TF]"
        print(f"    {ticker}: {strat.file} ({tf_str}){flags}")
    print()


async def test_order(config: BotConfig, ticker: str = "AAPL",
                     qty: float = 1) -> None:
    """Submit a test market order (paper mode only) and immediately close."""
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

        print(f"  Closing test position...")
        close_trade = await broker.close_position(ticker)
        if close_trade:
            print(f"  Closed @ ${close_trade.entry_price:.2f}")
        print("  Test order flow complete!\n")

    except Exception as e:
        logger.error(f"Test order failed: {e}", exc_info=True)
    finally:
        await broker.disconnect()
