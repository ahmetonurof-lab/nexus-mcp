# config.py — NEXUS V3 (Production-Ready)

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
MIN_RR = 2.0          # 1.5'ten güncellendi — 4H SL ile R:R korunması için
MIN_NET_RR = 1.5      # 1.2'den güncellendi
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
CHOCH_BREAK_WINDOW = 15

# ── CHoCH Maksimum Yaş (Saat) ──────────────────────────
# detect_chochs() içinde lookback hesaplaması için kullanılır.
# 15m → 8*60/15 = 32 bar, 5m → 8*60/5 = 96 bar
CHOCH_MAX_AGE_HOURS = 8

# ── ADX / DI Filtresi ────────────────────────────────────────
# NOT: 1D bias artık ADX ile değil BOS yönüyle belirleniyor.
# D1_ADX_THRESHOLD sadece ek filtre olarak bırakıldı, ana bias kaynağı DEĞİL.
D1_ADX_THRESHOLD = 20
ADX_THRESHOLD = 20.0
ADX_THRESHOLD_DEFAULT = 20.0
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
ADX_HIGH_TP_THRESHOLD = 35.0
DI_MARGIN = 0.0
EMA_PERIOD = 200

# ── H4 Market Structure ──────────────────────────────────
H4_SWING_LEFT = 2
H4_SWING_RIGHT = 2
H4_SWING_LOOKBACK = 120

# ── HTF Bias (1D BOS yönü) ───────────────────────────────
# 1D bias artık ADX değil BOS kırılımıyla belirlenir.
# H4 teyit ederse güçlü sinyal, etmezse bias düşük güvenilirlik.
#
# D1_BOS_LOOKBACK: 1D'de kaç bar geriye bakılır (≈1 ay)
# H4_BOS_LOOKBACK: 4H'da kaç bar geriye bakılır (≈8-10 gün)
# HTF_BIAS_SFP_N:  HTF BOS onayı için kaç bar follow-through (1D'de 3 gün fazla)
D1_BOS_LOOKBACK = 25
H4_BOS_LOOKBACK = 50
HTF_BIAS_SFP_N = 1

# ── FVG Kalite Skoru ─────────────────────────────────────
FVG_SCORE_THRESHOLD = 0.40
FVG_SCORE_THRESHOLD_IMPULSIVE = 0.35
FVG_IMPULSIVE_ADX_THRESHOLD = 25.0
FVG_IMPULSIVE_DISPLACEMENT_MIN: float = 0.45

# ── Minimum FVG Boyutu ───────────────────────────────────
MIN_FVG_SIZE = 0.0001

# ── Breakeven Logging ────────────────────────────────────
BREAKEVEN_LOG_ENABLED = True

# ── Kademeli Stop ────────────────────────────────────────
# Kademe 1: Fiyat 1R gittiğinde SL = entry (breakeven)
# Kademe 2: Fiyat 2R gittiğinde SL = 1R (kârı kilitle)
BREAKEVEN_R = 1.0
TRAILING_ACTIVATE_R = 2.0
TRAILING_STEP_RATIO = 0.25

# ── Relax Filtresi ───────────────────────────────────────
FVG_RELAX_THRESHOLD = 0.25
FVG_RELAX_THRESHOLD_IMPULSIVE = 0.20
FVG_RELAX_AFTER_BARS = 5

# ── Sembol bazlı min_rr ──────────────────────────────────
MIN_RR_MAP = {
    "BTCUSDT": 2.0,
    "ETHUSDT": 2.0,
    "SOLUSDT": 2.0,
    "BNBUSDT": 2.0,
    "AVAXUSDT": 2.0,
    "LINKUSDT": 2.0,
    "SUIUSDT": 2.0,
    "XRPUSDT": 2.0,
    "NEARUSDT": 2.0,
    "INJUSDT": 2.0,
    "FETUSDT": 2.0,
    "DOGEUSDT": 2.0,
    "DOTUSDT": 2.0,
    "MATICUSDT": 2.0,
    "UNIUSDT": 2.0,
    "APTUSDT": 2.0,
    "OPUSDT": 2.0,
    "ARBUSDT": 2.0,
    "LDOUSDT": 2.0,
    "RNDRUSDT": 2.0,
    "STXUSDT": 2.0,
    "PEPEUSDT": 2.0,
    "ADAUSDT": 2.0,
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
H4_BARS = 300          # YENİ — H4 bias tespiti için
H1_BARS = 200
M15_BARS = 500
M5_BARS = 500
FVG_IMPULSIVE_LOW_DISP_CAP = 0.45

# ── FVG Maksimum Yaş (Bar) ──────────────────────────────
# 15m × 32 = 8 saat (CHOCH_MAX_AGE_HOURS ile tutarlı)
FVG_MAX_AGE_BARS = 32

# ── Warm-up ──────────────────────────────────────────────
WARMUP_D1_BARS = 110

# ── Log seviyesi ─────────────────────────────────────────
LOG_LEVEL = "INFO"