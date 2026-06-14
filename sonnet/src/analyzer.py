"""
analyzer.py
───────────
V3 Event-Driven Architecture — Stateless Event Producer (Sensor).
Produces raw market-structure events: SWEEP, MSS, FVG_CREATED, RETRACE, LTF_CONFIRM.
No trading decisions, no scoring, no ADX, no trend vetoes.
Pure observation → list[dict] output.

V3.2 Değişiklikler:
  - [FIX-1] Sweep tespiti düzeltildi: close kontrolü → wick kır + close içeri
  - [FIX-2] analyze() sırası düzeltildi: sweep → MSS → FVG (eski: sweep → FVG → MSS)
  - [FIX-3] fvg_since hesabı düzeltildi: mutlak bar index doğru kullanılıyor
  - [FIX-4] consumed_levels float precision: round(price, 5) ile normalize
"""

from __future__ import annotations

import logging
from typing import Literal

import config
from fvg import MIN_FVG_SIZE, cleanup_fvgs, detect_fvgs, update_fvg_states
from indicators import compute_atr_point
from models import FVG, Bar, SwingPoint
from mss import detect_mss
from pivot import SwingStateManager, find_swing_highs, find_swing_lows

logger = logging.getLogger("nexus.analyzer")
# Helpers for FVG clustering and overlap validation


def _interval_overlap_ratio(a_low: float, a_high: float, b_low: float, b_high: float) -> float:
    """Return overlap ratio relative to the smaller interval in [0,1]."""
    try:
        a_low, a_high = (a_low, a_high) if a_low <= a_high else (a_high, a_low)
        b_low, b_high = (b_low, b_high) if b_low <= b_high else (b_high, b_low)
        a_len = max(0.0, a_high - a_low)
        b_len = max(0.0, b_high - b_low)
        if a_len == 0.0 or b_len == 0.0:
            return 0.0
        left = max(a_low, b_low)
        right = min(a_high, b_high)
        ov = max(0.0, right - left)
        denom = min(a_len, b_len) if min(a_len, b_len) > 0 else 1.0
        return ov / denom
    except Exception:
        return 0.0


def _cluster_fvgs(fvgs: list[FVG], max_gap: float) -> list[FVG]:
    """Merge adjacent same-direction FVGs whose intervals touch or are within max_gap.
    Keeps earliest real_index; unions top/bottom bounds.
    """
    if not fvgs:
        return []
    items = sorted(fvgs, key=lambda f: f.real_index)
    out: list[FVG] = []
    cur = items[0]
    for f in items[1:]:
        same_dir = f.direction == cur.direction
        left_a, right_a = (min(cur.bottom, cur.top), max(cur.bottom, cur.top))
        left_b, right_b = (min(f.bottom, f.top), max(f.bottom, f.top))
        gap = max(0.0, max(left_b - right_a, left_a - right_b))
        if same_dir and gap <= max_gap:
            new_top = max(cur.top, f.top)
            new_bottom = min(cur.bottom, f.bottom)
            cur = FVG(
                direction=cur.direction,
                top=new_top,
                bottom=new_bottom,
                real_index=cur.real_index,
                timeframe=cur.timeframe,
            )
        else:
            out.append(cur)
            cur = f
    out.append(cur)
    return out


def _resample_to_2h(bars_h1: list[Bar]) -> list[Bar]:
    """2 adet 1H barı birleştirerek sentetik 2H bar üretir."""
    result = []
    for i in range(0, len(bars_h1) - 1, 2):
        b1, b2 = bars_h1[i], bars_h1[i + 1]
        result.append(
            Bar(
                index=i // 2,
                open=b1.open,
                high=max(b1.high, b2.high),
                low=min(b1.low, b2.low),
                close=b2.close,
                volume=b1.volume + b2.volume,
                timestamp=b1.timestamp,
            )
        )
    return result


def create_mss_event(
    symbol: str,
    timeframe: str,
    direction: str,
    level: float,
    timestamp: int,
    impulse_origin: float | None = None,
) -> dict:
    """Converts a structural Market Structure Shift (MSS) into a normalized V3 market event."""
    return {
        "type": "MSS",
        "tf": timeframe,
        "direction": direction,  # "LONG" veya "SHORT"
        "level": float(level),
        "time": int(timestamp),
        "impulse_origin": float(impulse_origin) if impulse_origin is not None else float(level),
        "bar_index": int(timestamp),  # caller override edecek
    }


