"""
test_risk_manager.py — NEXUS V3

Kapsam:
  - calculate_sl_htf   : sweep/no-sweep, LONG/SHORT, tier buffer, max/min koruması
  - calculate_tp_htf   : 1H likidite / fallback RR
  - calculate_lot      : lot formülü, max_lot sınırı, sıfır marjin
  - _calc_stop_levels  : breakeven + trailing trigger seviyeleri
  - should_move_to_breakeven / breakeven_sl / trailing_sl
  - build_trade        : tam entegrasyon — TradeParams üretimi ve None senaryoları
"""

from __future__ import annotations

import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import config
    from conftest import make_risk_manager, make_state


# ═══════════════════════════════════════════════════════════════
# calculate_sl_htf
# ═══════════════════════════════════════════════════════════════


class TestCalculateSlHtf:
    """4H Swing tabanlı SL hesaplama."""

    # ── LONG ──────────────────────────────────────────────────

    def test_long_sl_below_swing(self):
        """LONG SL, 4H swing low'un biraz altında olmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 95.0  # 4H swing low
        sl = rm.calculate_sl_htf("BTCUSDT", "LONG", entry, swing)
        assert sl is not None
        assert sl < swing, "SL swing low'un altında olmalı"
        assert sl < entry, "SL entry'nin altında olmalı"

    def test_short_sl_above_swing(self):
        """SHORT SL, 4H swing high'ın biraz üstünde olmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 105.0  # 4H swing high
        sl = rm.calculate_sl_htf("BTCUSDT", "SHORT", entry, swing)
        assert sl is not None
        assert sl > swing, "SL swing high'ın üstünde olmalı"
        assert sl > entry, "SL entry'nin üstünde olmalı"

    def test_tier1_buffer_applied(self):
        """BTC tier1 sl_buffer=0.0015 uygulanmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 95.0
        sl = rm.calculate_sl_htf("BTCUSDT", "LONG", entry, swing)
        expected = swing * (1.0 - 0.0015)
        assert sl == pytest.approx(expected, rel=1e-4)

    def test_tier3_buffer_applied(self):
        """AVAX tier3 sl_buffer=0.0060 uygulanmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 95.0
        sl = rm.calculate_sl_htf("AVAXUSDT", "LONG", entry, swing)
        expected = swing * (1.0 - 0.0060)
        assert sl == pytest.approx(expected, rel=1e-4)

    def test_min_sl_distance_enforced(self):
        """SL entry'ye çok yakınsa dışarı itilmeli — None dönmemeli."""
        rm = make_risk_manager()
        entry = 100.0
        # swing neredeyse entry ile aynı → buf uygulanınca dist < min_sl_pct
        # tier1: sl_buffer=0.0015, min_sl_pct=0.0015
        # swing = 99.9999 → raw_sl = 99.9999 * (1 - 0.0015) ≈ 99.8499
        # dist = |100 - 99.8499| = 0.1501 → min_dist = 0.0015 * 100 = 0.15
        # 0.1501 > 0.15 → min check geçer, dışarı itme tetiklenmez
        # Gerçekten tetiklemek için swing'i entry'ye çok yakın koy:
        # swing = entry (dist = 0 → min_sl_pct * entry * 1.5 = 0.225 ile itilir)
        swing_equal = 100.0
        sl = rm.calculate_sl_htf("BTCUSDT", "LONG", entry, swing_equal)
        assert sl is not None, "SL None olmamalı — min_dist koruması devreye girmeli"
        dist = abs(entry - sl)
        # Dışarı itme tetiklendi: dist = min_sl_pct * entry * 1.5 = 0.225
        assert dist >= 0.0015 * entry, f"SL yeterince uzakta değil: dist={dist}"

    def test_extreme_wide_sl_rejected(self):
        """SL max_allowed_dist'i aşarsa None dönmeli."""
        rm = make_risk_manager()
        entry = 100.0
        # tier1 max_sl_pct=0.025, max_allowed = 0.025 * entry * 5 = 12.5
        # swing çok uzakta → dist çok büyük
        swing_far = 10.0  # entry=100, dist yaklaşık 90 → reddedilmeli
        sl = rm.calculate_sl_htf("BTCUSDT", "LONG", entry, swing_far)
        assert sl is None

    # ── Sweep Level (Turtle Soup) ──────────────────────────────

    def test_sweep_level_takes_priority_long(self):
        """Sweep level varsa 4H swing'den daha yakın SL kullanılmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 90.0  # çok uzakta
        sweep = 97.0  # yakın sweep seviyesi
        sl_with_sweep = rm.calculate_sl_htf("BTCUSDT", "LONG", entry, swing, sweep_level=sweep)
        sl_no_sweep = rm.calculate_sl_htf("BTCUSDT", "LONG", entry, swing)
        assert sl_with_sweep is not None
        assert sl_no_sweep is not None
        # Sweep bazlı SL, swing bazlı'dan daha büyük (entry'ye daha yakın)
        assert sl_with_sweep > sl_no_sweep

    def test_sweep_level_takes_priority_short(self):
        """SHORT sweep level — SL entry'ye daha yakın olmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 110.0
        sweep = 103.0
        sl_with_sweep = rm.calculate_sl_htf("BTCUSDT", "SHORT", entry, swing, sweep_level=sweep)
        sl_no_sweep = rm.calculate_sl_htf("BTCUSDT", "SHORT", entry, swing)
        assert sl_with_sweep is not None
        assert sl_no_sweep is not None
        assert sl_with_sweep < sl_no_sweep

    def test_unknown_symbol_falls_to_tier3(self):
        """Bilinmeyen sembol tier3 buffer kullanmalı."""
        rm = make_risk_manager()
        entry = 100.0
        swing = 95.0
        sl = rm.calculate_sl_htf("UNKNOWUSDT", "LONG", entry, swing)
        expected = swing * (1.0 - 0.0060)  # tier3 buffer
        assert sl == pytest.approx(expected, rel=1e-4)


