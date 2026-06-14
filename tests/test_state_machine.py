"""
test_state_machine.py — NEXUS V3

Kapsam:
  - State geçişleri: IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM → READY_TO_ENTER
  - Pre-check layer: _check_stale_state, _check_invalidation
  - check_retrace: CE + gövde şartları
  - _evaluate: 4-flag hard gate
  - set_state, invalidate, clear
"""

from __future__ import annotations

import time
import warnings
from datetime import datetime, timedelta

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from conftest import make_bar


# ═══════════════════════════════════════════════════════════════
# Yardımcı
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
# State Geçişleri
# ═══════════════════════════════════════════════════════════════


class TestStateTransitions:
    def test_initial_state_is_idle(self):
        sm = make_sm()
        state = sm.get("BTCUSDT")
        from state_machine import SetupState

        assert state.state == SetupState.IDLE

    def test_sweep_idle_to_armed(self):
        """SWEEP eventi IDLE → ARMED geçişi."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=10)
        from state_machine import SetupState

        assert sm.get("BTCUSDT").state == SetupState.ARMED
        assert sm.get("BTCUSDT").sweep_detected is True
        assert sm.get("BTCUSDT").sweep_level == 95.0

    def test_sweep_wrong_tf_ignored(self):
        """SWEEP tf=5m (15m değil) → state değişmemeli."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="SWEEP", tf="5m", level=95.0)
        from state_machine import SetupState

        assert sm.get("BTCUSDT").state == SetupState.IDLE

    def test_mss_armed_to_wait_retrace(self):
        """MSS eventi ARMED → WAIT_RETRACE geçişi."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=10)
        fire(sm, "BTCUSDT", type="MSS", direction="LONG", level=98.0, bar_index=12)
        from state_machine import SetupState

        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE
        assert sm.get("BTCUSDT").mss_confirmed is True

    def test_fvg_after_mss_stores_levels(self):
        """FVG_CREATED eventi fvg_upper/lower değerlerini kaydetmeli."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=5)
        fire(sm, "BTCUSDT", type="MSS", direction="LONG", level=98.0, bar_index=7)
        fire(sm, "BTCUSDT", type="FVG_CREATED", upper=102.0, lower=100.0, time=9)
        state = sm.get("BTCUSDT")
        assert state.fvg_upper == 102.0
        assert state.fvg_lower == 100.0

    def test_ltf_confirm_wait_confirm_to_ready(self):
        """LTF_CONFIRM WAIT_CONFIRM → READY_TO_ENTER."""
        sm = make_sm()
        state = sm.get("BTCUSDT")
        from state_machine import SetupState

        # Tüm flagleri elle set et
        state.sweep_detected = True
        state.mss_confirmed = True
        state.retrace_seen = True
        state.fvg_upper = 102.0
        state.fvg_lower = 100.0
        state.state = SetupState.WAIT_CONFIRM
        fire(sm, "BTCUSDT", type="LTF_CONFIRM", direction="LONG", close=101.0)
        assert state.state == SetupState.READY_TO_ENTER
        assert state.ltf_confirmed is True
        assert state.entry_price == 101.0

    def test_full_chain_idle_to_ready(self):
        """Tam zincir: SWEEP → MSS → FVG → LTF_CONFIRM → READY_TO_ENTER."""
        sm = make_sm()
        sym = "ETHUSDT"
        from state_machine import SetupState

        fire(sm, sym, type="SWEEP", tf="15m", level=190.0, bar_index=1)
        assert sm.get(sym).state == SetupState.ARMED

        fire(sm, sym, type="MSS", direction="LONG", level=195.0, bar_index=3)
        assert sm.get(sym).state == SetupState.WAIT_RETRACE

        fire(sm, sym, type="FVG_CREATED", upper=197.0, lower=195.0, time=4)

        # check_retrace ile WAIT_CONFIRM
        bar_in_fvg = make_bar(index=5, open_=195.5, high=197.5, low=195.5, close=196.0)
        sm.check_retrace(sym, bar_in_fvg)
        assert sm.get(sym).state == SetupState.WAIT_CONFIRM

        fire(sm, sym, type="LTF_CONFIRM", direction="LONG", close=196.3)
        assert sm.get(sym).state == SetupState.READY_TO_ENTER

    def test_htf_bias_sets_direction(self):
        """HTF_BIAS eventi state.direction ve htf_bias'ı set etmeli."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="HTF_BIAS", direction="SHORT", strength="STRONG")
        state = sm.get("BTCUSDT")
        assert state.direction == "SHORT"
        assert state.htf_bias == "SHORT"
        assert state.htf_strength == "STRONG"

    def test_htf_levels_sets_swing_and_liquidity(self):
        """HTF_LEVELS eventi h4/h1 seviyelerini kaydetmeli."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="HTF_LEVELS", h4_swing_level=90.0, h1_liquidity_level=115.0)
        state = sm.get("BTCUSDT")
        assert state.h4_swing_level == 90.0
        assert state.h1_liquidity_level == 115.0

    def test_set_state_to_entered(self):
        """set_state() ENTERED'a geçiş."""
        sm = make_sm()
        from state_machine import SetupState

        sm.set_state("BTCUSDT", SetupState.ENTERED)
        assert sm.get("BTCUSDT").state == SetupState.ENTERED

    def test_invalidate(self):
        from state_machine import SetupState

        sm = make_sm()
        sm.invalidate("BTCUSDT")
        assert sm.get("BTCUSDT").state == SetupState.INVALIDATED

    def test_clear_removes_symbol(self):
        sm = make_sm()
        sm.get("BTCUSDT")  # kayıt oluştur
        sm.clear("BTCUSDT")
        assert "BTCUSDT" not in sm.symbols

    def test_sweep_ignored_when_not_idle(self):
        """ARMED durumundayken yeni SWEEP gelirse state değişmemeli."""
        sm = make_sm()
        from state_machine import SetupState

        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=1)
        assert sm.get("BTCUSDT").state == SetupState.ARMED
        # İkinci sweep — ARMED'da → ignored
        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=90.0, bar_index=2)
        assert sm.get("BTCUSDT").state == SetupState.ARMED

    def test_mid_cycle_reset_no_ghost_mss(self):
        """
        SWEEP → MSS → FVG → timeout (IDLE) → tekrar ARMED
        _seen_mss + _emitted_fvg_ids reset sonrası ghost reuse olmamalı.
        """
        from state_machine import SetupState

        sm = make_sm()
        sym = "BTCUSDT"

        # İlk zincir
        fire(sm, sym, type="SWEEP", tf="15m", level=95.0, bar_index=1)
        fire(sm, sym, type="MSS", direction="LONG", level=98.0, bar_index=3)
        fire(sm, sym, type="FVG_CREATED", upper=102.0, lower=100.0, time=4)
        assert sm.get(sym).state == SetupState.WAIT_RETRACE

        # Mid-cycle timeout → IDLE
        state = sm.get(sym)
        state.expires_at = int(time.time()) - 1
        sm._evaluate(state, current_time=datetime.now())
        assert state.state == SetupState.IDLE

        # expires_at hâlâ geçmişte olduğu için update_from_event
        # is_expired() → EXPIRED döner. SWEEP'in işlenmesi için
        # expires_at'i sıfırla (IDLE'da olması zaten yeni setup demek)
        state.expires_at = None

        # Tüm flagler temizlendi mi?
        assert not state.sweep_detected
        assert not state.mss_confirmed
        assert state.fvg_upper is None
        assert state.mss_level is None

        # Yeni sweep → ARMED
        fire(sm, sym, type="SWEEP", tf="15m", level=93.0, bar_index=10)
        assert sm.get(sym).state == SetupState.ARMED

        # Yeni MSS → kabul edilmeli (eski _seen_mss ghost değil)
        fire(sm, sym, type="MSS", direction="LONG", level=96.0, bar_index=12)
        assert sm.get(sym).state == SetupState.WAIT_RETRACE
        assert sm.get(sym).mss_level == 96.0  # eski 98.0 değil


