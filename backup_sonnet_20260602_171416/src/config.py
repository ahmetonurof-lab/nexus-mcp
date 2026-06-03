# config.py — NEXUS V2 (Production-Ready)

from datetime import datetime

IS_TESTNET = True

# ── Backtest zaman aralığı ──────────────────────────────
BACKTEST_START = datetime(2025, 1, 1)
BACKTEST_END = datetime(2025, 8, 31)

# ── Başlangıç bakiyesi ──────────────────────────────────
INITIAL_BALANCE = 10000.0
LEVERAGE = 10

# ── Risk parametreleri ───────────────────────────────────
RISK_PER_TRADE = 0.005
MIN_RR = 1.5
MIN_NET_RR = 1.2
DEFAULT_RR = 2.0
TAKER_FEE = 0.0004
SPREAD_PCT = 0.0001

# ── Slippage Modeli ──────────────────────────────────────
SLIPPAGE_ENTRY = 0.0002
SLIPPAGE_EXIT = 0.0002
SLIPPAGE_TOTAL = SLIPPAGE_ENTRY + SLIPPAGE_EXIT

# ── Momentum Filtresi (CHoCH kalite) ─────────────────────
CHoCH_MIN_BODY_RATIO = 1.0
CHoCH_ATR_OVERSHOOT = 0.2
CHoCH_ATR_PERIOD = 14
CHoCH_PIVOT_ADX_THRESHOLD = 35.0
CHOCH_BREAK_WINDOW = 15  # YENİ EKLENDİ: Sabırlı CHoCH arayışı

# ── CHoCH Maksimum Yaş (Saat) ──────────────────────────
# detect_chochs() içinde lookback hesaplaması için kullanılır.
# 15m → 8*60/15 = 32 bar, 5m → 8*60/5 = 96 bar
CHOCH_MAX_AGE_HOURS = 8

# ── ADX / DI Filtresi ────────────────────────────────────────
# 🧠 ADX Rejimi:
#   ADX < 20  → Strateji kör (SOL, BNB kanıtı) → İşlem ALINMAZ
#   ADX 20-30 → Sweet spot → Normal işlem (Kar bölgesi)
#   ADX > 35  → Breakeven'da takılı kalıyor → Sinyal al ama TP daralt
# ADX eşiği — TEMP BYPASS (normali 20)
D1_ADX_THRESHOLD = 15  # TODO: 20'ye geri al
ADX_THRESHOLD = 20.0
ADX_THRESHOLD_DEFAULT = 20.0  # Minimum ADX eşiği (20 altı işlem yasak)
ADX_THRESHOLDS = {
    "BTCUSDT": 20.0,
    "ETHUSDT": 20.0,
    "SOLUSDT": 20.0,
    "BNBUSDT": 20.0,
    "AVAXUSDT": 20.0,
    "LINKUSDT": 20.0,
    "SUIUSDT": 20.0,
    "XRPUSDT": 20.0,
    "NEARUSDT": 20.0,
    "INJUSDT": 20.0,
    "FETUSDT": 20.0,
    "DOGEUSDT": 20.0,
    "DOTUSDT": 20.0,
    "UNIUSDT": 20.0,
    "APTUSDT": 20.0,
    "OPUSDT": 20.0,
    "ARBUSDT": 20.0,
    "LDOUSDT": 20.0,
    "STXUSDT": 20.0,
    "ADAUSDT": 20.0,
}
# ── ADX > 35 TP Daraltma Kuralı ──────────────────────────
# Yüksek ADX'te fiyat hedefe ulaşamadan geri dönüyor.
# TP mesafesini %70'e çekerek daha hızlı realize et.
ADX_HIGH_TP_THRESHOLD = 35.0
ADX_HIGH_TP_MULTIPLIER = 0.7
DI_MARGIN = 0.0  # (Önceden 2.0 veya 1.0 ise 0 yapıyoruz. Sadece +DI>-DI olması yetsin,fark armasın)
EMA_PERIOD = 200

