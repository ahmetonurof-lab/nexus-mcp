"""
fvg.py
──────
Nexus SMC Trading Bot — Fair Value Gap (FVG) Motoru
Katmanlar: Core Engine (Tespit/State/Retest) + Quality Overlay (Skorlama/Veto)
Bağımlılıklar: models, indicators, volume_profile (opsiyonel)
KRİTİK KURAL: FVG dataclass'ında timestamp yoktur. real_index mutlak bar indeksidir.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final, Literal

from indicators import clamp
from models import FVG, Bar

if TYPE_CHECKING:
    from volume_profile import VPLevels

logger = logging.getLogger("nexus.fvg")

# ──────────────────────────────────────────────────────────
# SABİTLER & YAPILANDIRMA
# ──────────────────────────────────────────────────────────
DEFAULT_LOOKBACK: Final[int] = 100
MAX_FVG_AGE_BARS: Final[int] = 500
MIN_FVG_SIZE: Final[float] = 0.0
ATR_PERIOD: Final[int] = 14
IMPULSIVE_ADX_THRESHOLD: Final[float] = 20.0

# Sembol bazlı periyodik cleanup sayacı
_SYMBOL_COUNTERS: dict[str, int] = {}


# ──────────────────────────────────────────────────────────
# 1. CORE ENGINE (Tespit → State → Retest → Pipeline)
# ──────────────────────────────────────────────────────────
def detect_fvgs(
    bars: list[Bar],
    lookback: int = DEFAULT_LOOKBACK,
    timeframe: str = "5m",
    min_fvg_size: float = MIN_FVG_SIZE,
) -> list[FVG]:
    """
    Rolling buffer'daki son `lookback` bar'ı tarayarak FVG listesi üretir.
    - Dilim göreceli indeks yerine Bar.index (mutlak) saklanır.
    - Kapanmamış son mum FVG tespitine girmez.
    - Inside-bar eşit high/low dahil yakalanır.
    """
    segment = bars[-lookback:] if len(bars) > lookback else bars
    fvgs: list[FVG] = []

    for i in range(1, len(segment) - 1):
        b_prev = segment[i - 1]
        b_curr = segment[i]       # mother bar
        b_next = segment[i + 1]

        if not b_next.is_closed:
            continue

        # Inside bar filtresi (eşit seviyeler dahil)
        if b_next.high <= b_curr.high and b_next.low >= b_curr.low:
            continue

        gap_bull = b_next.low - b_prev.high
        gap_bear = b_prev.low - b_next.high

        if gap_bull > 0:
            fvg = FVG(
                direction="bullish",
                top=b_next.low,
                bottom=b_prev.high,
                real_index=b_curr.index,
                timeframe=timeframe,
            )
            if fvg.size >= min_fvg_size:
                fvgs.append(fvg)
            else:
                logger.debug("[FVG-SIZE] bullish size=%.6f < min=%.6f → atlanıyor.", fvg.size, min_fvg_size)

        elif gap_bear > 0:
            fvg = FVG(
                direction="bearish",
                top=b_prev.low,
                bottom=b_next.high,
                real_index=b_curr.index,
                timeframe=timeframe,
            )
            if fvg.size >= min_fvg_size:
                fvgs.append(fvg)
            else:
                logger.debug("[FVG-SIZE] bearish size=%.6f < min=%.6f → atlanıyor.", fvg.size, min_fvg_size)

    return fvgs


def update_fvg_states(
    fvgs: list[FVG],
    bars: list[Bar],
) -> None:
    """
    Mevcut bar listesine göre her FVG'nin filled / invalidated durumunu günceller.
    SMC Kuralı: Wick geçişi allow edilir, gövde kapanışı (close) invalidasyon sayılır.
    """
    if not bars:
        return

    first_abs = bars[0].index
    last_abs  = bars[-1].index

    for fvg in fvgs:
        if fvg.invalidated or fvg.real_index < first_abs:
            continue

        scan_from_abs = max(getattr(fvg, "_next_check_abs", fvg.real_index + 2), fvg.real_index + 2)

        for abs_i in range(scan_from_abs, last_abs + 1):
            list_pos = abs_i - first_abs
            if not (0 <= list_pos < len(bars)):
                continue
            b = bars[list_pos]
            if not b.is_closed:
                break

            if fvg.direction == "bullish":
                # SMC: Close < bottom → invalid
                if b.close < fvg.bottom:
                    object.__setattr__(fvg, "invalidated", True)
                    object.__setattr__(fvg, "filled", False)
                    logger.debug("[FVG-STATE] bullish invalidated (close=%.5f < bottom=%.5f)", b.close, fvg.bottom)
                    break
                elif fvg.bottom <= b.close <= fvg.top:
                    object.__setattr__(fvg, "filled", True)
                else:
                    object.__setattr__(fvg, "filled", False)

            else:  # bearish
                # SMC: Close > top → invalid
                if b.close > fvg.top:
                    object.__setattr__(fvg, "invalidated", True)
                    object.__setattr__(fvg, "filled", False)
                    logger.debug("[FVG-STATE] bearish invalidated (close=%.5f > top=%.5f)", b.close, fvg.top)
                    break
                elif fvg.bottom <= b.close <= fvg.top:
                    object.__setattr__(fvg, "filled", True)
                else:
                    object.__setattr__(fvg, "filled", False)

        if not fvg.invalidated:
            object.__setattr__(fvg, "_next_check_abs", last_abs)


def find_latest_unfilled_fvg(
    fvgs: list[FVG],
    direction: Literal["bullish", "bearish"],
    min_fvg_size: float = MIN_FVG_SIZE,
) -> FVG | None:
    """Belirtilen yönde, en güncel geçerli (unfilled + not invalidated) FVG'yi döner."""
    matches = [
        f for f in fvgs
        if f.direction == direction
        and not f.filled
        and not f.invalidated
        and f.size >= min_fvg_size
    ]
    logger.debug(
        "[FVG-DEBUG] dir=%s total=%d filled=%d invalidated=%d size_fail=%d active=%d",
        direction,
        len([f for f in fvgs if f.direction == direction]),
        sum(1 for f in fvgs if f.direction == direction and f.filled),
        sum(1 for f in fvgs if f.direction == direction and f.invalidated),
        sum(
            1
            for f in fvgs
            if f.direction == direction
            and not f.filled
            and not f.invalidated
            and f.size < min_fvg_size
        ),
        len(matches),
    )
    if not matches:
        return None
    return max(matches, key=lambda f: f.real_index)


