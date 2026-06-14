"""
test_scoring.py — NEXUS V3

Kapsam:
  1. build_scoring_context     — ScoringContext oluşturma
  2. detect_market_regime      — Piyasa rejimi tespiti
  3. compute_fvg_component_scores — FVG bileşen skorları
  4. _get_choch_score_for_direction — CHoCH skor entegrasyonu
  5. analyze_confluence        — Konfluens analizi
  6. compute_entry_exit_zones  — Giriş/çıkış bölgeleri
  7. calculate_rr_ratio        — Risk/ödül oranı
  8. evaluate_trade_signal     — Ana skorlama (mock'lu)
  9. classify_signal_strength  — Sinyal gücü sınıflandırma
 10. evaluate_all_signals      — İki yönlü değerlendirme
 11. generate_market_summary   — Piyasa özeti
"""

from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

# sys.path: sonnet/src
SRC = Path(__file__).parent.parent / "sonnet" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import config  # noqa: F401

from conftest import make_bar  # noqa: E402

# ─────────────────────────────────────────────────────────
# YARDIMCILAR
# ─────────────────────────────────────────────────────────


def _make_fvg(direction="bullish", top=105.0, bottom=100.0, real_index=5, timeframe="5m"):
    """Minimal geçerli FVG nesnesi üretir."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from models import FVG
    return FVG(
        direction=direction,
        top=top,
        bottom=bottom,
        real_index=real_index,
        timeframe=timeframe,
    )


def _make_choch(direction="bullish", level=102.0, bar_index=10, pivot_bar_index=5, strength=0.5):
    """Minimal geçerli CHoCH nesnesi üretir."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from models import CHoCH
    return CHoCH(
        direction=direction,
        level=level,
        bar_index=bar_index,
        pivot_bar_index=pivot_bar_index,
        strength=strength,
    )


def _make_bars_uptrend(n=60, base_price=100.0, step=1.0):
    """Yukarı trend bar dizisi — EMA ve ADX hesaplamaları için yeterli."""
    bars = []
    for i in range(n):
        price = base_price + i * step
        bars.append(
            make_bar(
                index=i,
                open_=price - 0.5,
                high=price + 1.0,
                low=price - 1.0,
                close=price + 0.3,
            )
        )
    return bars


def _make_bars_downtrend(n=60, base_price=200.0, step=1.0):
    """Aşağı trend bar dizisi."""
    bars = []
    for i in range(n):
        price = base_price - i * step
        bars.append(
            make_bar(
                index=i,
                open_=price + 0.5,
                high=price + 1.0,
                low=price - 1.0,
                close=price - 0.3,
            )
        )
    return bars


def _make_bars_ranging(n=60, base_price=100.0):
    """Yatay piyasa bar dizisi."""
    bars = []
    for i in range(n):
        offset = math.sin(i * 0.2) * 1.5
        price = base_price + offset
        bars.append(
            make_bar(
                index=i,
                open_=price - 0.3,
                high=price + 0.8,
                low=price - 0.8,
                close=price + 0.1,
            )
        )
    return bars


def _make_bars_volatile(n=100, base_price=100.0):
    """Volatil bar dizisi — son 15 bar çok yüksek vol, öncekiler çok düşük."""
    bars = []
    for i in range(n):
        # İlk 85 bar düşük volatilite, son 15 bar ekstrem yüksek volatilite
        if i < 85:
            vol = 0.5
            price = base_price
        else:
            vol = 20.0
            price = base_price
        bars.append(
            make_bar(
                index=i,
                open_=price - vol * 0.3,
                high=price + vol,
                low=price - vol,
                close=price + vol * 0.2,
            )
        )
    return bars


# ─────────────────────────────────────────────────────────
# 1. build_scoring_context
# ─────────────────────────────────────────────────────────


