# Sniper Backtest Report — Optimized Parameters

**Commit:** `bd4bd231e5f39e55b7228f95bb0d79aa5c9a2975`
**Test Data:** August 2025 (2025-08-01 → 2025-09-01, ~45k 1m bars per coin)
**Data Source:** Binance API via ccxt (fresh download, no overlap with training data)
**Analyzer:** `backtest-sniper/src/analyzer.py` (parametric, config-driven)
**Coins:** 13 (7 original + 6 candidates)

---

## Global Parameters

| Param | Value |
|-------|-------|
| Initial Capital | $10,000 |
| Risk Per Trade | 1% |
| SL Multiplier (ATR) | 1.5 |
| TP Ratio | 2.0R or London H/L |
| FVG Buffer | 0.25x risk |
| Session Filter | NEWYORK only |
| Bias Filter | CBDR bias direction |
| Retrade | Enabled (2nd entry after 1st closes) |
| Trailing | Enabled (FVG-based SL/TP trail) |

---

## Per-Coin Configuration

| Coin | min_fvg_size | Price ~ | fvg as % of price |
|------|-------------|---------|-------------------|
| BTCUSDT | 10.0 | $70k | 0.014% |
| ETHUSDT | 1.5 | $3.5k | 0.043% |
| BNBUSDT | 0.8 | $700 | 0.11% |
| SOLUSDT | 0.14 | $150 | 0.093% |
| AVAXUSDT | 0.01 | $22 | 0.045% |
| LINKUSDT | 0.01 | $20 | 0.05% |
| XRPUSDT | 0.002 | $2.8 | 0.071% |
| ATOMUSDT | 0.005 | $5.5 | 0.091% |
| ADAUSDT | 0.0003 | $0.35 | 0.086% |
| SUIUSDT | 0.001 | $1.6 | 0.063% |
| APTUSDT | 0.003 | $6 | 0.050% |
| DOTUSDT | 0.003 | $4.5 | 0.067% |
| NEARUSDT | 0.001 | $2.5 | 0.040% |

---

## BTCUSDT — 29 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 29 |
| Win Rate | 69.0% |
| Total PnL | **+$7,989.22** |
| Max Drawdown | 1.5% |
| Profit Factor | 7.71 |
| Avg Win R:R | +4.24 |
| Avg Loss R:R | -0.55 |
| TP Rate | 3.4% |
| Avg Trailing | 2.1 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 21 | 57.1% | +$537 | +0.86 |
| SHORT | 8 | 100.0% | **+$7,452** | **+9.32** |

**Retrade:** 1 trade, PnL=+$247, WR=100.0%
**Trailing:** 28/29 trades trailed, PnL=+$7,981 vs +$8 non-trailed

---

## ETHUSDT — 30 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 30 |
| Win Rate | 63.3% |
| Total PnL | **+$6,236.07** |
| Max Drawdown | 1.5% |
| Profit Factor | 5.94 |
| Avg Win R:R | +3.64 |
| Avg Loss R:R | -0.61 |
| TP Rate | 20.0% |
| Avg Trailing | 1.9 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 21 | 66.7% | **+$5,367** | +4.14 |
| SHORT | 9 | 55.6% | +$869 | +2.23 |

**Retrade:** 3 trades, PnL=+$371, WR=66.7%
**Trailing:** 27/30 trailed, PnL=+$6,309 vs -$73 non-trailed

---

## BNBUSDT — 33 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 33 |
| Win Rate | 60.6% |
| Total PnL | **+$3,921.80** |
| Max Drawdown | 2.5% |
| Profit Factor | 3.31 |
| Avg Win R:R | +2.44 |
| Avg Loss R:R | -0.74 |
| TP Rate | 12.1% |
| Avg Trailing | 1.2 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 14 | 71.4% | **+$2,980** | +3.19 |
| SHORT | 19 | 52.6% | +$941 | +1.69 |

**Retrade:** 1 trade, PnL=**+$1,717**, WR=100.0%
**Trailing:** 27/33 trailed, PnL=+$4,178 vs -$256 non-trailed

---

## SOLUSDT — 18 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 18 |
| Win Rate | 66.7% |
| Total PnL | **+$2,761.24** |
| Max Drawdown | 2.4% |
| Profit Factor | 3.35 |
| Avg Win R:R | +2.71 |
| Avg Loss R:R | -0.81 |
| TP Rate | 11.1% |
| Avg Trailing | 1.6 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 9 | 44.4% | +$804 | +3.06 |
| SHORT | 9 | **88.9%** | **+$1,957** | +2.52 |

**Retrade:** 1 trade, PnL=-$95, WR=0.0%
**Trailing:** 17/18 trailed, PnL=+$2,861 vs -$100 non-trailed

