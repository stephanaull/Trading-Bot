# Trading Strategy Memory

## Session Log
Update this file after each working session to track strategy iterations.

---

## Active Work
- **Tickers**: MSTR (5m), PLTR (10m), MSTZ (5m)
- **Capital**: $60,000 (margin account, Webull — ZERO COMMISSION)
- **Backtest Settings**: 90% equity/trade, fill-on-close, 0% commission, 0.02% slippage
- **Data**:
  - data/MSTR_5m.csv (1,668 bars, 2026-02-04 to 2026-02-17, ~10 days)
  - data/PLTR_10m.csv (682 bars, 2026-01-20 to 2026-02-13, ~18 days)
  - data/MSTZ_5m.csv (6,236 bars, 2025-12-24 to 2026-02-17, ~45 days)

## Best Strategies Per Ticker
- **MSTR**: SuperTrend+ADX → +$7,204 (+12.0%), PF 1.40, 55 trades (29L/26S)
- **PLTR**: VWAP Momentum v1 → +$5,963 (+9.9%), PF 2.36, 25 trades (8L/17S)
- **MSTZ**: SuperTrend+ADX → +$35,401 (+59.0%), PF 1.28, 230 trades (125L/105S)
- **Combined**: +$48,568 on $60k across all three tickers

---

## Session 2 — Aggressive Strategy Overhaul (2026-02-17)

### Key Changes Made
1. Fixed SuperTrend indicator bug (was stuck bullish, never flipped bearish)
2. Added built-in implementations: Stochastic, ADX, SuperTrend
3. Switched to Webull settings: ZERO commission, minimal 0.02% slippage
4. Increased position sizing: 90% equity per trade (margin account)
5. All strategies now trade BOTH long and short
6. Tight 1x ATR stops with 2.3-3x ATR targets (minimum 2.3:1 R:R)
7. Session filters to avoid pre/after-hours
8. Added MSTZ ticker (45 days of data — most statistically significant)

### MSTR Rankings (Session 2, Webull settings)
| # | Strategy | Net Profit | PF | Win% | Trades | MaxDD | L/S |
|---|----------|-----------|-----|------|--------|-------|-----|
| 1 | SuperTrend+ADX | +$7,204 (+12.0%) | 1.40 | 38% | 55 | -10.9% | 29L/26S |
| 2 | MACD+RSI v1 | +$6,296 (+10.5%) | 1.84 | 48% | 40 | -3.7% | 20L/20S |
| 3 | MACD+RSI v2 | +$5,996 (+10.0%) | 2.05 | 48% | 33 | -2.5% | 17L/16S |
| 4 | VWAP Momentum | +$2,836 (+4.7%) | 1.24 | 37% | 41 | -4.4% | 22L/19S |
| 5 | ORB | +$2,714 (+4.5%) | 1.79 | 67% | 6 | -5.3% | 1L/5S |
| 6 | Stoch+RSI | +$1,455 (+2.4%) | 1.31 | 44% | 16 | -3.4% | 7L/9S |

### PLTR Rankings (Session 2, Webull settings)
| # | Strategy | Net Profit | PF | Win% | Trades | MaxDD | L/S |
|---|----------|-----------|-----|------|--------|-------|-----|
| 1 | VWAP Momentum v1 | +$5,963 (+9.9%) | 2.36 | 60% | 25 | -2.4% | 8L/17S |
| 2 | VWAP Momentum v2 | +$5,624 (+9.4%) | 2.48 | 60% | 25 | -3.2% | 8L/17S |
| 3 | MACD+RSI | +$5,090 (+8.5%) | 1.91 | 46% | 35 | -4.5% | 13L/22S |
| 4 | SuperTrend+ADX | +$2,377 (+4.0%) | 1.15 | 39% | 56 | -5.4% | 18L/38S |
| 5 | SMA Cross | +$2,116 (+3.5%) | 2.25 | 60% | 5 | -2.7% | 2L/3S |
| 6 | Stoch+RSI | -$1,509 (-2.5%) | 0.43 | 30% | 10 | -3.4% | 5L/5S |

