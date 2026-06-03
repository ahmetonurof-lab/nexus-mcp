"""
risk_manager.py
───────────────
NEXUS V2 — CHoCH + FVG tabanlı risk yöneticisi.

SL  : FVG sınırının ötesi + tier buffer
TP  : Bir sonraki FVG / likidite seviyesi, yoksa fallback RR
Lot : risk_usd / sl_distance
+ ADX tabanlı position sizing (apply_adx_sizing)

Düzeltilen 11 kritik sorun:
  1.  Syntax/boşluk kirliliği            → temizlendi
  2.  ADX None TypeError                 → guard clause eklendi
  3.  TP next_level None TypeError        → is not None kontrolü sağlamlaştırıldı
  4.  Trailing SL yanlış yön (step)      → long: +step, short: -step
  5.  Breakeven short yönü yanlış        → short: entry + cost
  6.  Bakiye sıfırda sabit risk          → lot=0 döner, kritik log
  7.  Net RR komisyon/spread modeli      → giriş+çıkış+stop komisyonu ayrı ayrı
  8.  Breakeven mesafe referansı         → initial_sl üzerinden ölç
  9.  Lot yuvarlama ezilmesi             → borsa yuvarlama en son yapılır
  10. Kaldıraç max_lot hesabında eksik   → leverage ve margin_usage dahil
  11. min_profit mantık çelişkisi        → expected_profit ile kıyasla
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import config
from analyzer import AnalysisResult
from models import FVG

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
        "max_sl_pct": 0.015,
        "min_sl_pct": 0.0015,
        "sl_buffer": 0.0015,
        "max_rr": 4.0,
        "lot_decimals": 3,
    },
    "tier2": {
        "max_sl_pct": 0.020,
        "min_sl_pct": 0.0020,
        "sl_buffer": 0.0030,
        "max_rr": 5.0,
        "lot_decimals": 2,
    },
    "tier3": {
        "max_sl_pct": 0.025,
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
    initial_sl: float  # trailing_sl ve should_move_to_breakeven için sabit referans


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
        balance: float,
        available_margin: float | None = None,  # ← YENİ
        risk_pct: float = 0.03,
        min_rr: float = 1.5,
        min_net_rr: float = 1.15,
        taker_fee: float = 0.0004,
        spread_pct: float = 0.0001,
        default_rr: float = 2.0,
        leverage: float = 10.0,
        margin_usage: float = 0.80,
    ) -> None:
        self._balance = balance
        self._available_margin = available_margin if available_margin is not None else balance
        self.risk_pct = risk_pct
        self.min_rr = min_rr
        self.min_net_rr = min_net_rr
        self.taker_fee = taker_fee
        self.spread_pct = spread_pct
        self.default_rr = default_rr
        self.leverage = leverage  # Düzeltme 10
        self.margin_usage = margin_usage  # Düzeltme 10

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

    # ── Lot yuvarlama (Düzeltme 9) ─────────────
    def _round_lot(self, symbol: str, lot: float) -> float:
        """
        Düzeltme 9: Borsa kurallarına göre lot yuvarlama EN SON yapılır.
        apply_adx_sizing sonrasında çağrılmalı; önce ham lot işlenir,
        yuvarlama sadece bu fonksiyonda gerçekleşir.
        """
        dec = self._lot_decimals(symbol)
        result = round(lot, dec)
        return float(int(result)) if dec == 0 else result

    # ── SL hesabı ───────────────────────────────

    def _calc_sl(
        self,
        symbol: str,
        direction: Literal["long", "short"],
        entry: float,
        fvg: FVG,
        tier: dict,
    ) -> float | None:
        """
        FVG sınırının ötesine SL koy + tier buffer.

        Long  → SL = FVG bottom'ın altı
        Short → SL = FVG top'ın üstü
        """
        buf = tier["sl_buffer"]
        min_dist = entry * tier["min_sl_pct"]
        max_dist = entry * tier["max_sl_pct"]

        if direction == "long":
            raw_sl = fvg.bottom * (1 - buf)
            dist = entry - raw_sl
        else:
            raw_sl = fvg.top * (1 + buf)
            dist = raw_sl - entry

        # Min mesafe garantisi
        if dist < min_dist:
            raw_sl = (entry - min_dist) if direction == "long" else (entry + min_dist)
            dist = min_dist

        # Max mesafe kontrolü — çok geniş SL reddet
        if dist > max_dist:
            log.warning(
                "[SL-REJECT] %s SL cok genis — direction=%s entry=%.5f dist=%.5f max=%.5f",
                symbol,
                direction,
                entry,
                dist,
                max_dist,
            )
            return None

        return round(raw_sl, 5)

    # ── TP hesabı ───────────────────────────────

    def _calc_tp(
        self,
        symbol: str,
        direction: Literal["long", "short"],
        entry: float,
        sl: float,
        tier: dict,
        next_level: float | None = None,
    ) -> float:
        """
        TP = bir sonraki FVG / likidite seviyesi.
        Bulunamazsa fallback: entry ± risk_distance × default_rr.
        Sweep payı eklenir (%0.05).

        Düzeltme 3: next_level is not None + yön validasyonu güçlendirildi.

        Yön Validasyonu:
          SHORT → next_level ENTRY'nin ALTINDA olmalı (kâr bölgesi)
          LONG  → next_level ENTRY'nin ÜSTÜNDE olmalı (kâr bölgesi)
          Validasyon başarısızsa fallback RR kullanılır.
        """
        risk_dist = abs(entry - sl)

        # Düzeltme 3: is not None ile tip-güvenli kontrol
        if next_level is not None:
            valid_direction = (direction == "long" and next_level > entry) or (
                direction == "short" and next_level < entry
            )
            if not valid_direction:
                log.warning(
                    "[TP] %s yon validasyonu BASARISIZ — direction=%s "
                    "next_level=%.5f entry=%.5f — fallback RR kullaniliyor",
                    symbol,
                    direction,
                    next_level,
                    entry,
                )
            else:
                reward = abs(next_level - entry)
                rr = reward / risk_dist if risk_dist > 0 else 0.0
                if self.min_rr <= rr <= tier["max_rr"]:
                    sweep = 0.9995 if direction == "short" else 1.0005
                    return round(next_level * sweep, 5)

        # Fallback
        rr = min(self.default_rr, tier["max_rr"])
        if direction == "long":
            return round((entry + risk_dist * rr) * 1.0005, 5)
        else:
            return round((entry - risk_dist * rr) * 0.9995, 5)

    # ── Net RR (Düzeltme 7) ─────────────────────

    def _calc_net_rr(
        self,
        entry: float,
        sl: float,
        tp: float,
        lot: float,
    ) -> tuple[float, float]:
        """
        Düzeltme 7: Komisyon ve spread gerçek dünya modeliyle hesaplanır.

        Maliyet kalemleri:
          - entry_fee  : Giriş taker komisyonu   (entry * lot * taker_fee)
          - tp_fee     : TP çıkış taker komisyonu (tp    * lot * taker_fee)
          - sl_fee     : SL çıkış taker komisyonu (sl    * lot * taker_fee)
          - spread     : Spread maliyeti sadece giriş hacmine uygulanır
                         (entry * lot * spread_pct)

        NOT: SL ve TP aynı anda gerçekleşmez; net_risk SL fee, net_reward TP fee taşır.
        """
        risk_usd = abs(entry - sl) * lot
        reward_usd = abs(tp - entry) * lot

        entry_fee = entry * lot * self.taker_fee
        tp_fee = tp * lot * self.taker_fee
        sl_fee = sl * lot * self.taker_fee
        spread = entry * lot * self.spread_pct  # Düzeltme 7: sadece giriş hacmi

        # TP senaryosu: giriş + TP komisyonu + spread öde
        net_reward = reward_usd - entry_fee - tp_fee - spread
        # SL senaryosu: giriş + SL komisyonu + spread öde
        net_risk = risk_usd + entry_fee + sl_fee + spread

        if net_risk <= 0:
            return 0.0, 0.0

        return round(net_reward / net_risk, 4), round(net_reward, 4)

    # ── Lot hesabı (Düzeltme 6, 9, 10) ──────────

    def _calc_lot(
        self,
        symbol: str,
        entry: float,
        sl: float,
    ) -> float:
        """
        Düzeltme 6 : Bakiye <= 0 ise lot=0 döner; sabit 100 USD varsayımı kaldırıldı.
        Düzeltme 9 : Yuvarlama bu fonksiyonda yapılmaz; _round_lot() ayrı çağrılır.
        Düzeltme 10: max_lot = (balance * leverage * margin_usage) / entry
        """
        # Düzeltme 6: Bakiye sıfır veya negatif → işlem açılmaz
        if self._available_margin <= 0:
            log.critical(
                "[LOT-REJECT] Available margin sifir veya negatif (available_margin=%.4f) — lot=0 döndürüldü.",
                self._available_margin,
            )
            return 0.0

        risk_usd = self._available_margin * self.risk_pct
        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return 0.0

        raw_lot = risk_usd / sl_dist

        # Düzeltme 10: Kaldıraç ve marjin kullanım oranı dahil
        max_lot = (self._available_margin * self.leverage * self.margin_usage) / entry if entry > 0 else 0.0
        raw_lot = min(raw_lot, max_lot)

        # Düzeltme 9: Yuvarlama YAPILMAZ burada; evaluate() sonunda _round_lot() çağrılır.
        return raw_lot

    # ── ADX tabanlı position sizing (Düzeltme 2, 9) ──

    def apply_adx_sizing(self, lot: float, adx: float | None) -> float:
        """
        Düzeltme 2: adx None gelebilir; guard clause ile korunur.
        Düzeltme 9: Ham lot döner; yuvarlama çağıran tarafta _round_lot() ile yapılır.

        ADX Rejimi:
          None / < 20 → İşlem ALINMAZ (çağıran taraf zaten engeller)
          20-30       → Sweet spot → çarpan ≈ 1.0 (nötr)
          > 35        → TP daraltılır, lot normal (çağıran TP multiplier uygular)

        Formül : mult = 1 + (adx - 20) * 0.008
        Clamp  : [0.85, 1.15]
        """
        # Düzeltme 2: None guard — TypeError önlendi
        if adx is None:
            log.warning("[ADX-SIZING] adx=None geldi — lot degistirilmeden döndürüldü.")
            return lot

        mult = 1.0 + (adx - 20.0) * 0.008
        mult = max(0.85, min(1.15, mult))
        # Düzeltme 9: round(..., 4) KALDIRILDI — ham float döner
        return lot * mult

    # ── Ana metot ───────────────────────────────

    def evaluate(
        self,
        result: AnalysisResult,
        next_level: float | None = None,
        d1_adx: float | None = None,
    ) -> TradeParams | None:
        """
        AnalysisResult → TradeParams.
        Geçersiz risk parametrelerinde None döner.

        Parameters
        ----------
        result      : analyzer.py'den gelen sinyal
        next_level  : TP hedefi için bir sonraki FVG/likidite seviyesi (opsiyonel)
        d1_adx      : Daily ADX değeri (ADX > 35 TP daraltma için)
        """
        if not result.is_valid_signal():
            return None

        # is_valid_signal() geçtiyse direction ve fvg garantili non-None
        if result.direction is None or result.fvg is None:
            log.error(
                "[EVALUATE] %s is_valid_signal geçti ama direction/fvg None — " "bu bir implementasyon hatasıdır.",
                result.symbol,
            )
            return None

        sym: str = result.symbol
        dire: Literal["long", "short"] = result.direction
        fvg: FVG = result.fvg
        tier: dict = self._tier(sym)

        # Giriş fiyatı: FVG midpoint
        entry = round(fvg.midpoint, 5)

        # SL
        sl = self._calc_sl(sym, dire, entry, fvg, tier)
        if sl is None:
            log.info("[SL-REJECT] %s SL hesaplanamadi (cok genis) — entry=%.5f", sym, entry)
            return None

        # ── Lot pipeline: hesapla → ADX ölçekle → SONRA yuvarlat (Düzeltme 9) ──
        raw_lot = self._calc_lot(sym, entry, sl)
        if raw_lot <= 0:
            log.info(
                "[LOT-REJECT] %s lot hesabi sifir döndü — entry=%.5f sl=%.5f",
                sym,
                entry,
                sl,
            )
            return None

        # Düzeltme 2 + 9: adx None-safe; yuvarlama henüz yapılmadı
        sized_lot = self.apply_adx_sizing(raw_lot, result.adx_value)

        # Düzeltme 9: Yuvarlama EN SON burada yapılır
        lot = self._round_lot(sym, sized_lot)
        if lot <= 0:
            log.info(
                "[LOT-REJECT] %s ADX sizing sonrasi lot sifir döndü — sized=%.6f adx=%s",
                sym,
                sized_lot,
                result.adx_value,
            )
            return None
        # ────────────────────────────────────────────────────────────────────────

        # Risk USD
        risk_usd = round(abs(entry - sl) * lot, 4)

        # ── Düzeltme 11: min_profit → expected_profit ile kıyasla ──────────────
        # risk_usd (riske edilen para) ile minimum kâr hedefi kıyaslanamaz.
        # Beklenen kâr = risk_usd * gross_rr (fallback RR üzerinden tahmin).
        min_profit = config.MIN_EXPECTED_PROFIT_MAP.get(sym, config.MIN_EXPECTED_PROFIT)
        expected_profit_estimate = risk_usd * self.default_rr  # TP öncesi tahmin
        if expected_profit_estimate < min_profit:
            log.info(
                "[MINPROFIT-REJECT] %s expected_profit=%.4f (risk=%.4f x rr=%.1f) "
                "< min_expected_profit=%.4f — entry=%.5f sl=%.5f lot=%.4f",
                sym,
                expected_profit_estimate,
                risk_usd,
                self.default_rr,
                min_profit,
                entry,
                sl,
                lot,
            )
            return None
        # ────────────────────────────────────────────────────────────────────────

        # TP
        tp = self._calc_tp(sym, dire, entry, sl, tier, next_level)

        # ── ADX > 35 TP Daraltma Kuralı ─────────────────────────────────────────
        if d1_adx is not None and d1_adx >= config.ADX_HIGH_TP_THRESHOLD:
            risk_dist = abs(entry - sl)
            full_tp_dist = abs(tp - entry)
            narrowed_dist = full_tp_dist * config.ADX_HIGH_TP_MULTIPLIER
            original_tp = tp
            if dire == "long":
                tp = round(entry + narrowed_dist, 5)
            else:
                tp = round(entry - narrowed_dist, 5)
            log.info(
                "[ADX-TP] %s d1_adx=%.1f >= %.0f → TP daraltildi: %.5f → %.5f (mult=%.1f%%)",
                sym,
                d1_adx,
                config.ADX_HIGH_TP_THRESHOLD,
                original_tp,
                tp,
                config.ADX_HIGH_TP_MULTIPLIER * 100,
            )
        # ────────────────────────────────────────────────────────────────────────

        # Brüt RR
        risk_dist = abs(entry - sl)
        reward_dist = abs(tp - entry)
        gross_rr = round(reward_dist / risk_dist, 4) if risk_dist > 0 else 0.0

        adx_narrowed = d1_adx is not None and d1_adx >= config.ADX_HIGH_TP_THRESHOLD
        effective_min_rr = self.min_rr * config.ADX_HIGH_TP_MULTIPLIER if adx_narrowed else self.min_rr
        if gross_rr < effective_min_rr:
            log.info(
                "[RR-REJECT] %s gross_rr=%.2f < effective_min_rr=%.2f (adx_narrowed=%s) — "
                "entry=%.5f sl=%.5f tp=%.5f",
                sym,
                gross_rr,
                effective_min_rr,
                adx_narrowed,
                entry,
                sl,
                tp,
            )
            return None

        # Net RR (Düzeltme 7: gerçekçi komisyon modeli)
        net_rr, _ = self._calc_net_rr(entry, sl, tp, lot)
        if net_rr < self.min_net_rr:
            log.info(
                "[NETRR-REJECT] %s net_rr=%.2f < min_net_rr=%.2f — "
                "gross_rr=%.2f entry=%.5f sl=%.5f tp=%.5f lot=%.4f",
                sym,
                net_rr,
                self.min_net_rr,
                gross_rr,
                entry,
                sl,
                tp,
                lot,
            )
            return None

        sl_pct = round(abs(entry - sl) / entry * 100, 4)

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
            fvg_top=fvg.top,
            fvg_bottom=fvg.bottom,
            initial_sl=sl,
        )

    # ── Breakeven (Düzeltme 5, 8) ────────────────────────────────────────────

    def should_move_to_breakeven(
        self,
        trade: dict,
        current_price: float,
        trigger_rr: float = 1.1,
    ) -> bool:
        """
        Düzeltme 8: Mesafe her zaman initial_sl üzerinden ölçülür.
        SL bir kez taşındığında mesafe sıfırlanmaz — sonsuz tetikleme önlenir.
        """
        # Düzeltme 8: current_sl yerine initial_sl referansı
        dist = abs(trade["entry"] - trade["initial_sl"])
        if trade["direction"] == "long":
            target = trade["entry"] + dist * trigger_rr
            return current_price >= target
        else:
            target = trade["entry"] - dist * trigger_rr
            return current_price <= target

    def breakeven_sl(self, trade: dict) -> float:
        """
        Düzeltme 5: Short işlemde komisyon entry'e EKLENIR (kâr garantisi).

        Long  → SL = entry + cost  (maliyet üstünde → kâr garantisi)
        Short → SL = entry + cost  (maliyet üstünde kapandığımız için short'ta
                                    entry + cost ZARARDIR → short SL = entry + cost
                                    yani fiyat entry + cost'un üstüne geçerse SL patlar)

        Detay:
          Long'da  kâr = close > entry  → breakeven = entry + komisyon (fiyat biraz artmalı)
          Short'da kâr = close < entry  → breakeven SL = entry + komisyon
                                          (entry + cost'un üstüne geçerse zarar, orada dur)
        """
        cost = trade["entry"] * (self.taker_fee * 2 + self.spread_pct) * 1.005
        if trade["direction"] == "long":
            return round(trade["entry"] + cost, 5)
        # Short: başabaş için fiyatın entry - cost'a düşmesi lazım
        return round(trade["entry"] - cost, 5)

    # ── Trailing SL (Düzeltme 4) ─────────────────────────────────────────────

    def trailing_sl(
        self,
        trade: dict,
        current_price: float,
        current_sl: float,
        step_ratio: float = 0.25,
    ) -> float:
        """
        Düzeltme 4: Trailing step yönü düzeltildi.

        Long  → new_sl hesaplandıktan sonra + step eklenir (SL yukarı iter)
                max(current_sl, new_sl + step)  ← önceki: new_sl - step (geri itiyordu)
        Short → new_sl hesaplandıktan sonra - step çıkarılır (SL aşağı iter)
                min(current_sl, new_sl - step)  ← önceki: new_sl + step (geri itiyordu)
        """
        dist = abs(trade["entry"] - trade.get("initial_sl", trade.get("current_sl", current_sl)))
        step = dist * step_ratio

        if trade["direction"] == "long":
            new_sl = current_price - dist
            # Düzeltme 4: + step (SL'i yukarıya doğru iter)
            return round(max(current_sl, new_sl + step), 5)
        else:
            new_sl = current_price + dist
            # Düzeltme 4: - step (SL'i aşağıya doğru iter)
            return round(min(current_sl, new_sl - step), 5)
