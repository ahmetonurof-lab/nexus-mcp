# config.py â€” NEXUS V3 (Production-Ready)

from datetime import datetime

IS_TESTNET = True

# â”€â”€ Backtest zaman aralÄ±ÄŸÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BACKTEST_START = datetime(2025, 1, 1)
BACKTEST_END = datetime(2025, 8, 31)

# â”€â”€ BaÅŸlangÄ±Ã§ bakiyesi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
INITIAL_BALANCE = 10000.0
LEVERAGE = 10

# â”€â”€ Risk parametreleri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
RISK_PER_TRADE = 0.005
MIN_RR = 0.0  # 2.0 â†’ 0.0 (filtre kapalÄ±, tÃ¼m R:R oranlarÄ±na izin ver)
MIN_NET_RR = 1.5  # 1.2'den gÃ¼ncellendi
DEFAULT_RR = 2.0
TAKER_FEE = 0.0004
SPREAD_PCT = 0.0001

# â”€â”€ Slippage Modeli â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SLIPPAGE_ENTRY = 0.0002
SLIPPAGE_EXIT = 0.0002
SLIPPAGE_TOTAL = SLIPPAGE_ENTRY + SLIPPAGE_EXIT

# â”€â”€ Momentum Filtresi (CHoCH kalite) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
CHoCH_MIN_BODY_RATIO = 1.0
CHoCH_ATR_OVERSHOOT = 0.2
CHoCH_ATR_PERIOD = 14
CHoCH_PIVOT_ADX_THRESHOLD = 35.0
CHOCH_BREAK_WINDOW = 15

MAX_SETUP_WAIT_HOURS: float = 8.0

# â”€â”€ CHoCH Maksimum YaÅŸ (Saat) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# detect_chochs() iÃ§inde lookback hesaplamasÄ± iÃ§in kullanÄ±lÄ±r.
# 15m â†’ 8*60/15 = 32 bar, 5m â†’ 8*60/5 = 96 bar
CHOCH_MAX_AGE_HOURS = 8

# â”€â”€ ADX / DI Filtresi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# NOT: 1D bias artÄ±k ADX ile deÄŸil BOS yÃ¶nÃ¼yle belirleniyor.
# D1_ADX_THRESHOLD sadece ek filtre olarak bÄ±rakÄ±ldÄ±, ana bias kaynaÄŸÄ± DEÄžÄ°L.
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

# â”€â”€ ADX > 35 TP Daraltma KuralÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ADX_HIGH_TP_THRESHOLD = 35.0
DI_MARGIN = 0.0
EMA_PERIOD = 200

# â”€â”€ H4 Market Structure â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
H4_SWING_LEFT = 2
H4_SWING_RIGHT = 2
H4_SWING_LOOKBACK = 120

# â”€â”€ HTF Bias (1D BOS yÃ¶nÃ¼) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 1D bias artÄ±k ADX deÄŸil BOS kÄ±rÄ±lÄ±mÄ±yla belirlenir.
# H4 teyit ederse gÃ¼Ã§lÃ¼ sinyal, etmezse bias dÃ¼ÅŸÃ¼k gÃ¼venilirlik.
#
# D1_BOS_LOOKBACK: 1D'de kaÃ§ bar geriye bakÄ±lÄ±r (â‰ˆ1 ay)
# H4_BOS_LOOKBACK: 4H'da kaÃ§ bar geriye bakÄ±lÄ±r (â‰ˆ8-10 gÃ¼n)
# HTF_BIAS_SFP_N:  HTF BOS onayÄ± iÃ§in kaÃ§ bar follow-through (1D'de 3 gÃ¼n fazla)
D1_BOS_LOOKBACK = 25
H4_BOS_LOOKBACK = 50
HTF_BIAS_SFP_N = 1
HTF_STRICT_FILTER: bool = False  # H4 D1'e tersse iÅŸlem alma

# â”€â”€ FVG Kalite Skoru â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FVG_SCORE_THRESHOLD = 0.40
FVG_SCORE_THRESHOLD_IMPULSIVE = 0.35
FVG_IMPULSIVE_ADX_THRESHOLD = 25.0
FVG_IMPULSIVE_DISPLACEMENT_MIN: float = 0.45

# â”€â”€ Minimum FVG Boyutu â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MIN_FVG_SIZE = 0.0001

# â”€â”€ Missed FVG Parametreleri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MISSED_FVG_ATR_MULT: float = 0.75
POI_ATR_BUFFER: float = 0.3  # poi_anchor etrafÄ±ndaki kabul tamponu

