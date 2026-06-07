"""
conftest.py — Nexus V3 Test Fixtures

Bar, SymbolState, RiskManager fabrika fonksiyonları.
Exchange / WS bağlantısı gerektirmeyen pure-unit testler için.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── sys.path: sonnet/src klasörünü ekle ──────────────────────────────────────
SRC = Path(__file__).parent.parent / "sonnet" / "src"
sys.path.insert(0, str(SRC))

# config import'u (models.py'den önce) — DeprecationWarning engelle
import warnings  # noqa: E402

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import config  # noqa: E402, F401


# ── Bar Fabrikası ─────────────────────────────────────────────────────────────


def make_bar(
    index: int = 0,
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
    volume: float = 1000.0,
    is_closed: bool = True,
    timestamp: int = 0,
):
    """Minimal geçerli Bar nesnesi üretir."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from models import Bar
    return Bar(
        index=index,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        is_closed=is_closed,
        timestamp=timestamp,
    )


def make_bar_seq(prices: list[tuple[float, float, float, float]], base_index: int = 0):
    """
    (open, high, low, close) listesinden Bar dizisi üretir.
    Otomatik index atar, tüm barlar kapalı (is_closed=True).
    """
    return [make_bar(index=base_index + i, open_=o, high=h, low=lo, close=c) for i, (o, h, lo, c) in enumerate(prices)]


# ── SymbolState Fabrikası ─────────────────────────────────────────────────────


def make_state(
    symbol: str = "BTCUSDT",
    direction: str | None = "LONG",
    fvg_upper: float | None = 105.0,
    fvg_lower: float | None = 100.0,
    htf_strength: str | None = "STRONG",
    sweep_level: float | None = None,
    mss_level: float | None = 98.0,
    h4_swing_level: float | None = None,
    h1_liquidity_level: float | None = None,
):
    """
    Test için minimal SymbolState üretir.
    Tüm flagler (sweep_detected vb.) False başlar.
    """
    from state_machine import SymbolState

    state = SymbolState(symbol=symbol)
    state.direction = direction
    state.fvg_upper = fvg_upper
    state.fvg_lower = fvg_lower
    state.htf_strength = htf_strength
    state.sweep_level = sweep_level
    state.mss_level = mss_level
    state.h4_swing_level = h4_swing_level
    state.h1_liquidity_level = h1_liquidity_level
    return state


# ── RiskManager Fabrikası ─────────────────────────────────────────────────────


def make_risk_manager(
    balance: float = 10_000.0,
    risk_pct: float = 0.01,  # %1 — hesap kolaylığı için
    min_rr: float = 0.0,  # filtre kapalı (tüm RR'a izin ver)
    min_net_rr: float = 0.0,  # filtre kapalı
    leverage: float = 10.0,
    default_rr: float = 2.0,
):
    """Test için sıfır-filtreli RiskManager üretir."""
    from risk_manager import RiskManager

    return RiskManager(
        balance=balance,
        available_margin=balance,
        risk_pct=risk_pct,
        min_rr=min_rr,
        min_net_rr=min_net_rr,
        leverage=leverage,
        default_rr=default_rr,
    )


# ── pytest fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def btc_state():
    return make_state(symbol="BTCUSDT")


@pytest.fixture
def rm():
    """Sıfır-filtreli RiskManager (BTC tier1)."""
    return make_risk_manager()


@pytest.fixture
def rm_filtered():
    """Gerçek filtrelerle RiskManager (min_rr=2.0, min_net_rr=1.5)."""
    return make_risk_manager(min_rr=2.0, min_net_rr=1.5)
