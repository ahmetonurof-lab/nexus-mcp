# NEXUS V2 — Score Hesaplama Sistemi

> SMC/ICT tabanlı trading botu için 3 katmanlı, çok aşamalı skorlama ve veto mimarisi.
> Her katman bağımsız veto yetkisine sahiptir ("Giyotin Prensibi").

---

## 📐 MİMARİ GENEL BAKIŞ

```
H4 Trend (Yapısal Şalter) → H1 ADX (Rejim) → 15m CHoCH (Teyit) → 15m FVG (Hedef)
                                                    ↓
                              ┌─── KATMAN 1: FVG Quality Score (fvg.py)
                              │    - Bileşen skorları + veto
                              ├─── KATMAN 2: TradeSignal Confidence (scoring.py)
                              │    - Konfluens bonus + rejim çarpanı
                              └─── KATMAN 3: Sinyal Validasyonu (analyzer.py)
                                   - 7 adımlı veto zinciri
                                                    ↓
                                           5m LTF Trigger → ARMED → Trade
```

---

## 🔷 KATMAN 1: FVG Quality Score

**Dosya:** `sonnet/src/fvg.py` — `compute_fvg_quality()`

5 bileşen skorundan ağırlıklandırılarak nihai FVG kalite skoru üretilir.

### 1.1 Bileşen Skorları

| Bileşen | Fonksiyon | Açıklama | Range |
|---------|-----------|----------|:-----:|
| **d** (displacement) | `score_displacement()` | Mother bar momentumu = gövde / (ATR × 0.75). Yön uyuşmazlığında **VETO** (0.0) | [0, 1] |
| **f** (fvg_size) | `score_fvg_size()` | FVG boşluk boyutu = gap / (ATR × 1.5) | [0, 1] |
| **s** (sweep) | `score_sweep()` | Likidite avı: mother bar öncesi swing low/high kırıldı mı? | {0, 0.5, 1.0} |
| **r** (retest) | `score_retest()` | FVG'ye temas zamanlaması (kaç bar sonra?) | [0.2, 1.0] |
| **choch_score** | `_get_choch_score_for_direction()` | CHoCH yapısal uyumu (penetrasyon + onay + ADX) | [0, 1] |

#### displacement (d) Detayı

```python
body = mother_bar.body  # abs(close - open)
direction_val = close - open

# Yön uyuşmazlığı → VETO
if bullish and direction_val <= 0: return 0.0
if bearish and direction_val >= 0: return 0.0

return clamp(body / (atr * 0.75), 0.0, 2.0) / 2.0
```

#### sweep (s) Detayı

```python
# Bullish: mother_bar.low son N bar'ın en düşüğünden düşük mü?
if mother_bar.low < swing_low:
    return 1.0 if mother_bar.close > swing_low else 0.5
# Bearish: mother_bar.high son N bar'ın en yükseğinden yüksek mi?
if mother_bar.high > swing_high:
    return 1.0 if mother_bar.close < swing_high else 0.5
```

#### retest (r) Detayı

| FVG Sonrası Bar Sayısı | Skor |
|:----------------------:|:----:|
| ≤ 2 | 0.3 |
| 3 – 6 | **1.0** (optimal) |
| 7 – 12 | 0.6 |
| > 12 | 0.2 |

### 1.2 Ağırlıklandırma (Mod Bazlı)

İki mod vardır: **Reversal** (düşük ADX) ve **Impulsive** (yüksek ADX).

**Reversal Mod** (ADX < 25):
```
score = (s × 0.25) + (choch_score × 0.25) + (d × 0.25) + (f × 0.15) + (r × 0.10)
```
→ Sweep en kritik bileşen. CHoCH ve displacement eşit ağırlıkta.

**Impulsive Mod** (ADX ≥ 25):
```
score = (d × 0.55) + (f × 0.25) + (choch_score × 0.10) + (r × 0.10)
```
→ Displacement baskın (trend momentumu). Sweep tamamen çıkarıldı.

### 1.3 Veto Katmanı (Giyotin)

| Koşul | Mod | Sonuç |
|-------|:---:|:-----:|
| CHoCH yönü ≠ FVG yönü | Her ikisi | **score = 0.0** |
| Sweep yok (s < 0.01) | Reversal | **score = 0.0** |
| Premium/Discount ihlali | Reversal | **score = 0.0** |
| VP = HVN (yüksek hacim) | Her ikisi | **score - 0.20** (ceza) |

**Premium/Discount Kuralı:**
- Short (bearish): Fiyat Fibonacci %50 üstünde (Premium) olmalı
- Long (bullish): Fiyat Fibonacci %50 altında (Discount) olmalı

---

## 🔷 KATMAN 2: TradeSignal Confidence

**Dosya:** `sonnet/src/scoring.py` — `evaluate_trade_signal()`

FVG Quality Score üzerine konfluens ve rejim çarpanları eklenir.

### 2.1 Konfluens Kaynakları

