"""Historical bar bootstrap and strategy state priming.

On startup, we need to:
1. Fetch enough historical bars to satisfy all indicator lookback periods
2. Run strategy.setup() to compute indicators on the historical data
3. Simulate on_bar() calls through all historical bars (WITHOUT executing)
   to prime the strategy's internal state (e.g., _prev_st_dir)

After warmup, the strategy is in the same state it would be if the bot
had been running since the start of the historical data.
"""

import logging
from typing import Optional

import pandas as pd
import importlib.util

from bot.broker.base import BaseBroker
from strategies.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

# Minimum bars needed per indicator (largest lookback wins)
# SuperTrend(7) + ADX(14) + RSI(9) + ATR(10) + EMA(50)
# The longest is EMA(50) → need at least 50 bars for valid values
# Add safety margin for warmup to stabilize all state
DEFAULT_WARMUP_BARS = 200


async def warmup_strategy(
    strategy: BaseStrategy,
    broker: BaseBroker,
    ticker: str,
    timeframe: str,
    warmup_bars: int = DEFAULT_WARMUP_BARS,
) -> pd.DataFrame:
    """Bootstrap a strategy with historical data and prime its internal state.

    1. Fetches historical bars from the broker
    2. Runs strategy.setup() to add indicator columns
    3. Simulates on_bar() through all bars to prime state (no orders executed)

    Args:
        strategy: Strategy instance to warm up
        broker: Connected broker for fetching historical bars
        ticker: Symbol to fetch bars for
        timeframe: Bar timeframe (e.g., "5m", "10m")
        warmup_bars: Number of historical bars to fetch

    Returns:
        DataFrame with indicator columns populated, ready for live bars
    """
    logger.info(
        f"Warming up {strategy.name} on {ticker} ({timeframe}): "
        f"fetching {warmup_bars} bars..."
    )

    # Step 1: Fetch historical bars
    df = await broker.get_bars(ticker, timeframe, limit=warmup_bars)

    if df.empty:
        logger.warning(f"No historical bars returned for {ticker} ({timeframe})")
        return df

    logger.info(
        f"  Fetched {len(df)} bars from "
        f"{df.index[0].strftime('%Y-%m-%d %H:%M')} to "
        f"{df.index[-1].strftime('%Y-%m-%d %H:%M')}"
    )

    # Step 2: Add indicators
    df = strategy.setup(df)
    logger.info(f"  Indicators computed: {list(df.columns)}")

    # Step 3: Simulate on_bar() to prime strategy internal state
    # We call on_bar() for every historical bar but IGNORE the returned signals
    # This sets _prev_st_dir, _st_dir_count, etc. to correct values
    primed_count = 0
    for idx in range(len(df)):
        row = df.iloc[idx]
        try:
            _ = strategy.on_bar(idx, row, position=None)
            primed_count += 1
        except Exception:
            # Skip bars where indicators aren't ready yet (NaN values)
            pass

    logger.info(
        f"  Strategy state primed: simulated {primed_count}/{len(df)} bars. "
        f"Ready for live trading."
    )

    return df


def load_strategy(strategy_file: str, params: dict = None) -> BaseStrategy:
    """Dynamically load a strategy from a .py file.

    Args:
        strategy_file: Path to strategy file (e.g., "strategies/mstr_supertrend_v1.py")
        params: Optional parameter overrides

    Returns:
        Instantiated Strategy object
    """
    spec = importlib.util.spec_from_file_location("strat", strategy_file)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"Strategy file not found: {strategy_file}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "Strategy"):
        raise AttributeError(
            f"Strategy file {strategy_file} must define a 'Strategy' class"
        )

    strategy = mod.Strategy(params=params or {})
    logger.info(f"Loaded strategy: {strategy.name} {strategy.version} from {strategy_file}")
    return strategy
