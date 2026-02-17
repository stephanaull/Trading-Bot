"""Command-line interface for the backtesting engine.

Usage:
    python -m runner.cli backtest --strategy strategies/example_ema_cross.py --data data/AAPL_1d.csv
    python -m runner.cli download --ticker AAPL --start 2020-01-01 --end 2024-12-31
    python -m runner.cli compare --strategies "strategies/aapl_*.py" --data data/AAPL_1d.csv
    python -m runner.cli list-data
    python -m runner.cli list-strategies
"""

import argparse
import sys
import glob
from pathlib import Path


def cmd_backtest(args):
    from engine.data_loader import DataLoader
    from engine.backtest import BacktestEngine
    from runner.strategy_manager import StrategyManager
    from runner.report_generator import ReportGenerator

    mgr = StrategyManager()
    result = mgr.run_backtest(
        strategy_file=args.strategy,
        data_file=args.data,
        initial_capital=args.capital,
        commission=args.commission,
        slippage=args.slippage,
        position_sizing=args.sizing,
    )

    # Print summary
    result.print_summary()

    # Generate report if requested
    if args.report:
        rg = ReportGenerator(result)
        path = rg.generate_html_report()
        print(f"Report saved to: {path}")

    if args.trades:
        rg = ReportGenerator(result)
        path = rg.export_trade_log()
        print(f"Trade log saved to: {path}")


def cmd_download(args):
    from engine.data_downloader import DataDownloader

    print(f"Downloading {args.ticker} data from {args.source}...")
    if args.source == "yahoo":
        df = DataDownloader.from_yahoo(
            ticker=args.ticker,
            start=args.start,
            end=args.end,
            interval=args.interval,
        )
    elif args.source == "alphavantage":
        if not args.api_key:
            print("Error: --api-key required for Alpha Vantage")
            sys.exit(1)
        df = DataDownloader.from_alpha_vantage(
            ticker=args.ticker,
            api_key=args.api_key,
        )
    else:
        print(f"Unknown source: {args.source}")
        sys.exit(1)

    path = DataDownloader.save_to_csv(df, args.ticker, args.interval)
    print(f"Saved {len(df)} bars to {path}")


def cmd_compare(args):
    from runner.strategy_manager import StrategyManager

    mgr = StrategyManager()

    # Expand glob pattern
    files = []
    for pattern in args.strategies:
        files.extend(glob.glob(pattern))

    if not files:
        print("No strategy files found matching the pattern.")
        sys.exit(1)

    print(f"Comparing {len(files)} strategies against {args.data}...")
    comparison = mgr.compare(files, args.data, initial_capital=args.capital)
    ranked = mgr.rank(comparison)
    mgr.print_comparison(ranked)


def cmd_list_data(args):
    from engine.data_loader import DataLoader

    files = DataLoader.list_available()
    if not files:
        print("No data files found in data/ directory.")
        return

    print(f"\n{'Available Data Files':^50}")
    print("=" * 50)
    for f in files:
        print(f"  {f['filename']:<30} {f['rows']:>6} bars  {f['ticker']}/{f['timeframe']}")
    print()


def cmd_list_strategies(args):
    from runner.strategy_manager import StrategyManager

    mgr = StrategyManager()
    strategies = mgr.list_strategies()

    if not strategies:
        print("No strategy files found in strategies/ directory.")
        return

    print(f"\n{'Available Strategies':^60}")
    print("=" * 60)
    for s in strategies:
        if "error" in s:
            print(f"  {s['filename']:<35} ERROR: {s['error']}")
        else:
            print(f"  {s['filename']:<35} {s['name']} {s['version']}")
            if s['description']:
                print(f"  {'':35} {s['description'][:50]}")
    print()


def cmd_export(args):
    from runner.strategy_manager import StrategyManager
    from export.pine_exporter import PineExporter

    mgr = StrategyManager()
    strategy = mgr.load_strategy(args.strategy)
    exporter = PineExporter(strategy)
    path = exporter.export(args.output)
    print(f"Pine Script exported to: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="Trading Backtest Engine CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # backtest command
    bt = subparsers.add_parser("backtest", help="Run a backtest")
    bt.add_argument("--strategy", "-s", required=True, help="Path to strategy .py file")
    bt.add_argument("--data", "-d", required=True, help="Path to OHLCV CSV file")
    bt.add_argument("--capital", "-c", type=float, default=100000, help="Initial capital")
    bt.add_argument("--commission", type=float, default=0.001, help="Commission rate")
    bt.add_argument("--slippage", type=float, default=0.0005, help="Slippage rate")
    bt.add_argument("--sizing", choices=["fixed", "percent", "risk_based"], default="fixed")
    bt.add_argument("--report", action="store_true", help="Generate HTML report")
    bt.add_argument("--trades", action="store_true", help="Export trade log CSV")

    # download command
    dl = subparsers.add_parser("download", help="Download market data")
    dl.add_argument("--ticker", "-t", required=True, help="Ticker symbol")
    dl.add_argument("--start", default="2020-01-01", help="Start date")
    dl.add_argument("--end", default="2025-12-31", help="End date")
    dl.add_argument("--interval", default="1d", help="Data interval (1d, 1h, etc.)")
    dl.add_argument("--source", choices=["yahoo", "alphavantage"], default="yahoo")
    dl.add_argument("--api-key", help="API key for Alpha Vantage")

    # compare command
    cmp = subparsers.add_parser("compare", help="Compare multiple strategies")
    cmp.add_argument("--strategies", nargs="+", required=True, help="Strategy file patterns")
    cmp.add_argument("--data", "-d", required=True, help="Path to OHLCV CSV file")
    cmp.add_argument("--capital", "-c", type=float, default=100000, help="Initial capital")

    # list-data command
    subparsers.add_parser("list-data", help="List available data files")

    # list-strategies command
    subparsers.add_parser("list-strategies", help="List available strategies")

    # export command
    exp = subparsers.add_parser("export", help="Export strategy to Pine Script")
    exp.add_argument("--strategy", "-s", required=True, help="Path to strategy .py file")
    exp.add_argument("--output", "-o", required=True, help="Output .pine file path")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "backtest": cmd_backtest,
        "download": cmd_download,
        "compare": cmd_compare,
        "list-data": cmd_list_data,
        "list-strategies": cmd_list_strategies,
        "export": cmd_export,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
