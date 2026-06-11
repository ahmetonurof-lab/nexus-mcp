"""
analyzer.py
ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
V3 Event-Driven Architecture ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Stateless Event Producer (Sensor).
Produces raw market-structure events: SWEEP, MSS, FVG_CREATED, RETRACE, LTF_CONFIRM.
No trading decisions, no scoring, no ADX, no trend vetoes.
Pure observation ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ list[dict] output.

V3.2 DeÃƒâ€žÃ…Â¸iÃƒâ€¦Ã…Â¸iklikler:
  - [FIX-1] Sweep tespiti dÃƒÆ’Ã‚Â¼zeltildi: close kontrolÃƒÆ’Ã‚Â¼ ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ wick kÃƒâ€žÃ‚Â±r + close iÃƒÆ’Ã‚Â§eri
  - [FIX-2] analyze() sÃƒâ€žÃ‚Â±rasÃƒâ€žÃ‚Â± dÃƒÆ’Ã‚Â¼zeltildi: sweep ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ MSS ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ FVG (eski: sweep ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ FVG ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ MSS)
  - [FIX-3] fvg_since hesabÃƒâ€žÃ‚Â± dÃƒÆ’Ã‚Â¼zeltildi: mutlak bar index doÃƒâ€žÃ…Â¸ru kullanÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor
  - [FIX-4] consumed_levels float precision: round(price, 5) ile normalize
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
            cur = FVG(direction=cur.direction, top=new_top, bottom=new_bottom, real_index=cur.real_index, timeframe=cur.timeframe)
        else:
            out.append(cur)
            cur = f
    out.append(cur)
    return out


def _resample_to_2h(bars_h1: list[Bar]) -> list[Bar]:
    """2 adet 1H barÃƒâ€žÃ‚Â± birleÃƒâ€¦Ã…Â¸tirerek sentetik 2H bar ÃƒÆ’Ã‚Â¼retir."""
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
    No trading logic, no scoring ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â just reports the facts.

    AkÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸:
      0. HTF BIAS    ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1D BOS yÃƒÆ’Ã‚Â¶nÃƒÆ’Ã‚Â¼ (4H teyit). Bias yoksa hiÃƒÆ’Ã‚Â§ event ÃƒÆ’Ã‚Â¼retme.
      1. SWEEP       ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â H1 likidite sÃƒÆ’Ã‚Â¼pÃƒÆ’Ã‚Â¼rmesi (H1'de bulunamazsa 2H fallback)
      2. MSS         ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 15m Market Structure Shift (CHoCH), sweep sonrasÃƒâ€žÃ‚Â±
      3. FVG         ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1H/2H Fair Value Gap tespiti, MSS sonrasÃƒâ€žÃ‚Â±
      4. RETRACE     ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Fiyat FVG iÃƒÆ’Ã‚Â§inde mi? CE tap var mÃƒâ€žÃ‚Â±?
      5. LTF_CONFIRM ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1m V1 momentum onayÃƒâ€žÃ‚Â±
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._mss_state = SwingStateManager()
        self._seen_mss: set[int] = set()
        self._emitted_fvg_ids: set[int] = set()
        # [FIX-4] float ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ round(price, 5) normalize edilmiÃƒâ€¦Ã…Â¸ seviyeler saklanÃƒâ€žÃ‚Â±r
        self._consumed_levels: dict[str, set[float]] = {}
        self._last_d1_index: int = -1

    def reset_symbol_cache(self) -> None:
        """
        [FIX-2] State machine sembolÃƒÆ’Ã‚Â¼ IDLE'a dÃƒÆ’Ã‚Â¶ndÃƒÆ’Ã‚Â¼rdÃƒÆ’Ã‚Â¼Ãƒâ€žÃ…Â¸ÃƒÆ’Ã‚Â¼nde ÃƒÆ’Ã‚Â§aÃƒâ€žÃ…Â¸rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±r.

        Sorun: _emitted_fvg_ids ve _seen_mss sadece D1 bar deÃƒâ€žÃ…Â¸iÃƒâ€¦Ã…Â¸iminde
        temizleniyordu. State machine reset olduÃƒâ€žÃ…Â¸unda bu cache'ler temizlenmeden
        kalÃƒâ€žÃ‚Â±yor, aynÃƒâ€žÃ‚Â± FVG/MSS eventleri bir daha emit edilemiyor ve state
        WAIT_RETRACE'de fvg_upper=None ile mahsur kalÃƒâ€žÃ‚Â±yor.

        State machine = truth, analyzer cache = derived ephemeral state.
        State sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rlandÃƒâ€žÃ‚Â±Ãƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â±nda cache da sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rlanmalÃƒâ€žÃ‚Â±.

        _mss_state (SwingStateManager) da sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rlanÃƒâ€žÃ‚Â±r: reset sonrasÃƒâ€žÃ‚Â± aynÃƒâ€žÃ‚Â±
        swing bar'Ãƒâ€žÃ‚Â± "consumed" sayÃƒâ€žÃ‚Â±lmaya devam ederse detect_mss() o swing'i
        bir daha emit etmez ve yeni setup hiÃƒÆ’Ã‚Â§ baÃƒâ€¦Ã…Â¸lamaz (silent skip).
        """
        self._emitted_fvg_ids.clear()
        self._seen_mss.clear()
        self._mss_state = SwingStateManager()
        # _consumed_levels kasÃƒâ€žÃ‚Â±tlÃƒâ€žÃ‚Â± korunuyor: sweep seviyeleri D1 bazlÃƒâ€žÃ‚Â±,
        # symbol reset'ten baÃƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â±msÃƒâ€žÃ‚Â±z olarak geÃƒÆ’Ã‚Â§erliliÃƒâ€žÃ…Â¸ini korur.
        logger.debug("[CACHE-RESET] %s _emitted_fvg_ids + _seen_mss + _mss_state temizlendi", self.symbol)

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 0. HTF BIAS ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    @staticmethod
    def _detect_htf_bias(
        bars_d1: list[Bar],
        bars_h4: list[Bar],
    ) -> tuple[str | None, str]:
        """
        1D BOS yÃƒÆ’Ã‚Â¶nÃƒÆ’Ã‚Â¼nden ana bias'Ãƒâ€žÃ‚Â± belirler. 4H aynÃƒâ€žÃ‚Â± yÃƒÆ’Ã‚Â¶nde teyit ederse gÃƒÆ’Ã‚Â¼ÃƒÆ’Ã‚Â§lÃƒÆ’Ã‚Â¼ sinyal.

        Returns:
            (bias, strength) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â bias None ise strength "NONE" olur.
            strength: "STRONG" | "MODERATE" | "WEAK" | "NONE"

        Kural:
          - D1'de son D1_BOS_LOOKBACK bar iÃƒÆ’Ã‚Â§inde swing HIGH kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±ldÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ LONG
          - D1'de son D1_BOS_LOOKBACK bar iÃƒÆ’Ã‚Â§inde swing LOW  kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±ldÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ SHORT
          - Son kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±m hangisiyse bias odur (en gÃƒÆ’Ã‚Â¼ncel kazanÃƒâ€žÃ‚Â±r)
          - H4 aynÃƒâ€žÃ‚Â± yÃƒÆ’Ã‚Â¶ndeyse   ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ STRONG
          - H4 yoksa           ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ MODERATE
          - H4 tersse strict   ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ bias yok, "WEAK"
          - H4 tersse !strict  ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ bias var ama "WEAK"
        """
        if not bars_d1 or len(bars_d1) < 5:
            return None, "NONE"

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ D1 BOS tespiti ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
            logger.debug("[BIAS] %s: D1 BOS bulunamadÃƒâ€žÃ‚Â±", "symbol")
            return None, "NONE"

        d1_bias: Literal["LONG", "SHORT"] = "LONG" if last_bull_bos >= last_bear_bos else "SHORT"

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ H4 teyit ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ H4 ters ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        if h4_bias is not None and h4_bias != d1_bias:
            if config.HTF_STRICT_FILTER:
                logger.warning(
                    "[BIAS] %s: D1=%s H4=%s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ UYUMSUZ, zincir kiriliyor",
                    "symbol",
                    d1_bias,
                    h4_bias,
                )
                return None, "WEAK"
            logger.warning(
                "[BIAS] %s: D1=%s H4=%s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ ZAYIF (filtre kapali, D1 kazandi)",
                "symbol",
                d1_bias,
                h4_bias,
            )
            return d1_bias, "WEAK"

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ H4 aynÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        if h4_bias == d1_bias:
            logger.info("[BIAS] %s: D1=%s H4=%s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ GUCLU", "symbol", d1_bias, h4_bias)
            return d1_bias, "STRONG"

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ H4 belirsiz ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        logger.info("[BIAS] %s: D1=%s H4=belirsiz ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ MODERATE", "symbol", d1_bias)
        return d1_bias, "MODERATE"

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ HTF Seviyeleri (SL/TP referansÃƒâ€žÃ‚Â±) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    @staticmethod
    def _detect_h4_swing_level(
        bars_h4: list[Bar],
        bias: Literal["LONG", "SHORT"],
    ) -> float | None:
        """4H swing low (long) veya swing high (short) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â SL referansÃƒâ€žÃ‚Â±."""
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
        """1H BSL (long) veya SSL (short) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â TP referansÃƒâ€žÃ‚Â±."""
        if not bars_h1 or len(bars_h1) < 5:
            return None
        if bias == "LONG":
            highs = find_swing_highs(bars_h1, left=3, right=3)
            return highs[-1].price if highs else None
        lows = find_swing_lows(bars_h1, left=3, right=3)
        return lows[-1].price if lows else None

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 1. SWEEP (H1 ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ 2H fallback) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    def _detect_sweep_h1(
        self,
        symbol: str,
        bars_h1: list[Bar],
        bias: Literal["LONG", "SHORT"],
    ) -> list[dict]:
        """
        H1 swing high/low sweep tespiti. H1'de bulunamazsa 2H fallback.

        SHORT ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ BSL sweep: wick swing high ÃƒÆ’Ã‚Â¼stÃƒÆ’Ã‚Â¼ne ÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±ktÃƒâ€žÃ‚Â±, close iÃƒÆ’Ã‚Â§eri dÃƒÆ’Ã‚Â¶ndÃƒÆ’Ã‚Â¼
        LONG  ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ SSL sweep: wick swing low altÃƒâ€žÃ‚Â±na indi, close iÃƒÆ’Ã‚Â§eri dÃƒÆ’Ã‚Â¶ndÃƒÆ’Ã‚Â¼
        """
        # ÃƒÆ’Ã¢â‚¬â€œnce H1'de dene
        events = self._sweep_on_bars(symbol, bars_h1, bias, tf="1H")
        if events:
            return events

        # H1'de bulunamazsa 2H fallback
        bars_2h = _resample_to_2h(bars_h1)
        if bars_2h:
            events = self._sweep_on_bars(symbol, bars_2h, bias, tf="2H")

        return events

    def _sweep_on_bars(
        self,
        symbol: str,
        bars: list[Bar],
        bias: Literal["LONG", "SHORT"],
        tf: str,
    ) -> list[dict]:
        consumed = self._consumed_levels.setdefault(symbol, set())
        events: list[dict] = []
        current_bar = bars[-1]

        strength = getattr(config, "SWEEP_SWING_STRENGTH", 2)
        pen_atr_mult = getattr(config, "SWEEP_PENETRATION_ATR", 0.10)

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
                    if swing_size < atr * getattr(config, "SWEEP_PIVOT_QUALITY_ATR", 0.20):
                        continue

                penetration = sl.price - current_bar.low  # ne kadar aÃƒâ€¦Ã…Â¸aÃƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â± geÃƒÆ’Ã‚Â§ti
                if (
                    current_bar.low < sl.price  # swing low geÃƒÆ’Ã‚Â§ildi
                    and penetration >= min_penetration  # ATRÃƒÆ’Ã¢â‚¬â€0.10 kadar taÃƒâ€¦Ã…Â¸tÃƒâ€žÃ‚Â±
                    and current_bar.close > sl.price  # iÃƒÆ’Ã‚Â§eride kapandÃƒâ€žÃ‚Â±
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
                    if swing_size < atr * getattr(config, "SWEEP_PIVOT_QUALITY_ATR", 0.20):
                        continue

                penetration = current_bar.high - sh.price  # ne kadar yukarÃƒâ€žÃ‚Â± geÃƒÆ’Ã‚Â§ti
                if (
                    current_bar.high > sh.price  # swing high geÃƒÆ’Ã‚Â§ildi
                    and penetration >= min_penetration  # ATRÃƒÆ’Ã¢â‚¬â€0.10 kadar taÃƒâ€¦Ã…Â¸tÃƒâ€žÃ‚Â±
                    and current_bar.close < sh.price  # iÃƒÆ’Ã‚Â§eride kapandÃƒâ€žÃ‚Â±
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

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 2. MSS (15m) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    def _detect_mss_events(
        self,
        symbol: str,
        bars_15m: list[Bar],
        bias: Literal["LONG", "SHORT"],
        since_bar_index: int | None = None,
    ) -> list[dict]:
        """
        15m CHoCH/BOS tespiti. Bias yÃƒÆ’Ã‚Â¶nÃƒÆ’Ã‚Â¼yle eÃƒâ€¦Ã…Â¸leÃƒâ€¦Ã…Â¸en MSS'ler emit edilir.
        Ters yÃƒÆ’Ã‚Â¶n MSS'ler (counter-trend) filtrelenir.

        since_bar_index: sweep bar'Ãƒâ€žÃ‚Â±ndan sonraki MSS'leri filtreler.

        [FIX-1] since_bar_index=None ise sweep henÃƒÆ’Ã‚Â¼z gerÃƒÆ’Ã‚Â§ekleÃƒâ€¦Ã…Â¸memiÃƒâ€¦Ã…Â¸ demektir.
        Sweep anchor olmadan MSS emit etmek state machine'i sweep_detected=False
        iken WAIT_RETRACE'e sokabiliyor. Upstream'de engelle.
        """
        # [FIX-1] Sweep yoksa MSS taramasÃƒâ€žÃ‚Â± yapma ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â upstream correctness
        if since_bar_index is None:
            logger.debug("[MSS] %s since_bar_index=None ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ sweep yok, MSS taramasÃƒâ€žÃ‚Â± atlandÃƒâ€žÃ‚Â±", symbol)
            return []

        events: list[dict] = []
        self._mss_state.ingest(bars_15m, left=3, right=3)
        chochs = detect_mss(bars_15m, self._mss_state, timeframe="15m")

        for c in chochs:
            # Sweep ÃƒÆ’Ã‚Â¶ncesi MSS'leri atla
            if since_bar_index is not None and c.bar_index < since_bar_index:
                continue

            key = hash((c.bar_index, c.direction, c.level))
            if key in self._seen_mss:
                continue
            self._seen_mss.add(key)

            direction = "LONG" if c.direction == "bullish" else "SHORT"

            # Bias filtresi ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â ters yÃƒÆ’Ã‚Â¶n MSS emit edilmez
            if direction != bias:
                logger.debug(
                    "[MSS] %s yÃƒÆ’Ã‚Â¶n %s bias=%s ile uyumsuz, atlandÃƒâ€žÃ‚Â±",
                    symbol,
                    direction,
                    bias,
                )
                continue

            # --- impulse_origin: MSS kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±m barÃƒâ€žÃ‚Â±ndan ÃƒÆ’Ã‚Â¶nceki son karÃƒâ€¦Ã…Â¸Ãƒâ€žÃ‚Â±-yÃƒÆ’Ã‚Â¶n pivot ---
            impulse_origin: float | None = None
            if direction == "LONG":
                # Bullish MSS ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±mdan ÃƒÆ’Ã‚Â¶nceki son swing LOW (impulse dip)
                pre_mss = [b for b in bars_15m if b.index < c.bar_index]
                if pre_mss:
                    pre_lows = find_swing_lows(pre_mss, left=2, right=2)
                    if pre_lows:
                        impulse_origin = pre_lows[-1].price
            else:
                # Bearish MSS ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±mdan ÃƒÆ’Ã‚Â¶nceki son swing HIGH (impulse tepe)
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

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 3. FVG ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
    # Retrace kontrolÃƒÆ’Ã‚Â¼ artÃƒâ€žÃ‚Â±k state_machine._check_retrace() iÃƒÆ’Ã‚Â§inde yapÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor.
    # Analyzer sadece FVG_CREATED event'i ÃƒÆ’Ã‚Â¼retir; state machine her barda
    # kendi fvg_upper/lower referansÃƒâ€žÃ‚Â±yla retrace olup olmadÃƒâ€žÃ‚Â±Ãƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± kontrol eder.

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 4. LTF CONFIRM (1m) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    @staticmethod
    def _find_retracement_swing(
        bars_m1: list[Bar],
        fvg_entry_bar_index: int,
        direction: str,
        left: int = 1,
        right: int = 1,
    ) -> SwingPoint | None:
        """
        Retracement baÃƒâ€¦Ã…Â¸ladÃƒâ€žÃ‚Â±ktan (fvg_entry_bar_index) sonra oluÃƒâ€¦Ã…Â¸an
        son karÃƒâ€¦Ã…Â¸Ãƒâ€žÃ‚Â±-yÃƒÆ’Ã‚Â¶n pivot'u dÃƒÆ’Ã‚Â¶ndÃƒÆ’Ã‚Â¼rÃƒÆ’Ã‚Â¼r.

        LONG  ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ retracement aÃƒâ€¦Ã…Â¸aÃƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ son 1m swing HIGH aranÃƒâ€žÃ‚Â±r
                (fiyat bu high'Ãƒâ€žÃ‚Â± yukarÃƒâ€žÃ‚Â± kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±nca dÃƒÆ’Ã‚Â¶nÃƒÆ’Ã‚Â¼Ãƒâ€¦Ã…Â¸ teyitlenir)
        SHORT ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ retracement yukarÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ son 1m swing LOW aranÃƒâ€žÃ‚Â±r
                (fiyat bu low'u aÃƒâ€¦Ã…Â¸aÃƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â± kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±nca dÃƒÆ’Ã‚Â¶nÃƒÆ’Ã‚Â¼Ãƒâ€¦Ã…Â¸ teyitlenir)
        """
        post_entry = [b for b in bars_m1 if b.index >= fvg_entry_bar_index]
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
    ) -> list[dict]:
        """
        1m LTF onayÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â LTFTriggerDetector V1 kullanÃƒâ€žÃ‚Â±r.
        retracement_swing: FVG'ye giriÃƒâ€¦Ã…Â¸ten sonra oluÃƒâ€¦Ã…Â¸an son karÃƒâ€¦Ã…Â¸Ãƒâ€žÃ‚Â±-yÃƒÆ’Ã‚Â¶n pivot.
        """
        from mss import LTFTriggerDetector

        for f in fvgs:
            if not f.is_active:
                continue

            direction = "LONG" if f.direction == "bullish" else "SHORT"

            # FVG'ye ilk giriÃƒâ€¦Ã…Â¸ bar'Ãƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± 1m barlardan bul
            fvg_entry_bar_index: int | None = None
            for b in bars_m1:
                if b.index >= f.real_index:
                    fvg_entry_bar_index = b.index
                    break

            if fvg_entry_bar_index is None:
                continue

            retracement_swing = self._find_retracement_swing(
                bars_m1=bars_m1,
                fvg_entry_bar_index=fvg_entry_bar_index,
                direction=direction,
            )

            if retracement_swing is None:
                logger.debug("[LTF] %s retracement_swing bulunamadÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â confirm bekliyor", symbol)
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

    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Ana giriÃƒâ€¦Ã…Â¸ noktasÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    def analyze(
        self,
        bars_d1: list[Bar],
        bars_h4: list[Bar],
        bars_h1: list[Bar],  # geriye dÃƒÆ’Ã‚Â¶nÃƒÆ’Ã‚Â¼k uyumluluk iÃƒÆ’Ã‚Â§in tutuldu
        bars_15m: list[Bar],
        bars_m1: list[Bar],
    ) -> list[dict]:
        """
        Piyasa koÃƒâ€¦Ã…Â¸ullarÃƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± deÃƒâ€žÃ…Â¸erlendirir, ham yapÃƒâ€žÃ‚Â±sal event listesi dÃƒÆ’Ã‚Â¶ner.

        AkÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸:
          0. HTF Bias    ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1D BOS (4H teyit). Bias yoksa ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ boÃƒâ€¦Ã…Â¸ liste.
          1. SWEEP       ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â H1 likidite sÃƒÆ’Ã‚Â¼pÃƒÆ’Ã‚Â¼rmesi (H1'de bulunamazsa 2H fallback)
          2. MSS         ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 15m CHoCH, sweep bar'Ãƒâ€žÃ‚Â±ndan sonraki yapÃƒâ€žÃ‚Â± kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±mÃƒâ€žÃ‚Â±
          3. FVG         ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1H/2H FVG, MSS bar'Ãƒâ€žÃ‚Â±ndan sonraki boÃƒâ€¦Ã…Â¸luklar
          4. LTF_CONFIRM ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1m V1 pivot kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±mÃƒâ€žÃ‚Â± onayÃƒâ€žÃ‚Â±
          (Retrace kontrolÃƒÆ’Ã‚Â¼ artÃƒâ€žÃ‚Â±k state_machine._check_retrace() iÃƒÆ’Ã‚Â§inde)

        Returns:
            list[dict]: Ham event dict listesi.
        """
        events: list[dict] = []

        try:
            if not all([bars_d1, bars_15m, bars_m1]):
                return events

            current_close = bars_15m[-1].close

            # 0 ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ HTF Bias (ANA FÃƒâ€žÃ‚Â°LTRE)
            bias, strength = self._detect_htf_bias(bars_d1, bars_h4)
            if bias is None:
                logger.info("[ANALYZE] %s: HTF bias yok, event ÃƒÆ’Ã‚Â¼retilmiyor.", self.symbol)
                return events

            # D1 bar deÃƒâ€žÃ…Â¸iÃƒâ€¦Ã…Â¸ti mi? ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ likidite havuzunu sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rla
            if bars_d1:
                last_d1_idx = bars_d1[-1].index
                if last_d1_idx != self._last_d1_index:
                    self._consumed_levels.clear()
                    self._emitted_fvg_ids.clear()
                    self._last_d1_index = last_d1_idx
                    logger.info("[RESET] %s gÃƒÆ’Ã‚Â¼nlÃƒÆ’Ã‚Â¼k likidite havuzu sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rlandÃƒâ€žÃ‚Â±", self.symbol)

            logger.info(
                "[ANALYZE] %s | bias=%s | strength=%s | close=%.5f",
                self.symbol,
                bias,
                strength,
                current_close,
            )

            # Kill Zone log (zinciri kÃƒâ€žÃ‚Â±rmaz ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â kombinasyonu kullanÃƒâ€žÃ‚Â±cÃƒâ€žÃ‚Â± yapar)
            now_utc = datetime.now(UTC).hour
            in_kill_zone = (
                (config.LONDON_KILL_ZONE_START <= now_utc < config.LONDON_KILL_ZONE_END)
                or (config.NY_KILL_ZONE_START <= now_utc < config.NY_KILL_ZONE_END)
                or (config.ASYA_TOKYO_KILL_ZONE_START <= now_utc < config.ASYA_TOKYO_KILL_ZONE_END)
            )
            logger.info(
                "[KILLZONE] %s: UTC=%d | in_zone=%s",
                self.symbol,
                now_utc,
                in_kill_zone,
            )

            # Bias event ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â state_machine takip etsin
            events.append(
                {
                    "type": "HTF_BIAS",
                    "symbol": self.symbol,
                    "direction": bias,
                    "strength": strength,
                }
            )

            # HTF seviyeleri (SL/TP referansÃƒâ€žÃ‚Â±)
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

            # 1 ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ SWEEP (H1 ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ 2H fallback)
            sweep_events = self._detect_sweep_h1(self.symbol, bars_h1, bias)
            events.extend(sweep_events)

            # Sweep bar index'ini sonraki adÃƒâ€žÃ‚Â±mlar iÃƒÆ’Ã‚Â§in belirle
            sweep_bar_indices = [ev["bar_index"] for ev in sweep_events if "bar_index" in ev]
            sweep_since = max(sweep_bar_indices) if sweep_bar_indices else None

            # 2 ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ MSS (15m) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â sweep sonrasÃƒâ€žÃ‚Â± yapÃƒâ€žÃ‚Â± kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±mÃƒâ€žÃ‚Â±
            # [FIX-2] MSS artÃƒâ€žÃ‚Â±k FVG'den ÃƒÆ’Ã¢â‚¬â€œNCE ÃƒÆ’Ã‚Â§aÃƒâ€žÃ…Â¸rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor
            mss_events = self._detect_mss_events(self.symbol, bars_15m, bias, since_bar_index=sweep_since)
            events.extend(mss_events)

            # 3 â€” FVG (1H main; 2H validation; 1H clustering)
            fvg_direction = "bullish" if bias == "LONG" else "bearish"

            # Detect on 1H
            fvgs_h1: list[FVG] = []
            if bars_h1 and len(bars_h1) >= 5:
                fvgs_h1 = detect_fvgs(bars_h1, lookback=20, timeframe="1H", min_fvg_size=MIN_FVG_SIZE, since_index=None)
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

            # Update/age using 1H only
            update_fvg_states(fvgs_eff, bars_h1)
            fvgs_eff = cleanup_fvgs(fvgs_eff, bars_h1[-1].index if bars_h1 else bars_15m[-1].index)
            fvgs_eff.sort(key=lambda f: (not validated_map.get(f.real_index, False), -abs(f.top - f.bottom)))

            # Emit 1H only with robust duplicate key
            new_keys = set()
            for f in fvgs_eff:
                key = ("1H", round(float(f.top), 5), round(float(f.bottom), 5), int(f.real_index))
                if key in self._emitted_fvg_ids:
                    continue
                new_keys.add(key)
                events.append(
                    {
                        "type": "FVG_CREATED",
                        "symbol": self.symbol,
                        "upper": f.top,
                        "lower": f.bottom,
                        "ce_level": (f.top + f.bottom) / 2.0,
                        "time": f.real_index,
                        "bar_index": f.real_index,
                        "direction": f.direction,
                        "is_active": getattr(f, "is_active", True),
                        "tf": "1H",
                        "validated": bool(validated_map.get(f.real_index, False)),
                    }
                )
            for kf in new_keys:
                self._emitted_fvg_ids.add(kf)
            # 4 ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ LTF_CONFIRM (1m) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â pivot kÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±mÃƒâ€žÃ‚Â± onayÃƒâ€žÃ‚Â±
            # LTF confirm iÃƒÆ’Ã‚Â§in bars_h1 ÃƒÆ’Ã‚Â¼zerinden deÃƒâ€žÃ…Â¸il hÃƒÆ’Ã‚Â¢lÃƒÆ’Ã‚Â¢ 1m barlarÃƒâ€žÃ‚Â± kullanÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±r
            events.extend(self._detect_ltf_confirm(self.symbol, fvgs, bars_m1, current_close))

        except Exception as exc:
            logger.error(
                "[ANALYZE] %s event production error: %s",
                self.symbol,
                exc,
                exc_info=True,
            )

        return events

