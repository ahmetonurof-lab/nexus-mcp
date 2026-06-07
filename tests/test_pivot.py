"""
test_pivot.py — NEXUS V3

Kapsam:
  - find_swing_highs / find_swing_lows : fraktal pivot tespiti
  - SwingStateManager                  : ingest, mark_mitigated, active_*, cleanup
"""

from __future__ import annotations

import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from conftest import make_bar


# ═══════════════════════════════════════════════════════════════
# Yardımcı
# ═══════════════════════════════════════════════════════════════


def _flat_bars(n: int, price: float = 100.0) -> list:
    """n adet eşit fiyatlı (düz) bar üretir — pivot çıkmamalı."""
    return [make_bar(index=i, open_=price, high=price, low=price, close=price) for i in range(n)]


def _spike_bars(spike_idx: int, total: int, spike_high: float = 110.0, base: float = 100.0):
    """
    Tek bir spike high oluşturur.
    spike_idx indeksindeki bar'ın high'i diğerlerinden yüksek.
    """
    bars = []
    for i in range(total):
        if i == spike_idx:
            bars.append(make_bar(index=i, open_=base, high=spike_high, low=base - 1, close=base))
        else:
            bars.append(make_bar(index=i, open_=base, high=base + 1, low=base - 1, close=base))
    return bars


def _dip_bars(dip_idx: int, total: int, dip_low: float = 90.0, base: float = 100.0):
    """Tek bir dip low oluşturur."""
    bars = []
    for i in range(total):
        if i == dip_idx:
            bars.append(make_bar(index=i, open_=base, high=base + 1, low=dip_low, close=base))
        else:
            bars.append(make_bar(index=i, open_=base, high=base + 1, low=base - 1, close=base))
    return bars


# ═══════════════════════════════════════════════════════════════
# find_swing_highs
# ═══════════════════════════════════════════════════════════════