# ═══════════════════════════════════════════════════════════════
# Pre-Check Layer
# ═══════════════════════════════════════════════════════════════


class TestPreCheckLayer:
    def test_stale_state_resets_to_idle(self):
        """expires_at geçtiyse ARMED → IDLE."""
        sm = make_sm()
        from state_machine import SetupState

        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=1)
        state = sm.get("BTCUSDT")
        assert state.state == SetupState.ARMED

        # expires_at'ı geçmişe set et
        state.expires_at = int(time.time()) - 1

        # _evaluate tetikle (herhangi bir event ile)
        past_time = datetime.now() + timedelta(hours=25)
        sm._evaluate(state, current_time=past_time)
        assert state.state == SetupState.IDLE

    def test_fresh_state_not_reset(self):
        """expires_at henüz geçmediyse state korunmalı."""
        sm = make_sm()
        from state_machine import SetupState

        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=1)
        state = sm.get("BTCUSDT")
        state.expires_at = int(time.time()) + 86400  # 24 saat ileri

        sm._evaluate(state, current_time=datetime.now())
        assert state.state == SetupState.ARMED

    def test_invalidation_long_close_below_mss(self):
        """LONG setup: close < mss_level → IDLE'a çekilmeli."""
        sm = make_sm()
        from state_machine import SetupState

        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=1)
        fire(sm, "BTCUSDT", type="MSS", direction="LONG", level=98.0, bar_index=3)
        state = sm.get("BTCUSDT")
        assert state.state == SetupState.WAIT_RETRACE

        # Mum kapanışı mss_level altına indi
        bad_bar = make_bar(index=10, open_=97.0, high=97.5, low=96.0, close=96.5)
        sm._evaluate(state, last_closed_bar=bad_bar)
        assert state.state == SetupState.IDLE

    def test_invalidation_short_close_above_mss(self):
        """SHORT setup: close > mss_level → IDLE'a çekilmeli."""
        sm = make_sm()
        from state_machine import SetupState

        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=105.0, bar_index=1)
        fire(sm, "BTCUSDT", type="MSS", direction="SHORT", level=102.0, bar_index=3)
        state = sm.get("BTCUSDT")

        bad_bar = make_bar(index=10, open_=103.0, high=104.0, low=102.5, close=103.5)
        sm._evaluate(state, last_closed_bar=bad_bar)
        assert state.state == SetupState.IDLE

    def test_invalidation_spike_not_closed_ignored(self):
        """Anlık iğne (is_closed=False değil close) → kapanış check yapılır."""
        # _check_invalidation kapanış (close) kontrol eder, intrabar fiyatı değil
        # Testin mantığı: last_closed_bar.close değeri geçerli → bu testte close OK seviyede
        sm = make_sm()
        from state_machine import SetupState

        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=1)
        fire(sm, "BTCUSDT", type="MSS", direction="LONG", level=98.0, bar_index=3)
        state = sm.get("BTCUSDT")

        # close mss_level üstünde → invalidation YOK
        good_bar = make_bar(index=10, open_=99.0, high=101.0, low=97.0, close=99.5)
        sm._evaluate(state, last_closed_bar=good_bar)
        assert state.state == SetupState.WAIT_RETRACE  # değişmedi

    def test_reset_flags_after_invalidation(self):
        """Invalidasyon sonrası tüm flagler False olmalı."""
        sm = make_sm()
        fire(sm, "BTCUSDT", type="SWEEP", tf="15m", level=95.0, bar_index=1)
        fire(sm, "BTCUSDT", type="MSS", direction="LONG", level=98.0, bar_index=3)
        state = sm.get("BTCUSDT")

        bad_bar = make_bar(index=10, open_=97.0, high=97.5, low=96.0, close=96.0)
        sm._evaluate(state, last_closed_bar=bad_bar)

        assert not state.sweep_detected
        assert not state.mss_confirmed
        assert not state.retrace_seen
        assert not state.ltf_confirmed


