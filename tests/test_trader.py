"""
test_trader.py — NEXUS V3 LiveExecutor Characterization Tests

Kapsam (P1-0A):
  - send_order characterization tests (refactor öncesi behavior capture)
  - Tüm testler mevcut kodu DEĞİŞTİRMEZ, sadece behavior'u test eder
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# ── Test Doubles ──────────────────────────────────────────────────────────────


def make_trade_params(
    symbol: str = "BTCUSDT",
    direction: str = "long",
    lot: float = 0.01,
    entry: float = 50000.0,
    sl: float = 49500.0,
    tp: float = 51000.0,
    initial_sl: float = 49500.0,
    breakeven_level: float = 50200.0,
    trailing_level: float = 50400.0,
    risk_usd: float = 5.0,
):
    """TradeParams benzeri mock nesne — send_order dict/object dual path'ini test eder."""
    return SimpleNamespace(
        symbol=symbol,
        direction=direction,
        lot=lot,
        entry=entry,
        sl=sl,
        tp=tp,
        initial_sl=initial_sl,
        breakeven_level=breakeven_level,
        trailing_level=trailing_level,
        risk_usd=risk_usd,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_exchange():
    """AsyncMock ile ExchangeClient'in tüm async metodlarını mock'la."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from trader import ExchangeClient

    client = AsyncMock(spec=ExchangeClient)

    # Varsayılan davranışlar:
    client.fetch_position = AsyncMock(return_value=None)  # noqa: SIM115
    client.set_margin_mode = AsyncMock(return_value=True)  # noqa: SIM115
    client.create_order = AsyncMock(  # noqa: SIM115
        return_value={
            "symbol": "BTCUSDT",
            "orderId": 123456789,
            "clientOrderId": "choc_test_1234",
            "avgPrice": "50200.0",
            "status": "FILLED",
        }
    )
    client.create_algo_order = AsyncMock(  # noqa: SIM115
        return_value={
            "symbol": "BTCUSDT",
            "algoId": "algo_sl_001",
            "clientAlgoId": "choc_test_1234_sl_0",
            "stopPrice": "49500.0",
            "status": "NEW",
        }
    )
    client.close_position = AsyncMock(return_value=True)  # noqa: SIM115

    # Senkron metodlar da mock:
    client._apply_price_precision = lambda _, p: round(p, 5)
    client._apply_amount_precision = lambda _, a: round(a, 3)
    client._validate_min_amount = lambda *_, **__: True

    return client


@pytest.fixture
def executor(mock_exchange):
    """Fresh LiveExecutor — her test için yeni instance."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from trader import LiveExecutor

    ex = LiveExecutor(exchange_client=mock_exchange, cooldown_seconds=0.0)
    return ex


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Happy Path — MARKET Entry
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_market_happy_path(executor, mock_exchange):
    """MARKET entry + SL + TP — hepsi başarılı.

    Coverage:
      - Dict parametre codepath (attr check)
      - MARKET create_order
      - SL create_algo_order (2 retry, first success)
      - TP create_algo_order (2 retry, first success)
      - Return dict with sl_order_id, tp_order_id
    """
    tp = make_trade_params()

    result = await executor.send_order(tp)

    # Ana emir gönderildi mi?
    assert result is not None
    assert isinstance(result, dict)
    assert result.get("entry_price") == 50200.0
    assert result.get("partial") is False

    # SL/TP order ID'leri atandı mı?
    assert result.get("sl_order_id") == "algo_sl_001"
    assert result.get("tp_order_id") == "algo_sl_001"  # aynı mock döndü

    # API çağrıları doğru sırada ve sayıda mı?
    # fetch_position: 1 (dup check) + ~20 (_wait_for_fill polling) = ~21
    assert mock_exchange.fetch_position.await_count >= 2  # en az dup check + fill check
    assert mock_exchange.create_order.await_count == 1  # MARKET entry
    assert mock_exchange.create_algo_order.await_count == 2  # SL + TP

    # create_order MARKET olarak mı çağrıldı?
    call_kwargs = mock_exchange.create_order.await_args.kwargs
    assert call_kwargs["order_type"] == "MARKET"
    assert call_kwargs["side"] == "BUY"
    assert call_kwargs["amount"] == 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: Duplicate Position Guard
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_duplicate_position(executor, mock_exchange):
    """fetch_position mevcut pozisyon döndü → emir atlanır."""
    mock_exchange.fetch_position = AsyncMock(  # noqa: SIM115
        return_value={"symbol": "BTCUSDT", "positionAmt": "0.01", "markPrice": "50100.0"}
    )

    result = await executor.send_order(make_trade_params())

    assert result is None
    # create_order hiç çağrılmamalı
    mock_exchange.create_order.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: Cooldown Guard
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_cooldown(executor, mock_exchange):
    """Cooldown süresi içinde ikinci emir engellenir."""
    tp = make_trade_params()

    # _last_order_time'ı future'a set et → cooldown aktif
    executor._last_order_time["BTCUSDT"] = float("inf")

    result = await executor.send_order(tp)
    assert result is None
    mock_exchange.create_order.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Missing Parameters Guard
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_missing_symbol(executor):
    """symbol eksik → None döner, emir gönderilmez."""
    tp = make_trade_params(symbol="")
    result = await executor.send_order(tp)
    assert result is None


@pytest.mark.asyncio
async def test_send_order_missing_direction(executor):
    """direction eksik → None döner."""
    tp = make_trade_params(direction="")
    result = await executor.send_order(tp)
    assert result is None


@pytest.mark.asyncio
async def test_send_order_missing_lot(executor):
    """lot eksik (0) → None döner."""
    tp = make_trade_params(lot=0)
    result = await executor.send_order(tp)
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: STOP_MARKET Entry
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_stop_market(executor, mock_exchange):
    """STOP_MARKET entry → protection_missing=True, SL/TP denenmez."""
    tp = make_trade_params(entry=50200.0)
    current_price = 50100.0

    result = await executor.send_order(
        tp,
        entry_order_type="STOP_MARKET",
        current_price=current_price,
        stop_offset_pct=0.0005,
    )

    assert result is not None
    assert result.get("protection_missing") is True
    assert result.get("entry_type") == "STOP_MARKET"
    assert result.get("partial") is False

    # STOP_MARKET create_order çağrıldı mı?
    mock_exchange.create_order.assert_awaited_once()
    call_kwargs = mock_exchange.create_order.await_args.kwargs
    assert call_kwargs["order_type"] == "STOP_MARKET"
    assert call_kwargs["side"] == "BUY"
    # LONG: trigger >= current_price * (1 + offset)
    expected_trigger = current_price * (1.0 + 0.0005)
    assert call_kwargs["stop_price"] >= expected_trigger * 0.9999  # precision tolerance

    # SL/TP create_algo_order çağrılmamalı
    mock_exchange.create_algo_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_order_stop_market_short(executor, mock_exchange):
    """STOP_MARKET short direction → trigger=min, side=SELL."""
    tp = make_trade_params(direction="short", entry=49800.0)
    current_price = 49900.0

    result = await executor.send_order(
        tp,
        entry_order_type="STOP_MARKET",
        current_price=current_price,
        stop_offset_pct=0.0005,
    )

    assert result is not None
    assert result.get("protection_missing") is True
    assert result.get("entry_type") == "STOP_MARKET"
    assert result.get("side") == "short"

    mock_exchange.create_order.assert_awaited_once()
    call_kwargs = mock_exchange.create_order.await_args.kwargs
    assert call_kwargs["order_type"] == "STOP_MARKET"
    assert call_kwargs["side"] == "SELL"
    # SHORT: trigger = min(entry, current_price * (1 - 0.0005))
    # entry=49800 < 49900*(1-0.0005)=49875.05 → trigger=49800
    assert call_kwargs["stop_price"] == pytest.approx(49800.0, rel=1e-4)
    mock_exchange.create_algo_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_order_stop_market_zero_offset(executor, mock_exchange):
    """STOP_MARKET stop_offset_pct=0.0 → trigger trade_params.entry."""
    tp = make_trade_params(entry=50200.0)
    current_price = 50100.0

    result = await executor.send_order(
        tp,
        entry_order_type="STOP_MARKET",
        current_price=current_price,
        stop_offset_pct=0.0,
    )

    assert result is not None

    mock_exchange.create_order.assert_awaited_once()
    call_kwargs = mock_exchange.create_order.await_args.kwargs
    assert call_kwargs["order_type"] == "STOP_MARKET"
    # offset=0 → trigger = max(entry, current_price) = max(50200, 50100) = 50200
    assert call_kwargs["stop_price"] == pytest.approx(50200.0, rel=1e-4)


@pytest.mark.asyncio
async def test_send_order_stop_market_partial(executor, mock_exchange):
    """STOP_MARKET partial=True → partial flag korunur."""
    tp = make_trade_params(entry=50200.0)

    result = await executor.send_order(
        tp,
        entry_order_type="STOP_MARKET",
        current_price=50100.0,
        stop_offset_pct=0.0005,
        partial=True,
    )

    assert result is not None
    assert result.get("partial") is True
    assert result.get("protection_missing") is True


@pytest.mark.asyncio
async def test_send_order_stop_market_error(executor, mock_exchange):
    """STOP_MARKET API error → None döner, SL/TP denenmez."""
    mock_exchange.create_order = AsyncMock(side_effect=RuntimeError("API error"))
    tp = make_trade_params(entry=50200.0)

    result = await executor.send_order(
        tp,
        entry_order_type="STOP_MARKET",
        current_price=50100.0,
        stop_offset_pct=0.0005,
    )

    assert result is None
    mock_exchange.create_algo_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_order_stop_market_no_current_price(executor, mock_exchange):
    """STOP_MARKET current_price=None → trigger trade_params.entry direkt."""
    tp = make_trade_params(entry=50200.0)

    result = await executor.send_order(
        tp,
        entry_order_type="STOP_MARKET",
        current_price=None,
        stop_offset_pct=0.0005,
    )

    assert result is not None
    assert result.get("entry_type") == "STOP_MARKET"

    mock_exchange.create_order.assert_awaited_once()
    call_kwargs = mock_exchange.create_order.await_args.kwargs
    # current_price=None olduğu için trigger = trade_params.entry = 50200
    assert call_kwargs["stop_price"] == pytest.approx(50200.0, rel=1e-4)


@pytest.mark.asyncio
async def test_send_order_stop_market_with_sl_tp_params(executor, mock_exchange):
    """STOP_MARKET ile SL/TP parametreleri verilse bile protection_missing=True.

    STOP_MARKET path early return yapar, SL/TP gönderilmez.
    """
    tp = make_trade_params(entry=50200.0)

    result = await executor.send_order(
        tp,
        stop_loss=49000.0,
        take_profit=52000.0,
        entry_order_type="STOP_MARKET",
        current_price=50100.0,
        stop_offset_pct=0.0005,
    )

    assert result is not None
    assert result.get("protection_missing") is True
    mock_exchange.create_algo_order.assert_not_awaited()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: SL Placement Fail → Emergency Close
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_sl_fail_emergency_close(executor, mock_exchange):
    """SL 2 kere fail → RuntimeError outer try/except'te yakalanır → None döner.

    Not: RuntimeError inner try'de fırlatılır ama send_order'ın
    outer except bloğu (satır ~700) tarafından yakalanır → None döner.
    Bu, mevcut kodun karakterizasyon testidir (refactor kararı değil).
    """
    mock_exchange.create_algo_order = AsyncMock(side_effect=RuntimeError("SL timeout"))  # noqa: SIM115
    mock_exchange.close_position = AsyncMock(return_value=True)  # noqa: SIM115

    result = await executor.send_order(make_trade_params())

    # Outer try/except yakalar → None döner
    assert result is None

    # close_position emergency olarak çağrıldı mı?
    mock_exchange.close_position.assert_awaited_once()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: TP Placement Fail → Continue (No Crash)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_order_tp_fail_no_crash(executor, mock_exchange):
    """TP fail → exception fırlatılmaz, pozisyon SL korumalı devam eder."""
    # İlk create_algo_order (SL) başarılı, sonraki (TP) fail
    call_count = 0

    async def algo_side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:  # SL
            return {
                "symbol": "BTCUSDT",
                "algoId": "algo_sl_001",
                "clientAlgoId": "choc_test_1234_sl_0",
                "stopPrice": "49500.0",
                "status": "NEW",
            }
        raise RuntimeError("TP timeout")  # TP fail

    mock_exchange.create_algo_order = AsyncMock(side_effect=algo_side_effect)  # noqa: SIM115

    result = await executor.send_order(make_trade_params())

    assert result is not None
    assert result.get("sl_order_id") == "algo_sl_001"  # SL başarılı
    assert result.get("tp_order_id") is None or result.get("tp_order_id") == ""  # TP boş

    # Emergency close çağrılmamalı (sadece SL fail'de çağrılır)
    mock_exchange.close_position.assert_not_awaited()