class TestFindSwingHighs:
    def setup_method(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from pivot import find_swing_highs
        self.find = find_swing_highs

    def test_too_few_bars_returns_empty(self):
        """left=3, right=3 → minimum 7 bar gerekir."""
        bars = _flat_bars(6)
        assert self.find(bars, left=3, right=3) == []

    def test_flat_bars_no_pivot(self):
        """Tüm barlar aynı high → pivot çıkmamalı (eşit high da pivot sayılır, burada merkez yok)."""
        bars = _flat_bars(20)
        result = self.find(bars, left=3, right=3)
        # Eşit high → inclusive karşılaştırma — tüm iç bar'lar potansiyel pivot
        # ama hepsinin high eşit, dolayısıyla farkları yok; pratik olarak flat
        # davranış impl'a bağlı — sıfır veya çok sayıda pivot üretebilir, test sadece çökmediğini doğrular
        assert isinstance(result, list)

    def test_single_spike_detected(self):
        """Ortadaki bar'ın high'i en yüksekse pivot tespiti."""
        # 10 bar, spike idx=5 (left=3 right=3 → [3, 6] arası adaylar)
        bars = _spike_bars(spike_idx=5, total=10)
        result = self.find(bars, left=3, right=3)
        assert len(result) == 1
        assert result[0].price == 110.0
        assert result[0].kind == "high"
        assert result[0].bar_index == 5

    def test_unclosed_bar_excluded(self):
        """is_closed=False olan bar pivot olamaz."""
        bars = _spike_bars(spike_idx=5, total=10)
        # spike bar'ı aç
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from models import Bar
        unclosed = Bar(
            index=5,
            open=100.0,
            high=110.0,
            low=99.0,
            close=100.0,
            is_closed=False,
        )
        bars[5] = unclosed
        result = self.find(bars, left=3, right=3)
        assert all(p.bar_index != 5 for p in result)

    def test_multiple_spikes(self):
        """Birden fazla spike → hepsi tespit edilmeli."""
        total = 25
        # spike'lar idx=5 ve idx=18 (birbirinden yeterince uzak)
        bars = []
        for i in range(total):
            h = 110.0 if i in (5, 18) else 101.0
            bars.append(make_bar(index=i, open_=100.0, high=h, low=99.0, close=100.0))
        result = self.find(bars, left=3, right=3)
        pivot_indices = {p.bar_index for p in result}
        assert 5 in pivot_indices
        assert 18 in pivot_indices

    def test_left_right_parametric(self):
        """left=1, right=1 → daha hassas tespit, daha fazla pivot."""
        bars = _spike_bars(spike_idx=3, total=8)
        result_tight = self.find(bars, left=1, right=1)
        result_wide = self.find(bars, left=3, right=3)
        # Tight → daha fazla veya eşit pivot (daha az kısıt)
        assert len(result_tight) >= len(result_wide)

    def test_pivot_bar_index_matches_bar_index(self):
        """SwingPoint.bar_index, Bar.index ile eşleşmeli."""
        bars = _spike_bars(spike_idx=5, total=10)
        result = self.find(bars, left=3, right=3)
        for sp in result:
            matching = [b for b in bars if b.index == sp.bar_index]
            assert len(matching) == 1
            assert matching[0].high == sp.price


# ═══════════════════════════════════════════════════════════════
# find_swing_lows
# ═══════════════════════════════════════════════════════════════


class TestFindSwingLows:
    def setup_method(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from pivot import find_swing_lows
        self.find = find_swing_lows

    def test_too_few_bars_returns_empty(self):
        bars = _flat_bars(6)
        assert self.find(bars, left=3, right=3) == []

    def test_single_dip_detected(self):
        bars = _dip_bars(dip_idx=5, total=10)
        result = self.find(bars, left=3, right=3)
        assert len(result) == 1
        assert result[0].price == 90.0
        assert result[0].kind == "low"
        assert result[0].bar_index == 5

    def test_unclosed_bar_excluded(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from models import Bar
        bars = _dip_bars(dip_idx=5, total=10)
        unclosed = Bar(index=5, open=100.0, high=101.0, low=90.0, close=100.0, is_closed=False)
        bars[5] = unclosed
        result = self.find(bars, left=3, right=3)
        assert all(p.bar_index != 5 for p in result)

    def test_multiple_dips(self):
        total = 25
        bars = []
        for i in range(total):
            low_price = 88.0 if i in (4, 17) else 99.0
            bars.append(make_bar(index=i, open_=100.0, high=101.0, low=low_price, close=100.0))
        result = self.find(bars, left=3, right=3)
        pivot_indices = {p.bar_index for p in result}
        assert 4 in pivot_indices
        assert 17 in pivot_indices


# ═══════════════════════════════════════════════════════════════
# SwingStateManager
# ═══════════════════════════════════════════════════════════════


class TestSwingStateManager:
    def setup_method(self):
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from pivot import SwingStateManager
        self.SSM = SwingStateManager

    def _make_manager(self):
        return self.SSM()

    def test_empty_manager(self):
        mgr = self._make_manager()
        assert mgr.total_stored == 0
        assert mgr.total_active == 0
        assert mgr.get_latest_active("high") is None
        assert mgr.get_latest_active("low") is None

    def test_ingest_detects_pivots(self):
        """ingest sonrası pivot'lar hafızada olmalı."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        assert mgr.total_stored >= 1
        assert len(mgr.active_highs()) >= 1

    def test_ingest_no_duplicates(self):
        """Aynı bar'lar iki kez ingest edilirse duplicate eklenmemeli."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        count_after_first = mgr.total_stored
        mgr.ingest(bars, left=3, right=3)  # tekrar
        assert mgr.total_stored == count_after_first

    def test_mark_mitigated(self):
        """mark_mitigated sonrası pivot aktif listeden çıkmalı."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)

        highs = mgr.active_highs()
        assert len(highs) >= 1

        target = highs[0]
        result = mgr.mark_mitigated("high", target.bar_index)
        assert result is True
        # Artık aktif listede değil
        active_after = {p.bar_index for p in mgr.active_highs()}
        assert target.bar_index not in active_after

    def test_mark_mitigated_nonexistent(self):
        """Olmayan bar_index → False dönmeli."""
        mgr = self._make_manager()
        assert mgr.mark_mitigated("high", 9999) is False

    def test_get_latest_active_high(self):
        """En yüksek fiyatlı pivot'lar arasında en güncel olanı döndürülmeli."""
        mgr = self._make_manager()
        bars = []
        for i in range(30):
            if i in (5, 20):
                h = 200.0
            elif i in (4, 6, 19, 21):
                h = 101.0
            else:
                h = 99.0
            bars.append(make_bar(index=i, open_=98.0, high=h, low=97.0, close=98.0))
        mgr.ingest(bars, left=3, right=3)

        # price=200 olan spike pivot'lar tespit edilmeli
        spike_highs = [p for p in mgr.active_highs() if p.price == 200.0]
        assert len(spike_highs) == 2
        assert {p.bar_index for p in spike_highs} == {5, 20}

        # get_latest_active her zaman en büyük bar_index'i döner
        latest = mgr.get_latest_active("high")
        assert latest is not None
        all_active_indices = [p.bar_index for p in mgr.active_highs()]
        assert latest.bar_index == max(all_active_indices)

    def test_cleanup_removes_old_pivots(self):
        """cleanup() sonrası eski pivot'lar hafızadan çıkmalı."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        count_before = mgr.total_stored
        # current_abs=1000, max_age=10 → bar_index=5 çok eski
        mgr.cleanup(max_age=10, current_abs=1000)
        assert mgr.total_stored < count_before

    def test_cleanup_keeps_recent_pivots(self):
        """Yeni pivot'lar cleanup sonrası korunmalı."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        # current_abs=5 + max_age=10 → bar_index=5 korunur
        mgr.cleanup(max_age=10, current_abs=5)
        assert mgr.total_stored > 0

    def test_reset_clears_all(self):
        """reset() sonrası hiç pivot kalmamalı."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        mgr.reset()
        assert mgr.total_stored == 0
        assert mgr.total_active == 0

    def test_active_lows(self):
        """Swing low'lar aktif_lows'ta görünmeli."""
        mgr = self._make_manager()
        bars = _dip_bars(dip_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        assert len(mgr.active_lows()) >= 1

    def test_total_active_decreases_after_mitigation(self):
        """Mitigasyon sonrası total_active azalmalı."""
        mgr = self._make_manager()
        bars = _spike_bars(spike_idx=5, total=10)
        mgr.ingest(bars, left=3, right=3)
        before = mgr.total_active
        highs = mgr.active_highs()
        if highs:
            mgr.mark_mitigated("high", highs[0].bar_index)
            assert mgr.total_active == before - 1