| # | Kaynak | Açıklama |
|:-:|--------|----------|
| 1 | **FVG** | Varlık (otomatik, her zaman +1) |
| 2 | **CHoCH** | Aynı yönde CHoCH var mı? |
| 3 | **EMA alignment** | EMA100 > EMA200 (bullish) veya tersi (bearish) |
| 4 | **Price vs EMA100** | Fiyat EMA100'ün doğru tarafında mı? |
| 5 | **ADX trend** | ADX ≥ 20 (trend gücü var) |
| 6 | **Premium/Discount** | Doğru bölgede mi? |
| 7 | **VP_LVN** | Düşük hacim bölgesinde mi avantajlı? |

### 2.2 Confidence Formülü

```
base = fvg_quality.score
bonus = min((confluence_count - 1) × 0.05, 0.20)   // max +0.20
base_confidence = base + bonus

// Rejim çarpanı:
ranging               → base_confidence × 0.85
volatile              → base_confidence × 0.75
trend ile aynı yön    → base_confidence × 1.10  (bonus)
trend ile zıt yön     → base_confidence × 0.70  (ceza)

// CHoCH double-lock veto:
if choch_score > 0 AND choch_direction ≠ fvg_direction:
    final_confidence = 0.0

final_confidence = clamp(base_confidence, 0.0, 1.0)
```

### 2.3 Sinyal Sınıflandırması

| confidence | Sınıf | Anlamı |
|:----------:|:-----:|--------|
| ≥ 0.75 | **STRONG** | Güçlü sinyal, yüksek güven |
| ≥ 0.55 | **MODERATE** | Orta sinyal, standard işlem |
| ≥ 0.30 | **WEAK** | Zayıf, dikkatli |
| < 0.30 | **NONE** | Sinyal yok |

---

## 🔷 KATMAN 3: Sinyal Validasyonu

**Dosya:** `sonnet/src/analyzer.py` — `AnalysisResult.is_valid_signal()`

7 adımlı veto zinciri — tüm adımları geçen sinyal `is_valid = True` olur.

### 3.1 Veto Zinciri

```
Step 1: direction == None?                    → RED (yön yok)
Step 2: choch == None?                        → RED (yapısal teyit yok)
Step 3: choch.direction ≠ expected?           → RED (CHoCH uyumsuz)
Step 4: fvg == None?                          → RED (FVG yok)
Step 5: fvg_age > 32 bars?                   → RED (bayat)
Step 6: fvg_quality.score < threshold?        → RED (skor düşük)
Step 7: NOT (retest_ready OR impulsive_bypass)? → RED (giriş koşulu yok)
                                              ↓
                                         ✅ VALID
```

### 3.2 Impulsive Bypass

Yüksek ADX modunda, retest beklenmeden de giriş yapılabilir:

```python
impulsive_bypass = (
    is_impulsive                                   # ADX ≥ 25
    and self.fvg_quality.displacement ≥ 0.45       # güçlü momentum
)
```

### 3.3 Entry Zone Seçimi

```
proximal = FVG.bottom + FVG.size × 0.15   (bullish)
         = FVG.top - FVG.size × 0.15      (bearish)

CE = FVG.midpoint

Seçim: hangisi mevcut fiyata daha yakınsa o kullanılır.
```

---

## 🔷 EŞİK DEĞERLERİ

**Dosya:** `sonnet/src/config.py`

| Sabit | Değer | Açıklama |
|-------|:-----:|----------|
| `FVG_SCORE_THRESHOLD` | **0.40** | Reversal mod min FVG skoru |
| `FVG_SCORE_THRESHOLD_IMPULSIVE` | **0.35** | Impulsive mod min FVG skoru |
| `FVG_IMPULSIVE_ADX_THRESHOLD` | **25.0** | ADX ≥ 25 → Impulsive mod |
| `FVG_IMPULSIVE_DISPLACEMENT_MIN` | **0.45** | Impulsive bypass için min displacement |
| `MIN_CONFIDENCE_THRESHOLD` | **0.55** | scoring.py TradeSignal min barajı |
| `STRONG_CONFIDENCE_THRESHOLD` | **0.75** | Güçlü sinyal sınıflandırması |
| `FVG_MAX_AGE_BARS` | **32** | 15m × 32 = 8 saat (CHoCH ile tutarlı) |
| `FVG_RELAX_THRESHOLD` | **0.25** | Relax (gecikmiş) sinyal eşiği |
| `FVG_RELAX_THRESHOLD_IMPULSIVE` | **0.20** | Impulsive relax eşiği |
| `FVG_RELAX_AFTER_BARS` | **5** | Relax moduna geçiş için bekleme |
| `ADX_THRESHOLD` | **20.0** | Minimum ADX (altında işlem yasak) |
| `ADX_HIGH_TP_THRESHOLD` | **35.0** | Yüksek ADX'te TP daraltma |
| `ADX_HIGH_TP_MULTIPLIER` | **0.7** | TP mesafesi daraltma katsayısı |
| `IMPULSIVE_ADX_THRESHOLD` | **20.0** | fvg.py impulsive mod algılama |
| `CHoCH_PIVOT_ADX_THRESHOLD` | **35.0** | ADX ≥ 35 → pivot LR=2 (hassas) |
| `MIN_RR` | **1.5** | Minimum risk/ödül oranı |
| `MIN_NET_RR` | **1.2** | Net risk/ödül (fee sonrası) |
| `RISK_PER_TRADE` | **0.005** | Hesabın %0.5'i kadar risk |