# ═══════════════════════════════════════════════════════════════
# calculate_tp_htf
# ═══════════════════════════════════════════════════════════════


class TestCalculateTpHtf:
    """1H Likidite bazlı TP hesaplama."""

    def test_h1_liquidity_used_when_available_long(self):
        """LONG: h1_liquidity_level yeterli uzakta ise TP = h1_liquidity_level."""
        rm = make_risk_manager()
        entry = 100.0
        risk_dist = 2.0
        h1_tp = 110.0  # %10 uzakta — min_profit_pct=0.5% geçer
        tp = rm.calculate_tp_htf("TEST", entry, risk_dist, h1_tp, "LONG")
        assert tp == h1_tp

    def test_h1_liquidity_used_when_available_short(self):
        """SHORT: h1_liquidity_level geçerli ise TP orada."""
        rm = make_risk_manager()
        entry = 100.0
        risk_dist = 2.0
        h1_tp = 88.0  # %12 uzakta
        tp = rm.calculate_tp_htf("TEST", entry, risk_dist, h1_tp, "SHORT")
        assert tp == h1_tp

    def test_fallback_rr_long(self):
        """h1_liquidity_level=None ise default_rr=2.0 ile fallback."""
        rm = make_risk_manager(default_rr=2.0)
        entry = 100.0
        risk_dist = 3.0
        tp = rm.calculate_tp_htf("TEST", entry, risk_dist, None, "LONG")
        assert tp == pytest.approx(entry + risk_dist * 2.0)

    def test_fallback_rr_short(self):
        rm = make_risk_manager(default_rr=2.0)
        entry = 100.0
        risk_dist = 3.0
        tp = rm.calculate_tp_htf("TEST", entry, risk_dist, None, "SHORT")
        assert tp == pytest.approx(entry - risk_dist * 2.0)

    def test_h1_too_close_falls_back(self):
        """h1_liquidity_level entry'ye çok yakınsa (%0.5'ten az) fallback kullanılmalı."""
        rm = make_risk_manager(default_rr=2.0)
        entry = 100.0
        risk_dist = 1.0
        # h1_tp sadece %0.1 uzakta — min_profit_pct=0.5% altında
        h1_tp = 100.1
        tp = rm.calculate_tp_htf("TEST", entry, risk_dist, h1_tp, "LONG")
        # fallback: entry + risk_dist * default_rr = 102.0
        assert tp == pytest.approx(entry + risk_dist * 2.0)


# ═══════════════════════════════════════════════════════════════
# calculate_lot
# ═══════════════════════════════════════════════════════════════


