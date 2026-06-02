"""
risk_manager.py
───────────────
NEXUS V2 — CHoCH + FVG tabanlı risk yöneticisi (simplified).

SL  : FVG sınırının ötesi + tier buffer
TP  : Bir sonraki FVG / likidite seviyesi, yoksa fallback RR
Lot : risk_usd / sl_distance

build_trade(state) → TradeParams  (state_machine.get(symbol) çağrısıyla beslenir)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from models import FVG
from state_machine import SymbolState

log = logging.getLogger("nexus.risk")

# ──────────────────────────────────────────────
# Tier tanımları
# ──────────────────────────────────────────────

TIER_MAP: dict[str, str] = {
    "BTCUSDT":   "tier1",
    "ETHUSDT":   "tier1",
    "BNBUSDT":   "tier1",
    "SOLUSDT":   "tier2",
    "XRPUSDT":   "tier2",
    "AVAXUSDT":  "tier3",
    "LINKUSDT":  "tier3",
    "SUIUSDT":   "tier3",
    "NEARUSDT":  "tier3",
    "INJUSDT":   "tier3",
    "FETUSDT":   "tier3",
    "DOGEUSDT":  "tier3",
    "DOTUSDT":   "tier2",
    "MATICUSDT": "tier2",
    "UNIUSDT":   "tier2",
    "APTUSDT":   "tier2",
    "OPUSDT":    "tier3",
    "ARBUSDT":   "tier3",
    "LDOUSDT":   "tier2",
    "RNDRUSDT":  "tier2",
    "STXUSDT":   "tier2",
    "ADAUSDT":   "tier3",
}

TIER_CFG: dict[str, dict] = {
    "tier1": {
        "max_sl_pct":  0.015,
        "min_sl_pct":  0.0015,
        "sl_buffer":   0.0015,
        "max_rr":      4.0,
        "lot_decimals": 3,
    },
    "tier2": {
        "max_sl_pct":  0.020,
        "min_sl_pct":  0.0020,
        "sl_buffer":   0.0030,
        "max_rr":      5.0,
        "lot_decimals": 2,
    },
    "tier3": {
        "max_sl_pct":  0.025,
        "min_sl_pct":  0.0025,
        "sl_buffer":   0.0060,
        "max_rr":      6.0,
        "lot_decimals": 1,
    },
}

LOT_DECIMALS_OVERRIDE: dict[str, int] = {
    "DOGEUSDT": 0,
    "ADAUSDT":  0,
}

# ──────────────────────────────────────────────
# Çıktı yapısı
# ──────────────────────────────────────────────


@dataclass
class TradeParams:
    symbol:     str
    direction:  Literal["long", "short"]
    entry:      float
    sl:         float
    tp:         float
    lot:        float
    risk_usd:   float
    gross_rr:   float
    net_rr:     float
    sl_pct:     float
    fvg_top:    float
    fvg_bottom: float
    initial_sl: float


# ──────────────────────────────────────────────
# Risk manager
# ──────────────────────────────────────────────


class RiskManager:
    """
    Parameters
    ----------
    balance       : Mevcut bakiye (USDT)
    risk_pct      : Trade başına risk oranı (varsayılan %3)
    min_rr        : Minimum brüt RR (varsayılan 1.5)
    min_net_rr    : Minimum net RR  (varsayılan 1.15)
    taker_fee     : Taker komisyon oranı (varsayılan %0.04)
    spread_pct    : Spread oranı (varsayılan %0.01)
    default_rr    : TP bulunamazsa kullanılacak fallback RR
    leverage      : Kaldıraç (varsayılan 10x)
    margin_usage  : Kullanılacak maksimum marjin oranı (varsayılan %80)
    """

    def __init__(
        self,
        balance:          float,
        available_margin: float | None = None,
        risk_pct:         float = 0.03,
        min_rr:           float = 1.5,
        min_net_rr:       float = 1.15,
        taker_fee:        float = 0.0004,
        spread_pct:       float = 0.0001,
        default_rr:       float = 2.0,
        leverage:         float = 10.0,
        margin_usage:     float = 0.80,
    ) -> None:
        self._balance          = balance
        self._available_margin = available_margin if available_margin is not None else balance
        self.risk_pct          = risk_pct
        self.min_rr            = min_rr
        self.min_net_rr        = min_net_rr
        self.taker_fee         = taker_fee
        self.spread_pct        = spread_pct
        self.default_rr        = default_rr
        self.leverage          = leverage
        self.margin_usage      = margin_usage

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
        """Borsa kurallarına göre lot yuvarlama."""
        dec = self._lot_decimals(symbol)
        result = round(lot, dec)
        return float(int(result)) if dec == 0 else result

    # ── Public API ──────────────────────────────

    def calculate_sl(
        self,
        symbol:    str,
        direction: Literal["long", "short"],
        entry:     float,
        fvg:       FVG,
        tier:      dict,
    ) -> float | None:
        """FVG sınırının ötesine SL koy + tier buffer."""
        buf      = tier["sl_buffer"]
        min_dist = entry * tier["min_sl_pct"]
        max_dist = entry * tier["max_sl_pct"]

        if direction == "long":
            raw_sl = fvg.bottom * (1 - buf)
            dist   = entry - raw_sl
        else:
            raw_sl = fvg.top * (1 + buf)
            dist   = raw_sl - entry

        if dist < min_dist:
            raw_sl = (entry - min_dist) if direction == "long" else (entry + min_dist)
            dist   = min_dist

        if dist > max_dist:
            log.warning(
                "[SL-REJECT] %s SL cok genis — direction=%s entry=%.5f dist=%.5f max=%.5f",
                symbol, direction, entry, dist, max_dist,
            )
            return None

        return round(raw_sl, 5)

    def calculate_tp(
        self,
        symbol:    str,
        direction: Literal["long", "short"],
        entry:     float,
        sl:        float,
        tier:      dict,
    ) -> float:
        """TP = risk_distance × default_rr (fallback)."""
        risk_dist = abs(entry - sl)
        rr = min(self.default_rr, tier["max_rr"])
        if direction == "long":
            return round((entry + risk_dist * rr) * 1.0005, 5)
        else:
            return round((entry - risk_dist * rr) * 0.9995, 5)

    def calculate_lot(
        self,
        symbol: str,
        entry:  float,
        sl:     float,
    ) -> float:
        """risk_usd / sl_distance, kaldıraç ve marjin sınırlı."""
        if self._available_margin <= 0:
            log.critical(
                "[LOT-REJECT] Available margin sifir veya negatif (available_margin=%.4f) — lot=0 döndürüldü.",
                self._available_margin,
            )
            return 0.0

        risk_usd = self._available_margin * self.risk_pct
        sl_dist  = abs(entry - sl)
        if sl_dist <= 0:
            return 0.0

        raw_lot = risk_usd / sl_dist
        max_lot = (self._available_margin * self.leverage * self.margin_usage) / entry if entry > 0 else 0.0
        raw_lot = min(raw_lot, max_lot)
        return raw_lot

    # ── Ana giriş noktası ───────────────────────

    def build_trade(self, state: SymbolState) -> TradeParams | None:
        """
        state_machine.get(symbol) çıktısından TradeParams üretir.
        Geçersiz state durumunda None döner.
        """
        if state.direction is None:
            return None
        if state.fvg_lower is None or state.fvg_upper is None:
            return None

        sym:  str                      = state.symbol
        dire: Literal["long", "short"] = state.direction
        tier: dict                     = self._tier(sym)

        fvg = FVG(
            direction="bullish" if dire == "long" else "bearish",
            top=state.fvg_upper,
            bottom=state.fvg_lower,
            real_index=0,
        )
        entry = round(fvg.midpoint, 5)

        sl = self.calculate_sl(sym, dire, entry, fvg, tier)
        if sl is None:
            return None

        raw_lot = self.calculate_lot(sym, entry, sl)
        if raw_lot <= 0:
            return None

        lot = self._round_lot(sym, raw_lot)
        if lot <= 0:
            return None

        tp = self.calculate_tp(sym, dire, entry, sl, tier)

        risk_usd    = round(abs(entry - sl) * lot, 4)
        risk_dist   = abs(entry - sl)
        reward_dist = abs(tp - entry)
        gross_rr    = round(reward_dist / risk_dist, 4) if risk_dist > 0 else 0.0
        sl_pct      = round(abs(entry - sl) / entry * 100, 4)

        return TradeParams(
            symbol=sym,
            direction=dire,
            entry=entry,
            sl=sl,
            tp=tp,
            lot=lot,
            risk_usd=risk_usd,
            gross_rr=gross_rr,
            net_rr=0.0,
            sl_pct=sl_pct,
            fvg_top=state.fvg_upper,
            fvg_bottom=state.fvg_lower,
            initial_sl=sl,
        )