def is_retesting_fvg(
    fvg: FVG | None,
    current_bar: Bar,
    atr: float,
    atr_buffer_factor: float = 0.10,
) -> bool:
    """
    FVG retest kontrolü. ATR bazlı dinamik buffer kullanır.
    None guard + is_active kontrolü içerir.
    """
    if fvg is None or not fvg.is_active:
        return False

    body_high = max(current_bar.open, current_bar.close)
    body_low  = min(current_bar.open, current_bar.close)
    buffer    = max(atr * atr_buffer_factor, fvg.size * 0.10)

    if fvg.direction == "bullish":
        wick_touches = current_bar.low <= fvg.top + buffer and current_bar.low >= fvg.bottom - buffer
        body_safe    = body_low >= fvg.bottom - buffer
        return wick_touches and body_safe
    else:
        wick_touches = current_bar.high >= fvg.bottom - buffer and current_bar.high <= fvg.top + buffer
        body_safe    = body_high <= fvg.top + buffer
        return wick_touches and body_safe


def cleanup_fvgs(
    fvgs: list[FVG],
    current_abs: int,
    max_age: int = MAX_FVG_AGE_BARS,
) -> list[FVG]:
    """Eski / iptal edilmiş / tamamen mitigation edilmiş FVG'leri listeden çıkarır."""
    before = len(fvgs)
    kept = [
        f for f in fvgs
        if not f.invalidated
        and not (f.filled and (current_abs - f.real_index) > max_age)
        and not (not f.filled and (current_abs - f.real_index) > max_age * 2)
    ]
    if before != len(kept):
        logger.info("[FVG-CLEANUP] %d FVG temizlendi (%d → %d).", before - len(kept), before, len(kept))
    return kept


def refresh_fvg_list(
    fvgs: list[FVG],
    bars: list[Bar],
    lookback: int = DEFAULT_LOOKBACK,
    min_fvg_size: float = MIN_FVG_SIZE,
    max_age: int = MAX_FVG_AGE_BARS,
    timeframe: str = "5m",
    cleanup_every: int = 50,
    symbol: str = "default",
) -> list[FVG]:
    """Tek entry-point: tespit → mükerrer önleme → state güncelleme → periyodik temizlik."""
    _SYMBOL_COUNTERS[symbol] = _SYMBOL_COUNTERS.get(symbol, 0) + 1
    call_n = _SYMBOL_COUNTERS[symbol]

    existing_indices = {f.real_index for f in fvgs}
    new_fvgs = [
        f for f in detect_fvgs(bars, lookback=lookback, timeframe=timeframe, min_fvg_size=min_fvg_size)
        if f.real_index not in existing_indices
    ]
    fvgs.extend(new_fvgs)
    update_fvg_states(fvgs, bars)

    if call_n % cleanup_every == 0 and bars:
        fvgs = cleanup_fvgs(fvgs, current_abs=bars[-1].index, max_age=max_age)

    return fvgs


