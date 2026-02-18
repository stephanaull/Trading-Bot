# Strategy Documentation — Entry, Exit, Stop-Loss & Take-Profit Logic

This document describes the trading strategies used by the bot, their entry/exit criteria, risk management logic, and how the multi-timeframe engine selects signals.

---

## Table of Contents

1. [Strategy Overview](#strategy-overview)
2. [MSTR SuperTrend v1](#mstr-supertrend-v1) — Used by MSTU, MSTZ, HIMS
3. [PLTR SuperTrend v2](#pltr-supertrend-v2) — Used by PLTR
4. [Multi-Timeframe Signal Selection](#multi-timeframe-signal-selection)
5. [Risk Manager Checks](#risk-manager-checks)
6. [Position Sizing](#position-sizing)

---

## Strategy Overview

Both strategies are **trend-following** systems built on the same core: SuperTrend direction confirms the trend, ADX confirms trend strength, and RSI confirms momentum alignment. Entries happen when all filters agree; exits happen when SuperTrend flips.

| Feature | MSTR v1 | PLTR v2 |
|---------|---------|---------|
| Used for | MSTU, MSTZ, HIMS | PLTR |
| ADX threshold | 20 (moderate trend) | 25 (strong trend) |
| RSI long filter | > 50 | > 55 (stricter) |
| RSI short filter | < 50 | < 45 (stricter) |
| Stop-loss | 1.0x ATR | 1.5x ATR (wider) |
| Take-profit | 2.5x ATR (2.5:1 R:R) | 3.5x ATR (3.5:1 R:R) |
| Anti-whipsaw | None | 2-bar hold filter |
| Post-stop cooldown | None | 3 bars |
| ATR floor | None | ATR must be >= 20-SMA of ATR |
| Candle body filter | None | Body > 40% of H-L range |
| Session end | 19:45 UTC | 17:00 UTC (earlier) |

---

## MSTR SuperTrend v1

**File:** `strategies/mstr_supertrend_v1.py`
**Tickers:** MSTU (long only), MSTZ (long only), HIMS

### Indicators

| Indicator | Parameters | Column |
|-----------|-----------|--------|
| SuperTrend | length=7, multiplier=2.5 | `SUPERTd_7_2.5` (direction: +1 bull, -1 bear) |
| ADX | length=14 | `ADX_14` |
| RSI | length=9 | `RSI_9` |
| ATR | length=10 | `ATR_10` |
| EMA | length=50 | `EMA_50` (trend filter) |

### Long Entry Conditions

All of these must be true simultaneously:

1. **SuperTrend is bullish** — `SUPERTd_7_2.5 > 0`
2. **Market is trending** — `ADX_14 > 20`
3. **Momentum is bullish** — `RSI_9 > 50`
4. **Candle confirmation** — Either:
   - SuperTrend just flipped from bearish to bullish (fresh flip), OR
   - Current candle is bullish (`close > open`)
5. **Trend alignment** — Either:
   - Price is above the 50 EMA (`close > EMA_50`), OR
   - SuperTrend just flipped bullish (relaxed on flip)
6. **No existing position** — Must be flat
7. **Within session hours** — Between 14:35 and 19:45 UTC (9:35 AM - 3:45 PM ET)

### Short Entry Conditions

Mirror of long entry:

1. **SuperTrend is bearish** — `SUPERTd_7_2.5 < 0`
2. **Market is trending** — `ADX_14 > 20`
3. **Momentum is bearish** — `RSI_9 < 50`
4. **Candle confirmation** — SuperTrend just flipped bearish OR current candle is bearish (`close < open`)
5. **Trend alignment** — Price below 50 EMA OR SuperTrend just flipped bearish
6. **No existing position**
7. **Within session hours**

> **Note:** MSTU and MSTZ run in `long_only` mode — short signals are ignored for these leveraged/inverse ETFs.

### Exit Conditions

Exits are triggered by **SuperTrend direction change**:

- **Long exit:** SuperTrend flips from bullish to bearish → `close_long` signal with reason "SuperTrend flipped bearish"
- **Short exit:** SuperTrend flips from bearish to bullish → `close_short` signal with reason "SuperTrend flipped bullish"
- **End-of-session exit:** At 19:45 UTC (3:45 PM ET), if still in a position, a close signal is sent

### Stop-Loss Calculation

```
stop_distance = ATR_10 * 1.0    (1x ATR)

Long:  stop_loss = entry_price - stop_distance
Short: stop_loss = entry_price + stop_distance
```

The stop is set at entry time as an absolute price level. It is checked locally by the engine on every bar (comparing bar low/high against the stop level). This provides tight stops — about 1 ATR away from entry.

**Example:** If MSTU entry price = $5.03 and ATR = $0.10, then stop = $5.03 - $0.10 = $4.93.

### Take-Profit Calculation

```
target_distance = ATR_10 * 2.5    (2.5x ATR)

Long:  take_profit = entry_price + target_distance
Short: take_profit = entry_price - target_distance
```

This creates a **2.5:1 reward-to-risk ratio** — the profit target is 2.5x the stop distance.

**Example:** If MSTU entry = $5.03, ATR = $0.10, then target = $5.03 + $0.25 = $5.28.

> **Note:** When used for HIMS, the TOML config overrides `atr_stop_mult = 1.5` and `atr_target_mult = 3.5`, giving HIMS the same stops as PLTR v2.

### Trailing Stop

Not implemented in v1. The fixed stop and SuperTrend exit handle risk management.

### State Tracking

- `_prev_st_dir` — Previous bar's SuperTrend direction. Used to detect flips (when current direction differs from previous direction).

---

## PLTR SuperTrend v2

**File:** `strategies/pltr_supertrend_v2.py`
**Tickers:** PLTR

This is an enhanced version of v1 with additional filters to reduce false signals and whipsaw losses. It trades the same core pattern but with stricter entry criteria.

### Indicators

| Indicator | Parameters | Column |
|-----------|-----------|--------|
| SuperTrend | length=7, multiplier=2.5 | `SUPERTd_7_2.5` |
| ADX | length=14 | `ADX_14` |
| RSI | length=9 | `RSI_9` |
| ATR | length=10 | `ATR_10` |
| EMA | length=50 | `EMA_50` |
| SMA (volume) | length=20 | `SMA_20` |
| ATR SMA | 20-period SMA of ATR | `ATR_SMA_20` |

### Long Entry Conditions

All of these must be true simultaneously:

1. **SuperTrend is bullish** — `SUPERTd_7_2.5 > 0`
2. **Strong trend** — `ADX_14 > 25` (stricter than v1's 20)
3. **Strong bullish momentum** — `RSI_9 > 55` (stricter than v1's 50)
4. **Candle confirmation** — Bullish candle (`close > open`) or SuperTrend just flipped
5. **Trend alignment** — Price above EMA_50 or SuperTrend just flipped
6. **Anti-whipsaw filter** — SuperTrend has held bullish for >= 2 bars, OR it's a fresh flip
7. **Not in cooldown** — At least 3 bars since the last stop-loss exit
8. **ATR floor filter** — `ATR_10 >= ATR_SMA_20` (current volatility above average — no choppy markets)
9. **Candle body filter** — Candle body > 40% of high-low range (rejects dojis, spinning tops)
10. **No existing position**
11. **Within session hours** — Between 14:35 and 17:00 UTC (9:35 AM - 1:00 PM ET, shorter session)

### Short Entry Conditions

Mirror of long, with:
- SuperTrend bearish
- RSI < 45
- Bearish candle or fresh flip
- Price below EMA_50 or fresh flip
- Same anti-whipsaw, cooldown, ATR floor, and candle body filters

### Exit Conditions

Same as v1 — SuperTrend direction flip:

- **Long exit:** SuperTrend flips bearish → `close_long`
- **Short exit:** SuperTrend flips bullish → `close_short`
- **End-of-session exit:** At 17:00 UTC (1:00 PM ET) — earlier cutoff than v1

### Stop-Loss Calculation

```
stop_distance = ATR_10 * 1.5    (1.5x ATR — wider than v1)

Long:  stop_loss = entry_price - stop_distance
Short: stop_loss = entry_price + stop_distance
```

Wider stops to give trades more room, reducing premature stop-outs on PLTR's higher volatility.

**Example:** If PLTR entry = $139.70 and ATR = $1.00, then stop = $139.70 - $1.50 = $138.20.

### Take-Profit Calculation

```
target_distance = ATR_10 * 3.5    (3.5x ATR)

Long:  take_profit = entry_price + target_distance
Short: take_profit = entry_price - target_distance
```

This gives a **3.5:1 reward-to-risk ratio** — higher than v1's 2.5:1.

**Example:** If PLTR entry = $139.70, ATR = $1.00, then target = $139.70 + $3.50 = $143.20.

### Trailing Stop

Not implemented. The SuperTrend exit and fixed stop/target handle risk.

### V2 Filters Explained

#### Anti-Whipsaw Filter (2-Bar Hold)
After SuperTrend flips to a new direction, the strategy waits for it to hold that direction for at least 2 consecutive bars before entering. This prevents entering on false signals where SuperTrend flips back and forth rapidly.

**Exception:** If the SuperTrend just flipped this bar (fresh signal), the entry is allowed immediately — the hold requirement only applies to "stale" signals.

#### Post-Stop Cooldown (3 Bars)
After a trade exits via stop-loss, the strategy enters a 3-bar cooldown where no new entries are taken. This prevents the common pattern of: stop out → immediately re-enter in the same direction → stop out again.

The cooldown counter decrements each bar and is triggered via `on_trade_closed()`.

#### ATR Floor Filter
Compares current ATR to its 20-period simple moving average. If current ATR is below average, the market is in a low-volatility choppy phase — not ideal for trend-following. Trades are skipped until volatility picks up.

#### Candle Body Filter (40%)
Measures `abs(close - open) / (high - low)`. If the candle body is less than 40% of the total range, it's a doji or spinning top — an indecision candle. The strategy skips these unreliable signals.

### State Tracking

- `_prev_st_dir` — Previous SuperTrend direction (detects flips)
- `_st_dir_count` — How many consecutive bars SuperTrend has held current direction (for the hold filter)
- `_cooldown_remaining` — Bars remaining in post-stop cooldown (decrements each bar)

---

## Multi-Timeframe Signal Selection

When a ticker runs on multiple timeframes (2m, 5m, 10m), the `MultiTimeframeEngine` scores signals from each and picks the best one.

### Scoring Formula (Higher = Better)

| Factor | Max Points | Logic |
|--------|-----------|-------|
| ADX strength | 40 | ADX > 25: `ADX * 1.0` (capped at 40). ADX 20-25: `ADX * 0.5`. ADX < 20: `ADX * 0.2` |
| Risk:Reward | 30 | `min(R:R ratio * 10, 30)` — e.g., 2:1 = 20 pts, 3:1 = 30 pts |
| Timeframe preference | ~17 | `20 - (tf_minutes * 1.5)` — 2m = 17 pts, 5m = 12.5, 10m = 5 |
| Signal agreement | 10/TF | +10 points for each other timeframe with same-direction signal |
| RSI filter | +5/-10 | +5 if RSI not extreme. -10 penalty if buying overbought (RSI>80) or selling oversold (RSI<20) |

### Example Scoring

A 2m long signal with ADX=30, R:R=2.5:1, and no agreement from other TFs:
- ADX: 30 * 1.0 = **30 pts**
- R:R: 2.5 * 10 = **25 pts**
- TF: 20 - 3 = **17 pts**
- Agreement: **0 pts**
- RSI (RSI=65, not extreme): **5 pts**
- **Total: 77 pts**

### Signal Freshness

Signals are buffered for up to 120 seconds (2 minutes). When multiple timeframes have signals within this window, they're scored together. Stale signals (> 2 min old) are discarded.

### Why Lower Timeframes Score Higher

Lower timeframes (2m) get a preference bonus because:
- **Tighter stops** — Lower TF means smaller ATR, so smaller stop distance
- **Better R:R** — Same profit target logic but with tighter risk
- **Faster entries** — Don't wait for 10m bar to close

However, higher ADX or signal agreement from multiple TFs can override the TF preference.

---

## Risk Manager Checks

Before any order is submitted to the broker, the risk manager validates it through 11 sequential checks:

| # | Check | Action on Fail |
|---|-------|----------------|
| 1 | Is trading paused? | Block |
| 2 | Trading blocked by broker? | Pause all trading |
| 3 | Equity below $25,000 (PDT threshold)? | Pause all trading |
| 4 | Daily loss limit exceeded ($3,000)? | Pause all trading |
| 5 | Drawdown circuit breaker (15%)? | Pause all trading |
| 6 | Already in position for this ticker? | Block |
| 7 | Max total positions reached (2)? | Block |
| 8 | Total exposure cap exceeded (90% equity)? | Block |
| 9 | Single share > max position value? | Block |
| 10 | Insufficient Reg-T buying power? | Block |
| 11 | Outside market hours? | Block |

**Note:** Exit signals (close_long, close_short) always bypass all checks — we always want to be able to close a position.

---

## Position Sizing

### Calculation Steps

1. **Base desired value** — Determined by sizing method:
   - `percent`: `equity * 0.90` (90% of equity)
   - `fixed`: Fixed dollar amount ($10,000)
   - `risk_based`: `(equity * risk_pct / stop_distance) * price`

2. **Cap by exposure capacity** — If other positions are open:
   - `remaining = (equity * 0.90) - sum(open_position_values)`
   - If desired > remaining, size down to remaining

3. **Cap by buying power** — Prevent margin violations:
   - `available_bp = regt_buying_power - current_exposure`
   - If desired > available_bp, size down to available_bp

4. **Convert to shares** — `quantity = max(1, int(desired_value / price))`

### Example

- Equity: $100,000
- HIMS already open at $89,000
- Exposure cap: 90% = $90,000
- Remaining capacity: $90,000 - $89,000 = $1,000
- Reg-T BP: $200,000
- Available BP: $200,000 - $89,000 = $111,000

**Result:** Position sized to $1,000 (exposure cap is the tighter constraint).
At PLTR $140/share → 7 shares. At MSTU $5/share → 200 shares.

---

## How Stops and Targets Are Checked

The engine checks stops/targets **locally** on every bar by comparing:
- **Stop-loss:** Long → `bar_low <= stop_level`. Short → `bar_high >= stop_level`
- **Take-profit:** Long → `bar_high >= target_level`. Short → `bar_low <= target_level`

If either is hit, a close signal is generated immediately (before calling `on_bar()`). The broker also holds the position, but local checking ensures behavior matches the backtest engine exactly.

### Trailing Stops

If a trailing stop distance is set (currently not used by either strategy), the `Position.update_trailing_stop(current_price)` method adjusts the stop level as price moves favorably:
- Long: stop moves up as price rises, never moves down
- Short: stop moves down as price falls, never moves up
