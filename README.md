# Trading Backtest Engine

A prompt-based Python backtesting engine that replicates TradingView's Strategy Tester. Describe a strategy in natural language, and Claude Code creates, backtests, iterates, and exports it to Pine Script.

## Setup

```bash
pip install -r requirements.txt
```

## Quick Start

### 1. Download Data
```python
from engine.data_downloader import DataDownloader
df = DataDownloader.from_yahoo("AAPL", "2020-01-01", "2025-12-31")
DataDownloader.save_to_csv(df, "AAPL", "1d")
```

### 2. Run a Backtest
```bash
python -m runner.cli backtest -s strategies/example_ema_cross.py -d data/AAPL_1d.csv --report
```

### 3. Compare Strategies
```bash
python -m runner.cli compare --strategies "strategies/aapl_*.py" -d data/AAPL_1d.csv
```

### 4. Export to Pine Script
```bash
python -m runner.cli export -s strategies/best_strategy.py -o export/best.pine
```

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `engine/` | Core backtesting engine (broker, portfolio, metrics, indicators) |
| `strategies/` | Strategy files (examples + AI-generated) |
| `data/` | OHLCV CSV files |
| `export/` | Pine Script exports |
| `reports/` | HTML reports and trade logs |
| `runner/` | CLI, strategy manager, report generator |
| `tests/` | Test suite |

## Using with Claude Code

The engine is designed for prompt-based interaction. See `CLAUDE.md` for full instructions. Simply describe a trading strategy and Claude will create, backtest, and iterate on it.

## Running Tests

```bash
pytest tests/ -v
```
