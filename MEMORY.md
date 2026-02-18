# Trading Strategy Memory

## Session Log
Update this file after each working session to track strategy iterations.

---

## Active Work
- **Tickers**: MSTR (5m), PLTR (10m), MSTZ (5m)
- **Capital**: $60,000 (margin account, Webull — ZERO COMMISSION)
- **Backtest Settings**: 90% equity/trade, fill-on-close, 0% commission, 0% slippage
- **Data**:
  - data/MSTR_5m.csv (1,668 bars, 2026-02-04 to 2026-02-17, ~10 days)
  - data/PLTR_10m.csv (682 bars, 2026-01-20 to 2026-02-13, ~18 days)
  - data/MSTZ_5m.csv (6,236 bars, 2025-12-24 to 2026-02-17, ~45 days)

## Current Best Strategies (Session 3)
- **MSTR**: SuperTrend+ADX v1 (1.5x/3.5x) → +$8,968 (+14.9%), PF 1.9, 29 trades, -7.7% DD
- **PLTR**: SuperTrend+ADX v2 (smart filters) → +$9,604 (+16.0%), PF 7.0, 16 trades, -4.0% DD
- **MSTZ**: SuperTrend+ADX v1 (1.5x/3.5x) → +$45,782 (+76.3%), PF 1.5, 147 trades, -24.3% DD
- **Combined**: +$62,731 (+104.6% on $60k) using v1 baseline across all tickers

---

## Session 3 — Strategy Iteration v1-v4 + SMRT Algo (2026-02-18)

### Key Changes Made
1. Compared original SuperTrend+ADX (1.0x/2.5x ATR) vs loosened (1.5x/3.5x ATR) — loosened wins by +$6,927
2. Built SMRT Algo (Daily Single Trade) - opening range breakout strategy from TradingView
3. Created SuperTrend+ADX v2 (smart filters): ATR floor, candle body, stricter RSI, early session end
4. Created SuperTrend+ADX v3 (trailing stops): proved trailing stops HURT performance
5. Created SuperTrend+ADX v4 (continuation entries): RSI pullback re-entries within trend
6. Pine Script exports created for TradingView
7. Loosened stop on Daily Single Trade Pine Script from 1.0x to 1.5x ATR

### Full Rankings (Session 3, all tickers combined)

#### SuperTrend+ADX Version Comparison
| Version | Total Profit | Avg WR | Avg PF | Stop-Outs | Notes |
|---------|-------------|--------|--------|-----------|-------|
| v1 (1.5x/3.5x) | +$62,731 | 46.6% | 1.8x | 93 | Most profit, most trades |
| v4 (hybrid) | +$49,233 | 42.9% | 2.3x | 65 | Best balance |
| v3 (trailing) | +$36,081 | 51.3% | 2.7x | 85 | Trailing stop hurts |
| v2 (smart) | +$35,120 | 57.8% | 3.6x | 30 | Best WR + PF, fewest trades |

#### Best Version Per Ticker
- **MSTR**: v1 wins on profit (+$8,968), v2 wins on quality (60% WR, 2.3x PF)
- **PLTR**: v2 wins EVERYTHING (+$9,604, 68.8% WR, 7.0x PF, only 2 stop-outs)
- **MSTZ**: v1 wins on profit (+$45,782), v4 is runner-up (+$37,606)

#### All Strategies Ranked (Combined, $60k capital)
| # | Strategy | Total | MSTR | PLTR | MSTZ |
|---|----------|-------|------|------|------|
| 1 | ST+ADX v1 (1.5x/3.5x) | +$62,731 | +$8,968 | +$7,981 | +$45,782 |
| 2 | ST+ADX v1 (1.0x/2.5x) | +$55,804 | +$8,553 | +$3,635 | +$43,616 |
| 3 | ST+ADX v4 (hybrid) | +$49,233 | +$3,664 | +$7,963 | +$37,606 |
| 4 | ST+ADX v3 (trailing) | +$36,081 | +$3,664 | +$9,361 | +$23,055 |
| 5 | ST+ADX v2 (smart) | +$35,120 | +$4,036 | +$9,604 | +$21,480 |
| 6 | MACD+RSI v1 | +$33,792 | +$7,254 | +$5,907 | +$20,631 |
| 7 | VWAP Momentum | +$31,952 | +$3,764 | +$6,556 | +$21,632 |
| 8 | MACD+RSI v2 | +$19,266 | +$6,779 | — | +$12,487 |
| 9 | SMRT Algo (ORB) | +$8,742 | +$3,333 | +$7,561 | -$2,152 |
| 10 | Stoch+RSI | -$7,210 | +$1,810 | -$1,296 | -$7,724 |

### Trade-Level Loss Analysis (Session 3)
Key findings from analyzing all losing trades:
1. **Stop losses = 100% of all losses** (93 out of 97 losing exits across all tickers)
2. **Late-day trading (17:00+ UTC) consistently loses** on all tickers
3. **Many stop-outs within 1-2 bars** — entering during chop/whipsaw
4. **MSTR favors longs** (60% WR longs vs 35.7% shorts)
5. **PLTR favors shorts** (60.9% WR shorts vs 46.2% longs)
6. **Take-profit exits are 100% winners** — the TP levels are well-calibrated
7. **Different tickers need different optimal stop widths**: MSTZ best at tight 0.75x, MSTR/PLTR best at wider 2.5x

