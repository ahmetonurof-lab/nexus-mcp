"""
choch.py
────────
Nexus SMC Trading Bot — Change of Character (CHoCH) Modülü (Final Merge)
File 1 SMC mikro-yapı filtreleri + File 2 pipeline/state yönetimi birleştirildi.
KRİTİK KURAL: `timestamp` SADECE `CHoCH` dataclass'ında set edilir.
"""
from __future__ import annotations

import logging
from typing import Final, Literal

import config
from indicators import clamp, compute_atr_series as _compute_atr_series
from models import (
    Bar,
    CHoCH,
    SwingPoint,
    tf_params,
)
from pivot import SwingStateManager

logger = logging.getLogger("nexus.choch")

# ──────────────────────────────────────────────────────────
# SABITLER & YAPILANDIRMA
# ──────────────────────────────────────────────────────────
# Artık kullanılmıyor — CHOCH_MAX_AGE_HOURS ile dinamik hesaplanıyor
DEFAULT_LOOKBACK: Final[int] = 100
MAX_CHOCH_AGE_BARS: Final[int] = 500
MIN_CHOCH_ATR_MULT: Final[float] = 0.15

# Sembol bazlı periyodik cleanup sayacı (thread-safe dict)
_SYMBOL_COUNTERS: dict[str, int] = {}


# ──────────────────────────────────────────────────────────
# 1. SMC MİKRO-YAPI YARDIMCILARI
# ──────────────────────────────────────────────────────────
def _is_convincing_break(
    break_bar: Bar,
    level: float,
    avg_body: float,
    atr_val: float,
    direction: Literal["bullish", "bearish"],
    bars_after: list[Bar],
    sfp_n: int,
) -> bool:
    """
    Kırılma kalitesi & SFP follow-through filtresi.
    avg_body/atr==0 fallback'leri içerir.
    """
    body_ok = atr_ok = False

    if avg_body > 0:
        body_ok = break_bar.body >= avg_body * config.CHoCH_MIN_BODY_RATIO
    else:
        bar_range = break_bar.high - break_bar.low
        body_ok = bar_range > 0 and break_bar.body >= bar_range * 0.3

    if atr_val > 0:
        atr_ok = abs(break_bar.close - level) >= atr_val * config.CHoCH_ATR_OVERSHOOT
    else:
        atr_ok = (direction == "bearish" and break_bar.close < level) or \
                 (direction == "bullish" and break_bar.close > level)

    if not (body_ok or atr_ok):
        return False

    # SFP Follow-through
    confirmations = 0
    for fb in bars_after[:sfp_n]:
        if not fb.is_closed:
            break
        if direction == "bearish" and fb.close < level:
            confirmations += 1
        elif direction == "bullish" and fb.close > level:
            confirmations += 1

    return confirmations >= sfp_n