---

## 🔷 TAM İŞLEM AKIŞI

```
1. MarketAnalyzer.analyze() çağrılır
   │
   ├── bars_d1 → EMA100 hesapla
   ├── bars_h4 → _trend_direction() → LONG/SHORT/None
   │   (Swing high/low kırılımı, 120 bar lookback)
   │
   ├── bars_h1 → ADX hesapla → Rejim belirle (impulsive/reversal)
   │
   ├── bars_15m → refresh_choch_list() → son CHoCH
   │   ├── CHoCH bulundu → direction = choch.direction
   │   └── CHoCH yok → direction = H4 trend
   │
   ├── bars_15m → refresh_fvg_list() → find_latest_unfilled_fvg()
   │   ├── FVG + CHoCH varsa: age ≤ 32 bar kontrolü
   │   └── FVG yoksa: return (sinyal yok)
   │
   ├── Bileşen skorları: d, f, s, r, choch_score
   │
   ├── compute_fvg_quality() → FVGQuality.score
   │   ├── Veto kontrolleri (mod bazlı)
   │   └── Ağırlıklı skor hesaplama
   │
   ├── score ≥ threshold kontrolü
   │   └── Altındaysa: monitor.update_reject("score_below_threshold")
   │
   ├── Entry Zone hesapla (proximal vs CE)
   │
   └── 5m LTF Trigger:
       ├── check_ltf_trigger() → 5m CHoCH veya Engulfing
       ├── Tetik varsa → ARMED = True
       │   ├── stop_loss = compute_structural_sl()
       │   └── monitor.update_signal("armed_...")
       └── Tetik yoksa → bekle (sonraki bar)
```

---

## 🔷 ÖRNEK SENARYOLAR

### Senaryo 1: Impulsive Long (BTCUSDT)

| Bileşen | Değer | Skor |
|---------|:-----:|:----:|
| ADX | 32.4 | → Impulsive mod |
| displacement (d) | 0.72 | → 0.55 × 0.72 = 0.396 |
| fvg_size (f) | 0.45 | → 0.25 × 0.45 = 0.113 |
| choch_score | 0.55 | → 0.10 × 0.55 = 0.055 |
| retest (r) | 0.30 | → 0.10 × 0.30 = 0.030 |
| **FVG Quality Score** | | **0.594** ✅ (≥ 0.35) |
| Confluence: FVG+CHoCH+ADX+EMA = 4 | bonus +0.15 |
| Regim: trending_up (aynı yön) | × 1.10 |
| **Final Confidence** | | **0.818** → **STRONG** |

### Senaryo 2: Reversal Short (ETHUSDT)

| Bileşen | Değer | Skor |
|---------|:-----:|:----:|
| ADX | 22.1 | → Reversal mod |
| sweep (s) | 1.0 | → 0.25 × 1.0 = 0.250 |
| choch_score | 0.30 | → 0.25 × 0.30 = 0.075 |
| displacement (d) | 0.40 | → 0.25 × 0.40 = 0.100 |
| fvg_size (f) | 0.50 | → 0.15 × 0.50 = 0.075 |
| retest (r) | 0.60 | → 0.10 × 0.60 = 0.060 |
| **FVG Quality Score** | | **0.560** ✅ (≥ 0.40) |

### Senaryo 3: Veto (SOLUSDT)

| Koşul | Durum | Sonuç |
|-------|:-----|:------|
| H4 trend | Long (bullish) | OK |
| CHoCH | Bearish (zıt yön) | **CHoCH yön veto** |
| | | `score = 0.0` ❌ |

---

## 🔷 DOSYA BAĞIMLILIKLARI

```
models.py (Foundation)
   └── indicators.py (Hesaplamalar)
        ├── pivot.py (Swing tespiti)
        │    └── choch.py (CHoCH tespiti)
        │         └── fvg.py ← FVG Quality Score & Veto
        │              └── scoring.py ← TradeSignal Confidence
        │                   └── analyzer.py ← MarketAnalyzer & Validasyon
        │                        └── trader.py (İşlem açma)
        └── volume_profile.py (VP analizi)
```

---

## 🔷 MONITORING

Tüm ret'ler `monitor.py` üzerinden kaydedilir:

| Ret Sebebi | Açıklama |
|------------|----------|
| `timeout_reject` | FVG bayat (> 32 bar) |
| `adx_impulsive_reject` | Impulsive modda ADX(15m) < 20 |
| `no_sweep_reject` | Reversal modda sweep yok |
| `score_below_threshold` | FVGQuality.score < eşik |

Başarılı sinyaller:

| Sinyal | Açıklama |
|--------|----------|
| `armed_5m_choch_score_0.XXX` | 5m CHoCH tetiklemesiyle ARMED |
| `armed_5m_engulfing_score_0.XXX` | 5m Engulfing tetiklemesiyle ARMED |
