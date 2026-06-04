"""
analyzer.py
───────────
V3 Event-Driven Architecture — Stateless Event Producer (Sensor).
Produces raw market-structure events: SWEEP, MSS, FVG_CREATED, RETRACE, LTF_CONFIRM.
No trading decisions, no scoring, no ADX, no trend vetoes.
Pure observation → list[dict] output.

V3.1 Değişiklikler:
  - HTF bias tespiti eklendi (1D BOS yönü, 4H teyit)
  - Sweep 1H → 15m'e taşındı

  - LTFTriggerDetector V1 (2 kriter) bağlandı
  - bars_d1 / bars_h4 artık aktif olarak kullanılıyor
"""

from __future__ import annotations

import logging
from typing import Literal

import config
from fvg import MIN_FVG_SIZE, detect_fvgs, update_fvg_states, cleanup_fvgs
from models import FVG, Bar, SwingPoint
from mss import detect_mss
from pivot import SwingStateManager, find_swing_highs, find_swing_lows

logger = logging.getLogger("nexus.analyzer")


def create_mss_event(symbol: str, timeframe: str, direction: str, level: float, timestamp: int) -> dict:
    """Converts a structural Market Structure Shift (MSS) into a normalized V3 market event."""
    return {
        "type": "MSS",
        "tf": timeframe,
        "direction": direction,  # "LONG" veya "SHORT"
        "level": float(level),
        "time": int(timestamp),
    }


