# Sniper Backtest — 13 Coin Nihai Rapor

**Commit:** `bd4bd231e5f39e55b7228f95bb0d79aa5c9a2975`
**Test Verisi:** Ağustos 2025 (2025-08-01 → 2025-09-01, ~45k 1m bar/coin)
**Session:** NEWYORK (13:00-22:00 UTC) + LONDON (02:00-13:00 UTC)
**Bias Filter:** Açık (bullish/bearish/neutral kontrolü)
**Config:** `backtest-sniper/src/coins_config.py` (optimize edilmiş min_fvg_size)

---

## Global Parametreler

| Parametre | Değer |
|-----------|-------|
| Başlangıç Sermayesi | $10,000 |
| Risk/İşlem | 1% |
| SL Çarpanı (ATR) | 1.5 |
| TP Oranı | 2.0R veya London H/L |
| FVG Buffer | 0.25x risk |
| Trailing | Açık (FVG bazlı SL/TP) |
| Retrade | Açık (2. entry) |

---

## Coin Bazlı Sonuçlar

| # | Coin | fvg | İşlem | Kazanç | WR | PnL (USDT) | Max DD | PF |
|---|------|-----|-------|--------|----|-----------|--------|-----|
| 1 | BTCUSDT | 10.0 | 50 | 27 | %54.0 | **+$7,879** | %2.0 | 7.28 |
| 2 | ETHUSDT | 1.5 | 40 | 22 | %55.0 | **+$6,202** | %2.1 | 6.05 |
| 3 | BNBUSDT | 0.8 | 45 | 24 | %53.3 | +$2,546 | %4.1 | 2.46 |
| 4 | SOLUSDT | 0.14 | 34 | 26 | **%76.5** | **+$5,345** | %1.2 | 2.80 |
| 5 | AVAXUSDT | 0.01 | 49 | 33 | %67.3 | +$5,817 | %2.1 | 4.20 |
| 6 | LINKUSDT | 0.01 | 46 | 34 | %73.9 | **+$7,632** | %4.0 | 3.76 |
| 7 | XRPUSDT | 0.002 | 48 | 36 | %75.0 | **+$7,937** | %1.2 | 3.77 |
| 8 | ATOMUSDT ⭐ | 0.005 | 42 | 34 | **%81.0** | **+$7,909** | **%0.7** | 5.13 |
| 9 | ADAUSDT | 0.0003 | 56 | 39 | %69.6 | +$5,021 | %1.2 | 2.88 |
| 10 | SUIUSDT | 0.001 | 39 | 29 | %74.4 | +$4,445 | %1.4 | 2.84 |
| 11 | APTUSDT | 0.003 | 25 | 20 | %80.0 | +$4,807 | %1.5 | 4.75 |
| 12 | DOTUSDT | 0.003 | 44 | 29 | %65.9 | +$4,269 | %2.4 | 3.86 |
| 13 | NEARUSDT | 0.001 | 29 | 24 | **%82.8** | +$3,589 | %1.0 | 3.46 |
| | **TOPLAM** | | **547** | **397** | **%72.6** | **+$74,398** | — | — |

---

## En Yüksek Performans Gösterenler

### En Karlı 3 Coin
| # | Coin | PnL | WR | DD |
|---|------|-----|-----|-----|
| 🥇 | **XRPUSDT** | **+$7,937** | %75.0 | %1.2 |
| 🥈 | **ATOMUSDT** | **+$7,909** | %81.0 | %0.7 |
| 🥉 | **BTCUSDT** | **+$7,879** | %54.0 | %2.0 |

### En Yüksek WR 3 Coin
| # | Coin | WR | PnL | DD |
|---|------|-----|-----|-----|
| 🥇 | **NEARUSDT** | **%82.8** | +$3,589 | %1.0 |
| 🥈 | **ATOMUSDT** | **%81.0** | +$7,909 | %0.7 |
| 🥉 | **APTUSDT** | **%80.0** | +$4,807 | %1.5 |

### En Düşük DD 3 Coin
| # | Coin | DD | PnL | WR |
|---|------|-----|-----|-----|
| 🥇 | **ATOMUSDT** | **%0.7** | +$7,909 | %81.0 |
| 🥈 | **NEARUSDT** | **%1.0** | +$3,589 | %82.8 |
| 🥉 | **SOLUSDT** | **%1.2** | +$5,345 | %76.5 |

---

## Long / Short Dağılımı