class MarketAnalyzer:
    """
    V3 Stateless Event Producer (Sensor).
    Evaluates current market conditions and emits raw structural events.
    No trading logic, no scoring — just reports the facts.

    Akış:
      0. HTF BIAS    — 1D BOS yönü (4H teyit). Bias yoksa hiç event üretme.
      1. SWEEP       — H1 likidite süpürmesi (H1'de bulunamazsa 2H fallback)
      2. MSS         — 15m Market Structure Shift (CHoCH), sweep sonrası
      3. FVG         — 1H/2H Fair Value Gap tespiti, MSS sonrası
      4. RETRACE     — Fiyat FVG içinde mi? CE tap var mı?
      5. LTF_CONFIRM — 1m V1 momentum onayı
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._mss_state = SwingStateManager()
        self._seen_mss: set[int] = set()
        self._emitted_fvg_ids: set[int] = set()
        # [FIX-4] float → round(price, 5) normalize edilmiş seviyeler saklanır
        self._consumed_levels: dict[str, set[float]] = {}
        self._last_d1_index: int = -1

    def reset_symbol_cache(self) -> None:
        """
        [FIX-2] State machine sembolü IDLE'a döndürdüğünde çağrılır.

        Sorun: _emitted_fvg_ids ve _seen_mss sadece D1 bar deÄŸiÅŸiminde
        temizleniyordu. State machine reset olduÄŸunda bu cache'ler temizlenmeden
        kalıyor, aynı FVG/MSS eventleri bir daha emit edilemiyor ve state
        WAIT_RETRACE'de fvg_upper=None ile mahsur kalıyor.

        State machine = truth, analyzer cache = derived ephemeral state.
        State sıfırlandığında cache da sıfırlanmalı.

        _mss_state (SwingStateManager) da sıfırlanır: reset sonrası aynı
        swing bar'ı "consumed" sayılmaya devam ederse detect_mss() o swing'i
        bir daha emit etmez ve yeni setup hiç başlamaz (silent skip).
        """
        self._emitted_fvg_ids.clear()
        self._seen_mss.clear()
        self._mss_state = SwingStateManager()
        # _consumed_levels kasıtlı korunuyor: sweep seviyeleri D1 bazlı,
        # symbol reset'ten bağımsız olarak geçerliliğini korur.
        logger.debug("[CACHE-RESET] %s _emitted_fvg_ids + _seen_mss + _mss_state temizlendi", self.symbol)

    # ── 0. HTF BIAS ────────────────────────────────────────────────────────────

    def _detect_htf_bias(
        self,
        bars_d1: list[Bar],
        bars_h4: list[Bar],
    ) -> tuple[str | None, str]:
        """
        1D BOS yönünden ana bias'ı belirler. 4H aynı yönde teyit ederse güçlü sinyal.

        Returns:
            (bias, strength) — bias None ise strength "NONE" olur.
            strength: "STRONG" | "MODERATE" | "WEAK" | "NONE"

        Kural:
          - D1'de son D1_BOS_LOOKBACK bar içinde swing HIGH kırıldı → LONG
          - D1'de son D1_BOS_LOOKBACK bar içinde swing LOW  kırıldı → SHORT
          - Son kırılım hangisiyse bias odur (en güncel kazanır)
          - H4 aynı yöndeyse   → STRONG
          - H4 yoksa           → MODERATE
          - H4 tersse strict   → bias yok, "WEAK"
          - H4 tersse !strict  → bias var ama "WEAK"
        """
        if not bars_d1 or len(bars_d1) < 5:
            return None, "NONE"

        # ── D1 BOS tespiti ──
        lookback_d1 = min(config.D1_BOS_LOOKBACK, len(bars_d1))
        segment_d1 = bars_d1[-lookback_d1:]

        d1_highs = find_swing_highs(segment_d1, left=2, right=2)
        d1_lows = find_swing_lows(segment_d1, left=2, right=2)

        last_close_d1 = bars_d1[-1].close

        last_bull_bos: int = -1
        last_bear_bos: int = -1

        for sh in d1_highs:
            if last_close_d1 > sh.price and sh.bar_index > last_bull_bos:
                last_bull_bos = sh.bar_index

        for sl in d1_lows:
            if last_close_d1 < sl.price and sl.bar_index > last_bear_bos:
                last_bear_bos = sl.bar_index

        if last_bull_bos == -1 and last_bear_bos == -1:
            logger.debug("[BIAS] %s: D1 BOS bulunamadı", self.symbol)
            return None, "NONE"

        d1_bias: Literal["LONG", "SHORT"] = "LONG" if last_bull_bos >= last_bear_bos else "SHORT"

        # ── H4 teyit ──
        h4_bias: Literal["LONG", "SHORT"] | None = None
        if bars_h4 and len(bars_h4) >= 5:
            lookback_h4 = min(config.H4_BOS_LOOKBACK, len(bars_h4))
            segment_h4 = bars_h4[-lookback_h4:]

            h4_highs = find_swing_highs(segment_h4, left=2, right=2)
            h4_lows = find_swing_lows(segment_h4, left=2, right=2)

            last_close_h4 = bars_h4[-1].close
            last_bull_h4: int = -1
            last_bear_h4: int = -1

            for sh in h4_highs:
                if last_close_h4 > sh.price and sh.bar_index > last_bull_h4:
                    last_bull_h4 = sh.bar_index

            for sl in h4_lows:
                if last_close_h4 < sl.price and sl.bar_index > last_bear_h4:
                    last_bear_h4 = sl.bar_index

            if last_bull_h4 != -1 or last_bear_h4 != -1:
                h4_bias = "LONG" if last_bull_h4 >= last_bear_h4 else "SHORT"

        # ── H4 ters ──
        if h4_bias is not None and h4_bias != d1_bias:
            if config.HTF_STRICT_FILTER:
                logger.warning(
                    "[BIAS] %s: D1=%s H4=%s → UYUMSUZ, zincir kiriliyor",
                    self.symbol,
                    d1_bias,
                    h4_bias,
                )
                return None, "WEAK"
            logger.warning(
                "[BIAS] %s: D1=%s H4=%s → ZAYIF (filtre kapali, D1 kazandi)",
                self.symbol,
                d1_bias,
                h4_bias,
            )
            return d1_bias, "WEAK"

        # ── H4 aynı ──
        if h4_bias == d1_bias:
            logger.info("[BIAS] %s: D1=%s H4=%s → GUCLU", self.symbol, d1_bias, h4_bias)
            return d1_bias, "STRONG"

        # ── H4 belirsiz ──
        logger.info("[BIAS] %s: D1=%s H4=belirsiz → MODERATE", self.symbol, d1_bias)
        return d1_bias, "MODERATE"

    # ── HTF Seviyeleri (SL/TP referansı) ───────────────────────────────────────

    @staticmethod
    def _detect_h4_swing_level(
        bars_h4: list[Bar],
        bias: Literal["LONG", "SHORT"],
    ) -> float | None:
        """4H swing low (long) veya swing high (short) — SL referansı."""
        if not bars_h4 or len(bars_h4) < 5:
            return None
        if bias == "LONG":
            lows = find_swing_lows(bars_h4, left=2, right=2)
            return lows[-1].price if lows else None
        highs = find_swing_highs(bars_h4, left=2, right=2)
        return highs[-1].price if highs else None

    @staticmethod
    def _detect_h1_liquidity(
        bars_h1: list[Bar],
        bias: Literal["LONG", "SHORT"],
    ) -> float | None:
        """1H BSL (long) veya SSL (short) — TP referansı."""
        if not bars_h1 or len(bars_h1) < 5:
            return None
        if bias == "LONG":
            highs = find_swing_highs(bars_h1, left=3, right=3)
            return highs[-1].price if highs else None
        lows = find_swing_lows(bars_h1, left=3, right=3)
        return lows[-1].price if lows else None

    # ── 1. SWEEP (H1 → 2H fallback) ────────────────────────────────────────────────

    def _detect_sweep_h1(
        self,
        symbol: str,
        bars_h1: list[Bar],
        bars_15m: list[Bar],
        bias: Literal["LONG", "SHORT"],
    ) -> list[dict]:
        """
        H1 sweep tespiti. H1'de bulunamazsa 15m fallback.
        2H fallback kaldırıldı.
        """
        events = self._sweep_on_bars(symbol, bars_h1, bias, tf="1H")
        if events:
            return events

        # 15m fallback
        return self._sweep_on_bars(
            symbol,
            bars_15m,
            bias,
            tf="15m",
            strength_override=getattr(config, "SWEEP_15M_STRENGTH", 1),
            pen_atr_override=getattr(config, "SWEEP_15M_PENETRATION_ATR", 0.15),
            quality_atr_override=getattr(config, "SWEEP_15M_PIVOT_QUALITY_ATR", 0.20),
        )

    def _sweep_on_bars(
        self,
        symbol: str,
        bars: list[Bar],
        bias: Literal["LONG", "SHORT"],
        tf: str,
        strength_override: int | None = None,
        pen_atr_override: float | None = None,
        quality_atr_override: float | None = None,
    ) -> list[dict]:
        consumed = self._consumed_levels.setdefault(symbol, set())
        events: list[dict] = []
        if not bars:
            return events
        current_bar = bars[-1]

        strength = strength_override if strength_override is not None else getattr(config, "SWEEP_SWING_STRENGTH", 2)
        pen_atr_mult = (
            pen_atr_override if pen_atr_override is not None else getattr(config, "SWEEP_PENETRATION_ATR", 0.10)
        )

        atr = compute_atr_point(bars, period=14)
        if atr is None or atr <= 0:
            return events

        min_penetration = atr * pen_atr_mult

        highs = find_swing_highs(bars, left=strength, right=strength)
        lows = find_swing_lows(bars, left=strength, right=strength)

        if bias == "LONG":
            for sl in reversed(lows[-5:]):
                level_key = (tf, round(sl.price, 5))
                if level_key in consumed:
                    continue

                # Pivot kalite filtresi
                if sl.bar_index > 0 and sl.bar_index < len(bars) - 1:
                    left_low = bars[sl.bar_index - 1].low
                    right_low = bars[sl.bar_index + 1].low
                    swing_size = min(left_low, right_low) - sl.price
                    quality_threshold = (
                        quality_atr_override
                        if quality_atr_override is not None
                        else getattr(config, "SWEEP_PIVOT_QUALITY_ATR", 0.20)
                    )
                    if swing_size < atr * quality_threshold:
                        continue

                penetration = sl.price - current_bar.low  # ne kadar aşağı geçti
                if (
                    current_bar.low < sl.price  # swing low geçildi
                    and penetration >= min_penetration  # ATR×0.10 kadar taştı
                    and current_bar.close > sl.price  # içeride kapandı
                ):
                    consumed.add(level_key)
                    events.append(
                        {
                            "type": "SWEEP",
                            "symbol": symbol,
                            "level": sl.price,
                            "tf": tf,
                            "side": "SSL",
                            "bar_index": current_bar.index,
                        }
                    )
                    break

        else:  # SHORT
            for sh in reversed(highs[-5:]):
                level_key = (tf, round(sh.price, 5))
                if level_key in consumed:
                    continue

                # Pivot kalite filtresi
                if sh.bar_index > 0 and sh.bar_index < len(bars) - 1:
                    left_high = bars[sh.bar_index - 1].high
                    right_high = bars[sh.bar_index + 1].high
                    swing_size = sh.price - max(left_high, right_high)
                    quality_threshold = (
                        quality_atr_override
                        if quality_atr_override is not None
                        else getattr(config, "SWEEP_PIVOT_QUALITY_ATR", 0.20)
                    )
                    if swing_size < atr * quality_threshold:
                        continue

                penetration = current_bar.high - sh.price  # ne kadar yukarı geçti
                if (
                    current_bar.high > sh.price  # swing high geçildi
                    and penetration >= min_penetration  # ATR×0.10 kadar taştı
                    and current_bar.close < sh.price  # içeride kapandı
                ):
                    consumed.add(level_key)
                    events.append(
                        {
                            "type": "SWEEP",
                            "symbol": symbol,
                            "level": sh.price,
                            "tf": tf,
                            "side": "BSL",
                            "bar_index": current_bar.index,
                        }
                    )
                    break

        return events

    # ── 2. MSS (15m) ───────────────────────────────────────────────────────────

    def _detect_mss_events(
        self,
        symbol: str,
        bars_15m: list[Bar],
        bias: Literal["LONG", "SHORT"],
        since_bar_index: int | None = None,
    ) -> list[dict]:
        """
        15m CHoCH/BOS tespiti. Bias yönüyle eşleşen MSS'ler emit edilir.
        Ters yön MSS'ler (counter-trend) filtrelenir.

        since_bar_index: sweep bar'ından sonraki MSS'leri filtreler.

        [FIX-1] since_bar_index=None ise sweep henüz gerçekleşmemiş demektir.
        Sweep anchor olmadan MSS emit etmek state machine'i sweep_detected=False
        iken WAIT_RETRACE'e sokabiliyor. Upstream'de engelle.
        """
        # [FIX-1] Sweep yoksa MSS taraması yapma — upstream correctness
        if since_bar_index is None:
            logger.debug("[MSS] %s since_bar_index=None → sweep yok, MSS taraması atlandı", symbol)
            return []

        events: list[dict] = []
        self._mss_state.ingest(bars_15m, left=3, right=3)
        chochs = detect_mss(bars_15m, self._mss_state, timeframe="15m")

        for c in chochs:
            # Sweep öncesi MSS'leri atla
            if since_bar_index is not None and c.bar_index < since_bar_index:
                continue

            key = hash((c.bar_index, c.direction, c.level))
            if key in self._seen_mss:
                continue
            self._seen_mss.add(key)

            direction = "LONG" if c.direction == "bullish" else "SHORT"

            # Bias filtresi — ters yön MSS emit edilmez
            if direction != bias:
                logger.debug(
                    "[MSS] %s yön %s bias=%s ile uyumsuz, atlandı",
                    symbol,
                    direction,
                    bias,
                )
                continue

            # --- impulse_origin: MSS kırılım barından önceki son karşı-yön pivot ---
            impulse_origin: float | None = None
            if direction == "LONG":
                # Bullish MSS → kırılımdan önceki son swing LOW (impulse dip)
                pre_mss = [b for b in bars_15m if b.index < c.bar_index]
                if pre_mss:
                    pre_lows = find_swing_lows(pre_mss, left=2, right=2)
                    if pre_lows:
                        impulse_origin = pre_lows[-1].price
            else:
                # Bearish MSS → kırılımdan önceki son swing HIGH (impulse tepe)
                pre_mss = [b for b in bars_15m if b.index < c.bar_index]
                if pre_mss:
                    pre_highs = find_swing_highs(pre_mss, left=2, right=2)
                    if pre_highs:
                        impulse_origin = pre_highs[-1].price

            logger.info(
                "[MSS-EMIT] symbol=%s sweep_since=%s mss_bar=%s dir=%s impulse_origin=%.5f",
                symbol,
                since_bar_index,
                c.bar_index,
                direction,
                impulse_origin if impulse_origin is not None else c.level,
            )
            events.append(
                {
                    "type": "MSS",
                    "symbol": symbol,
                    "level": c.level,
                    "direction": direction,
                    "tf": "15m",
                    "bar_index": c.bar_index,
                    "impulse_origin": impulse_origin if impulse_origin is not None else c.level,
                }
            )

        return events

    # ── 3. FVG ─────────────────────────────────────────────────────────────────
    # Retrace kontrolü artık state_machine._check_retrace() içinde yapılıyor.
    # Analyzer sadece FVG_CREATED event'i üretir; state machine her barda
    # kendi fvg_upper/lower referansıyla retrace olup olmadığını kontrol eder.

    # ── 4. LTF CONFIRM (1m) ────────────────────────────────────────────────────

    @staticmethod
    def _find_retracement_swing(
        bars_m1: list[Bar],
        fvg_entry_bar_timestamp: int,
        direction: str,
        left: int = 1,
        right: int = 1,
    ) -> SwingPoint | None:
        """
        Retracement başladıktan (fvg_entry_bar_timestamp) sonra oluşan
        son karşı-yön pivot'u döndürür.

        Args:
            bars_m1: 1m bar listesi
            fvg_entry_bar_timestamp: FVG oluşum zamanı (millisecond timestamp)
                                     0 ise tüm bars_m1 kullanılır (temporal filter yok)
            direction: "LONG" veya "SHORT"
            left: pivot sol pencere
            right: pivot sağ pencere

        LONG  → retracement aşağı → son 1m swing HIGH aranır
                (fiyat bu high'ı yukarı kırınca dönüş teyitlenir)
        SHORT → retracement yukarı → son 1m swing LOW aranır
                (fiyat bu low'u aşağı kırınca dönüş teyitlenir)
        """
        # Temporal filter: FVG timestamp'inden sonraki bar'ları al
        if fvg_entry_bar_timestamp > 0:
            post_entry = [b for b in bars_m1 if b.timestamp >= fvg_entry_bar_timestamp]
        else:
            # Fallback: tüm bars_m1 kullan (timestamp bilinmiyorsa)
            post_entry = bars_m1

        if len(post_entry) < left + right + 1:
            return None

        candidates: list[SwingPoint] = []
        for i in range(left, len(post_entry) - right):
            bar = post_entry[i]
            if direction == "LONG":
                is_pivot = all(bar.high >= post_entry[i - j].high for j in range(1, left + 1)) and all(
                    bar.high >= post_entry[i + j].high for j in range(1, right + 1)
                )
                if is_pivot:
                    candidates.append(
                        SwingPoint(
                            price=bar.high,
                            bar_index=bar.index,
                            kind="high",
                            mitigated=False,
                        )
                    )
            else:  # SHORT
                is_pivot = all(bar.low <= post_entry[i - j].low for j in range(1, left + 1)) and all(
                    bar.low <= post_entry[i + j].low for j in range(1, right + 1)
                )
                if is_pivot:
                    candidates.append(
                        SwingPoint(
                            price=bar.low,
                            bar_index=bar.index,
                            kind="low",
                            mitigated=False,
                        )
                    )

        return candidates[-1] if candidates else None

    def _detect_ltf_confirm(
        self,
        symbol: str,
        fvgs: list[FVG],
        bars_m1: list[Bar],
        current_close: float,
        fvg_timestamp_map: dict[int, int] | None = None,
    ) -> list[dict]:
        """
        1m LTF onayı — LTFTriggerDetector V1 kullanır.
        retracement_swing: FVG'ye girişten sonra oluşan son karşı-yön pivot.

        NOT: FVG event'inden gelen 'time' field'i artık timestamp (ms) içeriyor.
        Bar.index TF-specific olduğu için timestamp ile karşılaştırma yapılıyor.
        """
        from mss import LTFTriggerDetector

        for f in fvgs:
            if not f.is_active:
                continue

            direction = "LONG" if f.direction == "bullish" else "SHORT"

            # Temporal filter: FVG timestamp → fvg_timestamp_map'ten al,
            # bulunamazsa tüm bars_m1 kullanılır (temporal filter devre dışı).

            if not bars_m1:
                continue

            fvg_ts = fvg_timestamp_map.get(f.real_index, 0) if fvg_timestamp_map else 0
            if fvg_ts == 0:
                logger.debug("[LTF] %s FVG ts bulunamadı (idx=%s) — temporal filter devre dışı", symbol, f.real_index)
            retracement_swing = self._find_retracement_swing(
                bars_m1=bars_m1,
                fvg_entry_bar_timestamp=fvg_ts,
                direction=direction,
            )

            if retracement_swing is None:
                logger.debug("[LTF] %s retracement_swing bulunamadı — confirm bekliyor", symbol)
                continue

            detector = LTFTriggerDetector()
            result = detector.validate(
                bars=bars_m1,
                direction=f.direction,
                retracement_swing=retracement_swing,
            )

            if result.is_valid:
                return [
                    {
                        "type": "LTF_CONFIRM",
                        "symbol": symbol,
                        "tf": "1m",
                        "direction": direction,
                        "fvg_top": f.top,
                        "fvg_bottom": f.bottom,
                        "close": bars_m1[-1].close,
                    }
                ]

        return []

    # ── Ana giriş noktası ──────────────────────────────────────────────────────

    def analyze(
        self,
        bars_d1: list[Bar],
        bars_h4: list[Bar],
        bars_h1: list[Bar],  # geriye dönük uyumluluk için tutuldu
        bars_15m: list[Bar],
        bars_m1: list[Bar],
    ) -> list[dict]:
        """
        Piyasa koşullarını değerlendirir, ham yapısal event listesi döner.

        Akış:
          0. HTF Bias    — 1D BOS (4H teyit). Bias yoksa → boş liste.
          1. SWEEP       — H1 likidite süpürmesi (H1'de bulunamazsa 2H fallback)
          2. MSS         — 15m CHoCH, sweep bar'ından sonraki yapı kırılımı
          3. FVG         — 1H/2H FVG, MSS bar'ından sonraki boşluklar
          4. LTF_CONFIRM — 1m V1 pivot kırılımı onayı
          (Retrace kontrolü artık state_machine._check_retrace() içinde)

        Returns:
            list[dict]: Ham event dict listesi.
        """
        events: list[dict] = []

        try:
            if not all([bars_d1, bars_15m, bars_m1]):
                return events

            current_close = bars_15m[-1].close

            # 0 ─ HTF Bias (ANA FİLTRE)
            bias, strength = self._detect_htf_bias(bars_d1, bars_h4)
            if bias is None:
                logger.info("[ANALYZE] %s: HTF bias yok, event üretilmiyor.", self.symbol)
                return events

            # D1 bar değişti mi? → likidite havuzunu sıfırla
            if bars_d1:
                last_d1_idx = bars_d1[-1].index
                if last_d1_idx != self._last_d1_index:
                    self._consumed_levels.clear()
                    self._emitted_fvg_ids.clear()
                    self._last_d1_index = last_d1_idx
                    logger.info("[RESET] %s günlük likidite havuzu sıfırlandı", self.symbol)

            logger.info(
                "[ANALYZE] %s | bias=%s | strength=%s | close=%.5f",
                self.symbol,
                bias,
                strength,
                current_close,
            )

            # Bias event — state_machine takip etsin
            events.append(
                {
                    "type": "HTF_BIAS",
                    "symbol": self.symbol,
                    "direction": bias,
                    "strength": strength,
                }
            )

            # HTF seviyeleri (SL/TP referansı)
            h4_sl = self._detect_h4_swing_level(bars_h4, bias)
            h1_tp = self._detect_h1_liquidity(bars_h1, bias)
            events.append(
                {
                    "type": "HTF_LEVELS",
                    "symbol": self.symbol,
                    "h4_swing_level": h4_sl,
                    "h1_liquidity_level": h1_tp,
                }
            )

            # 1 ─ SWEEP (H1 → 15m fallback)
            sweep_events = self._detect_sweep_h1(self.symbol, bars_h1, bars_15m, bias)
            events.extend(sweep_events)

            # Sweep bar index'ini sonraki adımlar için belirle
            sweep_bar_indices = [ev["bar_index"] for ev in sweep_events if "bar_index" in ev]
            sweep_since = max(sweep_bar_indices) if sweep_bar_indices else None

            # 2 ─ MSS (15m) — sweep sonrası yapı kırılımı
            # [FIX-2] MSS artık FVG'den ÖNCE çağrılıyor
            mss_events = self._detect_mss_events(self.symbol, bars_15m, bias, since_bar_index=sweep_since)
            events.extend(mss_events)

            # 3 — FVG (sweep tf'e göre kaynak belirle)
            fvg_direction = "bullish" if bias == "LONG" else "bearish"

            # Sweep tf'e göre FVG kaynak belirle
            sweep_tf = sweep_events[0]["tf"] if sweep_events else "1H"
            use_15m_fvg = sweep_tf == "15m"

            if use_15m_fvg:
                # 15m sweep → sadece 15m FVG
                fvgs_eff = detect_fvgs(
                    bars_15m, lookback=20, timeframe="15m", min_fvg_size=MIN_FVG_SIZE, since_index=None
                )
                fvgs_eff = [f for f in fvgs_eff if f.direction == fvg_direction]
                update_fvg_states(fvgs_eff, bars_15m)
                fvgs_eff = cleanup_fvgs(fvgs_eff, bars_15m[-1].index)
                fvgs_eff = sorted(fvgs_eff, key=lambda f: abs(f.top - f.bottom), reverse=True)
                validated_map = {f.real_index: False for f in fvgs_eff}

                # Build timestamp lookup for 15m bars
                bar_timestamps_15m = {b.index: b.timestamp for b in bars_15m}

                # [FIX-7] FVG timestamp map — _detect_ltf_confirm için
                fvg_timestamp_map = {f.real_index: bar_timestamps_15m.get(f.real_index, 0) for f in fvgs_eff}

                # Emit 15m FVGs with robust duplicate key
                new_keys = set()
                for f in fvgs_eff:
                    key = ("15m", round(float(f.top), 5), round(float(f.bottom), 5), int(f.real_index))
                    if key in self._emitted_fvg_ids:
                        continue
                    new_keys.add(key)
                    fvg_timestamp = bar_timestamps_15m.get(f.real_index, 0)
                    events.append(
                        {
                            "type": "FVG_CREATED",
                            "symbol": self.symbol,
                            "upper": f.top,
                            "lower": f.bottom,
                            "ce_level": (f.top + f.bottom) / 2.0,
                            "time": fvg_timestamp,
                            "bar_index": f.real_index,
                            "direction": f.direction,
                            "is_active": getattr(f, "is_active", True),
                            "tf": "15m",
                            "validated": False,
                        }
                    )
                for kf in new_keys:
                    self._emitted_fvg_ids.add(kf)
            else:
                # 1H sweep → mevcut 1H + 2H validation mantığı
                fvgs_h1: list[FVG] = []
                if bars_h1 and len(bars_h1) >= 5:
                    fvgs_h1 = detect_fvgs(
                        bars_h1, lookback=20, timeframe="1H", min_fvg_size=MIN_FVG_SIZE, since_index=None
                    )
                    fvgs_h1 = [f for f in fvgs_h1 if f.direction == fvg_direction]

                # 2H prepared only for validation
                fvgs_2h: list[FVG] = []
                bars_2h = None
                if bars_h1 and len(bars_h1) >= 4:
                    bars_2h = _resample_to_2h(bars_h1)
                    if bars_2h:
                        fvgs_2h = detect_fvgs(
                            bars_2h, lookback=10, timeframe="2H", min_fvg_size=MIN_FVG_SIZE, since_index=None
                        )
                        fvgs_2h = [f for f in fvgs_2h if f.direction == fvg_direction]

                # Update states and cleanup for H1 FVGs before clustering
                if fvgs_h1 and bars_h1:
                    update_fvg_states(fvgs_h1, bars_h1)
                    fvgs_h1 = cleanup_fvgs(fvgs_h1, bars_h1[-1].index)

                # Cluster 1H FVGs
                try:
                    atr_h1 = compute_atr_point(bars_h1, period=14) if bars_h1 else 0.0
                except Exception:
                    atr_h1 = 0.0
                k = getattr(config, "FVG_CLUSTER_ATR_MULT", 0.4)
                max_gap = max(0.0, (atr_h1 or 0.0) * k)
                fvgs_eff = _cluster_fvgs(fvgs_h1, max_gap=max_gap)

                # Validate by 2H overlap
                overlap_min = getattr(config, "FVG_OVERLAP_MIN", 0.60)
                validated_map: dict[int, bool] = {}
                if fvgs_2h:
                    for f in fvgs_eff:
                        ok = False
                        for g in fvgs_2h:
                            if g.direction != f.direction:
                                continue
                            ov = _interval_overlap_ratio(f.bottom, f.top, g.bottom, g.top)
                            if ov >= overlap_min:
                                ok = True
                                break
                        validated_map[f.real_index] = ok
                else:
                    for f in fvgs_eff:
                        validated_map[f.real_index] = False

                # Sort 1H FVGs: validated first, then by size
                fvgs_eff.sort(key=lambda f: (not validated_map.get(f.real_index, False), -abs(f.top - f.bottom)))

                # Build timestamp lookup for 1H bars
                bar_timestamps_h1 = {b.index: b.timestamp for b in bars_h1} if bars_h1 else {}

                # [FIX-7] FVG timestamp map — _detect_ltf_confirm için
                fvg_timestamp_map = {f.real_index: bar_timestamps_h1.get(f.real_index, 0) for f in fvgs_eff}

                # Emit 1H FVGs with robust duplicate key
                new_keys = set()
                for f in fvgs_eff:
                    key = ("1H", round(float(f.top), 5), round(float(f.bottom), 5), int(f.real_index))
                    if key in self._emitted_fvg_ids:
                        continue
                    new_keys.add(key)
                    fvg_timestamp = bar_timestamps_h1.get(f.real_index, 0)
                    events.append(
                        {
                            "type": "FVG_CREATED",
                            "symbol": self.symbol,
                            "upper": f.top,
                            "lower": f.bottom,
                            "ce_level": (f.top + f.bottom) / 2.0,
                            "time": fvg_timestamp,
                            "bar_index": f.real_index,
                            "direction": f.direction,
                            "is_active": getattr(f, "is_active", True),
                            "tf": "1H",
                            "validated": bool(validated_map.get(f.real_index, False)),
                        }
                    )
                for kf in new_keys:
                    self._emitted_fvg_ids.add(kf)
            # 4 ─ LTF_CONFIRM (1m) — pivot kırılımı onayı
            # LTF confirm için bars_h1 üzerinden değil hâlâ 1m barları kullanılır
            events.extend(self._detect_ltf_confirm(self.symbol, fvgs_eff, bars_m1, current_close, fvg_timestamp_map))
        except Exception as exc:
            logger.error(
                "[ANALYZE] %s event production error: %s",
                self.symbol,
                exc,
                exc_info=True,
            )

        return events