class MarketAnalyzer:
    """
    V3 Stateless Event Producer (Sensor).
    Evaluates current market conditions and emits raw structural events.
    No trading logic, no scoring — just reports the facts.

    Akış:
      0. HTF BIAS  — 1D BOS yönü (4H teyit). Bias yoksa hiç event üretme.
      1. SWEEP     — 15m likidite süpürmesi
      2. MSS       — 15m Market Structure Shift (CHoCH)
      3. FVG       — 15m Fair Value Gap tespiti
      5. LTF_CONFIRM — 5m V1 momentum onayı (2 kriter)
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._mss_state = SwingStateManager()
        self._seen_mss: set[int] = set()
        self._emitted_fvg_ids: set[int] = set()
        self._consumed_levels: dict[str, set[float]] = {}
        self._last_d1_index: int = -1

    # ── 0. HTF BIAS ────────────────────────────────────────

    @staticmethod
    def _detect_htf_bias(
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
          - H4 aynı yöndeyse → STRONG
          - H4 yoksa → MODERATE
          - H4 tersse ve strict=True → bias yok, "WEAK"
          - H4 tersse ve strict=False → bias var ama "WEAK"
        """
        if not bars_d1 or len(bars_d1) < 5:
            return None, "NONE"

        # ── D1 BOS tespiti ──
        lookback_d1 = min(config.D1_BOS_LOOKBACK, len(bars_d1))
        segment_d1 = bars_d1[-lookback_d1:]

        d1_highs = find_swing_highs(segment_d1, left=2, right=2)
        d1_lows = find_swing_lows(segment_d1, left=2, right=2)

        last_close_d1 = bars_d1[-1].close

        # En son kırılan swing hangisi? (bar_index büyük olan daha güncel)
        last_bull_bos: int = -1
        last_bear_bos: int = -1

        for sh in d1_highs:
            if last_close_d1 > sh.price:
                if sh.bar_index > last_bull_bos:
                    last_bull_bos = sh.bar_index

        for sl in d1_lows:
            if last_close_d1 < sl.price:
                if sl.bar_index > last_bear_bos:
                    last_bear_bos = sl.bar_index

        if last_bull_bos == -1 and last_bear_bos == -1:
            logger.debug("[BIAS] %s: D1 BOS bulunamadı", "symbol")
            return None, "NONE"

        d1_bias: Literal["LONG", "SHORT"]
        if last_bull_bos >= last_bear_bos:
            d1_bias = "LONG"
        else:
            d1_bias = "SHORT"

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

        # ── UYUMSUZLUK: H4 ters ──
        if h4_bias is not None and h4_bias != d1_bias:
            if config.HTF_STRICT_FILTER:
                logger.warning("[BIAS] %s: D1=%s H4=%s → UYUMSUZ, zincir kiriliyor",
                               "symbol", d1_bias, h4_bias)
                return None, "WEAK"
            else:
                logger.warning("[BIAS] %s: D1=%s H4=%s → ZAYIF (filtre kapali, D1 kazandi)",
                               "symbol", d1_bias, h4_bias)
                return d1_bias, "WEAK"

        # ── UYUMLU: H4 aynı ──
        if h4_bias == d1_bias:
            logger.info("[BIAS] %s: D1=%s H4=%s → GUCLU", "symbol", d1_bias, h4_bias)
            return d1_bias, "STRONG"

        # ── H4 None ──
        logger.info("[BIAS] %s: D1=%s H4=belirsiz → MODERATE", "symbol", d1_bias)
        return d1_bias, "MODERATE"

    # ── HTF Seviyeleri (SL/TP referansı) ────────────────────

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
        else:
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
        else:
            lows = find_swing_lows(bars_h1, left=3, right=3)
            return lows[-1].price if lows else None

    # ── 1. SWEEP (15m) ─────────────────────────────────────

    def _detect_sweep_15m(
        self,
        symbol: str,
        bars_15m: list[Bar],
        current_close: float,
        bias: Literal["LONG", "SHORT"],
    ) -> list[dict]:
        """
        15m swing high/low sweep tespiti.
        Bias yönüne göre sadece ilgili taraf taranır:
          LONG  → SSL (swing low sweep) aranır — fiyat düşük likiditesi aldı
          SHORT → BSL (swing high sweep) aranır — fiyat yüksek likiditesi aldı
        """
        consumed = self._consumed_levels.setdefault(symbol, set())
        events: list[dict] = []
        highs = find_swing_highs(bars_15m, left=3, right=3)
        lows = find_swing_lows(bars_15m, left=3, right=3)

        if bias == "LONG":
            # SSL sweep: fiyat swing low altına indi
            for sl in reversed(lows[-5:]):
                if sl.price in consumed:
                    continue
                if current_close < sl.price:
                    consumed.add(sl.price)
                    events.append(
                        {
                            "type": "SWEEP",
                            "symbol": symbol,
                            "level": sl.price,
                            "tf": "15m",
                            "side": "SSL",
                            "bar_index": sl.bar_index,          # YENİ
                        }
                    )
                    break
        else:
            # BSL sweep: fiyat swing high üstüne çıktı
            for sh in reversed(highs[-5:]):
                if sh.price in consumed:
                    continue
                if current_close > sh.price:
                    consumed.add(sh.price)
                    events.append(
                        {
                            "type": "SWEEP",
                            "symbol": symbol,
                            "level": sh.price,
                            "tf": "15m",
                            "side": "BSL",
                            "bar_index": sh.bar_index,          # YENİ
                        }
                    )
                    break

        logger.debug(
            "[SWEEP-CHECK] %s | bias=%s | close=%.5f | lows=%s | highs=%s | events=%s",
            symbol,
            bias,
            current_close,
            [round(s.price, 4) for s in lows[-5:]],
            [round(s.price, 4) for s in highs[-5:]],
            events,
        )

        return events

    # ── 2. MSS (15m) ───────────────────────────────────────

    def _detect_mss_events(
        self,
        symbol: str,
        bars_15m: list[Bar],
        bias: Literal["LONG", "SHORT"],
    ) -> list[dict]:
        """
        15m CHoCH/BOS tespiti. Bias yönüyle eşleşen MSS'ler emit edilir.
        Ters yön MSS'ler (counter-trend) filtrelenir.
        """
        events: list[dict] = []
        self._mss_state.ingest(bars_15m, left=3, right=3)
        chochs = detect_mss(bars_15m, self._mss_state, timeframe="15m")

        for c in chochs:
            key = hash((c.bar_index, c.direction, c.level))
            if key in self._seen_mss:
                continue
            self._seen_mss.add(key)

            direction = "LONG" if c.direction == "bullish" else "SHORT"

            # Bias filtresi — ters yön MSS emit edilmez
            if direction != bias:
                logger.debug("[MSS] %s yön %s bias ile uyumsuz, atlandı", direction, bias)
                continue

            events.append(
                {
                    "type": "MSS",
                    "symbol": symbol,
                    "level": c.level,
                    "direction": direction,
                    "tf": "15m",
                    "bar_index": c.bar_index,
                }
            )

        return events

    # ── 3-4. FVG & RETRACE ─────────────────────────────────

    @staticmethod
    def _detect_retrace(
        symbol: str,
        fvgs: list[FVG],
        current_bar: Bar,
        bias: Literal["LONG", "SHORT"],
    ) -> list[dict]:
        """
        3-Aşamalı SMC Retrace Filtresi:
          1. KESİŞİM (Touch):   Mum fitili FVG içine girdi mi?
          2. SAYGI (Respect):    Kurumsal para FVG'yi delip geçmedi mi?
          3. DERİNLİK (CE Tap):  Fitil FVG'nin %50'sine (Consequent Encroachment) ulaştı mı?

        Invalidation: Kapanış FVG'yi delip geçerse FVG pasif edilir (invalidated=True).
        """
        for f in fvgs:
            if not f.is_active:
                continue

            # 1. KESİŞİM: Fitil FVG aralığına temas etti mi?
            touched = (current_bar.high >= f.bottom) and (current_bar.low <= f.top)
            logger.debug(
                "[RETRACE-DETAIL] %s | fvg=[%.5f-%.5f] touched=%s respected=%s deep=%s active=%s",
                symbol,
                f.bottom,
                f.top,
                touched,
                "N/A",
                "N/A",
                f.is_active,
            )
            if not touched:
                continue

            # 2. SAYGI: Kapanış FVG'yi delip geçmedi mi?
            if bias == "SHORT":
                respected = current_bar.close <= f.top
            else:  # LONG
                respected = current_bar.close >= f.bottom

            if not respected:
                # FVG delindi → Invalidate
                object.__setattr__(f, "invalidated", True)
                continue

            # 3. DERİNLİK (Consequent Encroachment)
            ce_level = (f.top + f.bottom) / 2.0
            if bias == "SHORT":
                deep_enough = current_bar.high >= ce_level
            else:  # LONG
                deep_enough = current_bar.low <= ce_level

            return [
                {
                    "type": "RETRACE",
                    "symbol": symbol,
                    "price": current_bar.close,
                    "fvg_upper": f.top,
                    "fvg_lower": f.bottom,
                    "bar_index": current_bar.index,
                    "is_active": f.is_active,    # ← EKLE: state machine kontrol etsin
                    "is_ce_tap": deep_enough,
                }
            ]

        return []

    # ── 5. LTF CONFIRM (5m, V1 — 2 kriter) ────────────────

    @staticmethod
    def _find_retracement_swing(
        bars_m5: list[Bar],
        fvg_entry_bar_index: int,
        direction: str,
        left: int = 1,
        right: int = 1,
    ) -> SwingPoint | None:
        """
        Retracement başladıktan (fvg_entry_bar_index) sonra oluşan
        son karşı-yön pivot'u döndürür.

        LONG setup  → retracement aşağı gidiyor → son 5m swing HIGH arıyoruz
        (fiyat bu high'ı yukarı kırınca dönüş teyitlenir)

        SHORT setup → retracement yukarı gidiyor → son 5m swing LOW arıyoruz
        (fiyat bu low'u aşağı kırınca dönüş teyitlenir)
        """
        post_entry = [b for b in bars_m5 if b.index >= fvg_entry_bar_index]
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
        bars_m5: list[Bar],
        current_close: float,
    ) -> list[dict]:
        """
        5m LTF onayı — LTFTriggerDetector V1 (2 kriter) kullanır.
        retracement_swing: FVG'ye girişten sonra oluşan son karşı-yön pivot.
        """
        from mss import LTFTriggerDetector

        for f in fvgs:
            if not f.is_active:
                continue
            if f.bottom <= current_close <= f.top:
                direction = "LONG" if f.direction == "bullish" else "SHORT"

                # FVG'ye ilk giriş bar'ını 5m barlardan bul
                fvg_entry_bar_index: int | None = None
                for b in bars_m5:
                    if b.index >= f.real_index and f.bottom <= b.close <= f.top:
                        fvg_entry_bar_index = b.index
                        break

                if fvg_entry_bar_index is None:
                    continue

                retracement_swing = self._find_retracement_swing(
                    bars_m5=bars_m5,
                    fvg_entry_bar_index=fvg_entry_bar_index,
                    direction=direction,
                )

                if retracement_swing is None:
                    logger.debug("[LTF] %s retracement_swing bulunamadı — confirm bekliyor", symbol)
                    continue

                detector = LTFTriggerDetector()
                result = detector.validate(
                    bars=bars_m5,
                    direction=f.direction,
                    retracement_swing=retracement_swing,
                )

                if result.is_valid:
                    return [
                        {
                            "type": "LTF_CONFIRM",
                            "symbol": symbol,
                            "tf": "5m",
                            "direction": direction,
                            "fvg_top": f.top,
                            "fvg_bottom": f.bottom,
                            "close": bars_m5[-1].close,
                        }
                    ]
        return []

    # ── Ana giriş noktası ──────────────────────────────────

    def analyze(
        self,
        bars_d1: list[Bar],
        bars_h4: list[Bar],
        bars_h1: list[Bar],  # geriye dönük uyumluluk için tutuldu, kullanılmıyor
        bars_15m: list[Bar],
        bars_m5: list[Bar],
    ) -> list[dict]:
        """
        Piyasa koşullarını değerlendirir, ham yapısal event listesi döner.

        Akış:
          0. HTF Bias  — 1D BOS (4H teyit). Bias yoksa → boş liste.
          1. SWEEP     — 15m likidite süpürmesi (bias yönüne göre)
          2. MSS       — 15m CHoCH (bias yönüyle eşleşen)
          3. FVG       — 15m FVG tespiti
          4. RETRACE   — Fiyat FVG içinde mi?
          5. LTF_CONFIRM — 5m V1 2-kriter onayı

        Returns:
            list[dict]: Ham event dict listesi.
        """
        events: list[dict] = []

        try:
            if not all([bars_d1, bars_15m, bars_m5]):
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
                bars_15m[-1].close,
            )

            # Bias event olarak da emit et — state_machine takip etsin
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

            # 1 ─ SWEEP on 15m
            sweep_events = self._detect_sweep_15m(self.symbol, bars_15m, current_close, bias)
            events.extend(sweep_events)

            # 2 ─ FVG — SADECE sweep sonrası (MSS henüz yok)
            sweep_indices = [ev.get("bar_index") for ev in sweep_events if ev.get("bar_index") is not None]
            fvg_since = max(sweep_indices) if sweep_indices else None
            effective_lookback = 60
            if fvg_since is not None and len(bars_15m) > 0:
                effective_lookback = min(60, max(10, len(bars_15m) - fvg_since))
            fvgs = detect_fvgs(
                bars_15m,
                lookback=effective_lookback,
                timeframe="15m",
                min_fvg_size=MIN_FVG_SIZE,
                since_index=fvg_since,
            )
            # Bias yönüyle eşleşen FVG'leri filtrele
            fvg_direction = "bullish" if bias == "LONG" else "bearish"
            fvgs = [f for f in fvgs if f.direction == fvg_direction]

            # FVG state'lerini güncelle (filled/invalidated) ve yaşlıları temizle
            update_fvg_states(fvgs, bars_15m)
            fvgs = cleanup_fvgs(fvgs, bars_15m[-1].index)

            new_fvgs = [f for f in fvgs if f.real_index not in self._emitted_fvg_ids]
            for f in new_fvgs:
                self._emitted_fvg_ids.add(f.real_index)
            events.extend(
                {
                    "type": "FVG_CREATED",
                    "symbol": self.symbol,
                    "upper": f.top,
                    "lower": f.bottom,
                    "time": f.real_index,
                    "bar_index": f.real_index,
                    "direction": f.direction,
                    "is_active": f.is_active,
                }
                for f in new_fvgs
            )

            # 3 ─ MSS — FVG'den SONRA
            mss_events = self._detect_mss_events(self.symbol, bars_15m, bias)
            events.extend(mss_events)

            # 4 ─ RETRACE
            events.extend(self._detect_retrace(self.symbol, fvgs, bars_15m[-1], bias))

            # 5 ─ LTF_CONFIRM (V1 — 2 kriter)
            events.extend(self._detect_ltf_confirm(self.symbol, fvgs, bars_m5, current_close))

        except Exception as exc:
            logger.error(
                "[ANALYZE] %s event production error: %s",
                self.symbol,
                exc,
                exc_info=True,
            )

        return events