# â”€â”€ FVG Penetration Trade Zone â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FVG_PENETRATION_MIN: float = 0.15  # Minimum penetration oranÄ± (trade zone alt sÄ±nÄ±r)
FVG_PENETRATION_MID: float = 0.30  # Mid-band lower bound for adaptive READY_TO_ENTER
FVG_PENETRATION_MAX: float = 0.70  # Maksimum penetration oranÄ± (trade zone Ã¼st sÄ±nÄ±r)

# â”€â”€ Adaptive LTF Gating â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
ADAPTIVE_LTF_ENABLE: bool = True

# â”€â”€ WAIT_CONFIRM time-box + partial sizing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
WAIT_CONFIRM_TIMEBOX_MIN: int = 3  # dakika; partial entry'e LTF'siz izin ver
PARTIAL_RISK_SCALE: float = 0.40  # normal risk/lot'un %40'Ä±

# â”€â”€ Entry order type variant (slippage reduction) â”€â”€â”€â”€â”€â”€â”€â”€
ENTRY_ORDER_TYPE: str = "MARKET"  # "MARKET" veya "STOP_MARKET"
ENTRY_STOP_OFFSET_PCT: float = 0.0005  # 5 bps trigger cushion

# â”€â”€ Breakeven Logging â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BREAKEVEN_LOG_ENABLED = True

# â”€â”€ Kademeli Stop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Kademe 1: Fiyat 1R gittiÄŸinde SL = entry (breakeven)
# Kademe 2: Fiyat 2R gittiÄŸinde SL = 1R (kÃ¢rÄ± kilitle)
BREAKEVEN_R = 1.0
TRAILING_ACTIVATE_R = 2.0
TRAILING_STEP_RATIO = 0.25

# â”€â”€ Relax Filtresi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
FVG_RELAX_THRESHOLD = 0.25
FVG_RELAX_THRESHOLD_IMPULSIVE = 0.20
FVG_RELAX_AFTER_BARS = 5

# â”€â”€ Sembol bazlÄ± min_rr â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

# â”€â”€ Sembol bazlÄ± risk oranÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

# â”€â”€ Semboller â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

# â”€â”€ Veri klasÃ¶rÃ¼ â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
DATA_DIR = "data"
OUTPUT_DIR = "output"

# â”€â”€ Timeframe tanÄ±mlarÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
LTF_TF = "1m"

# â”€â”€ Bar sayÄ±larÄ± â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
D1_BARS = 150
H4_BARS = 300  # YENÄ° â€” H4 bias tespiti iÃ§in
H1_BARS = 200
M15_BARS = 500
M1_BARS = 500
FVG_IMPULSIVE_LOW_DISP_CAP = 0.45

# â”€â”€ FVG Maksimum YaÅŸ (Bar) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# 15m Ã— 32 = 8 saat (CHOCH_MAX_AGE_HOURS ile tutarlÄ±)
FVG_MAX_AGE_BARS = 32

# â”€â”€ Sweep Filtreleri â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SWEEP_SWING_STRENGTH = 2  # left=2, right=2 â†’ 5 mum pivot
SWEEP_PENETRATION_ATR = 0.10  # min penetration ATRÃ—0.10
SWEEP_PIVOT_QUALITY_ATR = 0.20  # pivot kalite filtresi ATRÃ—0.20

# â”€â”€ Warm-up â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
WARMUP_D1_BARS = 110

# â”€â”€ Log seviyesi â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
LOG_LEVEL = "INFO"

# â”€â”€ Kill Zone (veri toplama modu, zincir kÄ±rmaz) â”€â”€â”€â”€â”€â”€â”€â”€â”€
KILL_ZONES_ENABLED: bool = False
KILL_ZONES_LOG_ONLY: bool = True
LONDON_KILL_ZONE_START: int = 7
LONDON_KILL_ZONE_END: int = 9
NY_KILL_ZONE_START: int = 12
NY_KILL_ZONE_END: int = 14
ASYA_TOKYO_KILL_ZONE_START: int = 0
ASYA_TOKYO_KILL_ZONE_END: int = 2

# — FVG validation & clustering (1H main)
FVG_OVERLAP_MIN: float = 0.60   # 1H↔2H overlap threshold for validation
FVG_CLUSTER_ATR_MULT: float = 0.40  # merge 1H gaps if distance ≤ ATR×k
# — Ranking (aux) weights (standalone; no decision impact)
RANK_W1: float = 0.01   # validated weight
RANK_W2: float = 0.50   # distance-to-HTF-liquidity weight
RANK_W3: float = 0.49   # cluster weight (see scoring)
RANK_DIST_K: float = 1.2   # ATR multiplier for distance normalization
RANK_SPAN_K: float = 1.0   # ATR multiplier for size/cluster proxy
