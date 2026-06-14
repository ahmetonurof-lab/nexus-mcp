"""
test_fvg_missed_flow.py — NEXUS V3 FVG Missed Flow Characterization (P1-0C)

Kapsam:
  - Case C patikası: MISSED_FVG → WAIT_POI_CONFIRM → READY_TO_ENTER
  - _check_missed_fvg: pen < 0.15 tetikleme, erken return durumları
  - check_poi_retrace: POI anchor bölgesine dönüş, buffer hesaplama
  - fvg_missed flag: set/reset davranışı
  - Case C _evaluate gate: sweep + mss + fvg_missed + ltf
  - WAIT_CONFIRM'de FVG tamamen aşılma → WAIT_NEW_FVG
"""

from __future__ import annotations

import time
import warnings
from datetime import datetime

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from conftest import make_bar


# ═══════════════════════════════════════════════════════════════
# Yardımcılar
# ═══════════════════════════════════════════════════════════════


def make_sm():
    """Temiz StateMachine instance'ı."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from state_machine import StateMachine
    return StateMachine()


def fire(sm, symbol, **event_kwargs):
    """Tek event gönder."""
    sm.update_from_event(symbol, event_kwargs)


# ═══════════════════════════════════════════════════════════════
# _check_missed_fvg — Temel Tetikleme Koşulları
# ═══════════════════════════════════════════════════════════════


class TestCheckMissedFvg:
    """_check_missed_fvg: pen < 0.15 → MISSED_FVG tetikleme."""

    def _setup_wait_retrace(self, sm, symbol="BTCUSDT", direction="LONG", fvg_upper=100.1, fvg_lower=99.9):
        from state_machine import SetupState

        state = sm.get(symbol)
        state.direction = direction
        state.fvg_upper = fvg_upper
        state.fvg_lower = fvg_lower
        state.sweep_detected = True
        state.mss_confirmed = True
        state.displacement_origin = 99.5
        state.state = SetupState.WAIT_RETRACE
        return state

    def test_long_pen_below_min_after_passing_fvg_triggers_missed(self):
        """
        LONG: Fiyat FVG'yi çok az girip (pen < 0.15) geçmişse → MISSED_FVG.
        size=0.2, pen = |99.92 - 99.9| / 0.2 = 0.10 < 0.15
        Ayrıca fiyat FVG içinde (LONG için geçerli).
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        # Fiyat FVG içinde ama pen < 0.15
        # displacement_origin _setup_wait_retrace'te 99.5 olarak set edildi
        bar = make_bar(index=10, open_=99.95, high=99.98, low=99.90, close=99.92)
        sm.check_retrace("BTCUSDT", bar)
        st = sm.get("BTCUSDT")
        assert st.state == SetupState.MISSED_FVG
        assert st.fvg_missed is True
        assert st.missed_fvg_at_price == 99.92
        assert st.missed_fvg_bar_index == 10
        assert st.poi_anchor == 99.5  # displacement_origin'dan gelir

    def test_short_pen_below_min_triggers_missed(self):
        """
        SHORT: pen < 0.15, fiyat FVG içinde → MISSED_FVG.
        size=0.2, pen = (100.1 - 100.08) / 0.2 = 0.10 < 0.15
        close=100.08 < fvg_upper=100.1 → fiyat FVG'ye girmiş
        """
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_wait_retrace(sm, direction="SHORT", fvg_upper=100.1, fvg_lower=99.9)
        state.displacement_origin = 100.5
        # SHORT: fiyat FVG içinde (close=100.08 < fvg_upper=100.1 ✓)
        # pen = (100.1-100.08)/0.2 = 0.10 < 0.15 → Missed FVG
        bar = make_bar(index=10, open_=100.09, high=100.12, low=100.06, close=100.08)
        sm.check_retrace("BTCUSDT", bar)
        st = sm.get("BTCUSDT")
        assert st.state == SetupState.MISSED_FVG
        assert st.fvg_missed is True
        assert st.poi_anchor == 100.5
        assert st.direction == "SHORT"

    def test_retrace_seen_blocks_missed_fvg(self):
        """retrace_seen=True ise _check_missed_fvg early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        state.retrace_seen = True
        bar = make_bar(index=10, open_=99.95, high=99.98, low=99.88, close=99.92)
        sm.check_retrace("BTCUSDT", bar)
        # retrace_seen=True → _check_missed_fvg'den early return
        # Pen=0.10 < pen_min=0.15 ama retrace_seen=True olduğu için early return eder.
        # WAIT_RETRACE kalır (pen trade zone dışında)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE
        assert sm.get("BTCUSDT").fvg_missed is False

    def test_long_price_not_yet_reached_fvg_no_missed(self):
        """
        LONG: Fiyat FVG'nin altında (henüz gelmedi) → _check_missed_fvg early return.
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        # Fiyat 99.8 — FVG'nin altında, henüz gelmemiş
        bar = make_bar(index=10, open_=99.8, high=99.85, low=99.78, close=99.8)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE
        assert sm.get("BTCUSDT").fvg_missed is False

    def test_short_price_not_yet_reached_fvg_no_missed(self):
        """
        SHORT: Fiyat FVG'nin üstünde (henüz gelmedi) → _check_missed_fvg early return.
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="SHORT", fvg_upper=100.1, fvg_lower=99.9)
        # Fiyat 100.2 — FVG'nin üstünde, henüz gelmemiş
        bar = make_bar(index=10, open_=100.2, high=100.3, low=100.15, close=100.2)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE
        assert sm.get("BTCUSDT").fvg_missed is False

    def test_bars_since_too_few_blocks_missed_fvg(self):
        """
        fvg_entry_bar_index'ten sonra < 3 bar geçtiyse → early return.
        Erken false positive'leri engeller.
        """
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        state.fvg_entry_bar_index = 8  # sadece 2 bar önce
        bar = make_bar(index=10, open_=99.95, high=99.98, low=99.90, close=99.92)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE
        assert sm.get("BTCUSDT").fvg_missed is False

    def test_no_fvg_levels_blocks_missed_fvg(self):
        """FVG seviyeleri yoksa _check_missed_fvg early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_RETRACE
        state.direction = "LONG"
        state.fvg_upper = None
        state.fvg_lower = None
        bar = make_bar(index=10, open_=98.5, high=98.8, low=98.4, close=98.55)
        sm.check_retrace("BTCUSDT", bar)
        assert state.fvg_missed is False


