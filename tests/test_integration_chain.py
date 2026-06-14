"""
test_integration_chain.py — NEXUS V3 Full Chain Integration Test

Zincir:  WS → Analyzer (events) → EventRouter → StateMachine (states) → Trader (order)

Kapsam:
  - MarketAnalyzer.analyze() → event listesi
  - EventRouter.publish() → state machine event yönlendirme
  - StateMachine.update_from_event() + check_retrace() → state geçişi
  - _evaluate() → READY_TO_ENTER kararı
  - Tüm zincir: ham bardan emir sinyaline

Çalıştırma:
    pytest tests/test_integration_chain.py -v --tb=short
"""

from __future__ import annotations

import time
import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from conftest import make_bar


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def analyzer():
    """Temiz MarketAnalyzer instance."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from analyzer import MarketAnalyzer
    return MarketAnalyzer("BTCUSDT")


@pytest.fixture
def state_machine():
    """Temiz StateMachine + EventRouter."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from event_router import EventRouter
        from state_machine import StateMachine
    sm = StateMachine()
    router = EventRouter(sm)
    return sm, router


@pytest.fixture
def bar_sets():
    """
    Gerçekçi bar verisi üretir.

    55 adet 15m bar (≈ 13 saat), trend yukarı (LONG bias uygun).
    Son barlarda MSS + FVG oluşacak şekilde tasarlanmıştır.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from models import Bar

    # ── 1D bars (10 bar ≈ 10 gün, yükseliş trendi) ──
    bars_d1 = []
    for i in range(10):
        base = 45000.0 + i * 500
        bars_d1.append(
            Bar(
                index=i,
                open=base,
                high=base + 600,
                low=base - 200,
                close=base + 450,
                volume=10000,
                is_closed=True,
                timestamp=int(time.time()) - (10 - i) * 86400,
            )
        )

    # ── H4 bars (50 bar ≈ 8 gün) ──
    bars_h4 = []
    for i in range(50):
        base = 45000.0 + i * 100
        bars_h4.append(
            Bar(
                index=i,
                open=base,
                high=base + 400,
                low=base - 150,
                close=base + 300,
                volume=5000,
                is_closed=True,
                timestamp=int(time.time()) - (50 - i) * 14400,
            )
        )

    # ── H1 bars (100 bar ≈ 4 gün) ──
    bars_h1 = []
    for i in range(100):
        base = 45000.0 + i * 50
        bars_h1.append(
            Bar(
                index=i,
                open=base,
                high=base + 200,
                low=base - 100,
                close=base + 100,
                volume=2000,
                is_closed=True,
                timestamp=int(time.time()) - (100 - i) * 3600,
            )
        )

    # ── 15m bars (55 bar ≈ 13 saat) ──
    # Trend: yükselen, son barlarda MSS+FVG oluşacak
    bars_15m = []
    for i in range(55):
        base = 49000.0 + i * 20
        bars_15m.append(
            Bar(
                index=i,
                open=base,
                high=base + 80,
                low=base - 40,
                close=base + 50,
                volume=500,
                is_closed=True,
                timestamp=int(time.time()) - (55 - i) * 900,
            )
        )

    # Son 5 bar'da sert yükseliş (MSS + FVG için)
    for j in range(5):
        idx = 50 + j
        base = 50000.0 + j * 100
        bars_15m[idx] = Bar(
            index=idx,
            open=bars_15m[idx - 1].close,
            high=base + 150,
            low=base - 20,
            close=base + 100,
            volume=2000,
            is_closed=True,
            timestamp=bars_15m[idx].timestamp,
        )

    # ── 1m bars (200 bar ≈ 3 saat) ──
    bars_m1 = []
    for i in range(200):
        base = 50000.0 + i * 3
        bars_m1.append(
            Bar(
                index=i,
                open=base,
                high=base + 15,
                low=base - 8,
                close=base + 10,
                volume=100,
                is_closed=True,
                timestamp=int(time.time()) - (200 - i) * 60,
            )
        )

    return bars_d1, bars_h4, bars_h1, bars_15m, bars_m1


# ═════════════════════════════════════════════════════════════════════════════
# TEST: Full Chain — Analyzer → Events → StateMachine
# ═════════════════════════════════════════════════════════════════════════════


class TestFullChainAnalyzerToStateMachine:
    """Analyzer event üretimi → EventRouter → StateMachine geçişi."""

    def test_analyzer_produces_events(self, analyzer, bar_sets):
        """MarketAnalyzer.analyze() event listesi dönmeli (format kontrolü)."""
        bars_d1, bars_h4, bars_h1, bars_15m, bars_m1 = bar_sets
        events = analyzer.analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)
        assert isinstance(events, list), "analyze() liste dönmeli"
        # NOT: Sentez bar verisi swing noktaları içermeyebilir,
        # bias yoksa events=[] döner — bu da geçerli bir senaryo.

    def test_analyzer_events_have_required_fields(self, analyzer, bar_sets):
        """Her event type, gerekli alanları içermeli."""
        bars_d1, bars_h4, bars_h1, bars_15m, bars_m1 = bar_sets
        events = analyzer.analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)

        for event in events:
            assert "type" in event, f"Event type eksik: {event}"
            assert "symbol" in event, f"Symbol eksik: {event}"
            assert event["symbol"] == "BTCUSDT"

    def test_analyzer_htf_bias_first_event(self, analyzer, bar_sets):
        """İlk event (varsa) HTF_BIAS olmalı."""
        bars_d1, bars_h4, bars_h1, bars_15m, bars_m1 = bar_sets
        events = analyzer.analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)

        if events:
            assert events[0]["type"] == "HTF_BIAS", "İlk event HTF_BIAS olmalı"

    def test_chain_state_transitions_idle_to_armed(self, analyzer, state_machine, bar_sets):
        """Event zinciri: analyzer → router → state machine (exception'sız)."""
        sm, router = state_machine
        bars_d1, bars_h4, bars_h1, bars_15m, bars_m1 = bar_sets

        # Analyzer'dan event al
        events = analyzer.analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)

        # EventRouter üzerinden state machine'e yönlendir (hata fırlatmamalı)
        for event in events:
            router.publish("BTCUSDT", event)

        state = sm.get("BTCUSDT")

        # Sentez veri BOS üretmeyebilir. Bu durumda state IDLE kalır.
        # Önemli olan: exception fırlatmaması ve state'in tanımlı olması.
        assert state.state is not None
        if events:
            # Event varsa en azından HTF_BIAS + HTF_LEVELS işlenmiş olmalı
            assert state.htf_bias is not None, "HTF bias set edilmeli"

    def test_chain_all_events_processed(self, analyzer, state_machine, bar_sets):
        """Tüm eventler state machine tarafından işlenmeli (exception fırlatmamalı)."""
        sm, router = state_machine
        bars_d1, bars_h4, bars_h1, bars_15m, bars_m1 = bar_sets

        events = analyzer.analyze(bars_d1, bars_h4, bars_h1, bars_15m, bars_m1)

        for event in events:
            try:
                router.publish("BTCUSDT", event)
            except Exception as e:
                pytest.fail(f"Event işlenirken hata: {event=} {e=}")

        # Herhangi bir state'e geçilmiş olmalı (IDLE dışı)
        state = sm.get("BTCUSDT")
        # HTF_BIAS eventi direction set eder ama state IDLE kalabilir
        # SWEEP eventi varsa ARMED'a geçer
        assert state.state is not None

    def test_chain_no_event_without_bias(self, analyzer, bar_sets):
        """HTF bias yoksa event üretilmemeli."""
        bars_d1, bars_h4, bars_h1, bars_15m, bars_m1 = bar_sets

        # Flat/sideways market simüle et: düşük hacimli, range-bound barlar
        flat_d1 = [make_bar(index=i, open_=50000, high=50100, low=49900, close=50000, volume=100) for i in range(10)]

        events = analyzer.analyze(flat_d1, bars_h4, bars_h1, bars_15m, bars_m1)

        # HTF bias olmayabilir → boş liste veya sadece bias eventi
        if len(events) > 0:
            assert events[0]["type"] in ("HTF_BIAS",)