# ──────────────────────────────────────────────────────────
# 2. QUALITY OVERLAY (Skorlama & Veto Katmanı)
# ──────────────────────────────────────────────────────────
def score_displacement(fvg_bar: Bar, atr: float, fvg_direction: str = "") -> float:
    """Momentum / gövde büyüklüğü alt skoru (0-1). Yön uyuşmazsa VETO."""
    if atr <= 0:
        return 0.0
    body = fvg_bar.body
    direction_val = fvg_bar.close - fvg_bar.open

    if fvg_direction == "bullish" and direction_val <= 0:
        return 0.0
    if fvg_direction == "bearish" and direction_val >= 0:
        return 0.0

    return clamp(body / (atr * 0.75), 0.0, 2.0) / 2.0


def score_fvg_size(fvg: FVG, atr: float) -> float:
    """FVG boşluk büyüklüğü alt skoru (0-1)."""
    if atr <= 0:
        return 0.0
    size = fvg.top - fvg.bottom
    return clamp(size / (atr * 1.5), 0.0, 1.0)


def score_sweep(
    bars: list[Bar],
    fvg: FVG,
    lookback: int = 5,
) -> float:
    """
    Likidite avı (sweep) alt skoru (0-1).
    FVG'yi oluşturan yapının (Bar 1 veya Mother Bar)
    swing'i temizlemesine bakılır.
    """
    logger.debug(
        "score_sweep entered | fvg_dir=%s | fvg_top=%.4f",
        fvg.direction, fvg.top
    )
    bar_idx = fvg.real_index

    # 1. Referans Bölgesi: FVG formasyonu başlamadan önceki eski likidite havuzu (Swing)
    start_idx = max(0, bar_idx - lookback - 1)
    ref_end_idx = max(0, bar_idx - 1) # Mother bar'dan önceki mum (Bar 1) hariç

    ref_bars = bars[start_idx : ref_end_idx]

    # 2. Aday Mumlar: Likiditeyi avlaması beklenen mumlar (Bar 1 ve Mother Bar)
    sweep_candidates = bars[ref_end_idx : bar_idx + 1]

    if not ref_bars or not sweep_candidates:
        return 0.0

    if fvg.direction == "bullish":
        # Eski yapının en düşük seviyesi (Likidite çizgisi)
        swing_low = min(b.low for b in ref_bars)

        # Adaylardan herhangi biri bu çizgiyi aşağı doğru kırdı mı?
        sweeping_bars = [b for b in sweep_candidates if b.low < swing_low]

        if sweeping_bars:
            # En derine inen mumu asıl avcı (turtle soup) kabul et
            deepest_bar = min(sweeping_bars, key=lambda b: b.low)
            # Fiyatı temizleyip swing_low'un üzerinde kapatabildiyse tam puan (1.0), altında kapattıysa yarım puan (0.5)
            return 1.0 if deepest_bar.close > swing_low else 0.5

    else:
        # Eski yapının en yüksek seviyesi (Likidite çizgisi)
        swing_high = max(b.high for b in ref_bars)

        # Adaylardan herhangi biri bu çizgiyi yukarı doğru kırdı mı?
        sweeping_bars = [b for b in sweep_candidates if b.high > swing_high]

        if sweeping_bars:
            highest_bar = max(sweeping_bars, key=lambda b: b.high)
            return 1.0 if highest_bar.close < swing_high else 0.5

    return 0.0


def score_retest(bars_since_fvg: int) -> float:
    """Zamanında retest alt skoru (0-1)."""
    if bars_since_fvg <= 2:
        return 0.3
    if bars_since_fvg <= 6:
        return 1.0
    if bars_since_fvg <= 12:
        return 0.6
    return 0.2


def is_premium_discount_valid(
    bars: list[Bar], current_price: float, fvg_direction: str, lookback: int = 50
) -> bool:
    """
    ICT Premium/Discount Vetosu (Fibonacci %50).
    - Short (bearish): Fiyat %50 üstünde (Premium) olmalı.
    - Long  (bullish): Fiyat %50 altında (Discount) olmalı.
    """
    segment = bars[-lookback:] if len(bars) >= lookback else bars
    range_high = max(b.high for b in segment)
    range_low  = min(b.low for b in segment)
    equilibrium = (range_high + range_low) / 2.0

    if fvg_direction == "bearish" and current_price < equilibrium:
        return False
    if fvg_direction == "bullish" and current_price > equilibrium:
        return False
    return True


def _get_vp_status(fvg: FVG, vp: VPLevels | None) -> str:
    """FVG alanının HVN/LVN ile kesişimini kontrol eder."""
    if vp is None or not getattr(vp, "poc", None):
        return "LVN"

    fvg_mid = (fvg.top + fvg.bottom) / 2.0
    prox_pct = 0.002

    if abs(fvg_mid - vp.poc) < (abs(vp.poc) * prox_pct):
        return "HVN"
    for level in getattr(vp, "hvn", []):
        if abs(fvg_mid - level) < (abs(level) * prox_pct):
            return "HVN"

    return "LVN"