# ═══════════════════════════════════════════════════════════════
# check_poi_retrace — POI Anchor Bölgesine Dönüş
# ═══════════════════════════════════════════════════════════════


class TestCheckPoiRetrace:
    """check_poi_retrace: MISSED_FVG → WAIT_POI_CONFIRM."""

    def _setup_missed_fvg(
        self, sm, symbol="BTCUSDT", direction="LONG", fvg_upper=102.0, fvg_lower=98.0, poi_anchor=100.0
    ):
        from state_machine import SetupState

        state = sm.get(symbol)
        state.direction = direction
        state.fvg_upper = fvg_upper
        state.fvg_lower = fvg_lower
        state.sweep_detected = True
        state.mss_confirmed = True
        state.fvg_missed = True
        state.poi_anchor = poi_anchor
        state.state = SetupState.MISSED_FVG
        return state

    def test_poi_retrace_exact_anchor_triggers_wait_poi_confirm(self):
        """
        Fiyat tam poi_anchor'a dönerse → WAIT_POI_CONFIRM.
        fvg_size=4, buffer=4*0.3=1.2, zone=[98.8, 101.2].
        close=100.0 tam anchor → in zone.
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_missed_fvg(sm, poi_anchor=100.0)
        bar = make_bar(index=15, open_=99.5, high=100.5, low=99.5, close=100.0)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_POI_CONFIRM

    def test_poi_retrace_upper_buffer_edge_triggers(self):
        """
        Fiyat buffer üst sınırında → WAIT_POI_CONFIRM.
        fvg_size=4, buffer=1.2, upper=101.2. close=101.2 → in zone.
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_missed_fvg(sm, poi_anchor=100.0)
        bar = make_bar(index=15, open_=101.0, high=101.5, low=100.8, close=101.2)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_POI_CONFIRM

    def test_poi_retrace_lower_buffer_edge_triggers(self):
        """
        Fiyat buffer alt sınırında → WAIT_POI_CONFIRM.
        fvg_size=4, buffer=1.2, lower=98.8. close=98.8 → in zone.
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_missed_fvg(sm, poi_anchor=100.0)
        bar = make_bar(index=15, open_=98.8, high=99.2, low=98.5, close=98.8)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_POI_CONFIRM

    def test_poi_outside_buffer_no_transition(self):
        """
        Fiyat buffer dışında → MISSED_FVG kalır.
        anchor=100, buffer=1.2, zone=[98.8, 101.2]. close=97.0 → dışarıda.
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_missed_fvg(sm, poi_anchor=100.0)
        bar = make_bar(index=15, open_=97.0, high=97.5, low=96.5, close=97.0)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.MISSED_FVG

    def test_not_missed_fvg_state_ignored(self):
        """MISSED_FVG değilse check_poi_retrace early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_RETRACE
        state.poi_anchor = 100.0
        bar = make_bar(index=15, open_=100.0, high=100.5, low=99.5, close=100.0)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert state.state == SetupState.WAIT_RETRACE

    def test_poi_anchor_none_ignored(self):
        """poi_anchor None ise check_poi_retrace early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.MISSED_FVG
        state.poi_anchor = None
        bar = make_bar(index=15, open_=100.0, high=100.5, low=99.5, close=100.0)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert state.state == SetupState.MISSED_FVG

    def test_no_fvg_levels_poi_retrace_ignored(self):
        """FVG seviyeleri yoksa check_poi_retrace early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.MISSED_FVG
        state.poi_anchor = 100.0
        state.fvg_upper = None
        state.fvg_lower = None
        bar = make_bar(index=15, open_=100.0, high=100.5, low=99.5, close=100.0)
        sm.check_poi_retrace("BTCUSDT", bar)
        assert state.state == SetupState.MISSED_FVG


# ═══════════════════════════════════════════════════════════════
# Case C Tam Zincir Testleri
# ═══════════════════════════════════════════════════════════════


class TestCaseCFullChain:
    """Case C: IDLE → ARMED → WAIT_RETRACE → MISSED_FVG → WAIT_POI_CONFIRM → READY_TO_ENTER."""

    def test_full_case_c_chain_long(self):
        """
        Tam Case C zinciri (LONG):
        SWEEP → MSS → FVG → check_retrace (Case C) → check_poi_retrace → LTF_CONFIRM → READY_TO_ENTER
        """
        sm = make_sm()
        from state_machine import SetupState

        sym = "BTCUSDT"

        # 1. SWEEP → ARMED
        fire(sm, sym, type="SWEEP", tf="15m", level=9500.0, bar_index=1)
        assert sm.get(sym).state == SetupState.ARMED

        # 2. MSS → WAIT_RETRACE
        fire(sm, sym, type="MSS", direction="LONG", level=9800.0, bar_index=3, impulse_origin=10000.0)
        assert sm.get(sym).state == SetupState.WAIT_RETRACE
        assert sm.get(sym).displacement_origin == 10000.0

        # 3. FVG_CREATED (realistic ~0.2% size on ~10000 price)
        fire(sm, sym, type="FVG_CREATED", upper=10020.0, lower=9980.0, time=4)
        st = sm.get(sym)
        assert st.fvg_upper == 10020.0
        assert st.fvg_lower == 9980.0

        # 4. check_retrace: pen < 0.15 → MISSED_FVG
        # size=40, pen = |9985.0-9980.0|/40 = 0.125 < 0.15
        # realistic: fvg_size/price = 40/10000 = 0.004 → scale = 2.0 (capped)
        # pen_min = 0.15/2.0 = 0.075, pen_max = 0.70*2.0 = 0.85 (capped at 0.85)
        # pen=0.125 > 0.075 → would be in zone with dynamic!
        # Need pen < 0.075 → close < 9980 + 0.075*40 = 9983.0
        bar_miss = make_bar(index=10, open_=9982.0, high=9983.0, low=9980.0, close=9982.0)
        sm.check_retrace(sym, bar_miss)
        st_after = sm.get(sym)
        # With scale=2.0, pen_min=0.075:
        # pen = (9982-9980)/40 = 0.05 < 0.075 → not in zone
        # _check_missed_fvg: close=9982 > fvg_lower=9980 → passes direction check
        assert st_after.state == SetupState.MISSED_FVG
        assert st_after.fvg_missed is True
        assert st_after.poi_anchor == 10000.0

        # 5. check_poi_retrace: fiyat poi_anchor'a döndü → WAIT_POI_CONFIRM
        # fvg_size=40, buffer=40*0.3=12, zone=[9988, 10012], close=10000.0 → in zone
        bar_poi = make_bar(index=15, open_=9995.0, high=10005.0, low=9990.0, close=10000.0)
        sm.check_poi_retrace(sym, bar_poi)
        assert sm.get(sym).state == SetupState.WAIT_POI_CONFIRM

        # 6. LTF_CONFIRM → READY_TO_ENTER (Case C path in _handle_ltf)
        fire(sm, sym, type="LTF_CONFIRM", direction="LONG", close=10005.0)
        assert sm.get(sym).state == SetupState.READY_TO_ENTER
        assert sm.get(sym).ltf_confirmed is True
        assert sm.get(sym).entry_price == 10005.0

    def test_full_case_c_chain_short(self):
        """
        Tam Case C zinciri (SHORT):
        SWEEP → MSS → FVG → check_retrace (Case C) → check_poi_retrace → LTF_CONFIRM → READY_TO_ENTER
        """
        sm = make_sm()
        from state_machine import SetupState

        sym = "ETHUSDT"

        # 1. SWEEP → ARMED
        fire(sm, sym, type="SWEEP", tf="15m", level=2100.0, bar_index=1)
        assert sm.get(sym).state == SetupState.ARMED

        # 2. MSS (SHORT) → WAIT_RETRACE
        fire(sm, sym, type="MSS", direction="SHORT", level=2050.0, bar_index=3, impulse_origin=2000.0)
        assert sm.get(sym).state == SetupState.WAIT_RETRACE
        assert sm.get(sym).displacement_origin == 2000.0

        # 3. FVG_CREATED
        fire(sm, sym, type="FVG_CREATED", upper=2060.0, lower=1980.0, time=4)

        # 4. check_retrace: pen < 0.15 → MISSED_FVG (SHORT)
        # SHORT: fiyat FVG içinde olmalı (close < fvg_upper=2060.0)
        # size=80, fvg_ratio=80/2000=0.04 → scale=2.0 (capped)
        # pen_min=0.15/2=0.075, pen_max=0.70*2=1.40 (capped at 0.85)
        # Need pen < 0.075 → close > 2060 - 0.075*80 = 2054.0
        bar_miss = make_bar(index=10, open_=2055.0, high=2055.5, low=2048.0, close=2055.0)
        sm.check_retrace(sym, bar_miss)
        assert sm.get(sym).state == SetupState.MISSED_FVG
        assert sm.get(sym).fvg_missed is True
        assert sm.get(sym).poi_anchor == 2000.0

        # 5. check_poi_retrace: fiyat poi_anchor'a döndü → WAIT_POI_CONFIRM
        # fvg_size=80, buffer=80*0.3=24, zone=[1976, 2024], close=2000.0 → in zone
        bar_poi = make_bar(index=15, open_=1995.0, high=2005.0, low=1990.0, close=2000.0)
        sm.check_poi_retrace(sym, bar_poi)
        assert sm.get(sym).state == SetupState.WAIT_POI_CONFIRM

        # 6. LTF_CONFIRM → READY_TO_ENTER (Case C)
        fire(sm, sym, type="LTF_CONFIRM", direction="SHORT", close=1998.0)
        assert sm.get(sym).state == SetupState.READY_TO_ENTER


# ═══════════════════════════════════════════════════════════════
# fvg_missed Flag Set/Reset Davranışı
# ═══════════════════════════════════════════════════════════════


class TestFvgMissedFlag:
    """fvg_missed flag set/reset senaryoları."""

    def test_fvg_missed_set_on_case_c_trigger(self):
        """Case C tetiklendiğinde fvg_missed=True."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.direction = "LONG"
        state.fvg_upper = 100.1
        state.fvg_lower = 99.9
        state.sweep_detected = True
        state.mss_confirmed = True
        state.displacement_origin = 99.5
        state.state = SetupState.WAIT_RETRACE

        # size=0.2, pen = (99.92-99.9)/0.2 = 0.10 < 0.15 → MISSED_FVG
        bar = make_bar(index=10, open_=99.95, high=99.98, low=99.90, close=99.92)
        sm.check_retrace("BTCUSDT", bar)

        st = sm.get("BTCUSDT")
        assert st.fvg_missed is True
        assert st.missed_fvg_at_price == 99.92
        assert st.missed_fvg_bar_index == 10

    def test_fvg_missed_reset_by_reset_flags(self):
        """SymbolState.reset_flags() fvg_missed'i False yapmalı."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import SymbolState

        state = SymbolState(symbol="BTCUSDT")
        state.fvg_missed = True
        state.poi_anchor = 100.0
        state.displacement_origin = 99.0
        state.missed_fvg_at_price = 98.5
        state.missed_fvg_bar_index = 10
        state.displacement_high = 105.0
        state.displacement_low = 95.0

        state.reset_flags()

        assert state.fvg_missed is False
        assert state.poi_anchor is None
        assert state.displacement_origin is None
        assert state.missed_fvg_at_price is None
        assert state.missed_fvg_bar_index is None
        assert state.displacement_high is None
        assert state.displacement_low is None

    def test_fvg_missed_flag_without_displacement_origin(self):
        """
        displacement_origin None ise poi_anchor None olur.
        Yine de fvg_missed=True set edilir.
        """
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.direction = "LONG"
        state.fvg_upper = 100.1
        state.fvg_lower = 99.9
        state.sweep_detected = True
        state.mss_confirmed = True
        state.displacement_origin = None  # MSS gelmediğinde None olabilir
        state.state = SetupState.WAIT_RETRACE

        # size=0.2, pen = (99.92-99.9)/0.2 = 0.10 < 0.15 → MISSED_FVG
        bar = make_bar(index=10, open_=99.95, high=99.98, low=99.90, close=99.92)
        sm.check_retrace("BTCUSDT", bar)

        st = sm.get("BTCUSDT")
        assert st.fvg_missed is True
        assert st.poi_anchor is None  # displacement_origin'dan gelir

    def test_fvg_missed_not_set_on_normal_retrace(self):
        """Normal retrace (pen trade zone içinde) → fvg_missed False kalır."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.direction = "LONG"
        state.fvg_upper = 100.1
        state.fvg_lower = 99.9
        state.sweep_detected = True
        state.mss_confirmed = True
        state.state = SetupState.WAIT_RETRACE

        # FVG 100.1-99.9 (size=0.2), close=100.0 → pen = (100.0-99.9)/0.2 = 0.50 → trade zone içinde
        bar = make_bar(index=10, open_=100.02, high=100.05, low=99.95, close=100.0)
        sm.check_retrace("BTCUSDT", bar)

        st = sm.get("BTCUSDT")
        assert st.state == SetupState.WAIT_CONFIRM
        assert st.fvg_missed is False
        assert st.retrace_seen is True


