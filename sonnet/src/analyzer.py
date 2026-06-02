"""
analyzer.py
───────────
MSS + FVG tabanlı trading bot analizörü.
Ana analiz pipeline'ı ve MarketAnalyzer sınıfı.
Bağımlılıklar (tek yönlü, döngüsüz):
models → indicators → pivot → fvg → mss → scoring → analyzer
config, monitor, volume_profile
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import config
import monitor
from fvg import (
    MIN_FVG_SIZE,
    _get_vp_status,
    compute_fvg_quality,
    find_latest_unfilled_fvg,
    is_retesting_fvg,
    refresh_fvg_list,
    score_displacement,
    score_fvg_size,
    score_retest,
    score_sweep,
)
from indicators import compute_adx, compute_atr, compute_ema100
from models import FVG, Bar, FVGQuality, mss
from mss import (
    detect_mss,
    refresh_mss_list,
)
from pivot import SwingStateManager, find_swing_highs, find_swing_lows
from volume_profile import VolumeProfile, VPLevels

logger = logging.getLogger("nexus.analyzer")


@dataclass
class AnalysisResult:
    """
    Tek bir sembol için tam analiz sonucu.
    Alan hiyerarşisi (öncelik sırası):
    direction mss → fvg → fvg_quality → retest_ready / impulsive_bypass
    """

    symbol: str
    direction: Literal["long", "short"] | None = None
    mss: mss | None = None
    fvg: FVG | None = None
    fvg_quality: FVGQuality | None = None
    retest_ready: bool = False
    adx_value: float = 0.0
    ema100: float = 0.0
    close_d1: float = 0.0
    tp_level: float | None = None
    vp_levels: VPLevels | None = None
    entry_zone: float | None = None
    entry_zone_type: Literal["proximal", "ce"] | None = None
    armed: bool = False
    stop_loss: float | None = None

    @property
    def expected_mss_direction(self) -> Literal["bullish", "bearish"] | None:
        if self.direction == "long":
            return "bullish"
        if self.direction == "short":
            return "bearish"
        return None

    def is_valid_signal(
        self,
        threshold: float | None = None,
        adx: float | None = None,
    ) -> bool:
        effective_adx = adx if adx is not None else self.adx_value
        is_impulsive = effective_adx >= config.FVG_IMPULSIVE_ADX_THRESHOLD

        if threshold is None:
            threshold = (
                config.FVG_SCORE_THRESHOLD_IMPULSIVE
                if is_impulsive
                else config.FVG_SCORE_THRESHOLD
            )

        mode_label = "impulsive" if is_impulsive else "reversal"

        if self.direction is None:
            logger.info("[VALID] %s red — direction=None", self.symbol)
            return False

        if self.mss is None:
            logger.info(
                "[VALID] %s red — mss=None (yapısal teyit yok, direction=%s)",
                self.symbol, self.direction,
            )
            return False

        expected = self.expected_mss_direction
        if self.mss.direction != expected:
            logger.info(
                "[VALID] %s red — direction=%s ↔ mss.direction=%s uyumsuz",
                self.symbol, self.direction, self.mss.direction,
            )
            return False

        if self.fvg is None:
            logger.info(
                "[VALID] %s red — fvg=None (mss.bar_index=%d, direction=%s)",
                self.symbol, self.mss.bar_index, self.direction,
            )
            return False

        if self.mss.bar_index - self.fvg.real_index > config.FVG_MAX_AGE_BARS:
            logger.info(
                "[VALID] %s red — FVG bayat: age=%d > %d",
                self.symbol, self.mss.bar_index - self.fvg.real_index,
                config.FVG_MAX_AGE_BARS,
            )
            return False

        if self.fvg_quality is None:
            logger.info(
                "[VALID] %s red — fvg_quality=None (fvg.real_index=%d)",
                self.symbol, self.fvg.real_index,
            )
            return False

        if self.fvg_quality.score < threshold:
            logger.info(
                "[VALID] %s red — score=%.3f < threshold=%.3f "
                "(adx=%.1f mode=%s)",
                self.symbol, self.fvg_quality.score, threshold,
                effective_adx, mode_label,
            )
            return False

        retest_ok = self.retest_ready
        impulsive_bypass = (
            is_impulsive
            and self.fvg_quality.displacement
            >= config.FVG_IMPULSIVE_DISPLACEMENT_MIN
        )

        if not (retest_ok or impulsive_bypass):
            logger.info(
                "[VALID] %s red — giriş koşulu sağlanamadı: "
                "retest_ready=%s impulsive_bypass=%s "
                "(adx=%.1f displacement=%.3f threshold_displacement=%.2f)",
                self.symbol, retest_ok, impulsive_bypass,
                effective_adx, self.fvg_quality.displacement,
                config.FVG_IMPULSIVE_DISPLACEMENT_MIN,
            )
            return False

        logger.info(
            "[VALID] %s OK — direction=%s mss.bar=%d fvg.real=%d "
            "score=%.3f adx=%.1f mode=%s retest=%s bypass=%s",
            self.symbol, self.direction,
            self.mss.bar_index, self.fvg.real_index,
            self.fvg_quality.score, effective_adx,
            mode_label, retest_ok, impulsive_bypass,
        )
        return True

    def summary(self) -> str:
        mss_str = (
            f"mss={self.mss.direction}@{self.mss.level:.2f} "
            f"bar={self.mss.bar_index}"
            if self.mss else "mss=None"
        )
        fvg_str = (
            f"fvg=[{self.fvg.bottom:.2f}-{self.fvg.top:.2f}] "
            f"real={self.fvg.real_index}"
            if self.fvg else "fvg=None"
        )
        score_str = (
            f"score={self.fvg_quality.score:.3f} "
            f"disp={self.fvg_quality.displacement:.3f}"
            if self.fvg_quality else "quality=None"
        )
        return (
            f"{self.symbol} | {self.direction} | {mss_str} | {fvg_str} | "
            f"{score_str} | adx={self.adx_value:.1f} | "
            f"retest={self.retest_ready}"
        )


def _is_5m_engulfing(prev: Bar, curr: Bar, direction: str) -> bool:
    bar_range = curr.high - curr.low
    if bar_range == 0:
        return False

    body_ratio = curr.body / bar_range
    if body_ratio < 0.55:
        return False

    if direction == "bullish":
        return (
            curr.close > prev.open
            and curr.open < prev.close
            and curr.close > prev.high
        )
    return (
        curr.close < prev.open
        and curr.open > prev.close
        and curr.close < prev.low
    )


def check_ltf_trigger(
    symbol: str,
    fvg: FVG,
    bars_5m: list[Bar],
    direction: str,
    entry_zone: float,
    atr_val: float,
    mss_state: SwingStateManager | None = None,
) -> tuple[bool, str]:
    if len(bars_5m) < 3:
        return False, "none"

    last = bars_5m[-1]
    prev = bars_5m[-2]

    if not last.is_closed:
        return False, "none"

    zone_tolerance = atr_val * 0.20
    price_in_zone = abs(last.close - entry_zone) <= zone_tolerance
    price_in_fvg = fvg.bottom <= last.close <= fvg.top

    if not (price_in_zone or price_in_fvg):
        return False, "none"

    if mss_state is not None:
        try:
            mss_state.ingest(bars_5m, left=3, right=3)
            mss_5m = detect_mss(
                bars=bars_5m,
                swing_mgr=mss_state,
                lookback=None,
                timeframe="5m",
            )
            latest_5m = mss_5m[-1] if mss_5m else None
            if latest_5m and latest_5m.direction == direction:
                logger.info(
                    "[FAZ4] %s 5m MSS onayı → direction=%s "
                    "level=%.5f bar=%d",
                    symbol, latest_5m.direction,
                    latest_5m.level, latest_5m.bar_index,
                )
                return True, "5m_mss"
        except Exception as exc:
            logger.warning("[FAZ4] %s 5m MSS kontrolü hata: %s", symbol, exc)

    if _is_5m_engulfing(prev, last, direction):
        logger.info(
            "[FAZ4] %s 5m Engulfing onayı → direction=%s "
            "close=%.5f prev_open=%.5f",
            symbol, direction, last.close, prev.open,
        )
        return True, "5m_engulfing"

    return False, "none"


def compute_structural_sl(
    fvg: FVG,
    direction: str,
    sl_buffer_pct: float = 0.001,
) -> float:
    if direction == "bullish":
        sl = fvg.bottom * (1.0 - sl_buffer_pct)
    else:
        sl = fvg.top * (1.0 + sl_buffer_pct)
    return round(sl, 6)


class MarketAnalyzer:
    """
    Sembol bazlı trading analiz motoru.
    H4 → Yapısal trend (swing kırılımı)
    H1 → ADX hesaplaması + Volume Profile
    15m → MSS + FVG tespiti ve skorlama
    5m  → LTF tetik mekanizması
    """

    def __init__(
        self,
        symbol: str,
        adx_threshold: float = 25.0,
        ema_period: int = 100,
        bot_state=None,
    ) -> None:
        self.symbol = symbol
        self.adx_threshold = adx_threshold
        self.ema_period = ema_period
        self.bot_state = bot_state
        self.vp = VolumeProfile(bins=24)
        self._mss_state = SwingStateManager()
        self.fvgs: list[FVG] = []
        self.mss: list[mss] = []

    def _trend_direction(
        self, bars_h4: list[Bar]
    ) -> Literal["long", "short"] | None:
        lookback = config.H4_SWING_LOOKBACK
        segment = bars_h4[-lookback:] if len(bars_h4) > lookback else bars_h4
        close = segment[-1].close

        highs = find_swing_highs(
            segment, left=config.H4_SWING_LEFT, right=config.H4_SWING_RIGHT
        )
        lows = find_swing_lows(
            segment, left=config.H4_SWING_LEFT, right=config.H4_SWING_RIGHT
        )

        if len(highs) < 2 or len(lows) < 2:
            logger.info(
                "[H4-STRUCT] %s yetersiz swing (highs=%d lows=%d) "
                "→ trend=None",
                self.symbol, len(highs), len(lows),
            )
            return None

        last_high, prev_high = highs[-1].price, highs[-2].price
        last_low, prev_low = lows[-1].price, lows[-2].price

        bullish_struct = last_high > prev_high and last_low > prev_low
        bearish_struct = last_low < prev_low and last_high < prev_high

        if not bullish_struct and not bearish_struct:
            if len(highs) >= 3 and len(lows) >= 3:
                h3, l3 = highs[-3].price, lows[-3].price
                bullish_struct = last_high > h3 and last_low > l3
                bearish_struct = last_low < l3 and last_high < h3

        if not bullish_struct and not bearish_struct:
            logger.info(
                "[H4-STRUCT] %s kararsız yapı (HH+HL yok, LL+LH yok) "
                "→ trend=None", self.symbol,
            )
            return None

        if bullish_struct:
            if close < last_low:
                logger.info(
                    "[H4-STRUCT] %s Bullish yapıda SWING LOW KIRILDI "
                    "(close=%.4f < low=%.4f) → SHORT",
                    self.symbol, close, last_low,
                )
                return "short"
            logger.info(
                "[H4-STRUCT] %s — LONG modu KİLİTLİ "
                "(HH=%.4f > prev_HH=%.4f, HL=%.4f > prev_HL=%.4f, "
                "close=%.4f)",
                self.symbol, last_high, prev_high, last_low, prev_low, close,
            )
            return "long"

        if close > last_high:
            logger.info(
                "[H4-STRUCT] %s Bearish yapıda SWING HIGH KIRILDI "
                "(close=%.4f > high=%.4f) → LONG",
                self.symbol, close, last_high,
            )
            return "long"
        logger.info(
            "[H4-STRUCT] %s — SHORT modu KİLİTLİ "
            "(LL=%.4f < prev_LL=%.4f, LH=%.4f < prev_LH=%.4f, "
            "close=%.4f)",
            self.symbol, last_low, prev_low, last_high, prev_high, close,
        )
        return "short"

    def analyze(
        self,
        bars_d1: list[Bar],
        bars_h4: list[Bar],
        bars_h1: list[Bar],
        bars_15m: list[Bar],
        bars_m5: list[Bar],
        fvg_score_threshold: float | None = None,
    ) -> AnalysisResult:
        result = AnalysisResult(symbol=self.symbol)
        try:
            if not all([bars_h4, bars_h1, bars_15m, bars_m5, bars_d1]):
                return result

            trend = self._trend_direction(bars_h4)
            if trend is None:
                logger.info(
                    "[TREND] %s trend=None — H4 yapısal trend "
                    "belirlenemedi, sinyal red", self.symbol,
                )
                return result

            result.ema100 = compute_ema100(bars_d1)
            result.close_d1 = bars_d1[-1].close
            adx = compute_adx(bars_h1)
            result.adx_value = adx

            threshold = fvg_score_threshold
            if threshold is None:
                if self.bot_state is not None:
                    threshold = self.bot_state.current_threshold(adx=adx)
                else:
                    threshold = (
                        config.FVG_SCORE_THRESHOLD_IMPULSIVE
                        if adx >= config.FVG_IMPULSIVE_ADX_THRESHOLD
                        else config.FVG_SCORE_THRESHOLD
                    )

            pivot_lr = 2 if adx >= config.MSS_PIVOT_ADX_THRESHOLD else 3
            self._mss_state.ingest(bars_15m, left=pivot_lr, right=pivot_lr)

            self.mss = refresh_mss_list(
                self.mss,
                bars_15m,
                swing_mgr=self._mss_state,
                lookback=None,
                timeframe="15m",
                symbol=self.symbol,
            )
            mss = self.mss[-1] if self.mss else None
            result.mss = mss

            mss_score = 0.5
            if mss is not None:
                aligns = (
                    (trend == "long" and mss.direction == "bullish")
                    or (trend == "short" and mss.direction == "bearish")
                )
                mss_score = 1.0 if aligns else 0.3
                logger.info(
                    "[MSS] %s %s → score=%.1f",
                    self.symbol,
                    "uyumlu" if aligns else "uyumsuz",
                    mss_score,
                )
            else:
                logger.info("[MSS] %s bulunamadı → nötr (0.5)", self.symbol)

            if mss is not None:
                result.direction = (
                    "long" if mss.direction == "bullish" else "short"
                )
                fvg_dir = mss.direction
            else:
                result.direction = trend
                fvg_dir = "bullish" if trend == "long" else "bearish"

            self.fvgs = refresh_fvg_list(
                self.fvgs, bars_15m, lookback=60,
                timeframe="15m", symbol=self.symbol,
            )

            active_fvg = (
                find_latest_unfilled_fvg(
                    self.fvgs, fvg_dir, min_fvg_size=MIN_FVG_SIZE
                )
                if mss is not None else None
            )

            if mss is None:
                logger.info(
                    "[FVG-MSS] %s MSS bulunamadı — "
                    "FVG sinyali işleme alınmıyor", self.symbol,
                )
            elif active_fvg is None:
                logger.info(
                    "[FVG-RED] %s aktif FVG bulunamadı — "
                    "yon=%s (mss.direction=%s)",
                    self.symbol, fvg_dir, mss.direction,
                )

            if active_fvg and mss:
                fvg_age = mss.bar_index - active_fvg.real_index
                if fvg_age > config.FVG_MAX_AGE_BARS:
                    logger.info(
                        "[FVG-OLD] %s FVG bayat — age=%d > %d",
                        self.symbol, fvg_age, config.FVG_MAX_AGE_BARS
                    )
                    active_fvg = None

            if active_fvg is None:
                logger.info(
                    "[FVG-RED] %s aktif FVG bulunamadı — "
                    "yon=%s toplam FVG=%d adet",
                    self.symbol, fvg_dir, len(self.fvgs),
                )
                return result

            object.__setattr__(active_fvg, "timeframe", "15m")
            result.fvg = active_fvg

            first_abs = bars_15m[0].index
            list_pos = max(
                0, min(active_fvg.real_index - first_abs, len(bars_15m) - 1)
            )
            fvg_bar = bars_15m[list_pos]
            atr_val = compute_atr(bars_15m)
            bars_since = max(0, bars_15m[-1].index - active_fvg.real_index)

            adx_15m = compute_adx(bars_15m)
            market_mode = (
                "IMPULSIVE"
                if adx >= config.FVG_IMPULSIVE_ADX_THRESHOLD
                else "REVERSAL"
            )

            if bars_since > config.FVG_MAX_AGE_BARS:
                logger.info(
                    "[TIMEOUT] %s FVG bayat — bars_since=%d > %d",
                    self.symbol, bars_since, config.FVG_MAX_AGE_BARS,
                )
                monitor.update_reject(self.symbol, "timeout_reject")
                return result

            if market_mode == "IMPULSIVE" and adx_15m < 20:
                logger.info(
                    "[VETO] Testere Piyasası: %s Impulsive modda ama "
                    "ADX (%.1f) 25'in altında.", self.symbol, adx_15m,
                )
                monitor.update_reject(self.symbol, "adx_impulsive_reject")
                return result

            sweep_detected = score_sweep(
                bars_15m, active_fvg
            ) > 0.0
            if market_mode == "REVERSAL" and not sweep_detected:
                logger.info(
                    "[VETO] Likidite Avı Yok: %s Reversal modda ancak "
                    "sweep tespit edilemedi.", self.symbol,
                )
                monitor.update_reject(self.symbol, "no_sweep_reject")
                return result

            d = score_displacement(fvg_bar, atr_val, active_fvg.direction)
            f = score_fvg_size(active_fvg, atr_val)
            s = score_sweep(
                bars_15m, active_fvg
            )
            retest_now = is_retesting_fvg(active_fvg, bars_15m[-1], atr_val)
            result.retest_ready = retest_now

            r = 0.0
            if retest_now:
                r = score_retest(bars_since)
            else:
                for offset in range(1, min(bars_since, 20)):
                    check_pos = list_pos + offset
                    if check_pos < len(bars_15m):
                        if is_retesting_fvg(
                            active_fvg, bars_15m[check_pos], atr_val
                        ):
                            r = score_retest(offset)
                            break

            mss_score, mss_dir = 0.0, ""
            if mss is not None:
                from mss import compute_mss_score_for_fvg as _mss_fvg_score
                mss_score, mss_dir = _mss_fvg_score(
                    mss, bars_15m, active_fvg.direction, adx=adx
                )

            vp_levels = self.vp.build(bars_15m, symbol=self.symbol)
            result.vp_levels = vp_levels
            vp_status = _get_vp_status(active_fvg, vp_levels)

            logger.debug(
                "FVG veto chain | symbol=%s | passed_structure=%s | passed_mss=%s | passed_adx=%s",
                self.symbol, trend is not None, mss is not None,
                adx >= config.FVG_IMPULSIVE_ADX_THRESHOLD,
                    )

            if vp_levels.poc > 0:
                vp_h1 = self.vp.build(bars_h1, symbol=f"{self.symbol}_h1")
                if vp_h1.poc > 0:
                    result.tp_level = vp_h1.poc
                    logger.debug(
                        "[FAZ2] %s VP TP mıknatısı: POC=%.6f",
                        self.symbol, vp_h1.poc,
                    )

            fvg_quality = compute_fvg_quality(
                bars_tf=bars_15m,
                current_price=bars_15m[-1].close,
                fvg=active_fvg,
                adx=adx,
                d=d, f=f, s=s, r=r,
                mss_score=mss_score,
                mss_direction=mss_dir,
                vp=vp_levels,
            )
            result.fvg_quality = fvg_quality

            logger.info(
                "[FAZ2] %s FVG Quality: score=%.3f d=%.3f f=%.3f s=%.3f "
                "r=%.3f mss=%.3f adx=%.1f vp=%s mode=%s",
                self.symbol, fvg_quality.score, fvg_quality.displacement,
                fvg_quality.fvg_size, fvg_quality.sweep,
                fvg_quality.retest, mss_score, adx, vp_status, market_mode,
            )

            if fvg_quality.score < threshold:
                logger.info(
                    "[FAZ2] %s skor eşik altı: %.3f < %.3f → sinyal red",
                    self.symbol, fvg_quality.score, threshold,
                )
                monitor.update_reject(self.symbol, "score_below_threshold")
                return result

            if active_fvg.direction == "bullish":
                proximal = active_fvg.bottom + active_fvg.size * 0.15
                ce = active_fvg.midpoint
            else:
                proximal = active_fvg.top - active_fvg.size * 0.15
                ce = active_fvg.midpoint

            current_close = bars_15m[-1].close
            dist_prox = abs(current_close - proximal)
            dist_ce = abs(current_close - ce)

            if dist_ce < dist_prox:
                entry_zone, entry_zone_type = ce, "ce"
            else:
                entry_zone, entry_zone_type = proximal, "proximal"

            result.entry_zone = round(entry_zone, 6)
            result.entry_zone_type = entry_zone_type

            logger.info(
                "[FAZ3] %s Killzone: entry=%.6f type=%s "
                "(proximal=%.6f dist=%.6f, ce=%.6f dist=%.6f, close=%.6f)",
                self.symbol, entry_zone, entry_zone_type,
                proximal, dist_prox, ce, dist_ce, current_close,
            )

            atr_15m = atr_val
            zone_tolerance = atr_15m * 0.25
            price_in_zone = abs(current_close - entry_zone) <= zone_tolerance
            price_in_fvg = active_fvg.bottom <= current_close <= active_fvg.top

            if price_in_zone or price_in_fvg:
                logger.info(
                    "[FAZ4] %s fiyat entry_zone'da: close=%.6f entry=%.6f "
                    "tolerance=%.6f in_zone=%s in_fvg=%s",
                    self.symbol, current_close, entry_zone,
                    zone_tolerance, price_in_zone, price_in_fvg,
                )

                triggered, trigger_reason = check_ltf_trigger(
                    symbol=self.symbol,
                    fvg=active_fvg,
                    bars_5m=bars_m5,
                    direction=active_fvg.direction,
                    entry_zone=entry_zone,
                    atr_val=atr_15m,
                    mss_state=SwingStateManager(),
                )

                if triggered:
                    result.armed = True
                    result.stop_loss = compute_structural_sl(
                        active_fvg, active_fvg.direction
                    )
                    logger.info(
                        "[FAZ4] %s ARMED! trigger=%s entry=%.6f sl=%.6f "
                        "fvg=[%.6f-%.6f] direction=%s",
                        self.symbol, trigger_reason, entry_zone,
                        result.stop_loss, active_fvg.bottom,
                        active_fvg.top, active_fvg.direction,
                    )
                    monitor.update_signal(
                        self.symbol,
                        reason=(
                            f"armed_{trigger_reason}_"
                            f"score_{fvg_quality.score:.3f}"
                        ),
                    )
                else:
                    logger.debug(
                        "[FAZ4] %s entry_zone'da ama 5m tetik yok "
                        "(reason=%s).", self.symbol, trigger_reason,
                    )
            else:
                logger.debug(
                    "[FAZ4] %s fiyat entry_zone dışında: close=%.6f "
                    "entry=%.6f distance=%.6f tolerance=%.6f",
                    self.symbol, current_close, entry_zone,
                    abs(current_close - entry_zone), zone_tolerance,
                )

            logger.info(
                "[ANALYZE] %s tamamlandı: direction=%s mss=%s fvg=%s "
                "score=%.3f armed=%s retest=%s entry=%.6f sl=%s",
                self.symbol, result.direction,
                result.mss.direction if result.mss else "None",
                (
                    f"{active_fvg.direction}@{active_fvg.real_index}"
                    if active_fvg else "None"
                ),
                fvg_quality.score if fvg_quality else 0.0,
                result.armed, result.retest_ready,
                result.entry_zone,
                f"{result.stop_loss:.6f}" if result.stop_loss else "None",
            )

        except Exception as exc:
            logger.error(
                "[ANALYZE] %s analiz hatası: %s",
                self.symbol, exc, exc_info=True,
            )

        return result