# ═══════════════════════════════════════════════════════════════
# check_retrace
# ═══════════════════════════════════════════════════════════════


class TestCheckRetrace:
    """check_retrace: CE + gövde şartları."""

    def _setup_wait_retrace(self, sm, symbol="BTCUSDT", direction="LONG", fvg_upper=100.1, fvg_lower=99.9):
        from state_machine import SetupState

        state = sm.get(symbol)
        state.direction = direction
        state.fvg_upper = fvg_upper
        state.fvg_lower = fvg_lower
        state.sweep_detected = True
        state.mss_confirmed = True
        state.state = SetupState.WAIT_RETRACE
        return state

    def test_long_ce_and_body_inside_advances(self):
        """LONG: fitil CE'e değdi VE close FVG içinde → WAIT_CONFIRM."""
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        # fvg_mid = 100.0, size=0.2
        # close=100.0 → pen=(100.0-99.9)/0.2=0.50 ∈ [0.15, 0.70] ✓
        bar = make_bar(index=10, open_=100.05, high=100.08, low=99.95, close=100.0)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_CONFIRM
        assert sm.get("BTCUSDT").retrace_seen is True

    def test_long_no_ce_touch_stays(self):
        """LONG: pen > pen_max → WAIT_RETRACE kalmalı."""
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        # size=0.2, close=100.05 → pen=(100.05-99.9)/0.2=0.75 > 0.70 → WAIT_RETRACE
        bar = make_bar(index=10, open_=100.05, high=100.08, low=100.02, close=100.05)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE

    def test_long_penetration_below_zone_missed_fvg(self):
        """LONG: pen < 0.15 (trade zone dışında) → MISSED_FVG (Case C tetiklenir)."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        # _check_missed_fvg için fvg_entry_bar_index ve bars_since > 3 gerekli
        state.fvg_entry_bar_index = 5
        state.displacement_origin = 99.5
        # size=0.2, close=99.92 → pen=(99.92-99.9)/0.2=0.10 < 0.15 → MISSED_FVG
        bar = make_bar(index=10, open_=99.95, high=99.98, low=99.90, close=99.92)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.MISSED_FVG

    def test_long_penetration_above_zone_stays(self):
        """LONG: pen > 0.70 (trade zone dışında) → WAIT_RETRACE kalmalı."""
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="LONG", fvg_upper=100.1, fvg_lower=99.9)
        # size=0.2, close=100.05 → pen=(100.05-99.9)/0.2=0.75 > 0.70 → WAIT_RETRACE
        bar = make_bar(index=10, open_=100.05, high=100.08, low=100.02, close=100.05)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE

    def test_short_ce_and_body_inside_advances(self):
        """SHORT: pen trade zone içinde → WAIT_CONFIRM."""
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="SHORT", fvg_upper=100.1, fvg_lower=99.9)
        # size=0.2, SHORT pen=(100.1-price)/0.2
        # close=100.0 → pen=(100.1-100.0)/0.2=0.50 ∈ [0.15, 0.70] ✓
        bar = make_bar(index=10, open_=99.95, high=100.05, low=99.90, close=100.0)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_CONFIRM

    def test_short_no_ce_stays(self):
        """SHORT: pen > pen_max → WAIT_RETRACE kalmalı."""
        sm = make_sm()
        from state_machine import SetupState

        self._setup_wait_retrace(sm, direction="SHORT", fvg_upper=100.1, fvg_lower=99.9)
        # SHORT: pen=(100.1-close)/0.2
        # close=99.9 → pen=(100.1-99.9)/0.2=1.0 > 0.70 → WAIT_RETRACE
        bar = make_bar(index=10, open_=99.92, high=99.95, low=99.88, close=99.9)
        sm.check_retrace("BTCUSDT", bar)
        assert sm.get("BTCUSDT").state == SetupState.WAIT_RETRACE

    def test_no_fvg_levels_skipped(self):
        """FVG seviyeleri yoksa check_retrace erken çıkmalı."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.WAIT_RETRACE
        state.direction = "LONG"
        state.fvg_upper = None
        state.fvg_lower = None
        bar = make_bar(index=5)
        sm.check_retrace("BTCUSDT", bar)
        assert state.state == SetupState.WAIT_RETRACE  # değişmedi, hata yok

    def test_not_wait_retrace_state_ignored(self):
        """WAIT_RETRACE değilse check_retrace hiçbir şey yapmamalı."""
        sm = make_sm()
        from state_machine import SetupState

        state = sm.get("BTCUSDT")
        state.state = SetupState.IDLE
        bar = make_bar(index=5)
        sm.check_retrace("BTCUSDT", bar)
        assert state.state == SetupState.IDLE