### SMRT Algo (Opening Range Breakout)
- Implemented as `strategies/daily_single_trade_v1.py`
- Pure price action: captures first candle H/L at market open, trades breakout
- One trade per day max, fixed 2:1 R:R
- Best on PLTR (+$7,561, 3.6x PF) — worst on MSTZ (-$2,152)
- Very selective (9-36 trades) — good PF but low volume

---

## Session 2 — Aggressive Strategy Overhaul (2026-02-17)

### Key Changes Made
1. Fixed SuperTrend indicator bug (was stuck bullish, never flipped bearish)
2. Added built-in implementations: Stochastic, ADX, SuperTrend
3. Switched to Webull settings: ZERO commission, minimal slippage
4. Increased position sizing: 90% equity per trade (margin account)
5. All strategies now trade BOTH long and short
6. Tight 1x ATR stops with 2.3-3x ATR targets (minimum 2.3:1 R:R)
7. Session filters to avoid pre/after-hours
8. Added MSTZ ticker (45 days of data — most statistically significant)

---

## Cross-Ticker Insights (All Sessions)
- **SuperTrend+ADX dominates on volatile stocks**: #1 on both MSTR and MSTZ
- **v2 smart filters dominate on PLTR**: lower-volatility stock benefits from selectivity
- **Fundamental tradeoff: win rate vs total profit** — cannot fully eliminate
  - v2: 58% WR, 3.6x PF, +$35k total (quality)
  - v1: 47% WR, 1.8x PF, +$63k total (volume)
- **Trailing stops (v3) hurt performance** — cause premature exits
- **SMRT Algo (ORB) works best on steady stocks** (PLTR), fails on volatile (MSTZ)
- **Commission-free trading is a massive edge**: critical for high-frequency strategies
- **All top strategies trade BOTH directions** — critical for volatile stocks

## Strategy Files
### SuperTrend+ADX Variants (primary strategy)
- `strategies/mstr_supertrend_v1.py` — Original: ST(7,2.5) + ADX>20 + RSI + EMA50. Use with params {'atr_stop_mult': 1.5, 'atr_target_mult': 3.5} for best results
- `strategies/mstr_supertrend_v2.py` — Smart filters: ATR floor, candle body>40%, RSI 55/45, ADX>25, session to 17:00, cooldown after stop-out
- `strategies/mstr_supertrend_v3.py` — Trailing stop: breakeven after 1x ATR profit (PROVEN TO HURT - avoid)
- `strategies/mstr_supertrend_v4.py` — Continuation entries: RSI pullback re-entry within established trends
- Same files exist for PLTR (`pltr_supertrend_v1-v4.py`)

### Other Strategies
- `strategies/mstr_macd_rsi_v1.py` / `v2.py` — MACD histogram + RSI + dual EMA
- `strategies/mstr_vwap_momentum_v1.py` — VWAP + EMA + RSI + volume
- `strategies/mstr_stoch_rsi_v1.py` — Stochastic + RSI [DELETE CANDIDATE - worst everywhere]
- `strategies/daily_single_trade_v1.py` — SMRT Algo opening range breakout
- Same patterns for PLTR variants

### Pine Script Exports
- `export/supertrend_adx_v1.pine` — Original SuperTrend+ADX (1.0x/2.5x)
- `export/Daily Single Trade.pine` — Loosened to 1.5x/3.5x ATR stops

## Ideas Queue
- **Ticker-adaptive strategy**: auto-select v1 vs v2 per ticker based on volatility
- MACD v3: Combine MACD + VWAP for confirmation
- Portfolio mode: run SuperTrend + VWAP as uncorrelated signals
- Get more MSTR/PLTR data (60+ days) for statistical validation
- Test on other volatile stocks: NVDA, TSLA, COIN, SOXL
- Export v2 smart filters to Pine Script (for PLTR specifically)
- Implement max daily loss limit (risk management)
- Volume-weighted entry sizing (bigger positions on high-volume signals)

## Engine Fixes (Session 2)
- Fixed SuperTrend built-in indicator: was stuck bullish due to NaN propagation in band adjustment
- Added built-in Stochastic oscillator implementation
- Added built-in ADX/DI+/DI- implementation
- All 3 new indicators work without pandas-ta dependency

## Data Notes
- MSTR: BATS exchange, timestamps need UTC conversion. ~10 trading days. Price $100-$139.
- PLTR: yfinance 5m resampled to 10m. ~18 trading days. Price $127-$172.
- MSTZ: BATS exchange, leveraged inverse MSTR ETF. 45 trading days (best dataset). Price $10-$31.
- MSTZ has the most data = most statistically significant results
- Webull: zero commission, PFOF-based, tight spreads