# ═══════════════════════════════════════════════════════════════
# Case C _evaluate Flag Gate
# ═══════════════════════════════════════════════════════════════


class TestCaseCEvaluateGate:
    """Case C _evaluate: sweep + mss + fvg_missed + ltf → READY_TO_ENTER."""

    def _setup_case_c_ready(self, sm, symbol="BTCUSDT"):
        from state_machine import SetupState

        state = sm.get(symbol)
        state.sweep_detected = True
        state.mss_confirmed = True
        state.fvg_missed = True
        state.ltf_confirmed = True
        state.fvg_upper = 102.0
        state.fvg_lower = 98.0
        state.poi_anchor = 100.0
        state.direction = "LONG"
        state.state = SetupState.WAIT_POI_CONFIRM
        return state

    def test_case_c_all_flags_advances_to_ready(self):
        """Tüm Case C flagleri True → READY_TO_ENTER."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        sm._evaluate(state)
        assert state.state == SetupState.READY_TO_ENTER

    def test_case_c_from_missed_fvg_state_advances(self):
        """MISSED_FVG state'indeyken tüm flagler True → READY_TO_ENTER."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        state.state = SetupState.MISSED_FVG
        sm._evaluate(state)
        assert state.state == SetupState.READY_TO_ENTER

    def test_case_c_from_wait_retrace_state_advances(self):
        """WAIT_RETRACE state'indeyken tüm flagler True → READY_TO_ENTER."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        state.state = SetupState.WAIT_RETRACE
        sm._evaluate(state)
        assert state.state == SetupState.READY_TO_ENTER

    def test_case_c_missing_fvg_missed_flag_blocks(self):
        """fvg_missed=False ise Case C gate tetiklenmez."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        state.fvg_missed = False
        sm._evaluate(state)
        # Case A gate de tetiklenmemeli çünkü retrace_seen False
        assert state.state != SetupState.READY_TO_ENTER

    def test_case_c_missing_sweep_blocks(self):
        """sweep_detected=False ise Case C gate tetiklenmez."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        state.sweep_detected = False
        sm._evaluate(state)
        assert state.state != SetupState.READY_TO_ENTER

    def test_case_c_missing_mss_blocks(self):
        """mss_confirmed=False ise Case C gate tetiklenmez."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        state.mss_confirmed = False
        sm._evaluate(state)
        assert state.state != SetupState.READY_TO_ENTER

    def test_case_c_missing_ltf_blocks(self):
        """ltf_confirmed=False ise Case C gate tetiklenmez."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_case_c_ready(sm)
        state.ltf_confirmed = False
        sm._evaluate(state)
        assert state.state != SetupState.READY_TO_ENTER


# ═══════════════════════════════════════════════════════════════
# WAIT_CONFIRM'de FVG Tamamen Aşılma → WAIT_NEW_FVG
# ═══════════════════════════════════════════════════════════════


class TestWaitConfirmFvgBreach:
    """WAIT_CONFIRM'de pen > FVG_PENETRATION_MAX → WAIT_NEW_FVG."""

    def _setup_wait_confirm(self, sm, symbol="BTCUSDT", direction="LONG", fvg_upper=102.0, fvg_lower=98.0):
        from state_machine import SetupState

        state = sm.get(symbol)
        state.direction = direction
        state.fvg_upper = fvg_upper
        state.fvg_lower = fvg_lower
        state.sweep_detected = True
        state.mss_confirmed = True
        state.retrace_seen = True
        state.state = SetupState.WAIT_CONFIRM
        return state

    def test_long_pen_above_max_transitions_to_wait_new_fvg(self):
        """
        LONG: WAIT_CONFIRM'de pen > 0.70 → WAIT_NEW_FVG.
        size=4, pen = |100.9-98.0|/4 = 0.725 > 0.70
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_confirm(sm, direction="LONG")
        bar = make_bar(index=15, open_=100.5, high=101.0, low=100.0, close=100.9)
        sm.check_ltf_fvg_validity("BTCUSDT", bar)

        st = sm.get("BTCUSDT")
        assert st.state == SetupState.WAIT_NEW_FVG
        assert st.retrace_seen is False
        assert st.ltf_confirmed is False
        assert st.fvg_upper is None
        assert st.fvg_lower is None

    def test_short_pen_above_max_transitions_to_wait_new_fvg(self):
        """
        SHORT: WAIT_CONFIRM'de pen > 0.70 → WAIT_NEW_FVG.
        size=4, pen = |99.1-102.0|/4 = 0.725 > 0.70
        """
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_confirm(sm, direction="SHORT")
        bar = make_bar(index=15, open_=99.5, high=100.0, low=98.5, close=99.1)
        sm.check_ltf_fvg_validity("BTCUSDT", bar)

        st = sm.get("BTCUSDT")
        assert st.state == SetupState.WAIT_NEW_FVG

    def test_pen_still_in_zone_no_transition(self):
        """pen hâlâ trade zone içinde → WAIT_CONFIRM kalır."""
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_confirm(sm, direction="LONG")
        # pen = |99.5-98.0|/4 = 0.375 → zone içinde (0.15-0.70)
        bar = make_bar(index=15, open_=99.5, high=100.0, low=99.0, close=99.5)
        sm.check_ltf_fvg_validity("BTCUSDT", bar)

        st = sm.get("BTCUSDT")
        assert st.state == SetupState.WAIT_CONFIRM

    def test_not_wait_confirm_state_ignored(self):
        """WAIT_CONFIRM değilse check_ltf_fvg_validity early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_RETRACE
        state.fvg_upper = 102.0
        state.fvg_lower = 98.0
        state.direction = "LONG"
        bar = make_bar(index=15, open_=101.0, high=101.5, low=100.5, close=101.0)
        sm.check_ltf_fvg_validity("BTCUSDT", bar)
        assert state.state == SetupState.WAIT_RETRACE

    def test_no_fvg_levels_check_ltf_validity_ignored(self):
        """FVG seviyeleri yoksa check_ltf_fvg_validity early return."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_CONFIRM
        state.direction = "LONG"
        state.fvg_upper = None
        state.fvg_lower = None
        bar = make_bar(index=15)
        sm.check_ltf_fvg_validity("BTCUSDT", bar)
        assert state.state == SetupState.WAIT_CONFIRM

    def test_wait_new_fvg_accepts_new_fvg(self):
        """
        WAIT_NEW_FVG → yeni active FVG gelirse → WAIT_RETRACE.
        """
        sm = make_sm()
        from state_machine import SetupState

        # Önce WAIT_CONFIRM'den WAIT_NEW_FVG'ye düş
        self._setup_wait_confirm(sm, symbol="ETHUSDT")
        bar_breach = make_bar(index=15, open_=100.5, high=101.5, low=100.0, close=100.9)
        sm.check_ltf_fvg_validity("ETHUSDT", bar_breach)
        assert sm.get("ETHUSDT").state == SetupState.WAIT_NEW_FVG

        # Yeni active FVG gelir → WAIT_RETRACE
        fire(sm, "ETHUSDT", type="FVG_CREATED", upper=108.0, lower=104.0, time=16, is_active=True)
        assert sm.get("ETHUSDT").state == SetupState.WAIT_RETRACE
        assert sm.get("ETHUSDT").fvg_upper == 108.0
        assert sm.get("ETHUSDT").fvg_lower == 104.0
        assert sm.get("ETHUSDT").retrace_seen is False
        assert sm.get("ETHUSDT").is_ce_tap is False

    def test_wait_new_fvg_rejects_inactive_fvg(self):
        """
        WAIT_NEW_FVG'de is_active=False FVG reddedilir.
        """
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("ETHUSDT")
        state.state = SetupState.WAIT_NEW_FVG
        state.sweep_detected = True
        state.mss_confirmed = True

        fire(sm, "ETHUSDT", type="FVG_CREATED", upper=108.0, lower=104.0, time=16, is_active=False)
        assert sm.get("ETHUSDT").state == SetupState.WAIT_NEW_FVG


# ═══════════════════════════════════════════════════════════════
# PenetrationEngine Kenar Durumları
# ═══════════════════════════════════════════════════════════════


class TestPenetrationEngineEdgeCases:
    """PenetrationEngine: sıfır boyutlu FVG, sınırda pen değerleri."""

    def test_zero_size_fvg_returns_zero_penetration(self):
        """FVG boyutu 0 ise get_penetration 0 döner."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import PenetrationEngine

        engine = PenetrationEngine(fvg_upper=100.0, fvg_lower=100.0, direction="LONG")
        assert engine.get_penetration(100.0) == 0.0

    def test_long_exact_upper_boundary_pen_one(self):
        """LONG: fiyat tam fvg_upper'da → pen=1.0."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import PenetrationEngine

        engine = PenetrationEngine(fvg_upper=102.0, fvg_lower=98.0, direction="LONG")
        assert engine.get_penetration(102.0) == 1.0

    def test_long_exact_lower_boundary_pen_zero(self):
        """LONG: fiyat tam fvg_lower'da → pen=0.0."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import PenetrationEngine

        engine = PenetrationEngine(fvg_upper=102.0, fvg_lower=98.0, direction="LONG")
        assert engine.get_penetration(98.0) == 0.0

    def test_short_exact_upper_boundary_pen_zero(self):
        """SHORT: fiyat tam fvg_upper'da → pen=0.0."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import PenetrationEngine

        engine = PenetrationEngine(fvg_upper=102.0, fvg_lower=98.0, direction="SHORT")
        assert engine.get_penetration(102.0) == 0.0

    def test_short_exact_lower_boundary_pen_one(self):
        """SHORT: fiyat tam fvg_lower'da → pen=1.0."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import PenetrationEngine

        engine = PenetrationEngine(fvg_upper=102.0, fvg_lower=98.0, direction="SHORT")
        assert engine.get_penetration(98.0) == 1.0


