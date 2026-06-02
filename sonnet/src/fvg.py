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
from typing import Final, Literal

from models import FVG, Bar

logger = logging.getLogger("nexus.fvg")

# ──────────────────────────────────────────────────────────
# SABİTLER & YAPILANDIRMA
# ──────────────────────────────────────────────────────────
DEFAULT_LOOKBACK: Final[int] = 100
MAX_FVG_AGE_BARS: Final[int] = 500
MIN_FVG_SIZE: Final[float] = 0.0
ATR_PERIOD: Final[int] = 14
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

def create_fvg_event(fvg_obj, timeframe: str) -> dict:
    """Converts a structural FVG object into a normalized V3 market event."""
    return {
        "type": "FVG_CREATED",
        "tf": timeframe,
        "upper": float(fvg_obj.upper),
        "lower": float(fvg_obj.lower),
        "time": int(fvg_obj.timestamp),
    }

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