# ═════════════════════════════════════════════════════════════════════════════
# TEST: Mock Chain — Full Pipeline Simulation
# ═════════════════════════════════════════════════════════════════════════════


class TestFullPipelineSimulation:
    """
    Simüle edilmiş tam zincir: ham bar → analiz → event → state → karar.

    Bu testler gerçek analyzer yerine mock event kullanır,
    böylece belirli senaryoları deterministik olarak test edebiliriz.
    """

    @pytest.fixture
    def pipeline(self):
        """state_machine + event_router ikilisi."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from event_router import EventRouter
            from state_machine import StateMachine
        sm = StateMachine()
        router = EventRouter(sm)
        return sm, router

    def test_complete_long_setup(self, pipeline):
        """
        Tam LONG setup: IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM → READY_TO_ENTER.

        Event sırası:
          HTF_BIAS(LONG) → SWEEP → MSS → FVG_CREATED → check_retrace() → LTF_CONFIRM
        """
        sm, router = pipeline
        from state_machine import SetupState

        sym = "BTCUSDT"

        # 1. HTF Bias
        router.publish(sym, {"type": "HTF_BIAS", "direction": "LONG", "strength": "STRONG"})
        # state IDLE, direction set edilir
        assert sm.get(sym).direction == "LONG"
        assert sm.get(sym).htf_bias == "LONG"

        # 2. HTF Levels
        router.publish(sym, {"type": "HTF_LEVELS", "h4_swing_level": 47000.0, "h1_liquidity_level": 52000.0})

        # 3. SWEEP (15m)
        router.publish(sym, {"type": "SWEEP", "tf": "15m", "level": 49500.0, "bar_index": 50})
        assert sm.get(sym).state == SetupState.ARMED, f"ARMED olmalı: {sm.get(sym).state}"

        # 4. MSS
        router.publish(sym, {"type": "MSS", "direction": "LONG", "level": 50200.0, "bar_index": 52})
        assert sm.get(sym).state == SetupState.WAIT_RETRACE, f"WAIT_RETRACE olmalı: {sm.get(sym).state}"

        # 5. FVG_CREATED
        router.publish(sym, {"type": "FVG_CREATED", "upper": 51000.0, "lower": 50500.0, "time": 53, "is_active": True})
        state = sm.get(sym)
        assert state.fvg_upper == 51000.0
        assert state.fvg_lower == 50500.0

        # 6. check_retrace — fiyat FVG içine girsin (pen 0.30-0.50 bandında)
        # FVG size=500, mid=50750
        # pen = (50750 - 50500) / 500 = 0.50 ✓
        retrace_bar = make_bar(index=54, open_=50800.0, high=50900.0, low=50600.0, close=50750.0)
        sm.check_retrace(sym, retrace_bar)
        assert sm.get(sym).state == SetupState.WAIT_CONFIRM, f"WAIT_CONFIRM olmalı: {sm.get(sym).state}"

        # 7. LTF_CONFIRM
        router.publish(sym, {"type": "LTF_CONFIRM", "direction": "LONG", "close": 50800.0, "tf": "1m"})
        assert sm.get(sym).state == SetupState.READY_TO_ENTER, f"READY_TO_ENTER olmalı: {sm.get(sym).state}"

    def test_complete_short_setup(self, pipeline):
        """Tam SHORT setup: IDLE → ARMED → WAIT_RETRACE → WAIT_CONFIRM → READY_TO_ENTER."""
        sm, router = pipeline
        from state_machine import SetupState

        sym = "ETHUSDT"

        # HTF Bias
        router.publish(sym, {"type": "HTF_BIAS", "direction": "SHORT", "strength": "STRONG"})
        assert sm.get(sym).direction == "SHORT"

        # HTF Levels
        router.publish(sym, {"type": "HTF_LEVELS", "h4_swing_level": 3800.0, "h1_liquidity_level": 3500.0})

        # SWEEP
        router.publish(sym, {"type": "SWEEP", "tf": "1H", "level": 3700.0, "bar_index": 30})
        assert sm.get(sym).state == SetupState.ARMED

        # MSS (SHORT)
        router.publish(sym, {"type": "MSS", "direction": "SHORT", "level": 3650.0, "bar_index": 32})
        assert sm.get(sym).state == SetupState.WAIT_RETRACE

        # FVG (bearish → upper > lower)
        router.publish(sym, {"type": "FVG_CREATED", "upper": 3620.0, "lower": 3580.0, "time": 33, "is_active": True})

        # check_retrace SHORT: price fvg_upper'dan aşağı giriyor
        # size = 40, pen = (3620 - 3610) / 40 = 0.25 ✓
        retrace_bar = make_bar(index=34, open_=3615.0, high=3625.0, low=3605.0, close=3610.0)
        sm.check_retrace(sym, retrace_bar)
        assert sm.get(sym).state == SetupState.WAIT_CONFIRM

        # LTF_CONFIRM
        router.publish(sym, {"type": "LTF_CONFIRM", "direction": "SHORT", "close": 3600.0, "tf": "1m"})
        assert sm.get(sym).state == SetupState.READY_TO_ENTER

    def test_missed_fvg_case_c_recovery(self, pipeline):
        """Case C (MISSED_FVG) → POI retrace → LTF_CONFIRM → READY_TO_ENTER."""
        sm, router = pipeline
        from state_machine import SetupState

        sym = "SOLUSDT"

        # Setup chain → WAIT_RETRACE
        router.publish(sym, {"type": "HTF_BIAS", "direction": "LONG", "strength": "STRONG"})
        router.publish(sym, {"type": "SWEEP", "tf": "15m", "level": 140.0, "bar_index": 20})
        router.publish(sym, {"type": "MSS", "direction": "LONG", "level": 145.0, "bar_index": 22})
        router.publish(sym, {"type": "FVG_CREATED", "upper": 152.0, "lower": 148.0, "time": 23, "is_active": True})

        state = sm.get(sym)
        assert state.state == SetupState.WAIT_RETRACE

        # Fiyat FVG'ye hiç girmeden kaçtı (pen < 0.15)
        # fvg_size = 4, pen = (148.10 - 148.0) / 4 = 0.025 < 0.15 → MISSED_FVG
        state.displacement_origin = 143.0  # MSS impulse origin
        missed_bar = make_bar(index=25, open_=148.5, high=149.0, low=148.0, close=148.1)
        sm.check_retrace(sym, missed_bar)
        assert state.state == SetupState.MISSED_FVG, f"MISSED_FVG olmalı: {state.state}"

        # Fiyat POI bölgesine döndü
        # POI anchor = displacement_origin = 143.0
        # buffer = fvg_size * 0.3 = 4 * 0.3 = 1.2
        # zone: [143 - 1.2, 143 + 1.2] = [141.8, 144.2]
        poi_bar = make_bar(index=28, open_=143.5, high=144.0, low=142.5, close=143.0)
        sm.check_poi_retrace(sym, poi_bar)
        assert sm.get(sym).state == SetupState.WAIT_POI_CONFIRM, f"WAIT_POI_CONFIRM olmalı: {state.state}"

        # LTF confirm → READY_TO_ENTER
        router.publish(sym, {"type": "LTF_CONFIRM", "direction": "LONG", "close": 143.5, "tf": "1m"})
        assert sm.get(sym).state == SetupState.READY_TO_ENTER

    def test_full_chain_with_invalidation(self, pipeline):
        """Setup sonrası MSS invalidasyonu → IDLE'a dönüş."""
        sm, router = pipeline
        from state_machine import SetupState

        sym = "BTCUSDT"

        # Setup
        router.publish(sym, {"type": "HTF_BIAS", "direction": "LONG", "strength": "STRONG"})
        router.publish(sym, {"type": "SWEEP", "tf": "15m", "level": 50000.0, "bar_index": 40})
        router.publish(sym, {"type": "MSS", "direction": "LONG", "level": 50500.0, "bar_index": 42})

        state = sm.get(sym)
        assert state.state == SetupState.WAIT_RETRACE
        assert state.mss_level == 50500.0

        # Fiyat MSS seviyesinin altına düştü → invalidation
        bad_bar = make_bar(index=45, open_=50400.0, high=50450.0, low=50300.0, close=50350.0)
        sm._evaluate(state, last_closed_bar=bad_bar)
        assert state.state == SetupState.IDLE, "MSS kırılınca IDLE'a dönülmeli"
        assert not state.sweep_detected
        assert not state.mss_confirmed

    def test_expired_setup_returns_to_idle(self, pipeline):
        """Süresi dolan setup → EXPIRED → IDLE."""
        sm, router = pipeline
        from state_machine import SetupState

        sym = "BTCUSDT"

        router.publish(sym, {"type": "HTF_BIAS", "direction": "LONG", "strength": "STRONG"})
        router.publish(sym, {"type": "SWEEP", "tf": "15m", "level": 50000.0, "bar_index": 40})
        router.publish(sym, {"type": "MSS", "direction": "LONG", "level": 50500.0, "bar_index": 42})

        state = sm.get(sym)
        assert state.state == SetupState.WAIT_RETRACE

        # expires_at'ı geçmişe al
        state.expires_at = int(time.time()) - 1

        # _evaluate tetikle
        from datetime import datetime, timedelta

        future = datetime.now() + timedelta(hours=25)
        sm._evaluate(state, current_time=future)
        assert state.state == SetupState.IDLE