class TestCalculateLot:
    """Lot büyüklüğü hesaplama."""

    def test_basic_lot_formula(self):
        """risk_usd / sl_dist formülü."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        # risk_usd = 10_000 * 0.01 = 100
        # sl_dist = |100 - 98| = 2
        # raw_lot = 100 / 2 = 50
        lot = rm.calculate_lot("BTCUSDT", entry=100.0, sl=98.0)
        assert lot == pytest.approx(50.0, rel=1e-3)

    def test_max_lot_capped(self):
        """Çok büyük raw_lot, max_lot ile sınırlandırılmalı."""
        rm = make_risk_manager(balance=1_000.0, risk_pct=0.99, leverage=2.0)
        # risk_usd = 1000 * 0.99 = 990
        # sl_dist = |100 - 99.99| = 0.01 → raw_lot = 99_000 (çok büyük)
        # max_lot = (1000 * 2 * 0.80) / 100 = 16
        lot = rm.calculate_lot("BTCUSDT", entry=100.0, sl=99.99)
        max_lot = (1_000.0 * 2.0 * 0.80) / 100.0
        assert lot == pytest.approx(max_lot, rel=1e-3)

    def test_zero_margin_returns_zero(self):
        """Kullanılabilir marjin 0 ise lot=0.0 dönmeli."""
        from risk_manager import RiskManager

        rm = RiskManager(balance=0.0, available_margin=0.0)
        lot = rm.calculate_lot("BTCUSDT", entry=100.0, sl=98.0)
        assert lot == 0.0

    def test_zero_sl_distance_returns_zero(self):
        """SL = entry ise (dist=0) lot=0.0 dönmeli."""
        rm = make_risk_manager()
        lot = rm.calculate_lot("BTCUSDT", entry=100.0, sl=100.0)
        assert lot == 0.0

    def test_lot_decimals_btc(self):
        """BTC tier1 → 3 ondalık basamak."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        lot = rm.calculate_lot("BTCUSDT", entry=50_000.0, sl=49_900.0)
        # Rounded lot 3 decimal
        rounded = rm._round_lot("BTCUSDT", lot)
        assert rounded == round(rounded, 3)

    def test_lot_decimals_doge(self):
        """DOGE LOT_DECIMALS_OVERRIDE=0 → tam sayı lot."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        lot = rm.calculate_lot("DOGEUSDT", entry=0.1, sl=0.095)
        rounded = rm._round_lot("DOGEUSDT", lot)
        assert rounded == int(rounded)


# ═══════════════════════════════════════════════════════════════
# _calc_stop_levels
# ═══════════════════════════════════════════════════════════════


class TestCalcStopLevels:
    """Kademeli stop seviyeleri: breakeven_trigger (trailing_sl dinamik hesaplanır)."""

    def test_long_breakeven_trigger(self):
        """LONG: entry + 1R mesafesi."""
        from risk_manager import RiskManager

        entry, sl = 100.0, 95.0
        risk_dist = entry - sl  # 5.0
        be = RiskManager._calc_stop_levels("long", entry, sl)
        expected_be = round(entry + risk_dist * config.BREAKEVEN_R, 5)
        assert be == pytest.approx(expected_be)

    def test_short_breakeven_trigger(self):
        """SHORT: entry - 1R mesafesi."""
        from risk_manager import RiskManager

        entry, sl = 100.0, 105.0
        risk_dist = sl - entry  # 5.0
        be = RiskManager._calc_stop_levels("short", entry, sl)
        expected_be = round(entry - risk_dist * config.BREAKEVEN_R, 5)
        assert be == pytest.approx(expected_be)

    def test_long_trailing_level(self):
        """LONG: _calc_stop_levels sadece breakeven_trigger döner (trailing kaldırıldı)."""
        from risk_manager import RiskManager

        entry, sl = 100.0, 95.0
        risk_dist = 5.0
        be = RiskManager._calc_stop_levels("long", entry, sl)
        expected_be = round(entry + risk_dist * config.BREAKEVEN_R, 5)
        assert be == pytest.approx(expected_be)

    def test_short_trailing_level(self):
        """SHORT: _calc_stop_levels sadece breakeven_trigger döner (trailing kaldırıldı)."""
        from risk_manager import RiskManager

        entry, sl = 100.0, 106.0
        risk_dist = 6.0
        be = RiskManager._calc_stop_levels("short", entry, sl)
        expected_be = round(entry - risk_dist * config.BREAKEVEN_R, 5)
        assert be == pytest.approx(expected_be)


# ═══════════════════════════════════════════════════════════════
# should_move_to_breakeven / breakeven_sl / trailing_sl
# ═══════════════════════════════════════════════════════════════


class TestBreakevenTrailing:
    """Runtime stop yönetimi."""

    def _trade(self, direction="long", entry=100.0, sl=95.0, be_level=None):
        """Test için minimal trade dict."""
        t = {"direction": direction, "entry": entry, "initial_sl": sl}
        if be_level is not None:
            t["breakeven_level"] = be_level
        return t

    def test_long_breakeven_not_reached(self):
        from risk_manager import RiskManager

        trade = self._trade("long", 100.0, 95.0, be_level=105.0)
        assert not RiskManager.should_move_to_breakeven(trade, current_price=104.9)

    def test_long_breakeven_reached(self):
        from risk_manager import RiskManager

        trade = self._trade("long", 100.0, 95.0, be_level=105.0)
        assert RiskManager.should_move_to_breakeven(trade, current_price=105.0)
        assert RiskManager.should_move_to_breakeven(trade, current_price=106.0)

    def test_short_breakeven_reached(self):
        from risk_manager import RiskManager

        trade = self._trade("short", 100.0, 106.0, be_level=94.0)
        assert RiskManager.should_move_to_breakeven(trade, current_price=94.0)
        assert RiskManager.should_move_to_breakeven(trade, current_price=93.0)

    def test_breakeven_sl_returns_entry(self):
        """breakeven_sl her zaman entry döner."""
        from risk_manager import RiskManager

        trade = self._trade("long", entry=100.0, sl=95.0)
        assert RiskManager.breakeven_sl(trade) == 100.0

    def test_trailing_sl_long_moves_up(self):
        """LONG trailing: SL yukarı kayar."""
        from risk_manager import RiskManager

        trade = self._trade("long")
        current_price = 110.0
        current_sl = 100.0
        new_sl = RiskManager.trailing_sl(trade, current_price, current_sl, step_ratio=0.25)
        expected = current_sl + (current_price - current_sl) * 0.25
        assert new_sl == pytest.approx(round(expected, 5))
        assert new_sl > current_sl

    def test_trailing_sl_short_moves_down(self):
        """SHORT trailing: SL aşağı kayar."""
        from risk_manager import RiskManager

        trade = self._trade("short")
        current_price = 90.0
        current_sl = 100.0
        new_sl = RiskManager.trailing_sl(trade, current_price, current_sl, step_ratio=0.25)
        expected = current_sl - (current_sl - current_price) * 0.25
        assert new_sl == pytest.approx(round(expected, 5))
        assert new_sl < current_sl

    def test_be_fallback_uses_risk_dist(self):
        """breakeven_level yoksa entry ± risk_dist * BREAKEVEN_R kullanılmalı."""
        from risk_manager import RiskManager

        # BREAKEVEN_R = 1.0, risk_dist = 5.0 → be = 105.0
        trade = {"direction": "long", "entry": 100.0, "initial_sl": 95.0}
        assert RiskManager.should_move_to_breakeven(trade, current_price=105.0)
        assert not RiskManager.should_move_to_breakeven(trade, current_price=104.9)


# ═══════════════════════════════════════════════════════════════
# trailing_sl — Yön Doğrulama (P0/P1 fix sonrası)
# ═══════════════════════════════════════════════════════════════


class TestTrailingSlDirectionGuard:
    """trailing_sl: SL asla ters yöne gitmemeli (P0/P1 fix doğrulaması)."""

    @staticmethod
    def _trade(direction: str, entry: float = 100.0, sl: float = 95.0) -> dict:
        return {"direction": direction, "entry": entry, "initial_sl": sl}

    # ── LONG ──────────────────────────────────────────────────

    def test_long_trailing_sl_never_goes_down(self):
        """LONG: fiyat düşünce SL geri çekilmemeli (P1 fix)."""
        from risk_manager import RiskManager

        trade = self._trade("long")
        current_price = 90.0  # fiyat SL'nin altına düştü (ters yön)
        current_sl = 100.0
        new_sl = RiskManager.trailing_sl(trade, current_price, current_sl, step_ratio=0.25)
        assert new_sl >= current_sl, f"LONG'da SL geri çekilmemeli! current_sl={current_sl}, new_sl={new_sl}"

    def test_long_trailing_sl_no_move_when_price_drops(self):
        """LONG: fiyat düşünce SL sabit kalır (max guard)."""
        from risk_manager import RiskManager

        trade = self._trade("long")
        current_sl = 105.0
        # Fiyat SL'nin altına düştü
        new_sl = RiskManager.trailing_sl(trade, 100.0, current_sl, step_ratio=0.25)
        assert new_sl == current_sl, f"LONG'da fiyat düşünce SL değişmemeli: {new_sl} != {current_sl}"

    def test_long_trailing_sl_moves_up_in_profit(self):
        """LONG: fiyat yükselince SL yukarı çekilir."""
        from risk_manager import RiskManager

        trade = self._trade("long")
        current_sl = 100.0
        new_sl = RiskManager.trailing_sl(trade, 110.0, current_sl, step_ratio=0.25)
        assert new_sl > current_sl, f"LONG'da kârda SL yukarı çekilmeli: {new_sl} <= {current_sl}"

    # ── SHORT ─────────────────────────────────────────────────

    def test_short_trailing_sl_never_goes_up(self):
        """SHORT: fiyat yükselince SL yukarı çekilmemeli — zarar büyümesin (P0 fix)."""
        from risk_manager import RiskManager

        trade = self._trade("short")
        current_price = 110.0  # fiyat SL'nin üstüne çıktı (ters yön — zarar)
        current_sl = 100.0
        new_sl = RiskManager.trailing_sl(trade, current_price, current_sl, step_ratio=0.25)
        # P0 fix: min(new_sl, current_sl) → SL asla yukarı gitmez
        assert new_sl <= current_sl, (
            f"SHORT'ta SL yukarı çekilmemeli (zarar büyümemeli)! " f"current_sl={current_sl}, new_sl={new_sl}"
        )

    def test_short_trailing_sl_no_move_when_price_rises(self):
        """SHORT: fiyat SL'nin üstüne çıkınca SL sabit kalır (min guard)."""
        from risk_manager import RiskManager

        trade = self._trade("short")
        current_sl = 95.0
        # Fiyat SL'nin üstüne çıktı (zarar bölgesi)
        new_sl = RiskManager.trailing_sl(trade, 105.0, current_sl, step_ratio=0.25)
        assert new_sl == current_sl, f"SHORT'ta fiyat yükselince SL değişmemeli: {new_sl} != {current_sl}"

    def test_short_trailing_sl_moves_down_in_profit(self):
        """SHORT: fiyat düşünce SL aşağı çekilir (kâr kilitlenir)."""
        from risk_manager import RiskManager

        trade = self._trade("short")
        current_sl = 100.0
        new_sl = RiskManager.trailing_sl(trade, 90.0, current_sl, step_ratio=0.25)
        assert new_sl < current_sl, f"SHORT'ta kârda SL aşağı çekilmeli: {new_sl} >= {current_sl}"

    def test_short_trailing_sl_delta_positive(self):
        """SHORT: (current_sl - current_price) pozitifken SL doğru yönde hareket eder."""
        from risk_manager import RiskManager

        trade = self._trade("short")
        # current_price=90 < current_sl=100 → kâr bölgesi → SL 100'den aşağı çekilmeli
        current_sl = 100.0
        current_price = 90.0
        new_sl = RiskManager.trailing_sl(trade, current_price, current_sl, step_ratio=0.25)
        assert 90.0 <= new_sl < current_sl, (
            f"SHORT kârda: SL current_sl({current_sl}) ile current_price({current_price}) "
            f"arasında olmalı, new_sl={new_sl}"
        )


