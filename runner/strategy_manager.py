"""Strategy versioning, comparison, ranking, and pruning.

Manages the lifecycle of AI-generated strategy files:
- Version tracking (ticker_approach_v1.py, v2, v3...)
- Side-by-side comparison across metrics
- Ranking by chosen metric (default: Sharpe Ratio)
- Auto-pruning of underperforming strategies
"""

import os
import re
import logging
import importlib.util
from pathlib import Path
from typing import Optional

import pandas as pd

from engine.backtest import BacktestEngine, BacktestResult
from engine.data_loader import DataLoader
from engine.utils import get_strategies_dir
from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class StrategyManager:
    """Manages strategy files: loading, comparison, ranking, and pruning."""

    def __init__(self, strategies_dir: str = None):
        self.strategies_dir = Path(strategies_dir) if strategies_dir else get_strategies_dir()

    def load_strategy(self, filepath: str) -> BaseStrategy:
        """Dynamically import and instantiate a strategy from a .py file.

        The strategy file must contain a class named 'Strategy' that
        subclasses BaseStrategy.

        Args:
            filepath: Path to the strategy .py file

        Returns:
            Instantiated strategy object
        """
        filepath = Path(filepath)
        if not filepath.is_absolute():
            # Try relative to CWD first, then relative to strategies dir
            if not filepath.exists():
                filepath = self.strategies_dir / filepath.name

        if not filepath.exists():
            raise FileNotFoundError(f"Strategy file not found: {filepath}")

        module_name = filepath.stem
        spec = importlib.util.spec_from_file_location(module_name, str(filepath))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "Strategy"):
            raise AttributeError(f"Strategy file {filepath.name} must define a 'Strategy' class")

        strategy = module.Strategy()
        if not isinstance(strategy, BaseStrategy):
            raise TypeError(f"Strategy class in {filepath.name} must subclass BaseStrategy")

        return strategy

    def run_backtest(self, strategy_file: str, data_file: str,
                     initial_capital: float = 100_000.0,
                     commission: float = 0.001,
                     slippage: float = 0.0005,
                     position_sizing: str = "fixed",
                     **kwargs) -> BacktestResult:
        """Load a strategy and run a backtest against a data file.

        Args:
            strategy_file: Path to strategy .py file
            data_file: Path to OHLCV CSV file
            initial_capital: Starting capital
            commission: Commission rate
            slippage: Slippage rate
            position_sizing: Position sizing method

        Returns:
            BacktestResult
        """
        strategy = self.load_strategy(strategy_file)
        data = DataLoader.from_csv(data_file)

        engine = BacktestEngine(
            data=data,
            strategy=strategy,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            position_sizing=position_sizing,
            **kwargs,
        )
        return engine.run()

    def compare(self, strategy_files: list, data_file: str,
                initial_capital: float = 100_000.0, **kwargs) -> pd.DataFrame:
        """Run multiple strategies against the same data and compare results.

        Args:
            strategy_files: List of paths to strategy .py files
            data_file: Path to OHLCV CSV file
            initial_capital: Starting capital

        Returns:
            DataFrame comparing key metrics across strategies
        """
        results = []

        for sf in strategy_files:
            try:
                result = self.run_backtest(sf, data_file,
                                           initial_capital=initial_capital, **kwargs)
                row = {"strategy": result.strategy_name, "file": Path(sf).name}
                row.update(result.metrics)
                results.append(row)
            except Exception as e:
                logger.error(f"Failed to backtest {sf}: {e}")
                results.append({"strategy": Path(sf).stem, "file": Path(sf).name,
                                "error": str(e)})

        return pd.DataFrame(results)

    def rank(self, comparison_df: pd.DataFrame,
             sort_by: str = "sharpe_ratio",
             ascending: bool = False) -> pd.DataFrame:
        """Rank strategies by a metric.

        Args:
            comparison_df: DataFrame from compare()
            sort_by: Metric column to sort by
            ascending: Sort direction

        Returns:
            Sorted DataFrame with rank column
        """
        if sort_by not in comparison_df.columns:
            logger.warning(f"Column {sort_by} not found. Using net_profit_pct.")
            sort_by = "net_profit_pct"

        ranked = comparison_df.sort_values(sort_by, ascending=ascending).reset_index(drop=True)
        ranked.index = ranked.index + 1
        ranked.index.name = "rank"
        return ranked

    def prune(self, ticker: str = None, keep_top_n: int = 3,
              min_sharpe: float = 0.5, min_profit_factor: float = 1.0,
              data_file: str = None, dry_run: bool = False) -> list:
        """Delete underperforming strategy files.

        Keeps the top N strategies by Sharpe ratio, plus any meeting
        minimum thresholds. Deletes the rest.

        Args:
            ticker: Only prune strategies for this ticker (None = all)
            keep_top_n: Number of top strategies to keep
            min_sharpe: Minimum Sharpe ratio to survive pruning
            min_profit_factor: Minimum profit factor to survive pruning
            data_file: Data file to backtest against (required if no cached results)
            dry_run: If True, only report what would be deleted

        Returns:
            List of deleted (or would-be-deleted) file paths
        """
        # Find strategy files
        pattern = f"{ticker.lower()}_*.py" if ticker else "*.py"
        files = [f for f in self.strategies_dir.glob(pattern)
                 if not f.name.startswith("base_") and
                    not f.name.startswith("__") and
                    not f.name.startswith("example_")]

        if len(files) <= keep_top_n:
            logger.info(f"Only {len(files)} strategies found. Nothing to prune.")
            return []

        if data_file is None:
            logger.error("data_file required for pruning (need to run backtests)")
            return []

        # Run backtests to get metrics
        comparison = self.compare([str(f) for f in files], data_file)
        if "error" in comparison.columns:
            comparison = comparison[comparison["error"].isna()]

        if len(comparison) == 0:
            return []

        # Rank by Sharpe
        ranked = self.rank(comparison, sort_by="sharpe_ratio")

        # Determine which to keep
        to_keep = set()
        # Keep top N
        for i, row in ranked.head(keep_top_n).iterrows():
            to_keep.add(row["file"])
        # Keep any meeting minimum thresholds
        for _, row in ranked.iterrows():
            if (row.get("sharpe_ratio", 0) >= min_sharpe and
                    row.get("profit_factor", 0) >= min_profit_factor):
                to_keep.add(row["file"])

        # Delete the rest
        deleted = []
        for f in files:
            if f.name not in to_keep:
                if dry_run:
                    logger.info(f"Would delete: {f.name}")
                else:
                    f.unlink()
                    logger.info(f"Deleted: {f.name}")
                deleted.append(str(f))

        return deleted

    def get_versions(self, ticker: str) -> list:
        """List all strategy versions for a ticker.

        Args:
            ticker: Ticker symbol (e.g., 'aapl', 'btc')

        Returns:
            List of dicts with filename, version, approach
        """
        pattern = f"{ticker.lower()}_*.py"
        files = sorted(self.strategies_dir.glob(pattern))

        versions = []
        for f in files:
            match = re.match(r"(.+?)_v(\d+)(?:_(.+))?\.py", f.name)
            if match:
                versions.append({
                    "filename": f.name,
                    "path": str(f),
                    "ticker": match.group(1),
                    "version": int(match.group(2)),
                    "suffix": match.group(3) or "",
                })
            else:
                versions.append({
                    "filename": f.name,
                    "path": str(f),
                    "ticker": ticker,
                    "version": 0,
                    "suffix": f.stem,
                })

        return versions

    def get_best(self, ticker: str, data_file: str,
                 sort_by: str = "sharpe_ratio") -> Optional[str]:
        """Return filepath of best-performing strategy for a ticker.

        Args:
            ticker: Ticker symbol
            data_file: Path to data file for backtesting
            sort_by: Metric to rank by

        Returns:
            Path to best strategy file, or None
        """
        versions = self.get_versions(ticker)
        if not versions:
            return None

        files = [v["path"] for v in versions]
        comparison = self.compare(files, data_file)
        if comparison.empty:
            return None

        ranked = self.rank(comparison, sort_by=sort_by)
        best_file = ranked.iloc[0]["file"]
        return str(self.strategies_dir / best_file)

    def list_strategies(self) -> list:
        """List all strategy files (excluding base and __init__)."""
        files = []
        for f in sorted(self.strategies_dir.glob("*.py")):
            if f.name.startswith("__") or f.name == "base_strategy.py":
                continue
            try:
                strategy = self.load_strategy(str(f))
                files.append({
                    "filename": f.name,
                    "name": strategy.name,
                    "version": strategy.version,
                    "description": strategy.description,
                    "ticker": strategy.ticker,
                    "timeframe": strategy.timeframe,
                })
            except Exception as e:
                files.append({
                    "filename": f.name,
                    "name": f.stem,
                    "error": str(e),
                })
        return files

    def print_comparison(self, comparison_df: pd.DataFrame) -> None:
        """Print a formatted comparison table to console."""
        key_cols = ["strategy", "net_profit_pct", "max_drawdown_pct",
                    "sharpe_ratio", "profit_factor", "win_rate_pct", "total_trades"]
        display_cols = [c for c in key_cols if c in comparison_df.columns]

        if not display_cols:
            print("No comparison data available.")
            return

        print(f"\n{'Strategy Comparison':^70}")
        print("=" * 70)

        headers = {"strategy": "Strategy", "net_profit_pct": "Net %",
                    "max_drawdown_pct": "Max DD %", "sharpe_ratio": "Sharpe",
                    "profit_factor": "PF", "win_rate_pct": "Win %",
                    "total_trades": "Trades"}

        header_line = f"{'Strategy':<25}"
        for col in display_cols[1:]:
            header_line += f" {headers.get(col, col):>10}"
        print(header_line)
        print("-" * 70)

        for _, row in comparison_df.iterrows():
            line = f"{str(row.get('strategy', ''))[:24]:<25}"
            for col in display_cols[1:]:
                val = row.get(col, "N/A")
                if isinstance(val, float):
                    line += f" {val:>10.2f}"
                else:
                    line += f" {str(val):>10}"
            print(line)

        print("=" * 70)
