# Trading Strategy Memory

## Session Log
Update this file after each working session to track strategy iterations.

---

## Active Work
- **Tickers**: MSTR (5m), PLTR (10m)
- **Capital**: $60,000 (margin account)
- **Data**:
  - data/MSTR_5m.csv (1,668 bars, 2026-02-04 to 2026-02-17, BATS exchange)
  - data/PLTR_10m.csv (682 bars, 2026-01-20 to 2026-02-13, yfinance 5m resampled)
- **Best MSTR Strategy**: mstr_orb_v1.py (ORB) -- PF 1.51
- **Best PLTR Strategy**: pltr_sma_cross_v1.py (SMA Cross) -- PF 1.72, +$233

## Strategy Iterations

### MSTR - Opening Range Breakout (2026-02-17) -- RANK #1
- v1: 15-min ORB with 2x range target, range-based stops. Net +$308 (+0.51%), PF 1.51, Win 67%, 6 trades, Max DD -0.93%. Best risk-adjusted. [BEST]

### MSTR - EMA Scalp (2026-02-17) -- RANK #2
- v1: EMA 5/13 cross with EMA 50 trend filter, ATR 1.5x/2.5x stops. Net +$194 (+0.32%), PF 1.06, Win 38%, 73 trades, Max DD -2.56%. High trade count but marginal edge. [KEPT]

### MSTR - Oversold Reversal (2026-02-17) -- RANK #3
- v1: RSI(7) < 25 + BB lower touch + bullish candle confirmation. Net -$127 (-0.21%), PF 0.83, Win 47%, 15 trades, Max DD -0.85%. Close to breakeven, decent win rate but avg loss > avg win. Best reversal strategy. [KEPT - ITERATE]

### MSTR - Overbought Reversal (2026-02-17) -- RANK #4
- v1: RSI(7) > 75 + BB upper touch + bearish candle, short entries. Net -$420 (-0.70%), PF 0.27, Win 30%, 10 trades, Max DD -1.06%. Shorting MSTR overbought is hard -- stock trends strongly, reversals get run over. [DELETE CANDIDATE]

### MSTR - SMA Cross (2026-02-17) -- RANK #5
- v1: SMA 10/30 cross with RSI filter + volume confirmation. Net -$1,719 (-2.87%), PF 0.18, Win 9.5%, 21 trades. Worst performer. SMA too slow for 5m. [DELETE CANDIDATE]

### PLTR - SMA Cross (2026-02-17) -- RANK #1
- v1: SMA 10/30 + RSI filter + volume 1.0x (relaxed for 10m). Net +$233 (+0.39%), PF 1.72, Win 60%, 5 trades, Max DD -0.51%. Best overall for PLTR -- slower MA works better on 10m. [BEST]

### PLTR - Oversold Reversal (2026-02-17) -- RANK #2
- v1: RSI(7) < 25 + BB lower touch + bullish candle → long. Net +$217 (+0.36%), PF inf (no losers), Win 100%, 2 trades, Max DD -0.20%. Perfect record but only 2 trades -- needs more data. [KEPT - NEEDS DATA]

### PLTR - Overbought Reversal (2026-02-17) -- RANK #3
- v1: RSI(7) > 75 + BB upper + bearish candle → short. Net +$47 (+0.08%), PF 4.74, Win 50%, 2 trades, Max DD -0.12%. Profitable but tiny sample size. [KEPT - NEEDS DATA]

### PLTR - EMA Scalp (2026-02-17) -- RANK #4
- v1: EMA 8/21 cross + EMA 50 trend filter + ATR stops. Net -$34 (-0.06%), PF 0.96, Win 44%, 16 trades, Max DD -0.78%. Near breakeven, most active strategy. [KEPT - ITERATE]

### PLTR - ORB (2026-02-17) -- RANK #5
- v1: 30-min ORB (3 bars @ 10m), 2x range target, session filter. Net -$154 (-0.26%), PF 0.81, Win 25%, 12 trades, Max DD -1.05%. Underperformed on PLTR unlike MSTR. [DELETE CANDIDATE]

## Cross-Ticker Observations (2026-02-17)
- **MSTR vs PLTR are opposite**: ORB is #1 on MSTR but #5 on PLTR; SMA is #5 on MSTR but #1 on PLTR
- **PLTR favors slower strategies**: SMA Cross and reversal strategies outperformed momentum/breakout
- **MSTR favors breakout/momentum**: ORB and EMA outperformed mean-reversion
- **Reversal strategies need more data**: 2 trades each on PLTR is not statistically significant
- **Key insight**: Strategy selection must be ticker-specific. No one-size-fits-all approach

## Ideas Queue
- ORB v2: Widen to 30-min opening range for more reliable levels
- ORB v2: Add volume spike confirmation on breakout
- ORB v2: Tighten session end to 19:00 UTC to avoid late-day chop
- Oversold Rev v2: Loosen RSI threshold to 30, require volume spike, add trend filter (only buy dips in uptrend)
- Oversold Rev v2: Use RSI(14) instead of RSI(7) for less noise
- EMA v2: Add RSI divergence filter to reduce false crossovers
- EMA v2: Try EMA 8/21 instead of 5/13
- Combine ORB + Oversold: use ORB for breakouts, oversold reversal for pullback entries
- Try VWAP bounce strategy (mean reversion to VWAP on 5m)

## Ideas Queue - PLTR
- SMA Cross v2: Try SMA 8/21 for faster signals, or add ADX trend strength filter
- SMA Cross v2: Add trailing stop to let winners run further
- Oversold Rev v2: Loosen RSI to 30, get more trade signals for statistical significance
- EMA Scalp v2: Try EMA 5/13 (faster) or add volume filter to reduce whipsaws
- Get 60+ days of PLTR data for more reliable results (only 682 bars currently)
- Try VWAP bounce strategy on PLTR (may suit its mean-reverting nature)

## Data Issues / Notes
- MSTR: Data is from BATS exchange, timestamps in UTC. Pre/after-hours included, strategies need session filtering. Only ~10 trading days. Price range $100-$140, high volatility, downtrend bias.
- PLTR: Downloaded via yfinance (5m resampled to 10m since yfinance doesn't support 10m). 682 bars over ~18 trading days (Jan 20 - Feb 13 2026). Less volatile than MSTR, more mean-reverting behavior.
- Both datasets are short (10-18 days). Results are preliminary -- need 60+ days for statistical confidence.