| Coin | Long Trades | Long WR | Long PnL | Short Trades | Short WR | Short PnL |
|------|------------|---------|----------|-------------|---------|-----------|
| BTCUSDT | 36 | %47.2 | +$519 | 14 | %71.4 | **+$7,360** |
| ETHUSDT | 28 | %53.6 | **+$5,147** | 12 | %58.3 | +$1,055 |
| BNBUSDT | 19 | %52.6 | +$1,205 | 26 | %53.8 | **+$1,341** |
| SOLUSDT | 19 | %68.4 | **+$2,899** | 15 | %86.7 | +$2,446 |
| AVAXUSDT | 19 | %63.2 | **+$2,986** | 30 | %70.0 | +$2,830 |
| LINKUSDT | 30 | **%76.7** | **+$4,385** | 16 | %68.8 | +$3,247 |
| XRPUSDT | 13 | %84.6 | +$3,329 | 35 | %71.4 | **+$4,607** |
| ATOMUSDT | 20 | %80.0 | +$3,747 | 22 | %81.8 | **+$4,162** |
| ADAUSDT | 18 | %77.8 | +$2,076 | 38 | %65.8 | **+$2,945** |
| SUIUSDT | 9 | %66.7 | +$1,529 | 30 | **%76.7** | **+$2,916** |
| APTUSDT | 2 | %50.0 | +$112 | 23 | **%82.6** | **+$4,695** |
| DOTUSDT | 24 | %62.5 | +$1,436 | 20 | %70.0 | **+$2,833** |
| NEARUSDT | 21 | **%85.7** | **+$2,831** | 8 | %75.0 | +$758 |

---

## Retrade (2. Entry) Analizi

| Coin | Retrade Sayısı | Retrade PnL | Retrade WR | Toplam PnL Katkısı |
|------|---------------|------------|-----------|-------------------|
| BTCUSDT | 2 | -$22 | %50.0 | -%0.3 |
| ETHUSDT | 4 | +$161 | %25.0 | +%2.6 |
| BNBUSDT | 0 | — | — | — |
| SOLUSDT | 1 | -$95 | %0.0 | -%1.8 |
| AVAXUSDT | 1 | +$36 | %100.0 | +%0.6 |
| LINKUSDT | 1 | +$106 | %100.0 | +%1.4 |
| XRPUSDT | 0 | — | — | — |
| ATOMUSDT | 0 | — | — | — |
| ADAUSDT | 1 | +$204 | %100.0 | +%4.1 |
| SUIUSDT | 1 | -$2 | %0.0 | -%0.0 |
| APTUSDT | 0 | — | — | — |
| DOTUSDT | 1 | +$187 | %100.0 | +%4.4 |
| NEARUSDT | 2 | -$77 | %50.0 | -%2.1 |

---

## Karşılaştırma: NEWYORK vs NEWYORK+LONDON

| Metric | NY Only | NY + LONDON | Fark |
|--------|---------|-------------|------|
| Toplam İşlem | 341 | **547** | **+%60** |
| Toplam PnL | +$60,405 | **+$74,398** | **+$13,993** |
| Ortalama WR | %73.6 | %71.5 | -%2.1 |
| Retrade Katkısı | +$4,400 | +$498 | Düşüş |

---

---

## Coin Puanlama (0-100)

| # | Coin | PnL | WR | DD | PF | İşlem | **PUAN** |
|---|------|-----|-----|-----|-----|-------|----------|
| 8 | **ATOMUSDT** ⭐ | A+ | A | A+ | A | A | **95** |
| 7 | XRPUSDT | A+ | A | A+ | A | A | **90** |
| 6 | LINKUSDT | A+ | A | B | A | A | **85** |
| 4 | SOLUSDT | A | A+ | A+ | A | B+ | **85** |
| 1 | BTCUSDT | A+ | C+ | A | A+ | A | **82** |
| 11 | APTUSDT | A | A | A | A | B | **80** |
| 5 | AVAXUSDT | A | B+ | A | A | A | **78** |
| 13 | NEARUSDT | B+ | A+ | A+ | B+ | B+ | **77** |
| 10 | SUIUSDT | B+ | A | A+ | B+ | A | **75** |
| 12 | DOTUSDT | B+ | B+ | A | A | A | **74** |
| 2 | ETHUSDT | A | C+ | A | A | A | **72** |
| 9 | ADAUSDT | B+ | B+ | A | B+ | A+ | **70** |
| 3 | BNBUSDT | B | C | B | B+ | A | **55** |

### Puanlama Kriterleri

| Harf | Anlamı |
|------|--------|
| **A+** | Mükemmel (en iyi %20) |
| **A** | Çok iyi |
| **B+** | İyi |
| **B** | Orta |
| **C+** | Zayıf |
| **C** | Kötü |

### Puan Analizi

- **ATOMUSDT (95)** — Her metriği dengeli, düşük riskli star performer
- **BNBUSDT (55)** — WR düşük (%53), DD en yüksek (%4.1), PnL en düşük. Parametre revizyonu gerekebilir
- **NEARUSDT (77)** — WR en yüksek (%83) ama PnL düşük. Fiyat düşük, pozisyon büyüklüğü limitli
- **BTCUSDT (82)** — WR düşük (%54) ama PF 7.28 ve PnL yüksek. Short trades çok kurtarıyor

---

## Özet

- **13 coinin tamamı pozitif**, toplam **+$74,398 PnL**
- Ortalama **%72.6 WR**, maksimum DD sadece **%4.0** (LINK)
- **En güçlü coin:** ATOMUSDT — %81 WR, %0.7 DD, +$7,909 PnL
- **En çok işlem:** ADAUSDT — 56 işlem
- **En yüksek WR:** NEARUSDT — %82.8
- Short ağırlıklı coinlerde (APT %82.6, SUI %76.7, XRP %71.4) WR yüksek
- Trailing hemen hemen tüm işlemlerde aktif, trailing yok işlemler genelde zararda