# ── H4 Market Structure (Swing Break Trend — EMA'nın yerine) ──
# H4 grafiğinde onaylı fraktal (sağ/sol mum) swing noktalarının kırılımıyla
# trend yönünü belirler. "Ana Şalter" — haftalarca aynı yönde kalır.
H4_SWING_LEFT = 2          # Swing onayı için sol mum sayısı
H4_SWING_RIGHT = 2         # Swing onayı için sağ mum sayısı
H4_SWING_LOOKBACK = 120    # H4 swing arama penceresi (bar sayısı)

# ── FVG Kalite Skoru (FIX-B için gerekli sabitler) ──────
# FVG eşikleri — TEMP BYPASS (normali 0.40 / 0.35)
FVG_SCORE_THRESHOLD = 0.40
FVG_SCORE_THRESHOLD_IMPULSIVE = 0.35
FVG_IMPULSIVE_ADX_THRESHOLD = 25.0
FVG_IMPULSIVE_DISPLACEMENT_MIN: float = 0.45

# ── Minimum FVG Boyutu ───────────────────────────────────
# FVG gap (top - bottom) bu değerden küçükse sinyal reddedilir.
# Çok küçük FVG'ler gürültü / spread içi boşluk kabul edilir.
MIN_FVG_SIZE = 0.0001

# ── Breakeven Logging (ADX > 35 korelasyon izleme) ───────
# True → Breakeven sinyalleri detaylı loglanır + ADX>35 ile korelasyon canlı izlenir.
BREAKEVEN_LOG_ENABLED = True

# ── Relax Filtresi (opsiyonel, daha sonra kullanılacak) ──
FVG_RELAX_THRESHOLD = 0.25
FVG_RELAX_THRESHOLD_IMPULSIVE = 0.20
FVG_RELAX_AFTER_BARS = 5  # 48 den 10 a çektik

# ── Trailing Stop ────────────────────────────────────────
TRAILING_STEP_RATIO = 0.25
TRAILING_TRIGGER_RR = 1.1

# 🔴 FIX #3: Sembol bazında minimum SL güncelleme mesafesi (USDT)
# Fark bu değerden küçükse SL güncellenmez, ping-pong engellenir.
MIN_TRAILING_STEP_MAP = {
    # Yüksek Fiyatlılar
    "BTCUSDT": 5.0,  # 5$ altındaki mikro değişimleri atla
    "ETHUSDT": 2.0,  # 2$ altındaki mikro değişimleri atla
    "BNBUSDT": 1.0,  # 1$ altındaki mikro değişimleri atla
    # Orta Fiyatlılar (10$ - 200$)
    "SOLUSDT": 0.5,
    "INJUSDT": 0.08,
    "LINKUSDT": 0.05,
    "AVAXUSDT": 0.1,
    "DOTUSDT": 0.02,
    "UNIUSDT": 0.03,
    "APTUSDT": 0.03,
    # Düşük Fiyatlılar (1$ - 10$)
    "SUIUSDT": 0.01,
    "NEARUSDT": 0.02,
    "FETUSDT": 0.01,
    "STXUSDT": 0.01,
    "OPUSDT": 0.01,
    "ARBUSDT": 0.005,
    "LDOUSDT": 0.005,
    # Mikro Fiyatlılar (< 1$)
    "XRPUSDT": 0.002,
    "DOGEUSDT": 0.001,
    "ADAUSDT": 0.002,
}
MIN_TRAILING_STEP_DEFAULT = 0.02  # Listede olmayan semboller için varsayılan