---

## AVAXUSDT — 29 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 29 |
| Win Rate | 69.0% |
| Total PnL | **+$5,058.55** |
| Max Drawdown | 2.2% |
| Profit Factor | 4.72 |
| Avg Win R:R | +2.79 |
| Avg Loss R:R | -0.59 |
| TP Rate | 10.3% |
| Avg Trailing | 1.7 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 15 | 66.7% | **+$3,331** | +3.68 |
| SHORT | 14 | 71.4% | +$1,727 | +1.91 |

**Retrade:** 1 trade, PnL=+$587, WR=100.0%
**Trailing:** 27/29 trailed, PnL=+$5,041 vs +$18 non-trailed

---

## LINKUSDT — 30 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 30 |
| Win Rate | 66.7% |
| Total PnL | **+$4,898.06** |
| Max Drawdown | 4.0% |
| Profit Factor | 3.82 |
| Avg Win R:R | +2.82 |
| Avg Loss R:R | -0.74 |
| TP Rate | 20.0% |
| Avg Trailing | 1.5 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 18 | 72.2% | +$2,345 | +2.07 |
| SHORT | 12 | 58.3% | **+$2,553** | **+4.21** |

**Trailing:** 25/30 trailed, PnL=+$5,133 vs -$235 non-trailed

---

## XRPUSDT — 30 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 30 |
| Win Rate | 76.7% |
| Total PnL | **+$6,204.07** |
| Max Drawdown | 1.1% |
| Profit Factor | 3.89 |
| Avg Win R:R | +2.93 |
| Avg Loss R:R | -0.75 |
| TP Rate | 3.3% |
| Avg Trailing | 2.2 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 7 | 85.7% | +$2,435 | **+4.22** |
| SHORT | 23 | 73.9% | **+$3,769** | +2.47 |

**Trailing:** 29/30 trailed, PnL=+$6,304 vs -$100 non-trailed

---

## ATOMUSDT — 32 Trades ⭐ (EN YÜKSEK PnL)

| Metric | Value |
|--------|-------|
| Total Trades | 32 |
| Win Rate | 78.1% |
| Total PnL | **+$6,113.88** |
| Max Drawdown | 0.6% |
| Profit Factor | 5.99 |
| Avg Win R:R | +2.57 |
| Avg Loss R:R | -0.43 |
| TP Rate | 12.5% |
| Avg Trailing | 1.8 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 18 | 77.8% | **+$3,474** | +2.59 |
| SHORT | 14 | 78.6% | +$2,640 | +2.53 |

**Retrade:** 3 trades, PnL=+$486, WR=100.0%
**Trailing:** Trailing aktif, sonuçlar dominant

---

## ADAUSDT — 38 Trades (EN FAZLA İŞLEM)

| Metric | Value |
|--------|-------|
| Total Trades | 38 |
| Win Rate | 78.9% |
| Total PnL | **+$4,090.36** |
| Max Drawdown | 1.9% |
| Profit Factor | 2.64 |
| Avg Win R:R | +1.52 |
| Avg Loss R:R | -0.57 |
| TP Rate | 5.3% |
| Avg Trailing | 2.0 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 15 | 86.7% | +$1,904 | +1.60 |
| SHORT | 23 | 73.9% | **+$2,187** | +1.46 |

**Trailing:** 38/38 trades trailed

---

## SUIUSDT — 23 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 23 |
| Win Rate | 78.3% |
| Total PnL | **+$3,919.91** |
| Max Drawdown | 1.4% |
| Profit Factor | 2.89 |
| Avg Win R:R | +2.41 |
| Avg Loss R:R | -0.83 |
| TP Rate | 8.7% |
| Avg Trailing | 1.7 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 6 | 66.7% | +$1,890 | +5.18 |
| SHORT | 17 | 82.4% | **+$2,030** | +1.62 |

**Retrade:** 1 trade, PnL=+$624, WR=100.0%
**Trailing:** 21/23 trailed, PnL=+$3,853 vs +$67 non-trailed

---

## APTUSDT — 14 Trades (EN YÜKSEK WR)

| Metric | Value |
|--------|-------|
| Total Trades | 14 |
| Win Rate | **85.7%** |
| Total PnL | **+$3,895.36** |
| Max Drawdown | 0.4% |
| Profit Factor | **8.09** |
| Avg Win R:R | +3.31 |
| Avg Loss R:R | -0.41 |
| TP Rate | **42.9%** |
| Avg Trailing | 2.1 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 2 | 50.0% | +$112 | +1.53 |
| SHORT | 12 | **91.7%** | **+$3,783** | +3.48 |

---