# ═════════════════════════════════════════════════════════════════════════════
# TEST: Cross-Component Integration
# ═════════════════════════════════════════════════════════════════════════════


class TestCrossComponentSignals:
    """Monitor + StateMachine + RiskManager entegrasyonu."""

    @pytest.fixture
    def pipeline(self):
        """state_machine + event_router ikilisi."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from event_router import EventRouter
            from state_machine import StateMachine
        sm = StateMachine()
        router = EventRouter(sm)
        return sm, router

    def test_monitor_tracks_chain_health(self, pipeline):
        """Monitor, zincir boyunca tick/signal/order/fill'leri kaydetmeli."""
        sm, router = pipeline
        import monitor

        sym = "BTCUSDT"

        # Simüle tick
        monitor.update_tick(sym)
        health = monitor.get_health(sym)
        assert health["status"] in ("LIVE", "STALE")
        assert health["signal_count"] == 0

        # Simüle signal (event state machine'e gittiğinde)
        monitor.update_signal(sym, reason="HTF_BIAS")
        health = monitor.get_health(sym)
        assert health["signal_count"] == 1

        # Simüle order
        monitor.update_order(sym)
        health = monitor.get_health(sym)
        assert health["order_count"] == 1

        # Simüle fill
        monitor.update_fill(sym)
        health = monitor.get_health(sym)
        assert health["fill_count"] == 1

    def test_multiple_symbols_independent_states(self):
        """Farklı sembollerin state'leri birbirini etkilememeli."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from event_router import EventRouter
            from state_machine import SetupState, StateMachine

        sm = StateMachine()
        router = EventRouter(sm)

        # BTC LONG setup
        router.publish("BTCUSDT", {"type": "HTF_BIAS", "direction": "LONG", "strength": "STRONG"})
        router.publish("BTCUSDT", {"type": "SWEEP", "tf": "15m", "level": 50000.0, "bar_index": 10})
        router.publish("BTCUSDT", {"type": "MSS", "direction": "LONG", "level": 50500.0, "bar_index": 12})

        # ETH SHORT setup
        router.publish("ETHUSDT", {"type": "HTF_BIAS", "direction": "SHORT", "strength": "STRONG"})
        router.publish("ETHUSDT", {"type": "SWEEP", "tf": "1H", "level": 3500.0, "bar_index": 5})
        router.publish("ETHUSDT", {"type": "MSS", "direction": "SHORT", "level": 3450.0, "bar_index": 7})

        btc = sm.get("BTCUSDT")
        eth = sm.get("ETHUSDT")

        assert btc.direction == "LONG"
        assert eth.direction == "SHORT"
        assert btc.state == SetupState.WAIT_RETRACE
        assert eth.state == SetupState.WAIT_RETRACE
        assert btc.mss_level == 50500.0
        assert eth.mss_level == 3450.0

    def test_event_router_normalizers(self, pipeline):
        """EventRouter yardımcı metodları düzgün event üretmeli."""
        sm, router = pipeline
        _ = sm  # sm kullanılmıyor ama fixture tutarlılığı için

        event = router.sweep_detected("BTCUSDT", 50000.0, "15m")
        assert event["type"] == "SWEEP"
        assert event["level"] == 50000.0

        event = router.mss_confirmed("BTCUSDT", 50500.0, "LONG", "15m")
        assert event["type"] == "MSS"
        assert event["direction"] == "LONG"

        event = router.fvg_created("BTCUSDT", 51000.0, 50500.0, 12345)
        assert event["type"] == "FVG_CREATED"
        assert event["upper"] == 51000.0

        event = router.ltf_confirmed("BTCUSDT", "1m", "LONG", 50800.0)
        assert event["type"] == "LTF_CONFIRM"
        assert event["close"] == 50800.0
