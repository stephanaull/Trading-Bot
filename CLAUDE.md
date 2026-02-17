# Trading Backtest Engine - Claude Code Instructions

## Overview
This is a Python backtesting engine for trading strategies. You (Claude) create strategy files, backtest them, iterate on results, and export winners to Pine Script for TradingView.

The engine produces TradingView-compatible backtest results including Sharpe Ratio, Profit Factor, Max Drawdown, Win Rate, and all standard metrics.

## Project Structure
```
data/            CSV files with OHLCV data (TICKER_INTERVAL.csv naming)
engine/          Core backtesting engine (DO NOT MODIFY)
strategies/      Strategy files (YOU CREATE AND ITERATE ON THESE)
export/          Pine Script exports
reports/         Generated HTML reports and trade logs
runner/          CLI and strategy management tools
MEMORY.md        Update after each session with iteration state
```

## Quick Reference

### Download Data
```python
import sys; sys.path.insert(0, '.')
from engine.data_downloader import DataDownloader
df = DataDownloader.from_yahoo("AAPL", "2020-01-01", "2025-12-31", interval="1d")
DataDownloader.save_to_csv(df, "AAPL", "1d")
```

### Run a Backtest
```python
import sys; sys.path.insert(0, '.')
import importlib.util
from engine.backtest import BacktestEngine
from engine.data_loader import DataLoader

# Load data
data = DataLoader.from_csv("data/AAPL_1d.csv")

# Load strategy dynamically
spec = importlib.util.spec_from_file_location("strat", "strategies/example_ema_cross.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
strategy = mod.Strategy()

# Run backtest
engine = BacktestEngine(data, strategy, initial_capital=100000)
result = engine.run()
result.print_summary()
```

### Compare Strategies
```python
from runner.strategy_manager import StrategyManager
mgr = StrategyManager()
comparison = mgr.compare(
    ["strategies/aapl_rsi_v1.py", "strategies/aapl_rsi_v2.py"],
    "data/AAPL_1d.csv"
)
mgr.print_comparison(mgr.rank(comparison))
```

### Export to Pine Script
```python
from export.pine_exporter import PineExporter
exporter = PineExporter(strategy)
exporter.export("export/aapl_rsi_final.pine")
```

### Generate HTML Report
```python
from runner.report_generator import ReportGenerator
rg = ReportGenerator(result)
rg.generate_html_report()  # Saves to reports/
```

### Prune Bad Strategies
```python
mgr = StrategyManager()
deleted = mgr.prune("aapl", keep_top_n=3, min_sharpe=0.5, data_file="data/AAPL_1d.csv")
```

## Creating a Strategy

### File Naming Convention
`strategies/{ticker}_{approach}_v{N}.py`
Examples: `aapl_rsi_v1.py`, `btc_macd_v3.py`, `spy_bollinger_v2.py`

### Strategy Template
```python
from typing import Optional
import pandas as pd
from strategies.base_strategy import BaseStrategy, Signal
from engine.indicators import Indicators

class Strategy(BaseStrategy):
    name = "Descriptive Name"
    version = "v1"
    description = "What this strategy does"
    ticker = "AAPL"
    timeframe = "1d"

    # Pine Script export metadata
    pine_indicators = [
        {"name": "ema", "params": {"length": 9}, "var": "fast_ema"},
        {"name": "ema", "params": {"length": 21}, "var": "slow_ema"},
    ]
    pine_conditions = {
        "long_entry": "ta.crossover(fast_ema, slow_ema)",
        "long_exit": "ta.crossunder(fast_ema, slow_ema)",
    }

    def __init__(self, params=None):
        defaults = {
            "fast_period": 9,
            "slow_period": 21,
            "stop_loss_pct": 0.03,
            "take_profit_pct": 0.06,
        }
        super().__init__({**defaults, **(params or {})})

    def setup(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add indicators. Called once before backtest starts."""
        df = Indicators.add(df, "ema", length=self.params["fast_period"])
        df = Indicators.add(df, "ema", length=self.params["slow_period"])
        return df

    def on_bar(self, idx: int, row: pd.Series,
               position=None) -> Optional[Signal]:
        """Called for each bar. Return Signal or None."""
        # Your strategy logic here
        # Access indicators: row["EMA_9"], row["RSI_14"], etc.
        # Access OHLCV: row["open"], row["high"], row["low"], row["close"], row["volume"]
        return None
```

### Signal Options
```python
Signal(
    direction="long",           # "long", "short", "close_long", "close_short"
    stop_loss=150.00,           # Absolute price level
    take_profit=170.00,         # Absolute price level
    trailing_stop_distance=5.0, # Distance in price units
    reason="RSI oversold",      # For logging
)
```

## Available Indicators