def _resolve_outside_bar_priority(
    bar: Bar,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> Literal["bearish", "bullish", "both", "none"]:
    """
    Tek bar hem high hem low süpürüyorsa fitil uzunluğuna göre öncelik belirler.
    Eşitlikte SMC convention gereği bearish baskın kabul edilir.
    """
    breaks_high = any(bar.close > sp.price for sp in swing_highs)
    breaks_low  = any(bar.close < sp.price for sp in swing_lows)

    if breaks_high and breaks_low:
        uw, lw = bar.upper_wick, bar.lower_wick
        if lw > uw:
            return "bearish"
        elif uw > lw:
            return "bullish"
        return "bearish"
    if breaks_high:
        return "bullish"
    if breaks_low:
        return "bearish"
    return "none"


# ──────────────────────────────────────────────────────────
# 2. CHoCH TESPİTİ (Hybrid Pipeline)
# ──────────────────────────────────────────────────────────
def detect_chochs(
    bars: list[Bar],
    swing_mgr: SwingStateManager,
    lookback: int | None = None,  # None → config'den dinamik hesapla
    timeframe: str = "5m",
    atr_series: list[float] | None = None,
    atr_mult: float = MIN_CHOCH_ATR_MULT,
) -> list[CHoCH]:
    """
    O(N) tarama + ATR size filter + SMC mikro-yapı veto + pivot mitigation.
    """
    # ── Dinamik lookback: timeframe'e göre saat bazında hesapla ──
    if lookback is None:
        _tf_minutes = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
        tf_min = _tf_minutes.get(timeframe, 15)
        lookback = int(config.CHOCH_MAX_AGE_HOURS * 60 / tf_min)

    if len(bars) < lookback:
        segment = bars
    else:
        segment = bars[-lookback:]

    if atr_series is None:
        atr_series = _compute_atr_series(bars, period=config.CHoCH_ATR_PERIOD)

    break_window, body_lookback, sfp_n = tf_params(timeframe)
    active_high_map: dict[int, SwingPoint] = {p.bar_index: p for p in swing_mgr.active_highs()}
    active_low_map:  dict[int, SwingPoint] = {p.bar_index: p for p in swing_mgr.active_lows()}

    found: list[CHoCH] = []
    first_abs = bars[0].index

    for bar in segment:
        # KRİTİK 1: Kapanmamış mum kesinlikle atlanır
        if not bar.is_closed:
            continue

        bar_close = bar.close
        bar_abs   = bar.index
        bar_pos   = bar_abs - first_abs  # KRİTİK 2: Birebir indeks hizalaması
        atr_val   = atr_series[bar_pos] if 0 <= bar_pos < len(atr_series) else 0.0

        # ═══════════════════════════════════════════════════
        # ── BULLISH ADAY ──────────────────────────────────
        # ═══════════════════════════════════════════════════
        best_sp: SwingPoint | None = None
        mitigated: list[SwingPoint] = []
        for sp_abs, sp in active_high_map.items():
            if sp.bar_index >= bar_abs or sp.mitigated:
                continue
            if bar_close > sp.price:
                if best_sp is None or sp.price > best_sp.price:
                    best_sp = sp
                mitigated.append(sp)

        if best_sp is not None:
            penetration = bar_close - best_sp.price
            # 1. ATR/Kapanış büyüklük filtresi
            passes_size_filter = atr_val <= 0 or penetration >= atr_val * atr_mult

            # 2. SMC Veto Mantığı: Outside bar önceliği net değilse mikro-yapı onayı şarttır
            if passes_size_filter:
                prio = _resolve_outside_bar_priority(bar, [best_sp], [])
                if prio != "bullish":
                    body_start = max(0, bar_pos - body_lookback)
                    local_bodies = [
                        bars[x].body
                        for x in range(body_start, bar_pos)
                        if bars[x].is_closed
                    ]
                    local_avg_body = sum(local_bodies) / len(local_bodies) if local_bodies else 0.0
                    bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]

                    if not _is_convincing_break(
                        bar, best_sp.price, local_avg_body,
                        atr_val, "bullish", bars_after, sfp_n,
                    ):
                        passes_size_filter = False

            # ── Sinyal Üretimi ────────────────────────────
            if passes_size_filter:
                # Strength: penetration + SFP follow-through bileşik skoru
                pen_ratio = (
                    max(0.0, min(1.0, penetration / (atr_val * config.CHoCH_ATR_OVERSHOOT)))
                    if atr_val > 0 else 0.0
                )
                _bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]
                _confirmations = 0
                for fb in _bars_after[:sfp_n]:
                    if not fb.is_closed:
                        break
                    if fb.close > best_sp.price:
                        _confirmations += 1
                sfp_ratio = _confirmations / sfp_n if sfp_n and sfp_n > 0 else 0.0
                strength = round(max(0.0, min(1.0, pen_ratio * 0.6 + sfp_ratio * 0.4)), 3)

                found.append(CHoCH(
                    direction="bullish", level=best_sp.price, bar_index=bar_abs,
                    pivot_bar_index=best_sp.bar_index, timeframe=timeframe, timestamp=bar.timestamp,
                    strength=strength
                ))
                logger.info("[CHoCH] Bullish @ %d (level=%.5f)", bar_abs, best_sp.price)
            else:
                logger.debug("[CHoCH] Bullish veto @ %d", bar_abs)

            # KRİTİK 3: Kırılan TÜM pivot'lar mitigate edilir (yön/sonuç bağımsız)
            for sp_m in mitigated:
                object.__setattr__(sp_m, "mitigated", True)
                swing_mgr.mark_mitigated("high", sp_m.bar_index)

        # ═══════════════════════════════════════════════════
        # ── BEARISH ADAY ──────────────────────────────────
        # ═══════════════════════════════════════════════════
        best_sp = None
        mitigated = []
        for sp_abs, sp in active_low_map.items():
            if sp.bar_index >= bar_abs or sp.mitigated:
                continue
            if bar_close < sp.price:
                if best_sp is None or sp.price < best_sp.price:
                    best_sp = sp
                mitigated.append(sp)

        if best_sp is not None:
            penetration = best_sp.price - bar_close
            passes_size_filter = atr_val <= 0 or penetration >= atr_val * atr_mult

            if passes_size_filter:
                prio = _resolve_outside_bar_priority(bar, [], [best_sp])
                if prio != "bearish":
                    body_start = max(0, bar_pos - body_lookback)
                    local_bodies = [
                        bars[x].body
                        for x in range(body_start, bar_pos)
                        if bars[x].is_closed
                    ]
                    local_avg_body = sum(local_bodies) / len(local_bodies) if local_bodies else 0.0
                    bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]

                    if not _is_convincing_break(
                        bar, best_sp.price, local_avg_body,
                        atr_val, "bearish", bars_after, sfp_n,
                    ):
                        passes_size_filter = False

            if passes_size_filter:
                # Strength: penetration + SFP follow-through bileşik skoru
                pen_ratio = (
                    max(0.0, min(1.0, penetration / (atr_val * config.CHoCH_ATR_OVERSHOOT)))
                    if atr_val > 0 else 0.0
                )
                _bars_after = bars[bar_pos + 1 : bar_pos + 1 + sfp_n]
                _confirmations = 0
                for fb in _bars_after[:sfp_n]:
                    if not fb.is_closed:
                        break
                    if fb.close < best_sp.price:
                        _confirmations += 1
                sfp_ratio = _confirmations / sfp_n if sfp_n and sfp_n > 0 else 0.0
                strength = round(max(0.0, min(1.0, pen_ratio * 0.6 + sfp_ratio * 0.4)), 3)

                found.append(CHoCH(
                    direction="bearish", level=best_sp.price, bar_index=bar_abs,
                    pivot_bar_index=best_sp.bar_index, timeframe=timeframe, timestamp=bar.timestamp,
                    strength=strength
                ))
                logger.info("[CHoCH] Bearish @ %d (level=%.5f)", bar_abs, best_sp.price)
            else:
                logger.debug("[CHoCH] Bearish veto @ %d", bar_abs)

            for sp_m in mitigated:
                object.__setattr__(sp_m, "mitigated", True)
                swing_mgr.mark_mitigated("low", sp_m.bar_index)

    return found