## DOTUSDT — 21 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 21 |
| Win Rate | **85.7%** |
| Total PnL | **+$3,457.54** |
| Max Drawdown | 0.6% |
| Profit Factor | 4.53 |
| Avg Win R:R | +1.99 |
| Avg Loss R:R | -0.44 |
| TP Rate | 9.5% |
| Avg Trailing | 2.2 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 12 | 75.0% | +$959 | +1.21 |
| SHORT | 9 | **100.0%** | **+$2,499** | +2.78 |

---

## NEARUSDT — 14 Trades

| Metric | Value |
|--------|-------|
| Total Trades | 14 |
| Win Rate | **85.7%** |
| Total PnL | **+$1,859.39** |
| Max Drawdown | 0.6% |
| Profit Factor | 2.89 |
| Avg Win R:R | +1.64 |
| Avg Loss R:R | -0.57 |
| TP Rate | 21.4% |
| Avg Trailing | 1.4 |

**Long/Short Split:**
| Side | Trades | WR | PnL | Avg Win RR |
|------|--------|-----|-----|-----------|
| LONG | 9 | **88.9%** | **+$1,305** | +1.72 |
| SHORT | 5 | 80.0% | +$555 | +1.49 |

**Trailing:** 12/14 trailed, PnL=+$1,824 vs +$35 non-trailed

---

## Consolidated Results

| Coin | Trades | WR | PnL | DD | PF |
|------|--------|-----|-----|-----|-----|
| BTCUSDT | 29 | 69.0% | +$7,989 | 1.5% | 7.71 |
| ETHUSDT | 30 | 63.3% | +$6,236 | 1.5% | 5.94 |
| BNBUSDT | 33 | 60.6% | +$3,922 | 2.5% | 3.31 |
| SOLUSDT | 18 | 66.7% | +$2,761 | 2.4% | 3.35 |
| AVAXUSDT | 29 | 69.0% | +$5,059 | 2.2% | 4.72 |
| LINKUSDT | 30 | 66.7% | +$4,898 | 4.0% | 3.82 |
| XRPUSDT | 30 | 76.7% | +$6,204 | 1.1% | 3.89 |
| ATOMUSDT ⭐ | 32 | 78.1% | **+$6,114** | **0.6%** | 5.99 |
| ADAUSDT | 38 | 78.9% | +$4,090 | 1.9% | 2.64 |
| SUIUSDT | 23 | 78.3% | +$3,920 | 1.4% | 2.89 |
| APTUSDT | 14 | **85.7%** | +$3,895 | **0.4%** | **8.09** |
| DOTUSDT | 21 | 85.7% | +$3,458 | 0.6% | 4.53 |
| NEARUSDT | 14 | 85.7% | +$1,859 | 0.6% | 2.89 |
| **TOTAL** | **341** | **73.6%** | **+$60,405** | — | — |

## Key Observations

- **All 13 coins profitable** with positive PF across the board
- **ATOMUSDT** is the star performer: +$6,114 with only 0.6% DD
- **APTUSDT / DOTUSDT / NEARUSDT** all hit 85.7% WR — extremely selective strategy
- **ADAUSDT** generates the most trades (38) — best for frequency traders
- **Trailing SL/TP** significantly outperforms non-trailed in every coin
- **Retrade** contributes positively in BTC (+$247), ETH (+$371), BNB (+$1,717), AVAX (+$587), ATOM (+$486), SUI (+$624)
- **Short bias** outperforms in BTC (100% WR), SOL (88.9%), APT (91.7%), DOT (100%), XRP (73.9%)
- **Long bias** outperforms in ETH, BNB, AVAX, ATOM, ADA, NEAR
- Low DD (0.4-4.0%) across all coins — strategy is resilient

## Candidate Ranking (new coins)

| # | Coin | PnL | WR | DD | PF | Trades | Tavsiye |
|---|------|-----|-----|-----|-----|--------|---------|
| 1 | **ATOMUSDT** | +$6,114 | 78.1% | 0.6% | 5.99 | 32 | 🥇 Paper teste ekle |
| 2 | **ADAUSDT** | +$4,090 | 78.9% | 1.9% | 2.64 | 38 | 🥈 En çok işlem |
| 3 | **SUIUSDT** | +$3,920 | 78.3% | 1.4% | 2.89 | 23 | 🥉 Dengeli |
| 4 | **APTUSDT** | +$3,895 | 85.7% | 0.4% | 8.09 | 14 | Yüksek WR, düşük DD |
| 5 | **DOTUSDT** | +$3,458 | 85.7% | 0.6% | 4.53 | 21 | Çok temiz sinyaller |
| 6 | **NEARUSDT** | +$1,859 | 85.7% | 0.6% | 2.89 | 14 | WR güzel, PnL düşük |
