"""
risk_manager.py
───────────────
NEXUS V3 — 4H swing SL + 1H likidite TP tabanlı risk yöneticisi.

SL   : 4H swing high/low + tier buffer  (eski: FVG sınırı)
TP   : 1H BSL/SSL likidite seviyesi     (eski: fallback RR çarpanı)
Entry: 5m confirmation mumu kapanışı    (eski: FVG midpoint)
Lot  : risk_usd / sl_distance

build_trade(state, entry_price, h4_swing_level, h1_liquidity_level)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import config
from models import FVG
from state_machine import SymbolState

log = logging.getLogger("nexus.risk")

# ──────────────────────────────────────────────
# Tier tanımları
# ──────────────────────────────────────────────

TIER_MAP: dict[str, str] = {
    "BTCUSDT": "tier1",
    "ETHUSDT": "tier1",
    "BNBUSDT": "tier1",
    "SOLUSDT": "tier2",
    "XRPUSDT": "tier2",
    "AVAXUSDT": "tier3",
    "LINKUSDT": "tier3",
    "SUIUSDT": "tier3",
    "NEARUSDT": "tier3",
    "INJUSDT": "tier3",
    "FETUSDT": "tier3",
    "DOGEUSDT": "tier3",
    "DOTUSDT": "tier2",
    "MATICUSDT": "tier2",
    "UNIUSDT": "tier2",
    "APTUSDT": "tier2",
    "OPUSDT": "tier3",
    "ARBUSDT": "tier3",
    "LDOUSDT": "tier2",
    "RNDRUSDT": "tier2",
    "STXUSDT": "tier2",
    "ADAUSDT": "tier3",
}

TIER_CFG: dict[str, dict] = {
    "tier1": {
        "max_sl_pct": 0.025,  # 4H swing geniş olabilir, tier1'de %2.5'e kadar izin ver
        "min_sl_pct": 0.0015,
        "sl_buffer": 0.0015,
        "max_rr": 4.0,
        "lot_decimals": 3,
    },
    "tier2": {
        "max_sl_pct": 0.030,
        "min_sl_pct": 0.0020,
        "sl_buffer": 0.0030,
        "max_rr": 5.0,
        "lot_decimals": 2,
    },
    "tier3": {
        "max_sl_pct": 0.035,
        "min_sl_pct": 0.0025,
        "sl_buffer": 0.0060,
        "max_rr": 6.0,
        "lot_decimals": 1,
    },
}

LOT_DECIMALS_OVERRIDE: dict[str, int] = {
    "DOGEUSDT": 0,
    "ADAUSDT": 0,
}

# ──────────────────────────────────────────────
# Çıktı yapısı
# ──────────────────────────────────────────────


@dataclass
class TradeParams:
    symbol: str
    direction: Literal["long", "short"]
    entry: float
    sl: float
    tp: float
    lot: float
    risk_usd: float
    gross_rr: float
    net_rr: float
    sl_pct: float
    fvg_top: float
    fvg_bottom: float
    initial_sl: float
    # Kademeli stop seviyeleri
    breakeven_level: float  # entry (1R'da SL buraya çekilir)
    trailing_level: float  # 1R kâr (2R'da SL buraya çekilir)


# ──────────────────────────────────────────────
# Risk manager
# ──────────────────────────────────────────────


class RiskManager:
    """
    Parameters
    ----------
    balance          : Mevcut bakiye (USDT)
    available_margin : Kullanılabilir marjin (None → balance)
    risk_pct         : Trade başına risk oranı (varsayılan %3)
    min_rr           : Minimum brüt RR (config.MIN_RR = 2.0)
    min_net_rr       : Minimum net RR
    taker_fee        : Taker komisyon oranı
    spread_pct       : Spread oranı
    default_rr       : 1H likidite bulunamazsa fallback RR
    leverage         : Kaldıraç
    margin_usage     : Maksimum marjin kullanım oranı
    """

    def __init__(
        self,
        balance: float,
        available_margin: float | None = None,
        risk_pct: float = 0.03,
        min_rr: float | None = None,
        min_net_rr: float = 1.5,
        taker_fee: float = 0.0004,
        spread_pct: float = 0.0001,
        default_rr: float = 2.0,
        leverage: float = 10.0,
        margin_usage: float = 0.80,
    ) -> None:
        self._balance = balance
        self._available_margin = available_margin if available_margin is not None else balance
        self.risk_pct = risk_pct
        self.min_rr = min_rr if min_rr is not None else config.MIN_RR
        self.min_net_rr = min_net_rr
        self.taker_fee = taker_fee
        self.spread_pct = spread_pct
        self.default_rr = default_rr
        self.leverage = leverage
        self.margin_usage = margin_usage

    @property
    def balance(self) -> float:
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        self._balance = value

    @property
    def available_margin(self) -> float:
        return self._available_margin

    @available_margin.setter
    def available_margin(self, value: float) -> None:
        self._available_margin = value

    # ── Tier yardımcıları ───────────────────────

    def _tier(self, symbol: str) -> dict:
        tier_key = TIER_MAP.get(symbol, "tier3")
        return TIER_CFG[tier_key]

    def _lot_decimals(self, symbol: str) -> int:
        if symbol in LOT_DECIMALS_OVERRIDE:
            return LOT_DECIMALS_OVERRIDE[symbol]
        tier_key = TIER_MAP.get(symbol, "tier3")
        return TIER_CFG[tier_key]["lot_decimals"]

    def _round_lot(self, symbol: str, lot: float) -> float:
        dec = self._lot_decimals(symbol)
        result = round(lot, dec)
        return float(int(result)) if dec == 0 else result

    # ── SL — 4H Swing tabanlı ──────────────────

    def calculate_sl_htf(
        self,
        symbol: str,
        direction: Literal["long", "short"],
        entry: float,
        h4_swing_level: float,  # 4H swing low (long) veya swing high (short)
        tier: dict,
    ) -> float | None:
        """
        SL = 4H swing seviyesinin biraz ötesi + tier buffer.

        LONG  → SL = 4H swing low  × (1 - buffer)
        SHORT → SL = 4H swing high × (1 + buffer)

        min_sl_pct / max_sl_pct ile makul aralıkta tutar.
        max_sl_pct aşılırsa trade reddedilir (R:R bozulur).
        """
        buf = tier["sl_buffer"]
        min_dist = entry * tier["min_sl_pct"]
        max_dist = entry * tier["max_sl_pct"]

        if direction == "long":
            raw_sl = h4_swing_level * (1.0 - buf)
            dist = entry - raw_sl
        else:
            raw_sl = h4_swing_level * (1.0 + buf)
            dist = raw_sl - entry

        if dist <= 0:
            log.warning("[SL-HTF] %s negatif/sıfır SL mesafesi — reddedildi", symbol)
            return None

        if dist < min_dist:
            # Çok yakın — minimum mesafeye çek
            raw_sl = (entry - min_dist) if direction == "long" else (entry + min_dist)
            dist = min_dist
            log.debug("[SL-HTF] %s min_dist'e çekildi: %.5f", symbol, raw_sl)

        if dist > max_dist:
            log.warning(
                "[SL-HTF] %s SL çok geniş — direction=%s entry=%.5f dist=%.5f max=%.5f → reddedildi",
                symbol,
                direction,
                entry,
                dist,
                max_dist,
            )
            return None

        return round(raw_sl, 5)

    # ── TP — 1H Likidite tabanlı ───────────────

    def calculate_tp_htf(
        self,
        symbol: str,
        direction: Literal["long", "short"],
        entry: float,
        sl: float,
        h1_liquidity_level: float | None,
        tier: dict,
    ) -> float:
        """
        TP = 1H BSL/SSL likidite seviyesi.

        Eğer h1_liquidity_level verilmemişse ya da R:R < min_rr ise
        fallback olarak default_rr × risk_distance kullanılır.

        LONG  → TP = 1H BSL (swing high likiditesi)
        SHORT → TP = 1H SSL (swing low likiditesi)
        """
        risk_dist = abs(entry - sl)
        if risk_dist <= 0:
            return entry

        # 1H likidite seviyesi varsa R:R kontrol et
        if h1_liquidity_level is not None:
            reward_dist = abs(h1_liquidity_level - entry)
            rr = reward_dist / risk_dist if risk_dist > 0 else 0.0

            if rr >= self.min_rr:
                log.info(
                    "[TP-HTF] %s 1H likidite kullanıldı — level=%.5f RR=%.2f",
                    symbol,
                    h1_liquidity_level,
                    rr,
                )
                return round(h1_liquidity_level, 5)
            else:
                log.warning(
                    "[TP-HTF] %s 1H likidite RR yetersiz (%.2f < %.2f) → fallback RR",
                    symbol,
                    rr,
                    self.min_rr,
                )

        # Fallback: default_rr × risk_distance
        rr = min(self.default_rr, tier["max_rr"])
        if direction == "long":
            tp = round(entry + risk_dist * rr, 5)
        else:
            tp = round(entry - risk_dist * rr, 5)

        log.info("[TP-FALLBACK] %s TP=%.5f (RR=%.1f)", symbol, tp, rr)
        return tp

    # ── Lot hesaplama ──────────────────────────

    def calculate_lot(
        self,
        symbol: str,
        entry: float,
        sl: float,
    ) -> float:
        """risk_usd / sl_distance, kaldıraç ve marjin sınırlı."""
        if self._available_margin <= 0:
            log.critical(
                "[LOT-REJECT] Available margin sıfır/negatif (%.4f) — lot=0",
                self._available_margin,
            )
            return 0.0

        risk_usd = self._available_margin * self.risk_pct
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return 0.0

        raw_lot = risk_usd / sl_dist
        max_lot = (self._available_margin * self.leverage * self.margin_usage) / entry if entry > 0 else 0.0
        return min(raw_lot, max_lot)

    # ── Kademeli stop seviyeleri ───────────────

    @staticmethod
    def _calc_stop_levels(
        direction: Literal["long", "short"],
        entry: float,
        sl: float,
    ) -> tuple[float, float]:
        """
        Kademe 1 (breakeven): Fiyat 1R gittiğinde SL = entry
        Kademe 2 (trailing) : Fiyat 2R gittiğinde SL = entry + 1R (long) / entry - 1R (short)

        Returns: (breakeven_trigger, trailing_sl)
        """
        risk_dist = abs(entry - sl)

        if direction == "long":
            breakeven_trigger = round(entry + risk_dist * config.BREAKEVEN_R, 5)
            trailing_sl = round(entry + risk_dist * (config.TRAILING_ACTIVATE_R - 1.0), 5)
        else:
            breakeven_trigger = round(entry - risk_dist * config.BREAKEVEN_R, 5)
            trailing_sl = round(entry - risk_dist * (config.TRAILING_ACTIVATE_R - 1.0), 5)

        return breakeven_trigger, trailing_sl

    # ── Ana giriş noktası ───────────────────────

    def build_trade(
        self,
        state: SymbolState,
        entry_price: float | None = None,  # 5m confirmation kapanışı
        h4_swing_level: float | None = None,  # 4H swing low (long) / high (short)
        h1_liquidity_level: float | None = None,  # 1H BSL (long) / SSL (short)
    ) -> TradeParams | None:
        """
        TradeParams üretir.

        entry_price        : 5m confirmation mumu kapanışı.
                             None ise FVG midpoint fallback kullanılır.
        h4_swing_level     : SL referansı (4H swing).
                             None ise eski FVG tabanlı SL'e düşer.
        h1_liquidity_level : TP referansı (1H BSL/SSL).
                             None ise fallback RR kullanılır.
        """
        if state.direction is None:
            log.warning("[BUILD] %s direction yok — reddedildi", state.symbol)
            return None
        if state.fvg_lower is None or state.fvg_upper is None:
            log.warning("[BUILD] %s FVG seviyeleri eksik — reddedildi", state.symbol)
            return None

        sym: str = state.symbol
        dire: Literal["long", "short"] = "long" if state.direction == "LONG" else "short"
        tier: dict = self._tier(sym)

        # ── Entry ──
        if entry_price is not None:
            entry = round(entry_price, 5)
        else:
            # Fallback: FVG midpoint
            fvg_mid = (state.fvg_upper + state.fvg_lower) / 2.0
            entry = round(fvg_mid, 5)
            log.debug("[BUILD] %s entry_price yok → FVG midpoint fallback: %.5f", sym, entry)

        log.info("[BUILD-IN] %s | entry=%s | h4_sl=%s | h1_tp=%s", sym, entry, h4_swing_level, h1_liquidity_level)

        # ── SL ──
        if h4_swing_level is not None:
            sl = self.calculate_sl_htf(sym, dire, entry, h4_swing_level, tier)
        else:
            # Fallback: eski FVG tabanlı SL
            log.warning("[BUILD] %s h4_swing_level yok → FVG SL fallback", sym)
            fvg = FVG(
                direction="bullish" if dire == "long" else "bearish",
                top=state.fvg_upper,
                bottom=state.fvg_lower,
                real_index=0,
            )
            buf = tier["sl_buffer"]
            raw_sl = fvg.bottom * (1.0 - buf) if dire == "long" else fvg.top * (1.0 + buf)
            dist = abs(entry - raw_sl)
            max_d = entry * tier["max_sl_pct"]
            sl = round(raw_sl, 5) if dist <= max_d else None

        if sl is None:
            log.warning("[BUILD] %s SL hesaplanamadı — reddedildi", sym)
            return None

        # ── R:R ön kontrolü (TP hesabından önce) ──
        risk_dist = abs(entry - sl)
        if risk_dist <= 0:
            return None

        # ── TP ──
        tp = self.calculate_tp_htf(sym, dire, entry, sl, h1_liquidity_level, tier)

        # ── R:R son kontrolü ──
        reward_dist = abs(tp - entry)
        gross_rr = round(reward_dist / risk_dist, 4)

        if gross_rr < self.min_rr:
            log.warning(
                "[BUILD] %s R:R yetersiz — gross_rr=%.2f < min_rr=%.2f → reddedildi",
                sym,
                gross_rr,
                self.min_rr,
            )
            return None

        # ── Lot ──
        raw_lot = self.calculate_lot(sym, entry, sl)
        if raw_lot <= 0:
            return None

        lot = self._round_lot(sym, raw_lot)
        if lot <= 0:
            return None

        # ── Net RR (komisyon + spread dahil) ──
        cost_pct = 2 * self.taker_fee + self.spread_pct
        net_rr = round((reward_dist - entry * cost_pct) / (risk_dist + entry * cost_pct), 4)

        if net_rr < self.min_net_rr:
            log.warning(
                "[BUILD] %s net R:R yetersiz — net_rr=%.2f < min_net_rr=%.2f → reddedildi",
                sym,
                net_rr,
                self.min_net_rr,
            )
            return None

        # ── Kademeli stop seviyeleri ──
        breakeven_level, trailing_level = self._calc_stop_levels(dire, entry, sl)

        risk_usd = round(risk_dist * lot, 4)
        sl_pct = round(risk_dist / entry * 100, 4)

        log.info(
            "[BUILD] %s %s entry=%.5f sl=%.5f tp=%.5f lot=%.4f RR=%.2f netRR=%.2f",
            sym,
            dire.upper(),
            entry,
            sl,
            tp,
            lot,
            gross_rr,
            net_rr,
        )

        return TradeParams(
            symbol=sym,
            direction=dire,
            entry=entry,
            sl=sl,
            tp=tp,
            lot=lot,
            risk_usd=risk_usd,
            gross_rr=gross_rr,
            net_rr=net_rr,
            sl_pct=sl_pct,
            fvg_top=state.fvg_upper,
            fvg_bottom=state.fvg_lower,
            initial_sl=sl,
            breakeven_level=breakeven_level,
            trailing_level=trailing_level,
        )