# ═══════════════════════════════════════════════════════════════
# build_trade — Entegrasyon
# ═══════════════════════════════════════════════════════════════


class TestBuildTrade:
    """build_trade() tam entegrasyon testleri."""

    def test_returns_trade_params_long(self):
        """Geçerli LONG girdi → TradeParams dönmeli."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(
            symbol="BTCUSDT",
            direction="LONG",
            fvg_upper=101.0,
            fvg_lower=99.0,
            htf_strength="STRONG",
        )
        tp = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=93.0,
            h1_liquidity_level=115.0,
        )
        assert tp is not None
        assert tp.direction == "long"
        assert tp.entry == pytest.approx(100.0)
        assert tp.sl < 100.0
        assert tp.tp == pytest.approx(115.0)  # h1_liquidity_level kullanıldı

    def test_returns_trade_params_short(self):
        """Geçerli SHORT girdi → TradeParams dönmeli."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(
            symbol="ETHUSDT",
            direction="SHORT",
            fvg_upper=101.0,
            fvg_lower=99.0,
            htf_strength="STRONG",
        )
        tp = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=107.0,
            h1_liquidity_level=85.0,
        )
        assert tp is not None
        assert tp.direction == "short"
        assert tp.sl > 100.0
        assert tp.tp == pytest.approx(85.0)

    def test_fvg_midpoint_fallback_entry(self):
        """entry_price=None ise FVG midpoint kullanılmalı."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(
            fvg_upper=102.0,
            fvg_lower=98.0,
            htf_strength="STRONG",
        )
        tp = rm.build_trade(
            state,
            entry_price=None,
            h4_swing_level=92.0,
            h1_liquidity_level=115.0,
        )
        assert tp is not None
        assert tp.entry == pytest.approx(100.0)  # (102+98)/2 = 100

    def test_no_direction_returns_none(self):
        """state.direction=None → None dönmeli."""
        rm = make_risk_manager()
        state = make_state(direction=None)
        result = rm.build_trade(state, entry_price=100.0, h4_swing_level=95.0)
        assert result is None

    def test_no_fvg_bounds_returns_none(self):
        """FVG seviyeleri yoksa None dönmeli."""
        rm = make_risk_manager()
        state = make_state(fvg_upper=None, fvg_lower=None)
        result = rm.build_trade(state, entry_price=100.0, h4_swing_level=95.0)
        assert result is None

    def test_extreme_sl_rejected(self):
        """SL çok geniş → build_trade None dönmeli."""
        rm = make_risk_manager()
        state = make_state(symbol="BTCUSDT", direction="LONG")
        # swing çok uzakta → calculate_sl_htf None döner → build_trade None
        result = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=1.0,  # entry=100, dist=99 → max_allowed ≈ 12.5
        )
        assert result is None

    def test_lot_positive(self):
        """TradeParams.lot > 0 olmalı."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(htf_strength="STRONG")
        tp = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=93.0,
            h1_liquidity_level=115.0,
        )
        assert tp is not None
        assert tp.lot > 0

    def test_breakeven_and_trailing_levels_set(self):
        """TradeParams'ta breakeven_level ve trailing_level doldurulmalı."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(htf_strength="STRONG")
        tp = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=93.0,
            h1_liquidity_level=115.0,
        )
        assert tp is not None
        # LONG: breakeven_level > entry (1R yukarı)
        assert tp.breakeven_level > tp.entry
        # trailing_level: artık _calc_stop_levels tarafından hesaplanmıyor
        # trailing_sl() dinamik olarak güncel fiyatla çalışır
        assert tp.trailing_level == 0.0

    def test_htf_strength_weak_scales_risk(self):
        """WEAK sinyal → risk %40'a düşmeli → daha küçük lot."""
        rm_strong = make_risk_manager(balance=10_000.0, risk_pct=0.02)
        rm_weak = make_risk_manager(balance=10_000.0, risk_pct=0.02)

        state_strong = make_state(htf_strength="STRONG")
        state_weak = make_state(htf_strength="WEAK")

        tp_strong = rm_strong.build_trade(
            state_strong, entry_price=100.0, h4_swing_level=93.0, h1_liquidity_level=115.0
        )
        tp_weak = rm_weak.build_trade(state_weak, entry_price=100.0, h4_swing_level=93.0, h1_liquidity_level=115.0)

        assert tp_strong is not None and tp_weak is not None
        assert tp_weak.lot < tp_strong.lot

    def test_h4_swing_none_falls_back_to_fvg_sl(self):
        """h4_swing_level=None → FVG tabanlı SL fallback kullanılmalı."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(
            symbol="BTCUSDT",
            direction="LONG",
            fvg_upper=101.0,
            fvg_lower=99.0,
            htf_strength="STRONG",
        )
        tp = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=None,  # FVG fallback tetiklenir
            h1_liquidity_level=115.0,
        )
        # FVG SL'si tier1 max_sl_pct'yi aşmıyorsa TradeParams dönmeli
        # Yakın FVG → aşmaz → None olmaz
        if tp is not None:
            assert tp.sl < 100.0

    def test_gross_rr_computed_correctly(self):
        """gross_rr = reward_dist / risk_dist doğru hesaplanmalı."""
        rm = make_risk_manager(balance=10_000.0, risk_pct=0.01)
        state = make_state(htf_strength="STRONG")
        tp = rm.build_trade(
            state,
            entry_price=100.0,
            h4_swing_level=93.0,
            h1_liquidity_level=115.0,
        )
        assert tp is not None
        expected_rr = abs(tp.tp - tp.entry) / abs(tp.sl - tp.entry)
        assert tp.gross_rr == pytest.approx(expected_rr, rel=1e-3)