# ──────────────────────────────────────────────────────────
# 3. DOĞRULAMA & SKORLAMA
# ──────────────────────────────────────────────────────────
def is_choch_confirmed(
    choch: CHoCH,
    bars: list[Bar],
    confirmation_bars: int = 2,
) -> bool:
    """Kırılım sonrası `confirmation_bars` kadar barın yönünde kaldığını doğrular."""
    first_abs = bars[0].index
    choch_pos = choch.bar_index - first_abs
    count = 0

    for i in range(choch_pos + 1, len(bars)):
        b = bars[i]
        if not b.is_closed:
            break
        if choch.direction == "bullish":
            if b.close > choch.level:
                count += 1
            elif b.close < choch.level:
                count = 0
        else:
            if b.close < choch.level:
                count += 1
            elif b.close > choch.level:
                count = 0

        if count >= confirmation_bars:
            return True
    return False


def compute_choch_score(
    choch: CHoCH,
    bars: list[Bar],
    atr_series: list[float] | None = None,
    adx: float = 0.0,
) -> float:
    """CHoCH kalite skoru (0.0 - 1.0)"""
    if atr_series is None:
        atr_series = _compute_atr_series(bars, period=14)

    first_abs = bars[0].index
    choch_pos = choch.bar_index - first_abs
    if not (0 <= choch_pos < len(atr_series)):
        return 0.0

    atr_val = atr_series[choch_pos]
    if atr_val <= 0:
        return 0.0

    break_bar = bars[choch_pos]
    penetration = abs(break_bar.close - choch.level)
    pen_score = clamp(penetration / (atr_val * 0.5), 0.0, 1.0) * 0.40

    conf = is_choch_confirmed(choch, bars, confirmation_bars=2)
    conf1 = is_choch_confirmed(choch, bars, confirmation_bars=1)
    confirmation_score = 0.25 if conf else (0.15 if conf1 else 0.05)

    adx_score = clamp(adx / 50.0, 0.0, 1.0) * 0.20
    age_score = clamp((choch.bar_index - choch.pivot_bar_index) / 50.0, 0.0, 1.0) * 0.15

    return clamp(pen_score + confirmation_score + adx_score + age_score, 0.0, 1.0)


