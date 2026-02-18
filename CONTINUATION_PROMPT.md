# Continuation Prompt — Trading Strategy Backtesting Project

Copy everything below this line into a new Claude Code session to continue where we left off.

---

## Project Context

This is a Python backtesting engine for day-trading strategies. The engine is COMPLETE and working — do NOT modify anything in the `engine/` folder. You create/iterate strategy files in `strategies/`, backtest them, and export winners to Pine Script for TradingView.

**Read `CLAUDE.md` first** — it has the full API reference for creating strategies, running backtests, comparing, and exporting.

**Read `MEMORY.md` second** — it has all session history, rankings, and learnings from previous iterations.

## Current State

**GitHub repo**: https://github.com/stephanaull/Trading-Strategies (branch: `main`, up to date)

**Tickers being traded**:
- MSTR (5m bars) — `data/MSTR_5m.csv` — 10 trading days, volatile crypto-correlated stock
- PLTR (10m bars) — `data/PLTR_10m.csv` — 18 trading days, steady tech stock
- MSTZ (5m bars) — `data/MSTZ_5m.csv` — 45 trading days, leveraged inverse MSTR ETF (most volatile, most data)

**Trading account**: Webull, $60,000 capital, margin account, ZERO commission

**Backtest settings** (always use these):
```python
BacktestEngine(data, strategy, initial_capital=60000, commission=0.0, slippage=0.0,
               position_sizing='percent', pct_equity=0.90, fill_on_close=True)
```

## Strategy Rankings (Current Best)

The primary strategy is **SuperTrend+ADX** with 4 versions:

| Version | Combined Profit | Avg Win Rate | Avg PF | Best For |
|---------|----------------|-------------|--------|----------|
| **v1 (1.5x/3.5x stops)** | **+$62,731** | 46.6% | 1.8x | Max profit (MSTR, MSTZ) |
| v4 (continuation entries) | +$49,233 | 42.9% | 2.3x | Balance of profit + quality |
| v2 (smart filters) | +$35,120 | 57.8% | 3.6x | **Best for PLTR** (+$9,604, 68.8% WR, 7.0x PF) |
| v3 (trailing stops) | +$36,081 | 51.3% | 2.7x | Avoid — trailing stops hurt |

**Important**: v1 strategy file uses default 1.0x/2.5x stops. To get the best results (1.5x/3.5x), pass params override:
```python
strategy = mod.Strategy(params={'atr_stop_mult': 1.5, 'atr_target_mult': 3.5})
```

**Other strategies** (all weaker than SuperTrend+ADX): MACD+RSI v1/v2, VWAP Momentum, Stoch+RSI (DELETE candidate), SMRT Algo (opening range breakout — only good on PLTR).

## Key Learnings (Don't Re-learn These)

1. **Stop losses account for 100% of all losses** — the TP targets are well-calibrated
2. **Trailing stops hurt performance** (v3 proved this) — they cause premature exits
3. **Fundamental tradeoff: win rate vs total profit** — v2 has 58% WR but v1 makes 2x more money due to more trades
4. **Different tickers need different strategies**: v1 for MSTR/MSTZ (volatile), v2 for PLTR (steady)
5. **Late-day trading (17:00+ UTC) consistently loses** on all tickers
6. **MSTR favors longs** (60% WR), **PLTR favors shorts** (61% WR)
7. **MSTZ drives most profit** due to extreme volatility ($10-$31 range)
8. **Commission-free (Webull) is critical** — strategies that were marginal at 0.1% commission become highly profitable at zero
9. **v2's smart filters** that work: ATR floor (skip low-vol chop), candle body > 40% (skip dojis), stricter RSI (55/45 vs 50/50)
10. **v2's filters** that were too restrictive: ADX > 25 (should be 20-22), session ending at 17:00 (can go to 19:00), cooldown after stop (kills re-entry)

## Open Ideas / Next Steps

Pick up from any of these:
- **Ticker-adaptive strategy**: auto-select v1 vs v2 per ticker based on volatility regime
- **MACD+VWAP hybrid**: combine the two strongest non-SuperTrend indicators
- **Portfolio mode**: run multiple uncorrelated strategies simultaneously
- **More data**: download 60+ days of MSTR/PLTR for statistical validation
- **New tickers**: test on NVDA, TSLA, COIN, SOXL
- **Export v2 to Pine Script** for PLTR live trading on TradingView
- **Risk management**: max daily loss limit, volume-weighted position sizing
- **Improve win rate without sacrificing profit** — the ongoing challenge (v2 got 58% WR but only $35k vs v1's $63k)

## Quick Commands

```python
# Run a single backtest
import sys; sys.path.insert(0, '.')
import importlib.util
from engine.backtest import BacktestEngine
from engine.data_loader import DataLoader
data = DataLoader.from_csv("data/MSTR_5m.csv")
spec = importlib.util.spec_from_file_location("strat", "strategies/mstr_supertrend_v1.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
strategy = mod.Strategy(params={'atr_stop_mult': 1.5, 'atr_target_mult': 3.5})
engine = BacktestEngine(data, strategy, initial_capital=60000, commission=0.0, slippage=0.0,
                        position_sizing='percent', pct_equity=0.90, fill_on_close=True)
result = engine.run()
result.print_summary()
```

```python
# Compare strategies
from runner.strategy_manager import StrategyManager
mgr = StrategyManager()
comparison = mgr.compare(["strategies/mstr_supertrend_v1.py", "strategies/mstr_supertrend_v2.py"], "data/MSTR_5m.csv")
mgr.print_comparison(mgr.rank(comparison))
```

```python
# Download new data
from engine.data_downloader import DataDownloader
df = DataDownloader.from_yahoo("NVDA", "2025-01-01", "2026-02-18", interval="5m")
DataDownloader.save_to_csv(df, "NVDA", "5m")
```
