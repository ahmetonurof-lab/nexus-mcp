"""
Minimal state flow tests — Case C (MISSED_FVG) and Overshoot.
"""

from models import Bar
from state_machine import SetupState, StateMachine


def make_bar(index, close, high=None, low=None, timestamp=None):
    return Bar(
        index=index,
        open=close,
        high=high or close,
        low=low or close,
        close=close,
        volume=1.0,
        timestamp=timestamp or (index * 60000),
    )


class TestCaseCFlow:
    """MISSED_FVG -> WAIT_POI_CONFIRM -> (LTF_CONFIRM) -> READY_TO_ENTER"""

    def test_missed_fvg_flow(self):
        sm = StateMachine()
        sym = "TESTUSDT"

        st = sm.get(sym)
        st.direction = "LONG"
        st.sweep_detected = True
        st.sweep_level = 100.0
        st.sweep_bar_index = 5
        st.mss_confirmed = True
        st.mss_level = 101.0
        st.fvg_upper = 106.0
        st.fvg_lower = 103.0
        st.displacement_origin = 99.0
        st.state = SetupState.WAIT_RETRACE

        # Fiyat FVG'ye girmeden yukari kacti -> MISSED_FVG
        # LONG: fvg_lower=103, pen = |103.2-103|/3 = 0.067 < 0.15 -> missed
        bar_close_above = make_bar(20, 103.2)
        sm.check_retrace(sym, bar_close_above)
        assert st.state == SetupState.MISSED_FVG
        assert st.fvg_missed is True
        assert st.poi_anchor is not None

        # Fiyat poi_anchor'a geri geldi -> WAIT_POI_CONFIRM
        bar_at_poi = make_bar(21, st.poi_anchor)
        sm.check_poi_retrace(sym, bar_at_poi)
        assert st.state == SetupState.WAIT_POI_CONFIRM

        # LTF confirm -> READY_TO_ENTER
        sm._handle_ltf(st, {"type": "LTF_CONFIRM", "direction": "LONG", "close": 99.5})
        assert st.state == SetupState.READY_TO_ENTER


class TestOvershootFlow:
    """WAIT_CONFIRM'de pen > max -> WAIT_NEW_FVG -> yeni FVG -> WAIT_RETRACE"""

    def test_overshoot_to_new_fvg(self):
        sm = StateMachine()
        sym = "TESTUSDT"

        st = sm.get(sym)
        st.direction = "SHORT"
        st.sweep_detected = True
        st.mss_confirmed = True
        st.fvg_upper = 106.0
        st.fvg_lower = 103.0
        st.state = SetupState.WAIT_CONFIRM

        # Fiyat FVG'yi deldi (pen > 0.70) -> WAIT_NEW_FVG
        bar_deep = make_bar(20, 101.0)  # pen = |101-106|/3 = 1.67 > 0.70
        sm.check_ltf_fvg_validity(sym, bar_deep)
        assert st.state == SetupState.WAIT_NEW_FVG
        assert st.fvg_upper is None

        # Yeni FVG geliyor
        sm._handle_fvg(
            st,
            {
                "type": "FVG_CREATED",
                "upper": 104.0,
                "lower": 101.5,
                "is_active": True,
            },
        )
        assert st.state == SetupState.WAIT_RETRACE
        assert st.fvg_upper == 104.0


class TestSweepTf:
    """sweep_tf alani telemetri icin dogru set ediliyor"""

    def test_sweep_tf_set(self):
        sm = StateMachine()
        sym = "TESTUSDT"
        st = sm.get(sym)

        sm._handle_sweep(st, {"type": "SWEEP", "tf": "2H", "level": 100.0, "bar_index": 10})
        assert st.sweep_tf == "2H"
        assert st.sweep_detected is True

    def test_sweep_tf_cleared_on_reset(self):
        sm = StateMachine()
        sym = "TESTUSDT"
        st = sm.get(sym)
        st.sweep_tf = "1H"
        st.reset_flags()
        assert st.sweep_tf is None