def compute_choch_score_for_fvg(
    choch: CHoCH | None,
    bars: list[Bar],
    fvg_direction: str,
    atr_series: list[float] | None = None,
    adx: float = 0.0,
) -> tuple[float, str]:
    """FVG-CHoCH uyum skoru."""
    if choch is None or choch.direction != fvg_direction:
        return 0.0, ""
    return compute_choch_score(choch, bars, atr_series=atr_series, adx=adx), choch.direction


# ──────────────────────────────────────────────────────────
# 4. BAKIM & PIPELINE
# ──────────────────────────────────────────────────────────
def cleanup_chochs(
    chochs: list[CHoCH],
    current_abs: int,
    max_age: int = MAX_CHOCH_AGE_BARS,
) -> list[CHoCH]:
    before = len(chochs)
    kept = [c for c in chochs if (current_abs - c.bar_index) <= max_age]
    if before != len(kept):
        logger.info(
            "[CHoCH-CLEANUP] %d eski sinyal temizlendi (%d → %d)",
            before - len(kept), before, len(kept),
        )
    return kept


def refresh_choch_list(
    chochs: list[CHoCH],
    bars: list[Bar],
    swing_mgr: SwingStateManager,
    lookback: int | None = None,  # None → detect_chochs dinamik hesaplar
    timeframe: str = "5m",
    atr_mult: float = MIN_CHOCH_ATR_MULT,
    max_age: int = MAX_CHOCH_AGE_BARS,
    cleanup_every: int = 50,
    symbol: str = "default",
) -> list[CHoCH]:
    _SYMBOL_COUNTERS[symbol] = _SYMBOL_COUNTERS.get(symbol, 0) + 1
    call_n = _SYMBOL_COUNTERS[symbol]

    existing_pivots = {c.pivot_bar_index for c in chochs}
    atr_series = _compute_atr_series(bars, period=config.CHoCH_ATR_PERIOD)

    new_signals = detect_chochs(
        bars, swing_mgr, lookback=lookback, timeframe=timeframe,
        atr_series=atr_series, atr_mult=atr_mult
    )

    for nc in new_signals:
        if nc.pivot_bar_index not in existing_pivots:
            chochs.append(nc)
            existing_pivots.add(nc.pivot_bar_index)

    if call_n % cleanup_every == 0 and bars:
        chochs = cleanup_chochs(chochs, current_abs=bars[-1].index, max_age=max_age)

    return chochs


def choch_direction_bias(chochs: list[CHoCH], recent_bars: int = 50) -> str:
    if not chochs:
        return "neutral"
    cutoff = max(c.bar_index for c in chochs) - recent_bars
    recent = [c for c in chochs if c.bar_index >= cutoff]
    if not recent:
        return "neutral"

    bull = sum(1 for c in recent if c.direction == "bullish")
    bear = sum(1 for c in recent if c.direction == "bearish")

    if bull > bear * 1.5:
        return "bullish"
    if bear > bull * 1.5:
        return "bearish"
    return "neutral"


def count_active_chochs(
    chochs: list[CHoCH],
    direction: str | None = None,
    since_bar: int = 0,
) -> int:
    pool = chochs
    if direction:
        pool = [c for c in pool if c.direction == direction]
    if since_bar > 0:
        pool = [c for c in pool if c.bar_index >= since_bar]
    return len(pool)