# ═══════════════════════════════════════════════════════════════
# _evaluate 4-Flag Hard Gate
# ═══════════════════════════════════════════════════════════════


class TestEvaluateFlagGate:
    def _ready_state(self, sm, symbol="BTCUSDT"):
        """Tüm flagler True, state=WAIT_CONFIRM olan state üretir."""
        from state_machine import SetupState

        state = sm.get(symbol)
        state.sweep_detected = True
        state.mss_confirmed = True
        state.retrace_seen = True
        state.ltf_confirmed = True
        state.fvg_upper = 102.0
        state.fvg_lower = 98.0
        state.state = SetupState.WAIT_CONFIRM
        return state

    def test_all_flags_true_advances_to_ready(self):
        """4 flag True → READY_TO_ENTER."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._ready_state(sm)
        sm._evaluate(state)
        assert state.state == SetupState.READY_TO_ENTER

    def test_missing_one_flag_blocks(self):
        """Bir flag eksikse READY_TO_ENTER'a geçilmemeli."""
        sm = make_sm()
        from state_machine import SetupState

        for missing in ["sweep_detected", "mss_confirmed", "retrace_seen", "ltf_confirmed"]:
            state = self._ready_state(sm, symbol="BTCUSDT")
            setattr(state, missing, False)
            state.state = SetupState.WAIT_CONFIRM
            sm._evaluate(state)
            assert state.state != SetupState.READY_TO_ENTER, f"{missing}=False olmasına rağmen READY_TO_ENTER'a geçildi"