# ── Minimum beklenen kâr ─────────────────────────────────
MIN_EXPECTED_PROFIT = 0.8
MIN_EXPECTED_PROFIT_MAP = {
    "BTCUSDT": 4.0,
    "ETHUSDT": 2.5,
    "SOLUSDT": 1.5,
    "BNBUSDT": 1.0,
    "AVAXUSDT": 0.3,
    "LINKUSDT": 0.2,
    "SUIUSDT": 0.05,
    "XRPUSDT": 0.15,
    "NEARUSDT": 0.15,
    "INJUSDT": 0.4,
    "FETUSDT": 0.08,
    "DOGEUSDT": 0.01,
    "DOTUSDT": 0.15,
    "UNIUSDT": 0.15,
    "APTUSDT": 0.15,
    "OPUSDT": 0.10,
    "ARBUSDT": 0.10,
    "LDOUSDT": 0.08,
    "STXUSDT": 0.08,
    "ADAUSDT": 0.08,
}

# ── Sembol bazlı min_rr ──────────────────────────────────
MIN_RR_MAP = {
    "BTCUSDT": 1.8,
    "ETHUSDT": 1.5,
    "SOLUSDT": 1.4,
    "BNBUSDT": 1.5,
    "AVAXUSDT": 1.3,
    "LINKUSDT": 1.4,
    "SUIUSDT": 1.3,
    "XRPUSDT": 1.4,
    "NEARUSDT": 1.4,
    "INJUSDT": 1.4,
    "FETUSDT": 1.3,
    "DOGEUSDT": 1.3,
    "DOTUSDT": 1.4,
    "MATICUSDT": 1.4,
    "UNIUSDT": 1.4,
    "APTUSDT": 1.4,
    "OPUSDT": 1.3,
    "ARBUSDT": 1.3,
    "LDOUSDT": 1.4,
    "RNDRUSDT": 1.3,
    "STXUSDT": 1.3,
    "PEPEUSDT": 1.3,
    "ADAUSDT": 1.4,
}
# ── Sembol bazlı risk oranı ──────────────────────────────
RISK_PER_TRADE_MAP = {
    "BTCUSDT": 0.02,
    "ETHUSDT": 0.03,
    "SOLUSDT": 0.03,
    "BNBUSDT": 0.025,
    "AVAXUSDT": 0.025,
    "LINKUSDT": 0.025,
    "SUIUSDT": 0.015,
    "XRPUSDT": 0.02,
    "NEARUSDT": 0.02,
    "INJUSDT": 0.015,
    "FETUSDT": 0.015,
    "DOGEUSDT": 0.02,
    "DOTUSDT": 0.02,
    "MATICUSDT": 0.02,
    "UNIUSDT": 0.02,
    "APTUSDT": 0.02,
    "OPUSDT": 0.015,
    "ARBUSDT": 0.015,
    "LDOUSDT": 0.02,
    "RNDRUSDT": 0.02,
    "STXUSDT": 0.02,
    "PEPEUSDT": 0.01,
    "ADAUSDT": 0.02,
}

# ── Semboller ────────────────────────────────────────────
SYMBOLS = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "SUIUSDT",
    "XRPUSDT",
    "NEARUSDT",
    "INJUSDT",
    "FETUSDT",
    "DOGEUSDT",
    "DOTUSDT",
    "UNIUSDT",
    "APTUSDT",
    "OPUSDT",
    "ARBUSDT",
    "LDOUSDT",
    "STXUSDT",
    "ADAUSDT",
]

# ── Veri klasörü ─────────────────────────────────────────
DATA_DIR = "data"
OUTPUT_DIR = "output"

# ── Bar sayıları ─────────────────────────────────────────
D1_BARS = 150
H1_BARS = 200
M15_BARS = 500
FVG_IMPULSIVE_LOW_DISP_CAP = 0.45  # impulsive modda düşük displacement skor tavanı
M5_BARS = 500

# ── FVG Maksimum Yaş (Bar) ──────────────────────────────
# 15m × 32 = 8 saat (CHOCH_MAX_AGE_HOURS ile tutarlı)
FVG_MAX_AGE_BARS = 32

# ── Warm-up ──────────────────────────────────────────────
WARMUP_D1_BARS = 110

# ── Log seviyesi ─────────────────────────────────────────
LOG_LEVEL = "INFO"