# ═══════════════════════════════════════════════════════════════
# MISSED_FVG ve WAIT_POI_CONFIRM State Koruma
# ═══════════════════════════════════════════════════════════════


class TestMissedFvgStateProtection:
    """MISSED_FVG / WAIT_POI_CONFIRM state'lerinde FVG event'lerinin reddi."""

    def test_fvg_event_rejected_in_missed_fvg_state(self):
        """MISSED_FVG state'indeyken yeni FVG event'i reddedilir."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.MISSED_FVG
        state.fvg_upper = 102.0
        state.fvg_lower = 98.0

        fire(sm, "BTCUSDT", type="FVG_CREATED", upper=105.0, lower=101.0, time=20)
        # Eski FVG seviyeleri korunur, yeni FVG uygulanmaz
        st = sm.get("BTCUSDT")
        assert st.fvg_upper is None  # _handle_fvg None yapar
        assert st.fvg_lower is None

    def test_ltf_event_handled_in_wait_poi_confirm_without_fvg(self):
        """
        WAIT_POI_CONFIRM'de LTF_CONFIRM, FVG seviyeleri None olsa bile
        poi_anchor varsa kabul edilir → READY_TO_ENTER.
        """
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_POI_CONFIRM
        state.direction = "LONG"
        state.poi_anchor = 100.0
        state.sweep_detected = True
        state.mss_confirmed = True
        state.fvg_missed = True
        # fvg_upper/fvg_lower None (FVG event'i reddedildikten sonra olabilir)
        state.fvg_upper = None
        state.fvg_lower = None

        fire(sm, "BTCUSDT", type="LTF_CONFIRM", direction="LONG", close=100.5)
        assert sm.get("BTCUSDT").state == SetupState.READY_TO_ENTER
        assert sm.get("BTCUSDT").ltf_confirmed is True

    def test_fvg_event_rejected_in_wait_poi_confirm_state(self):
        """WAIT_POI_CONFIRM state'indeyken yeni FVG event'i reddedilir."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_POI_CONFIRM
        state.fvg_upper = 102.0
        state.fvg_lower = 98.0

        fire(sm, "BTCUSDT", type="FVG_CREATED", upper=105.0, lower=101.0, time=20)
        st = sm.get("BTCUSDT")
        assert st.fvg_upper is None
        assert st.fvg_lower is None


# ═══════════════════════════════════════════════════════════════
# Stale State: MISSED_FVG / WAIT_POI_CONFIRM expiry
# ═══════════════════════════════════════════════════════════════


class TestCaseCExpiry:
    """Case C state'lerinde expiry → IDLE."""

    def test_missed_fvg_expiry_resets_to_idle(self):
        """MISSED_FVG'de expires_at geçtiyse → IDLE."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.MISSED_FVG
        state.fvg_missed = True
        state.poi_anchor = 100.0
        state.expires_at = int(time.time()) - 1

        sm._evaluate(state, current_time=datetime.now())
        assert state.state == SetupState.IDLE
        assert state.fvg_missed is False  # reset_flags çağrılır

    def test_wait_poi_confirm_expiry_resets_to_idle(self):
        """WAIT_POI_CONFIRM'de expires_at geçtiyse → IDLE."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_POI_CONFIRM
        state.fvg_missed = True
        state.poi_anchor = 100.0
        state.expires_at = int(time.time()) - 1

        sm._evaluate(state, current_time=datetime.now())
        assert state.state == SetupState.IDLE