def compute_fvg_quality(
    bars_tf: list[Bar],
    current_price: float,
    fvg: FVG,
    adx: float,
    d: float,  # displacement score
    f: float,  # fvg_size score
    s: float,  # sweep score
    r: float,  # retest score
    choch_score: float,
    choch_direction: str = "",
    vp: VPLevels | None = None,
) -> FVGQuality:
    """
    SMC/ICT Keskin Nişancı Skorlama ve Giyotin (Veto) Sistemi.
    Mod tespiti → Veto katmanı → Ağırlıklı skor → VP filtresi → Clamp.
    """
    logger.debug(
        "compute_fvg_quality entered | fvg_dir=%s | fvg_top=%.4f | fvg_bottom=%.4f",
        fvg.direction, fvg.top, fvg.bottom
    )
    mode = "impulsive" if adx >= IMPULSIVE_ADX_THRESHOLD else "reversal"

    # ── KATMAN 1: GIYOTIN (VETO) ──
    if choch_score > 0.0 and choch_direction and choch_direction != fvg.direction:
        logger.info("[VETO] CHoCH Yön Uyumsuzluğu → FVG: %s, CHoCH: %s", fvg.direction, choch_direction)
        return FVGQuality(displacement=d, fvg_size=f, sweep=s, retest=r, score=0.0)

    if mode == "reversal":
        # SWEEP VETOSU — TEMP BYPASS
        # if s < 0.01:
        #     logger.info("[VETO] Reversal modda SWEEP YOK → RED")
        #     return FVGQuality(displacement=d, fvg_size=f, sweep=s, retest=r, score=0.0)

        if not is_premium_discount_valid(bars_tf, current_price, fvg.direction, lookback=50):
            logger.info("[VETO] Premium/Discount İhlali → RED")
            return FVGQuality(displacement=d, fvg_size=f, sweep=s, retest=r, score=0.0)

    # ── KATMAN 2: AĞIRLIKLANDIRMA ──
    if mode == "reversal":
        base_score = (s * 0.25) + (choch_score * 0.25) + (d * 0.25) + (f * 0.15) + (r * 0.10)
    else:
        base_score = (d * 0.55) + (f * 0.25) + (choch_score * 0.10) + (r * 0.10)

    # ── KATMAN 3: VOLUME PROFILE (GARDIYAN) ──
    final_score = base_score
    vp_status = _get_vp_status(fvg, vp)
    if vp_status == "HVN":
        final_score -= 0.20
        logger.debug("[VP CEZA] HVN çarpımı → -0.20")

    final_score = clamp(final_score, 0.0, 1.0)

    return FVGQuality(
        displacement=round(d, 3),
        fvg_size=round(f, 3),
        sweep=round(s, 3),
        retest=round(r, 3),
        score=round(final_score, 3),
    )
# ──────────────────────────────────────────────────────────
# 3. YAPISAL SL & LTF TETİKLEYİCİ
# ──────────────────────────────────────────────────────────


def compute_structural_sl(fvg: FVG, direction: str) -> float:
    """
    FVG yapısına göre stop-loss seviyesini hesaplar.
    - Bullish: bottom'un bir miktar altı (likidite tuzağından korur)
    - Bearish: top'un bir miktar üstü
    """
    buffer = fvg.size * 0.1 if fvg.size > 0 else 0.0001
    if direction == "bullish":
        return fvg.bottom - buffer
    else:
        return fvg.top + buffer


def check_ltf_trigger(bars_5m: list[Bar], fvg: FVG, entry_zone: float) -> bool:
    """
    5m LTF (Lower Time Frame) tetikleyici.
    FVG bölgesinde momentum onayı arar:
    - Bullish: yeşil mum, close > entry_zone
    - Bearish: kırmızı mum, close < entry_zone
    """
    if not bars_5m or len(bars_5m) < 3:
        return False
    last = bars_5m[-1]
    if fvg.direction == "bullish":
        return last.close > entry_zone and last.close > last.open
    else:
        return last.close < entry_zone and last.close < last.open


# ──────────────────────────────────────────────────────────
# 4. GÜVENLİ BAR RESOLUTION YARDIMCISI
# ──────────────────────────────────────────────────────────


def resolve_fvg_bar(bars: list[Bar], fvg: FVG) -> Bar | None:
    """
    FVG'nin mother/impulse bar'ını real_index üzerinden güvenli çözümler.
    Döner: mother bar (listede yoksa bars[-2] fallback)
    """
    if not bars:
        return None
    first_abs = bars[0].index
    fvg_bar_pos = fvg.real_index - first_abs
    if 0 <= fvg_bar_pos < len(bars):
        return bars[fvg_bar_pos]
    return bars[-2] if len(bars) >= 2 else bars[-1]