class TestBuildScoringContext:
    """ScoringContext oluşturma — tüm gösterge hesaplamaları dahil."""

    def test_empty_bars_returns_default_context(self):
        """Boş bar listesi → default ScoringContext döner."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext, build_scoring_context

        ctx = build_scoring_context([], [], [])
        assert isinstance(ctx, ScoringContext)
        assert ctx.bars == []
        assert ctx.current_price == 0.0
        assert ctx.atr == 0.0
        assert ctx.adx == 0.0
        assert ctx.vp_status == "none"

    def test_normal_bars_produces_context(self):
        """Normal bar listesi → tüm göstergeler hesaplanır (EMA için 200+ bar gerekir)."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext, build_scoring_context

        bars = _make_bars_uptrend(220)
        ctx = build_scoring_context(bars, [], [], timeframe="15m")
        assert isinstance(ctx, ScoringContext)
        assert ctx.current_price == bars[-1].close
        assert ctx.atr > 0
        assert ctx.adx >= 0
        assert not math.isnan(ctx.ema100)
        assert not math.isnan(ctx.ema200)
        assert ctx.timeframe == "15m"
        assert ctx.vp_status == "none"

    def test_vp_integration_no_vp(self):
        """VP verilmezse → vp_status='none'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import build_scoring_context

        bars = _make_bars_uptrend(60)
        fvg = _make_fvg()
        ctx = build_scoring_context(bars, [fvg], [], vp=None, current_fvg=fvg)
        assert ctx.vp_status == "none"


# ─────────────────────────────────────────────────────────
# 2. detect_market_regime
# ─────────────────────────────────────────────────────────


class TestDetectMarketRegime:
    """Piyasa rejimi tespiti — ADX + EMA + fiyat kombinasyonu."""

    def test_few_bars_returns_ranging(self):
        """50 bar'dan az → 'ranging'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_uptrend(20)
        result = detect_market_regime(bars, adx=35.0, ema100=110.0, ema200=105.0, current_price=120.0)
        assert result == "ranging"

    def test_adx_above_30_trending_up(self):
        """ADX >= 30 + fiyat > EMA100 > EMA200 → 'trending_up'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_uptrend(60)
        result = detect_market_regime(bars, adx=35.0, ema100=150.0, ema200=140.0, current_price=160.0)
        assert result == "trending_up"

    def test_adx_above_30_trending_down(self):
        """ADX >= 30 + fiyat < EMA100 < EMA200 → 'trending_down'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_downtrend(60)
        result = detect_market_regime(bars, adx=40.0, ema100=130.0, ema200=140.0, current_price=120.0)
        assert result == "trending_down"

    def test_adx_between_20_and_30_ranging(self):
        """ADX [20,30) + fiyat EMA100'e yakın → 'ranging'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_uptrend(60)
        # fiyat EMA100'e çok yakın (fark < %2)
        result = detect_market_regime(bars, adx=22.0, ema100=155.0, ema200=140.0, current_price=156.0)
        assert result == "ranging"

    def test_adx_between_20_and_30_trending(self):
        """ADX [20,30) + fiyat EMA100'den uzak → trending."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_uptrend(60)
        result = detect_market_regime(bars, adx=22.0, ema100=150.0, ema200=140.0, current_price=162.0)
        assert result == "trending_up"

    def test_low_adx_ranging(self):
        """ADX < 20 + normal ATR → 'ranging'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_ranging(60)
        result = detect_market_regime(bars, adx=15.0, ema100=100.0, ema200=99.0, current_price=100.5)
        assert result == "ranging"

    def test_low_adx_volatile(self):
        """ADX < 20 + ATR 1.5x artmış → 'volatile'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_volatile(100)
        result = detect_market_regime(bars, adx=12.0, ema100=100.0, ema200=99.0, current_price=105.0)
        assert result == "volatile"

    def test_adx_above_30_ema_nan_fallback(self):
        """ADX >= 30 ama EMA'lar NaN → MA fallback ile trending tespiti."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import detect_market_regime

        bars = _make_bars_uptrend(60)
        result = detect_market_regime(bars, adx=35.0, ema100=math.nan, ema200=math.nan, current_price=160.0)
        # short MA (son 20) > long MA (son 50) → trending_up
        assert result == "trending_up"


# ─────────────────────────────────────────────────────────
# 3. compute_fvg_component_scores
# ─────────────────────────────────────────────────────────


class TestComputeFVGComponentScores:
    """FVG bileşen skorları — displacement, size, sweep, retest."""

    def test_fvg_out_of_range_returns_zeros(self):
        """FVG pozisyonu bar aralığı dışında → sıfır skorlar."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import compute_fvg_component_scores

        bars = _make_bars_uptrend(30)  # index 0..29
        fvg = _make_fvg(real_index=100)  # out of range
        d, f, s, r, bars_since = compute_fvg_component_scores(
            fvg, bars, atr=2.0, atr_series=[2.0] * 30, current_price=130.0
        )
        assert d == 0.0
        assert f == 0.0
        assert s == 0.0
        assert r == 0.0
        assert bars_since == 999

    def test_fvg_negative_position_returns_zeros(self):
        """FVG pozisyonu negatif → sıfır skorlar."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import compute_fvg_component_scores

        bars = _make_bars_uptrend(30)
        # bar[0].index=0, fvg.real_index=-5 → pos = -5
        bars[0] = make_bar(index=10, open_=100, high=105, low=95, close=102)  # first_abs=10
        fvg = _make_fvg(real_index=5)  # 5 < 10 → pos = -5
        d, f, s, r, bars_since = compute_fvg_component_scores(
            fvg, bars, atr=2.0, atr_series=[2.0] * 30, current_price=120.0
        )
        assert d == 0.0
        assert bars_since == 999


# ─────────────────────────────────────────────────────────
# 4. _get_choch_score_for_direction
# ─────────────────────────────────────────────────────────


class TestGetCHoCHScoreForDirection:
    """CHoCH listesinden FVG yönüne uygun en güncel CHoCH skoru."""

    def test_empty_chochs_returns_zero(self):
        """Boş CHoCH listesi → (0.0, '')."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import _get_choch_score_for_direction

        bars = _make_bars_uptrend(30)
        atr_series = [2.0] * 30
        score, direction = _get_choch_score_for_direction([], bars, "bullish", atr_series, adx=25.0)
        assert score == 0.0
        assert direction == ""

    def test_no_matching_direction_returns_zero(self):
        """Hiçbir CHoCH FVG yönüyle eşleşmiyor → (0.0, '')."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import _get_choch_score_for_direction

        bars = _make_bars_uptrend(30)
        atr_series = [2.0] * 30
        chochs = [_make_choch(direction="bearish", bar_index=15, pivot_bar_index=10)]
        score, direction = _get_choch_score_for_direction(chochs, bars, "bullish", atr_series, adx=25.0)
        assert score == 0.0
        assert direction == ""

    def test_matching_choch_returns_score(self):
        """Eşleşen CHoCH → pozitif skor döner."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import _get_choch_score_for_direction

        bars = _make_bars_uptrend(30)
        atr_series = [2.0] * 30
        chochs = [_make_choch(direction="bullish", level=105.0, bar_index=20, pivot_bar_index=15)]
        score, direction = _get_choch_score_for_direction(chochs, bars, "bullish", atr_series, adx=25.0)
        assert score > 0.0
        assert direction == "bullish"

    def test_choch_out_of_range_returns_zero(self):
        """CHoCH bar_index bar listesi dışında → (0.0, '')."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import _get_choch_score_for_direction

        bars = _make_bars_uptrend(30)  # index 0..29
        atr_series = [2.0] * 30
        chochs = [_make_choch(direction="bullish", bar_index=100, pivot_bar_index=95)]
        score, direction = _get_choch_score_for_direction(chochs, bars, "bullish", atr_series, adx=25.0)
        assert score == 0.0

    def test_best_choch_selected_by_strength_and_index(self):
        """En yüksek (strength, bar_index) kombinasyonuna sahip CHoCH seçilir."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import _get_choch_score_for_direction

        bars = _make_bars_uptrend(30)
        atr_series = [2.0] * 30
        chochs = [
            _make_choch(direction="bullish", bar_index=10, strength=0.3),
            _make_choch(direction="bullish", bar_index=20, strength=0.8),
            _make_choch(direction="bullish", bar_index=25, strength=0.5),
        ]
        score, direction = _get_choch_score_for_direction(chochs, bars, "bullish", atr_series, adx=25.0)
        assert score > 0.0
        assert direction == "bullish"