| Indicator | Add Call | Column Name(s) | Pine Script |
|-----------|----------|-----------------|-------------|
| SMA | `Indicators.add(df, 'sma', length=20)` | `SMA_20` | `ta.sma(close, 20)` |
| EMA | `Indicators.add(df, 'ema', length=20)` | `EMA_20` | `ta.ema(close, 20)` |
| RSI | `Indicators.add(df, 'rsi', length=14)` | `RSI_14` | `ta.rsi(close, 14)` |
| MACD | `Indicators.add(df, 'macd', fast=12, slow=26, signal=9)` | `MACD_12_26_9`, `MACDh_12_26_9`, `MACDs_12_26_9` | `ta.macd(close, 12, 26, 9)` |
| Bollinger | `Indicators.add(df, 'bbands', length=20, std=2)` | `BBL_20_2.0`, `BBM_20_2.0`, `BBU_20_2.0` | `ta.bb(close, 20, 2)` |
| ATR | `Indicators.add(df, 'atr', length=14)` | `ATR_14` | `ta.atr(14)` |
| ADX | `Indicators.add(df, 'adx', length=14)` | `ADX_14`, `DMP_14`, `DMN_14` | `ta.dmi(14, 14)` |
| Stochastic | `Indicators.add(df, 'stoch', k=14, d=3, smooth_k=3)` | `STOCHk_14_3_3`, `STOCHd_14_3_3` | `ta.stoch(close, high, low, 14)` |
| CCI | `Indicators.add(df, 'cci', length=20)` | `CCI_20` | `ta.cci(high, low, close, 20)` |
| MFI | `Indicators.add(df, 'mfi', length=14)` | `MFI_14` | `ta.mfi(hlc3, 14)` |
| OBV | `Indicators.add(df, 'obv')` | `OBV` | `ta.obv` |
| VWAP | `Indicators.add(df, 'vwap')` | `VWAP` | `ta.vwap(hlc3)` |
| SuperTrend | `Indicators.add(df, 'supertrend', length=7, multiplier=3)` | `SUPERT_7_3.0`, `SUPERTd_7_3.0` | `ta.supertrend(3, 7)` |
| PSAR | `Indicators.add(df, 'psar', af=0.02, max_af=0.2)` | `PSAR_long`, `PSAR_short` | `ta.sar(0.02, 0.2, 0.02)` |
| Williams %R | `Indicators.add(df, 'willr', length=14)` | `WILLR_14` | `ta.wpr(14)` |
| ROC | `Indicators.add(df, 'roc', length=10)` | `ROC_10` | `ta.roc(close, 10)` |
| Donchian | `Indicators.add(df, 'donchian', length=20)` | `DCL_20`, `DCM_20`, `DCU_20` | `ta.donchian(20)` |

### Crossover Helpers
```python
from engine.indicators import Indicators
# Returns boolean Series
cross_up = Indicators.crossover(df["EMA_9"], df["EMA_21"])
cross_down = Indicators.crossunder(df["EMA_9"], df["EMA_21"])
```

## Strategy Iteration Workflow

1. User describes a trading idea
2. Create v1 strategy implementing the core idea
3. Run backtest, show KPIs
4. Analyze weaknesses (high drawdown? low win rate? poor R:R?)
5. Create v2 with targeted improvements
6. Run comparison of all versions
7. Repeat until performance plateau
8. Prune losers (keep top 3 by Sharpe)
9. Export best to Pine Script
10. Update MEMORY.md

## Performance Targets
| Metric | Acceptable | Good | Excellent |
|--------|-----------|------|-----------|
| Sharpe Ratio | > 0.5 | > 1.0 | > 2.0 |
| Profit Factor | > 1.2 | > 1.5 | > 2.0 |
| Max Drawdown | < 30% | < 20% | < 10% |
| Win Rate (with 2:1 R:R) | > 35% | > 45% | > 55% |

Context: A 40% win rate with 2:1 risk/reward is profitable. Focus on R:R and expectancy, not just win rate.

## Backtest Parameters
```python
BacktestEngine(
    data=df,
    strategy=strategy,
    initial_capital=100_000,      # Starting cash
    commission=0.001,              # 0.1% per trade
    slippage=0.0005,               # 0.05% adverse fill
    position_sizing="fixed",       # "fixed", "percent", "risk_based"
    fixed_size=10_000,             # $ per trade (fixed sizing)
    pct_equity=0.10,               # 10% of equity (percent sizing)
    risk_pct=0.02,                 # 2% risk per trade (risk_based sizing)
    fill_on_close=False,           # True = TradingView default behavior
)
```

## Data Naming Convention
CSV files: `{TICKER}_{interval}.csv` in the `data/` folder
Examples: `AAPL_1d.csv`, `BTC-USD_1h.csv`, `SPY_5m.csv`

## MEMORY.md
After each session, update MEMORY.md with:
- Strategies tried and their results
- Best performing version (name + key metrics)
- Ideas for next iteration
- Any data issues found

## CLI Commands
```bash
python -m runner.cli backtest -s strategies/example_ema_cross.py -d data/AAPL_1d.csv --report
python -m runner.cli download -t AAPL --start 2020-01-01 --end 2025-12-31
python -m runner.cli compare --strategies "strategies/aapl_*.py" -d data/AAPL_1d.csv
python -m runner.cli list-data
python -m runner.cli list-strategies
python -m runner.cli export -s strategies/best.py -o export/best.pine
```