### MSTZ Rankings (Session 2, Webull settings) — MOST DATA
| # | Strategy | Net Profit | PF | Win% | Trades | MaxDD | L/S |
|---|----------|-----------|-----|------|--------|-------|-----|
| 1 | SuperTrend+ADX | +$35,401 (+59.0%) | 1.28 | 33% | 230 | -19.5% | 125L/105S |
| 2 | VWAP Momentum | +$17,627 (+29.4%) | 1.27 | 36% | 140 | -12.7% | 73L/67S |
| 3 | MACD+RSI v1 | +$15,689 (+26.1%) | 1.27 | 38% | 176 | -12.0% | 98L/78S |
| 4 | ORB | +$8,944 (+14.9%) | 3.29 | 83% | 6 | -5.4% | 1L/5S |
| 5 | MACD+RSI v2 | +$8,852 (+14.8%) | 1.18 | 36% | 143 | -10.7% | 76L/67S |
| 6 | Stoch+RSI | -$8,845 (-14.7%) | 0.64 | 28% | 60 | -22.3% | 32L/28S |

---

## Cross-Ticker Insights (Session 2)
- **SuperTrend+ADX dominates on volatile stocks**: #1 on both MSTR and MSTZ
- **VWAP Momentum dominates on PLTR**: lower-volatility stock benefits from VWAP mean-reversion
- **MACD+RSI is consistently good**: Top 3 on all three tickers
- **Stoch+RSI consistently worst**: DELETE across all tickers
- **ORB has high PF but too few trades**: only 6 trades, not scalable
- **MACD v2 (stricter filters) trades less = lower net profit but better PF**: useful for risk management
- **Commission-free trading is a massive edge**: strategies that were marginal with 0.1% commission became highly profitable
- **All top strategies trade BOTH directions** — critical for volatile stocks

## Strategy Files
### New (Session 2)
- `strategies/mstr_vwap_momentum_v1.py` — VWAP + EMA + RSI + volume, session filter
- `strategies/mstr_supertrend_v1.py` — SuperTrend + ADX + RSI + EMA50, session filter
- `strategies/mstr_macd_rsi_v1.py` — MACD histogram + RSI + dual EMA, 1x/2.5x ATR
- `strategies/mstr_macd_rsi_v2.py` — v2: stricter filters, 1x/3x ATR, min ATR threshold
- `strategies/mstr_stoch_rsi_v1.py` — Stochastic + RSI + EMA [DELETE CANDIDATE]
- `strategies/pltr_vwap_momentum_v1.py` — VWAP + EMA + RSI for 10m
- `strategies/pltr_vwap_momentum_v2.py` — v2: 3x target + trailing stop
- `strategies/pltr_supertrend_v1.py` — SuperTrend + ADX + RSI for 10m
- `strategies/pltr_macd_rsi_v1.py` — MACD + RSI + EMA for 10m
- `strategies/pltr_stoch_rsi_v1.py` — Stochastic + RSI [DELETE CANDIDATE]

### Session 1 (kept)
- `strategies/mstr_orb_v1.py` — ORB (still solid PF, low trade count)
- `strategies/pltr_sma_cross_v1.py` — SMA Cross (decent PF, low trades)

## Ideas Queue
- SuperTrend v2: Add trailing stop once in profit (lock gains on big moves)
- SuperTrend v2: Tune multiplier (try 2.0 and 3.0 vs current 2.5)
- MACD v3: Combine MACD + VWAP for confirmation (two strongest indicators)
- Combine strategies: run SuperTrend + VWAP as a portfolio (uncorrelated signals)
- Get more MSTR/PLTR data (60+ days) for statistical validation
- Export top strategies to Pine Script for TradingView live testing
- Implement position sizing cap (limit to 2x leverage on margin)
- Test on other volatile stocks: NVDA, TSLA, COIN, SOXL

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
- Webull: zero commission, PFOF-based, tight spreads (0.02% slippage estimate)