# ─────────────────────────────────────────────────────────
# 5. analyze_confluence
# ─────────────────────────────────────────────────────────


class TestAnalyzeConfluence:
    """Konfluens analizi — FVG yönüyle uyumlu sinyal sayımı."""

    def _make_ctx(
        self,
        bars=None,
        fvgs=None,
        chochs=None,
        current_price=100.0,
        atr=2.0,
        atr_series=None,
        adx=25.0,
        ema100=95.0,
        ema200=90.0,
        vp_status="none",
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext
        return ScoringContext(
            bars=bars or _make_bars_uptrend(30),
            fvgs=fvgs or [],
            chochs=chochs or [],
            current_price=current_price,
            atr=atr,
            atr_series=atr_series or [2.0] * 30,
            adx=adx,
            ema100=ema100,
            ema200=ema200,
            vp_status=vp_status,
        )

    def test_confluence_count_minimum(self):
        """FVG her zaman sayılır → min count=1."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx()
        count, active = analyze_confluence(ctx, "bullish")
        assert count >= 1
        assert "FVG" in active

    def test_confluence_with_choch(self):
        """Eşleşen CHoCH → count artar."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        chochs = [_make_choch(direction="bullish")]
        ctx = self._make_ctx(chochs=chochs)
        count, active = analyze_confluence(ctx, "bullish")
        assert count >= 2
        assert "CHoCH" in active

    def test_confluence_ema_alignment_bullish(self):
        """EMA100 > EMA200 (golden cross) → bullish konfluens."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(ema100=100.0, ema200=90.0)
        count, active = analyze_confluence(ctx, "bullish")
        assert "EMA_alignment" in active

    def test_confluence_ema_alignment_bearish(self):
        """EMA100 < EMA200 (death cross) → bearish konfluens."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(ema100=90.0, ema200=100.0)
        count, active = analyze_confluence(ctx, "bearish")
        assert "EMA_alignment" in active

    def test_confluence_price_ema100(self):
        """Fiyat EMA100'ün üstünde → bullish Price_EMA100 sinyali."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(current_price=105.0, ema100=100.0)
        count, active = analyze_confluence(ctx, "bullish")
        assert "Price_EMA100" in active

    def test_confluence_adx_trend(self):
        """ADX >= 20 → ADX_trend sinyali."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(adx=25.0)
        count, active = analyze_confluence(ctx, "bullish")
        assert "ADX_trend" in active

    def test_confluence_no_adx_low(self):
        """ADX < 20 → ADX_trend yok."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(adx=15.0)
        count, active = analyze_confluence(ctx, "bullish")
        assert "ADX_trend" not in active

    def test_confluence_vp_lvn(self):
        """vp_status='LVN' → VP_LVN sinyali."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(vp_status="LVN")
        count, active = analyze_confluence(ctx, "bullish")
        assert "VP_LVN" in active

    def test_confluence_no_vp_other(self):
        """vp_status='none' → VP_LVN yok."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import analyze_confluence

        ctx = self._make_ctx(vp_status="none")
        count, active = analyze_confluence(ctx, "bullish")
        assert "VP_LVN" not in active


# ─────────────────────────────────────────────────────────
# 6. compute_entry_exit_zones
# ─────────────────────────────────────────────────────────


class TestComputeEntryExitZones:
    """Giriş/çıkış bölgeleri hesaplaması."""

    def test_bullish_entry_zones(self):
        """Bullish FVG → uygun entry/stop/tp seviyeleri."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import compute_entry_exit_zones

        fvg = _make_fvg(direction="bullish", top=105.0, bottom=100.0)
        zones = compute_entry_exit_zones(fvg, atr=2.0, current_price=102.0, direction="bullish")
        assert zones["entry_low"] == fvg.bottom
        assert zones["entry_high"] > fvg.midpoint
        assert zones["stop_loss"] < fvg.bottom
        assert zones["tp1"] > fvg.top
        assert zones["tp2"] > zones["tp1"]

    def test_bearish_entry_zones(self):
        """Bearish FVG → uygun entry/stop/tp seviyeleri."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import compute_entry_exit_zones

        fvg = _make_fvg(direction="bearish", top=105.0, bottom=100.0)
        zones = compute_entry_exit_zones(fvg, atr=2.0, current_price=102.0, direction="bearish")
        assert zones["entry_high"] == fvg.top
        assert zones["entry_low"] < fvg.midpoint
        assert zones["stop_loss"] > fvg.top
        assert zones["tp1"] < fvg.bottom
        assert zones["tp2"] < zones["tp1"]


# ─────────────────────────────────────────────────────────
# 7. calculate_rr_ratio
# ─────────────────────────────────────────────────────────


class TestCalculateRRRatio:
    """Risk/Ödül oranı hesaplaması."""

    def test_normal_rr(self):
        """Normal durumda RR hesaplanır."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import calculate_rr_ratio

        rr = calculate_rr_ratio(entry=100.0, stop_loss=98.0, take_profit=106.0)
        assert rr == 3.0  # (106-100)/(100-98) = 6/2

    def test_zero_risk_returns_zero(self):
        """Risk sıfır → RR = 0.0."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import calculate_rr_ratio

        rr = calculate_rr_ratio(entry=100.0, stop_loss=100.0, take_profit=110.0)
        assert rr == 0.0

    def test_rr_less_than_one(self):
        """Risk > reward → RR < 1."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import calculate_rr_ratio

        rr = calculate_rr_ratio(entry=100.0, stop_loss=90.0, take_profit=105.0)
        assert rr == 0.5  # (105-100)/(100-90) = 5/10


# ─────────────────────────────────────────────────────────
# 8. evaluate_trade_signal
# ─────────────────────────────────────────────────────────


class TestEvaluateTradeSignal:
    """Ana skorlama fonksiyonu — NEUTRAL / LONG / SHORT."""

    def _make_ctx(
        self,
        bars=None,
        fvgs=None,
        chochs=None,
        current_price=100.0,
        atr=2.0,
        atr_series=None,
        adx=25.0,
        ema100=95.0,
        ema200=90.0,
        vp_status="none",
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext
        return ScoringContext(
            bars=bars or _make_bars_uptrend(60),
            fvgs=fvgs or [],
            chochs=chochs or [],
            current_price=current_price,
            atr=atr,
            atr_series=atr_series or [2.0] * 60,
            adx=adx,
            ema100=ema100,
            ema200=ema200,
            vp_status=vp_status,
        )

    def test_empty_context_returns_neutral(self):
        """Boş bar / ATR=0 → NEUTRAL sinyal."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext, evaluate_trade_signal

        ctx = ScoringContext(
            bars=[],
            fvgs=[],
            chochs=[],
            current_price=0.0,
            atr=0.0,
            atr_series=[],
            adx=0.0,
            ema100=math.nan,
            ema200=math.nan,
            vp_status="none",
        )
        signal = evaluate_trade_signal(ctx)
        assert signal.direction == "NEUTRAL"
        assert signal.confidence == 0.0

    def test_empty_bars_but_valid_atr_returns_neutral(self):
        """Barlar boş ama ATR pozitif → NEUTRAL."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext, evaluate_trade_signal

        ctx = ScoringContext(
            bars=[],
            fvgs=[],
            chochs=[],
            current_price=0.0,
            atr=2.0,
            atr_series=[],
            adx=0.0,
            ema100=math.nan,
            ema200=math.nan,
            vp_status="none",
        )
        signal = evaluate_trade_signal(ctx)
        assert signal.direction == "NEUTRAL"

    @patch("scoring.find_latest_unfilled_fvg")
    @patch("scoring.compute_fvg_quality")
    @patch("scoring.is_premium_discount_valid")
    def test_no_fvg_found_returns_neutral(self, mock_pd, mock_quality, mock_find):
        """FVG bulunamazsa → NEUTRAL sinyal."""
        mock_find.return_value = None
        mock_pd.return_value = False

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import evaluate_trade_signal

        ctx = self._make_ctx()
        signal = evaluate_trade_signal(ctx, fvg_direction="bullish")
        assert signal.direction == "NEUTRAL"
        assert signal.confidence == 0.0

    @patch("scoring.find_latest_unfilled_fvg")
    @patch("scoring.compute_fvg_quality")
    @patch("scoring.is_premium_discount_valid")
    def test_bullish_signal_generated(self, mock_pd, mock_quality, mock_find):
        """Geçerli bullish FVG → LONG sinyali (mock'lu)."""
        fvg = _make_fvg(direction="bullish", top=105.0, bottom=100.0)
        mock_find.return_value = fvg
        mock_pd.return_value = True

        # Mock FVGQuality
        mock_fvgq = MagicMock()
        mock_fvgq.score = 0.70
        mock_fvgq.displacement = 0.5
        mock_fvgq.fvg_size = 0.5
        mock_fvgq.sweep = 0.5
        mock_fvgq.retest = 0.5
        mock_quality.return_value = mock_fvgq

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import evaluate_trade_signal

        ctx = self._make_ctx()
        signal = evaluate_trade_signal(ctx, fvg_direction="bullish", min_confidence=0.50)
        assert signal.direction in ("LONG", "NEUTRAL")
        assert signal.confidence >= 0.0
        assert signal.market_regime in ("trending_up", "trending_down", "ranging", "volatile")

    @patch("scoring.find_latest_unfilled_fvg")
    @patch("scoring.compute_fvg_quality")
    @patch("scoring.is_premium_discount_valid")
    def test_veto_quality_zero_skips(self, mock_pd, mock_quality, mock_find):
        """FVG kalite skoru 0 → VETO (atlanır), sonraki yön denenir veya NEUTRAL."""
        fvg = _make_fvg(direction="bullish", top=105.0, bottom=100.0)
        mock_find.return_value = fvg
        mock_pd.return_value = False

        mock_fvgq = MagicMock()
        mock_fvgq.score = 0.0
        mock_quality.return_value = mock_fvgq

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import evaluate_trade_signal

        ctx = self._make_ctx()
        signal = evaluate_trade_signal(ctx, fvg_direction="bullish")
        # All FVGs vetoed, no best signal → NEUTRAL
        assert signal.direction == "NEUTRAL"

    @patch("scoring.find_latest_unfilled_fvg")
    @patch("scoring.compute_fvg_quality")
    @patch("scoring.is_premium_discount_valid")
    def test_auto_direction_detection(self, mock_pd, mock_quality, mock_find):
        """fvg_direction=None → hem bullish hem bearish kontrol edilir."""
        fvg_bull = _make_fvg(direction="bullish", top=105.0, bottom=100.0)
        mock_find.return_value = fvg_bull
        mock_pd.return_value = True

        mock_fvgq = MagicMock()
        mock_fvgq.score = 0.65
        mock_fvgq.displacement = 0.5
        mock_fvgq.fvg_size = 0.5
        mock_fvgq.sweep = 0.5
        mock_fvgq.retest = 0.5
        mock_quality.return_value = mock_fvgq

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import evaluate_trade_signal

        ctx = self._make_ctx()
        signal = evaluate_trade_signal(ctx, min_confidence=0.50)
        assert signal.direction in ("LONG", "SHORT", "NEUTRAL")


# ─────────────────────────────────────────────────────────
# 9. classify_signal_strength
# ─────────────────────────────────────────────────────────


class TestClassifySignalStrength:
    """Sinyal gücü sınıflandırması."""

    def test_strong(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import classify_signal_strength
        assert classify_signal_strength(0.80) == "STRONG"
        assert classify_signal_strength(0.75) == "STRONG"

    def test_moderate(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import classify_signal_strength
        assert classify_signal_strength(0.60) == "MODERATE"
        assert classify_signal_strength(0.55) == "MODERATE"

    def test_weak(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import classify_signal_strength
        assert classify_signal_strength(0.40) == "WEAK"
        assert classify_signal_strength(0.30) == "WEAK"

    def test_none(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import classify_signal_strength
        assert classify_signal_strength(0.20) == "NONE"
        assert classify_signal_strength(0.0) == "NONE"


# ─────────────────────────────────────────────────────────
# 10. evaluate_all_signals
# ─────────────────────────────────────────────────────────


class TestEvaluateAllSignals:
    """İki yönlü değerlendirme."""

    def _make_ctx(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext
        return ScoringContext(
            bars=_make_bars_uptrend(60),
            fvgs=[],
            chochs=[],
            current_price=160.0,
            atr=2.0,
            atr_series=[2.0] * 60,
            adx=35.0,
            ema100=150.0,
            ema200=140.0,
            vp_status="none",
        )

    @patch("scoring.find_latest_unfilled_fvg")
    @patch("scoring.compute_fvg_quality")
    @patch("scoring.is_premium_discount_valid")
    def test_returns_both_directions(self, mock_pd, mock_quality, mock_find):
        """Hem 'bullish' hem 'bearish' anahtarları döner."""
        mock_find.return_value = None
        mock_pd.return_value = False

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import evaluate_all_signals

        ctx = self._make_ctx()
        result = evaluate_all_signals(ctx)
        assert "bullish" in result
        assert "bearish" in result
        assert result["bullish"].direction == "NEUTRAL"
        assert result["bearish"].direction == "NEUTRAL"


# ─────────────────────────────────────────────────────────
# 11. generate_market_summary
# ─────────────────────────────────────────────────────────


class TestGenerateMarketSummary:
    """Piyasa özeti oluşturma."""

    def _make_ctx(
        self, bars=None, fvgs=None, chochs=None, current_price=100.0, atr=2.0, adx=25.0, ema100=95.0, ema200=90.0
    ):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext
        return ScoringContext(
            bars=bars or _make_bars_uptrend(60),
            fvgs=fvgs or [],
            chochs=chochs or [],
            current_price=current_price,
            atr=atr,
            atr_series=[2.0] * 60,
            adx=adx,
            ema100=ema100,
            ema200=ema200,
            vp_status="none",
        )

    def test_summary_has_required_keys(self):
        """Özette gerekli tüm anahtarlar mevcut."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        ctx = self._make_ctx()
        summary = generate_market_summary(ctx)
        assert "regime" in summary
        assert "adx" in summary
        assert "atr" in summary
        assert "trend" in summary
        assert "ema_status" in summary
        assert "active_fvgs" in summary
        assert "recent_chochs" in summary
        assert summary["adx"] == 25.0
        assert summary["atr"] == 2.0

    def test_golden_cross_detected(self):
        """EMA100 > EMA200 → 'golden_cross'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        ctx = self._make_ctx(ema100=150.0, ema200=140.0, current_price=160.0)
        summary = generate_market_summary(ctx)
        assert summary["ema_status"] == "golden_cross"
        assert summary["trend"] == "strong_bullish"

    def test_death_cross_detected(self):
        """EMA100 < EMA200 → 'death_cross'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        ctx = self._make_ctx(ema100=130.0, ema200=140.0, current_price=120.0)
        summary = generate_market_summary(ctx)
        assert summary["ema_status"] == "death_cross"
        assert summary["trend"] == "strong_bearish"

    def test_golden_cross_bullish(self):
        """EMA100 > EMA200 ama fiyat altında → 'bullish'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        ctx = self._make_ctx(ema100=150.0, ema200=140.0, current_price=145.0)
        summary = generate_market_summary(ctx)
        assert summary["trend"] == "bullish"

    def test_death_cross_bearish(self):
        """EMA100 < EMA200 ama fiyat üstünde → 'bearish'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        ctx = self._make_ctx(ema100=130.0, ema200=140.0, current_price=135.0)
        summary = generate_market_summary(ctx)
        assert summary["trend"] == "bearish"

    def test_ema_nan_insufficient_data(self):
        """EMA'lar NaN → 'insufficient_data'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        ctx = self._make_ctx(ema100=math.nan, ema200=math.nan)
        summary = generate_market_summary(ctx)
        assert summary["ema_status"] == "insufficient_data"
        assert summary["trend"] == "unknown"

    def test_active_fvgs_count(self):
        """Aktif FVG sayısı doğru hesaplanır."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import generate_market_summary

        fvg1 = _make_fvg(direction="bullish", top=105.0, bottom=100.0)
        fvg2 = _make_fvg(direction="bearish", top=95.0, bottom=90.0)
        # Mark one as filled
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            object.__setattr__(fvg2, "filled", True)

        ctx = self._make_ctx(fvgs=[fvg1, fvg2])
        summary = generate_market_summary(ctx)
        # Only fvg1 is not filled and not invalidated
        assert summary["active_fvgs"] == 1


# ─────────────────────────────────────────────────────────
# 12. TradeSignal & ScoringContext Dataclass Tests
# ─────────────────────────────────────────────────────────


class TestTradeSignalDataclass:
    """TradeSignal dataclass'ı temel testleri."""

    def test_trade_signal_creation(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import TradeSignal

        signal = TradeSignal(
            direction="LONG",
            confidence=0.75,
            fvg_quality=None,
            choch_score=0.5,
            choch_direction="bullish",
            entry_zone_low=100.0,
            entry_zone_high=102.0,
            stop_loss=98.0,
            take_profit_1=106.0,
            take_profit_2=110.0,
            risk_reward_ratio=2.0,
            market_regime="trending_up",
            confluence_count=3,
            timestamp=1234567890,
        )
        assert signal.direction == "LONG"
        assert signal.confidence == 0.75
        assert signal.market_regime == "trending_up"
        assert signal.confluence_count == 3
        assert signal.timestamp == 1234567890

    def test_trade_signal_neutral(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import TradeSignal

        signal = TradeSignal(
            direction="NEUTRAL",
            confidence=0.0,
            fvg_quality=None,
            choch_score=0.0,
            choch_direction="",
            entry_zone_low=0.0,
            entry_zone_high=0.0,
            stop_loss=0.0,
            take_profit_1=0.0,
            take_profit_2=0.0,
            risk_reward_ratio=0.0,
            market_regime="ranging",
            confluence_count=0,
        )
        assert signal.direction == "NEUTRAL"


class TestScoringContextDataclass:
    """ScoringContext dataclass'ı temel testleri."""

    def test_scoring_context_creation(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from scoring import ScoringContext

        bars = _make_bars_uptrend(30)
        ctx = ScoringContext(
            bars=bars,
            fvgs=[],
            chochs=[],
            current_price=130.0,
            atr=1.5,
            atr_series=[1.5] * 30,
            adx=28.0,
            ema100=125.0,
            ema200=120.0,
            timeframe="15m",
            vp_status="LVN",
        )
        assert ctx.current_price == 130.0
        assert ctx.atr == 1.5
        assert ctx.adx == 28.0
        assert ctx.timeframe == "15m"
        assert ctx.vp_status == "LVN"
        assert len(ctx.bars) == 30