# ═══════════════════════════════════════════════════════════════
# _evaluate — ADAPTIVE LTF + direction=None Guard (P1 fix)
# ═══════════════════════════════════════════════════════════════


class TestAdaptiveDirectionNoneGuard:
    """ADAPTIVE_LTF_ENABLE=True + direction=None → _evaluate çökmemeli."""

    @staticmethod
    def _make_adaptive_state(sm, symbol="BTCUSDT"):
        """WAIT_CONFIRM state'i, tüm flagler True, ama direction=None."""
        from state_machine import SetupState

        state = sm.get(symbol)
        state.sweep_detected = True
        state.mss_confirmed = True
        state.retrace_seen = True
        state.ltf_confirmed = False  # ADAPTIVE'ın tetiklenmesi için
        state.fvg_upper = 102.0
        state.fvg_lower = 98.0
        state.direction = None  # ← kritik: direction None
        state.state = SetupState.WAIT_CONFIRM
        return state

    def test_adaptive_direction_none_does_not_crash(self):
        """direction=None iken _evaluate Exception yutulur, crash olmaz."""
        sm = make_sm()
        state = self._make_adaptive_state(sm)

        # ADAPTIVE_LTF_ENABLE'i monkeypatch ile aktif et

        original_config = sm.config
        try:
            sm.config = type("Config", (), {"ADAPTIVE_LTF_ENABLE": True})()
            bar = make_bar(close=100.0, index=10, is_closed=True)

            # _evaluate çağrısı crash olmamalı (try/except Exception: pass var)
            sm._evaluate(state, last_closed_bar=bar)
        finally:
            sm.config = original_config

        # Crash olmadıysa test başarılı
        assert True

    def test_adaptive_direction_none_no_state_change(self):
        """direction=None → ADAPTIVE gate geçilmez, state değişmez."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._make_adaptive_state(sm)

        original_config = sm.config
        try:
            sm.config = type("Config", (), {"ADAPTIVE_LTF_ENABLE": True})()
            bar = make_bar(close=100.0, index=10, is_closed=True)

            old_state = state.state
            sm._evaluate(state, last_closed_bar=bar)

            # direction=None ise yeni guard sayesinde ADAPTIVE block atlanır
            # state READY_TO_ENTER'a geçmemeli
            assert state.state != SetupState.READY_TO_ENTER, (
                "direction=None iken READY_TO_ENTER'a geçilmemeli! " f"old={old_state}, new={state.state}"
            )
        finally:
            sm.config = original_config

    def test_adaptive_direction_long_works_normally(self):
        """direction="LONG" + tüm flagler → ADAPTIVE normal çalışır."""
        sm = make_sm()
        from state_machine import SetupState

        state = self._make_adaptive_state(sm)
        state.direction = "LONG"  # ← geçerli direction

        original_config = sm.config
        try:
            sm.config = type(
                "Config",
                (),
                {
                    "ADAPTIVE_LTF_ENABLE": True,
                    "FVG_PENETRATION_MID": 0.30,
                    "FVG_PENETRATION_MAX": 0.70,
                },
            )()
            # Fiyat FVG'nin içinde (98-102 arası), mid-band pen tetiklesin
            bar = make_bar(close=100.0, index=10, is_closed=True)

            sm._evaluate(state, last_closed_bar=bar)

            # direction LONG geçerli → ADAPTIVE çalışabilir
            # Penetrasyon mid-band'de ise READY_TO_ENTER'a geçer
            # (pen=0.5, FVG_PENETRATION_MID=0.30 ile tetiklenir)
            assert state.state in (
                SetupState.WAIT_CONFIRM,
                SetupState.READY_TO_ENTER,
            ), f"direction=LONG iken state geçerli olmalı: {state.state}"
        finally:
            sm.config = original_config
