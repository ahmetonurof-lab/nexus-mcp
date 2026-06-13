"""
test_sync_positions.py — NEXUS V3 _sync_positions Characterization Tests

Kapsam (P1-0B):
  - _sync_positions characterization tests (refactor öncesi behavior capture)
  - Tüm testler mevcut kodu DEĞİŞTİRMEZ, sadece behavior'u test eder
  - Hedef: main.py coverage 0% → 40%

Referans: test_trader.py (AsyncMock, fixture pattern, characterization test yapısı)
"""

from __future__ import annotations

import time as time_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Test Doubles ──────────────────────────────────────────────────────────────


def make_position(
    symbol: str = "BTCUSDT",
    position_amt: float = 0.01,
    entry_price: float = 50000.0,
    mark_price: float = 50200.0,
    unrealized_pnl: float = 2.0,
) -> dict:
    """Binance get_positions() response benzeri dict.

    NOT: 'contracts' alanı ExchangeClient.fetch_position tarafından
    eklenir. Mock'ladığımızda doğrudan bu dict döndüğü için
    contracts'ı da ekliyoruz.
    """
    return {
        "symbol": symbol,
        "positionAmt": str(position_amt),
        "entryPrice": str(entry_price),
        "markPrice": str(mark_price),
        "unRealizedProfit": str(unrealized_pnl),
        "contracts": position_amt,
    }


def make_sl_order(
    order_id: int = 1,
    price: float = 49500.0,
    update_time: int = 1000,
    is_algo: bool = False,
) -> dict:
    """Stop-loss open order dict."""
    if is_algo:
        return {
            "symbol": "BTCUSDT",
            "algoId": f"algo_sl_{order_id}",
            "triggerPrice": str(price),
            "orderType": "STOP_MARKET",
            "reduceOnly": True,
            "status": "NEW",
            "updateTime": update_time,
        }
    return {
        "symbol": "BTCUSDT",
        "orderId": order_id,
        "stopPrice": str(price),
        "type": "STOP_MARKET",
        "reduceOnly": True,
        "status": "NEW",
        "updateTime": update_time,
    }


def make_tp_order(
    order_id: int = 2,
    price: float = 51000.0,
    update_time: int = 2000,
    is_algo: bool = False,
) -> dict:
    """Take-profit open order dict."""
    if is_algo:
        return {
            "symbol": "BTCUSDT",
            "algoId": f"algo_tp_{order_id}",
            "triggerPrice": str(price),
            "orderType": "TAKE_PROFIT_MARKET",
            "reduceOnly": True,
            "status": "NEW",
            "updateTime": update_time,
        }
    return {
        "symbol": "BTCUSDT",
        "orderId": order_id,
        "stopPrice": str(price),
        "type": "TAKE_PROFIT_MARKET",
        "reduceOnly": True,
        "status": "NEW",
        "updateTime": update_time,
    }


def make_trade(
    symbol: str = "BTCUSDT",
    direction: str = "long",
    entry: float = 50000.0,
    sl: float = 49500.0,
    tp: float = 51000.0,
    lot: float = 0.01,
    sl_order_id: str = "sl_001",
    tp_order_id: str = "tp_001",
    status: str = "open",
    pnl: float = 0.0,
    last_price: float = 50200.0,
    open_time: int | None = None,
    **kwargs,
) -> dict:
    """active_trades içinde kullanılan trade dict."""
    trade = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "initial_sl": sl,
        "current_sl": sl,
        "tp": tp,
        "sl_order_id": sl_order_id,
        "tp_order_id": tp_order_id,
        "lot": lot,
        "status": status,
        "pnl": pnl,
        "last_price": last_price,
    }
    if open_time is not None:
        trade["open_time"] = open_time
    trade.update(kwargs)
    return trade


def make_current_bar(close: float = 50200.0) -> SimpleNamespace:
    """current_bar parametresi için dummy."""
    return SimpleNamespace(close=close)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_http_client():
    """BinanceHTTPClient mock — get_positions() sync metodunu mock'la."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from exchange import BinanceHTTPClient

    client = MagicMock(spec=BinanceHTTPClient)
    client.get_positions.return_value = []
    return client


def _make_tiered_risk_mgr():
    """_get_risk_manager için gerçekçi RiskManager mock'u — _tier metodu ile."""
    rm = MagicMock()
    rm.balance = 10000.0
    rm.default_rr = 2.0
    rm._tier = MagicMock(
        return_value={
            "sl_buffer": 0.0015,
            "min_sl_pct": 0.0015,
            "max_sl_pct": 0.025,
            "max_rr": 4.0,
            "lot_decimals": 3,
        }
    )
    return rm


@pytest.fixture
def bot(mock_http_client):
    """Partial-mock LiveTradingBot — tüm dış bağımlılıklar mock'lanmış.

    LiveTradingBot constructor'ı çağırır ama içindeki tüm async/metot
    çağrılarını mock'layarak izole eder. http_client global'i patcher
    ile değiştirilir. Patch, test süresince aktif kalır (yield + start/stop).

    NOT: _repair_protection ve _create_protection mock'lanmaz —
    coverage için gerçek kodları çalıştırılır. Alt bağımlılıkları
    (fetch_position, create_stop_order) mock'lanır.
    """
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import main as main_module

    # Patch'i test süresince aktif tut
    patcher = patch.object(main_module, "http_client", mock_http_client)
    patcher.start()

    try:
        bot_instance = main_module.LiveTradingBot()

        # Async dış çağrıları mock'la (sadece ham HTTP çağrıları)
        bot_instance._get_open_orders_async = AsyncMock(return_value=[])
        bot_instance._fetch_binance_signed = AsyncMock(return_value=[])
        bot_instance._fetch_binance_signed_delete = AsyncMock(return_value={})

        # _cancel_order_by_id mock'lanmaz — coverage için gerçek kod akar.
        # _fetch_binance_signed_delete yukarıda mock'landı.

        # _repair_protection ve _create_protection mock'lanmaz —
        # coverage için gerçek kod akar. Alt bağımlılıkları mock'la:
        bot_instance.executor.client.fetch_position = AsyncMock(return_value=make_position())
        bot_instance.executor.client.create_stop_order = AsyncMock(
            return_value={
                "algoId": "algo_new_sl",
                "orderId": 999,
                "stopPrice": "49600.0",
                "status": "NEW",
            }
        )
        bot_instance.executor.close_position = AsyncMock(return_value=True)

        # _clear_state mock'lanmaz — coverage için gerçek kod akar.
        # Alt bağımlılıklarını mock'la:
        bot_instance.state_machine.clear = MagicMock()
        for sym in list(bot_instance.analyzers.keys()):
            bot_instance.analyzers[sym].reset_symbol_cache = MagicMock()
        bot_instance._flush_state = MagicMock()

        # Senkron yardımcıları mock'la
        bot_instance._get_risk_manager = MagicMock(return_value=_make_tiered_risk_mgr())
        bot_instance.hub.get_bars = MagicMock(return_value=[])

        # Executor alt bileşenlerini mock'la
        bot_instance.executor.client.cancel_all_orders = AsyncMock(return_value=0)
        bot_instance.executor.reset_cooldown = MagicMock()

        # Zaman frenini sıfırla (ilk çağrı her zaman geçsin)
        bot_instance._last_pos_sync_time = 0.0

        yield bot_instance
    finally:
        patcher.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 1: Zaman Freni — Time Guard
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_time_guard_early_return(bot, mock_http_client):
    """_last_pos_sync_time 5 sn içindeyse → erken return, get_positions çağrılmaz."""
    # Zaman frenini aktif et: _last_pos_sync_time'ı şimdiye setle
    bot._last_pos_sync_time = time_module.time()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    # get_positions hiç çağrılmamalı
    mock_http_client.get_positions.assert_not_called()

    # _get_open_orders_async da çağrılmamalı
    bot._get_open_orders_async.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 2: PM Guard — Boş Pozisyon Listesi
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pm_guard_empty_positions(bot, mock_http_client):
    """get_positions → [] döndüğünde erken return, active_trades'e dokunulmaz."""
    mock_http_client.get_positions.return_value = []

    # active_trades'e bir trade ekle
    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    # Trade korunmalı (silinmemeli)
    assert "BTCUSDT" in bot.active_trades
    assert bot.active_trades["BTCUSDT"]["status"] == "open"

    # _get_open_orders_async hiç çağrılmamalı
    bot._get_open_orders_async.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 3: Tam Koruma — Happy Path (1 SL + 1 TP)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_protection_happy_path(bot, mock_http_client):
    """1 SL + 1 TP mevcut → API ID'leri/fiyatları güncellenir, protection_missing kaldırılır."""
    pos = make_position(mark_price=50300.0, unrealized_pnl=3.0)
    mock_http_client.get_positions.return_value = [pos]

    sl_order = make_sl_order(order_id=1, price=49500.0, is_algo=True)
    tp_order = make_tp_order(order_id=2, price=51000.0, is_algo=True)
    bot._get_open_orders_async = AsyncMock(return_value=[sl_order])
    bot._fetch_binance_signed = AsyncMock(return_value=[tp_order])

    bot.active_trades["BTCUSDT"] = make_trade(
        sl_order_id="old_sl",
        tp_order_id="old_tp",
        current_sl=49000.0,
        tp=51500.0,
        protection_missing=True,
        status="recovered_unprotected",
    )

    bar = make_current_bar()
    await bot._sync_positions(bar)

    trade = bot.active_trades["BTCUSDT"]

    # API'den gelen PnL ve fiyat güncellenmiş olmalı
    assert trade["pnl"] == 3.0
    assert trade["last_price"] == 50300.0

    # API'den gelen ID'lerle güncellenmiş olmalı
    assert trade["sl_order_id"] == "algo_sl_1"
    assert trade["tp_order_id"] == "algo_tp_2"
    assert trade["current_sl"] == 49500.0
    assert trade["tp"] == 51000.0

    # protection_missing kaldırılmalı, status open
    assert trade.get("protection_missing") is False
    assert trade["status"] == "open"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 4: SORGUSUZ İNFAZ — Duplicate SL
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_infaz_duplicate_sl(bot, mock_http_client):
    """2 SL + 1 TP → fazla SL iptal edilmeli, 1 SL korunmalı, repair çağrılmamalı."""
    mock_http_client.get_positions.return_value = [make_position()]

    # 2 SL order — sl2 daha güncel (update_time=2000), korunmalı
    sl1 = make_sl_order(order_id=1, price=49500.0, update_time=1000)
    sl2 = make_sl_order(order_id=2, price=49300.0, update_time=2000)
    # 1 TP order
    tp1 = make_tp_order(order_id=3, price=51000.0)
    bot._get_open_orders_async = AsyncMock(return_value=[sl1, sl2])
    bot._fetch_binance_signed = AsyncMock(return_value=[tp1])

    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    trade = bot.active_trades["BTCUSDT"]

    # En güncel SL korunmalı (orderId=2 — update_time=2000)
    assert trade["sl_order_id"] == "2"
    assert trade["current_sl"] == 49300.0

    # Eski SL (orderId=1) iptal edilmeli — _cancel_order_by_id gerçek kod
    # _fetch_binance_signed_delete'e istek gittiğini doğrula
    bot._fetch_binance_signed_delete.assert_any_call("/fapi/v1/order", "symbol=BTCUSDT&orderId=1")

    # TP güncellenmez (n_tp==1 → TP block atlanır, sadece SL temizlenir)
    assert trade["tp_order_id"] == "tp_001"  # değişmez, orijinal değer korunur


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 5: SORGUSUZ İNFAZ — Duplicate SL + TP
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_infaz_duplicate_sl_tp(bot, mock_http_client):
    """3 SL + 2 TP → 2 SL + 1 TP iptal, 1 SL + 1 TP koru, repair çağrılmamalı."""
    mock_http_client.get_positions.return_value = [make_position()]

    # 3 SL: en güncel (id=3, time=1003) korunur
    sl_orders = [make_sl_order(order_id=i, price=49500.0 - i * 10, update_time=1000 + i) for i in range(1, 4)]
    # 2 TP: en güncel (id=12, time=5002) korunur
    tp_orders = [make_tp_order(order_id=10 + i, price=51000.0 + i * 10, update_time=5000 + i) for i in range(1, 3)]
    bot._get_open_orders_async = AsyncMock(return_value=sl_orders)
    bot._fetch_binance_signed = AsyncMock(return_value=tp_orders)

    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    trade = bot.active_trades["BTCUSDT"]

    # En güncel SL korunur (orderId=3)
    assert trade["sl_order_id"] == "3"
    assert trade["current_sl"] == 49470.0  # 49500 - 3*10

    # En güncel TP korunur (orderId=12)
    assert trade["tp_order_id"] == "12"
    assert trade["tp"] == 51020.0  # 51000 + 2*10

    # Fazla SL'ler iptal edilmeli (orderId 1 ve 2)
    bot._fetch_binance_signed_delete.assert_any_call("/fapi/v1/order", "symbol=BTCUSDT&orderId=1")
    bot._fetch_binance_signed_delete.assert_any_call("/fapi/v1/order", "symbol=BTCUSDT&orderId=2")

    # Fazla TP'ler iptal edilmeli (orderId 11)
    bot._fetch_binance_signed_delete.assert_any_call("/fapi/v1/order", "symbol=BTCUSDT&orderId=11")


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 6: SORGUSUZ İNFAZ — İnfaz Sonrası Onarım (2 SL + 0 TP)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_infaz_with_repair(bot, mock_http_client):
    """2 SL + 0 TP → 1 SL iptal, 1 SL koru, TP eksik → _repair_protection çağrılmalı."""
    mock_http_client.get_positions.return_value = [make_position()]

    sl1 = make_sl_order(order_id=1, price=49500.0, update_time=1000)
    sl2 = make_sl_order(order_id=2, price=49300.0, update_time=2000)
    bot._get_open_orders_async = AsyncMock(return_value=[sl1, sl2])
    bot._fetch_binance_signed = AsyncMock(return_value=[])  # TP yok

    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    trade = bot.active_trades["BTCUSDT"]

    # Eski SL iptal edilmeli (orderId=1)
    bot._fetch_binance_signed_delete.assert_any_call("/fapi/v1/order", "symbol=BTCUSDT&orderId=1")

    # En güncel SL korunur
    assert trade["sl_order_id"] == "2"
    assert trade["current_sl"] == 49300.0

    # TP eksik → _repair_protection çalıştı: create_stop_order çağrıldı (TP için)
    # repair, fetch_position + create_stop_order ile TP oluşturur
    assert bot.executor.client.create_stop_order.await_count >= 1

    # protection_repairing flag temizlenmeli
    assert trade.get("protection_repairing") is False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 7: Eksik Koruma — 0 SL + 0 TP → Cooldown Geçmiş → _create_protection
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_protection_create(bot, mock_http_client):
    """0 SL + 0 TP, cooldown expired → _create_protection çağrılmalı."""
    mock_http_client.get_positions.return_value = [make_position()]

    # _create_protection'un TP hesaplamasından düşük mark_price ayarla
    # (entry=50000 → tp_candidate≈50150, mark_price 50200'den düşük olmalı)
    bot.executor.client.fetch_position = AsyncMock(return_value=make_position(mark_price=50100.0))

    bot._get_open_orders_async = AsyncMock(return_value=[])
    bot._fetch_binance_signed = AsyncMock(return_value=[])
    # Cooldown yok → hemen çalışır
    bot._last_protection_check = {}

    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    # _create_protection çalıştı: trade güncellenmeli
    trade = bot.active_trades["BTCUSDT"]
    assert trade.get("protection_missing") is False
    assert trade["status"] == "open"
    assert "sl_order_id" in trade
    assert trade["sl_order_id"]  # SL order ID atanmış olmalı

    # create_stop_order en az 1 kere çağrılmış olmalı (SL için)
    assert bot.executor.client.create_stop_order.await_count >= 1

    # protection_repairing flag temizlenmeli
    assert trade.get("protection_repairing") is False

    # _last_protection_check güncellenmeli
    assert "BTCUSDT" in bot._last_protection_check


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 8: Eksik Koruma — Cooldown Aktif → Skip
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_protection_cooldown(bot, mock_http_client):
    """0 SL + 0 TP, cooldown aktif (300sn içinde) → skip, create/repair çağrılmaz."""
    mock_http_client.get_positions.return_value = [make_position()]

    bot._get_open_orders_async = AsyncMock(return_value=[])
    bot._fetch_binance_signed = AsyncMock(return_value=[])
    # Cooldown'u şimdiye set et → 300sn dolmamış
    bot._last_protection_check["BTCUSDT"] = time_module.time()

    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    # Hiçbir onarım çağrılmamalı — trade dict değişmemeli
    assert bot.active_trades["BTCUSDT"]["status"] == "open"
    assert bot.active_trades["BTCUSDT"].get("protection_missing") is None
    assert bot.active_trades["BTCUSDT"].get("protection_repairing") is None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 9: Eksik Koruma — 1 SL + 0 TP → Cooldown Geçmiş → _repair_protection
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_missing_protection_repair(bot, mock_http_client):
    """1 SL + 0 TP, cooldown expired → _repair_protection çağrılmalı."""
    mock_http_client.get_positions.return_value = [make_position()]

    sl1 = make_sl_order(order_id=1, price=49500.0)
    bot._get_open_orders_async = AsyncMock(return_value=[sl1])
    bot._fetch_binance_signed = AsyncMock(return_value=[])  # algo TP yok
    bot._last_protection_check = {}  # cooldown yok

    bot.active_trades["BTCUSDT"] = make_trade()

    bar = make_current_bar()
    await bot._sync_positions(bar)

    # _repair_protection çalıştı: create_stop_order en az 1 kere çağrıldı (TP için)
    assert bot.executor.client.create_stop_order.await_count >= 1

    # protection_repairing flag temizlenmeli
    assert bot.active_trades["BTCUSDT"].get("protection_repairing") is False


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 10: Kapanmış Pozisyon — TP ile Kapanma
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_closed_position_tp(bot, mock_http_client):
    """Symbol active_trades'te var ama exchange_positions'ta yok → TP ile kapanma.

    exit_price (51000) >= tp_price (51000) * 0.995 → close_reason = "TP"
    """
    # Sadece ETHUSDT pozisyonu döndür (BTCUSDT kapandı)
    mock_http_client.get_positions.return_value = [make_position(symbol="ETHUSDT")]

    # BTCUSDT active_trades'te var ama exchange_positions'ta yok
    bot.active_trades["BTCUSDT"] = make_trade(tp=51000.0, pnl=10.0, last_price=51000.0)
    bot.active_trades["ETHUSDT"] = make_trade(symbol="ETHUSDT")

    # hub.get_bars boş dönsün → fallback last_price kullanılır
    bot.hub.get_bars = MagicMock(return_value=[])

    # performance patch
    with patch("main.performance") as mock_perf:
        bar = make_current_bar()
        await bot._sync_positions(bar)

    # _clear_state çalıştı: active_trades'ten silinmiş olmalı
    assert "BTCUSDT" not in bot.active_trades
    bot.state_machine.clear.assert_called_once_with("BTCUSDT")
    bot.executor.reset_cooldown.assert_called_once_with("BTCUSDT")

    # cancel_all_orders çağrılmalı
    bot.executor.client.cancel_all_orders.assert_awaited_once_with("BTCUSDT")

    # Balance güncellenmeli (initial 0 + pnl 10.0)
    assert bot._balance == 10.0

    # performance.record_trade çağrılmalı
    mock_perf.record_trade.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 11: Kapanmış Pozisyon — SL ile Kapanma
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_closed_position_sl(bot, mock_http_client):
    """Symbol active_trades'te var ama exchange_positions'ta yok → SL ile kapanma.

    exit_price (50200) < tp_price (51000) * 0.995 → close_reason = "SL"
    """
    mock_http_client.get_positions.return_value = [make_position(symbol="ETHUSDT")]

    bot.active_trades["BTCUSDT"] = make_trade(tp=51000.0, pnl=-5.0, last_price=50200.0)
    bot.active_trades["ETHUSDT"] = make_trade(symbol="ETHUSDT")

    bot.hub.get_bars = MagicMock(return_value=[])

    with patch("main.performance") as mock_perf:
        bar = make_current_bar()
        await bot._sync_positions(bar)

    # _clear_state çalıştı: active_trades'ten silinmiş olmalı
    assert "BTCUSDT" not in bot.active_trades
    bot.state_machine.clear.assert_called_once_with("BTCUSDT")

    # Balance güncellenmeli (0 + (-5.0))
    assert bot._balance == -5.0

    mock_perf.record_trade.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 12: Kapalı Pozisyon — Short Direction TP
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_closed_position_short_tp(bot, mock_http_client):
    """Short pozisyon, exit_price <= tp_price * 1.005 → close_reason = "TP"."""
    mock_http_client.get_positions.return_value = [make_position(symbol="ETHUSDT")]

    # Short trade: tp=49000, exit_price=48900 (below tp*1.005=49245 → TP)
    bot.active_trades["BTCUSDT"] = make_trade(
        direction="short",
        entry=50000.0,
        sl=50500.0,
        tp=49000.0,
        pnl=10.0,
        last_price=48900.0,
    )
    bot.active_trades["ETHUSDT"] = make_trade(symbol="ETHUSDT")
    bot.hub.get_bars = MagicMock(return_value=[])

    with patch("main.performance") as mock_perf:
        bar = make_current_bar()
        await bot._sync_positions(bar)

    # _clear_state çalıştı: trade silindi, state_machine.clear çağrıldı
    assert "BTCUSDT" not in bot.active_trades
    bot.state_machine.clear.assert_called_with("BTCUSDT")
    mock_perf.record_trade.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 13: Kapalı Pozisyon — Short Direction SL
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_closed_position_short_sl(bot, mock_http_client):
    """Short pozisyon, exit_price > tp_price * 1.005 → close_reason = "SL"."""
    mock_http_client.get_positions.return_value = [make_position(symbol="ETHUSDT")]

    bot.active_trades["BTCUSDT"] = make_trade(
        direction="short",
        entry=50000.0,
        sl=50500.0,
        tp=49000.0,
        pnl=-8.0,
        last_price=49500.0,  # 49500 > 49000*1.005=49245 → SL
    )
    bot.active_trades["ETHUSDT"] = make_trade(symbol="ETHUSDT")
    bot.hub.get_bars = MagicMock(return_value=[])

    with patch("main.performance") as mock_perf:
        bar = make_current_bar()
        await bot._sync_positions(bar)

    # _clear_state çalıştı: trade silindi
    assert "BTCUSDT" not in bot.active_trades
    bot.state_machine.clear.assert_called_with("BTCUSDT")
    mock_perf.record_trade.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 14: Çoklu Sembol — Bazıları Tam Koruma, Bazıları Eksik
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_multi_symbol_mixed_protection(bot, mock_http_client):
    """İki sembol: BTC (tam koruma), ETH (eksik=0/0) → her biri doğru koldan geçmeli."""
    mock_http_client.get_positions.return_value = [
        make_position(symbol="BTCUSDT"),
        make_position(symbol="ETHUSDT", mark_price=2000.0, unrealized_pnl=0.5),
    ]

    # BTC: 1 SL + 1 TP algo order
    btc_sl = make_sl_order(order_id=1, price=49000.0, is_algo=True)
    btc_tp = make_tp_order(order_id=2, price=52000.0, is_algo=True)

    # ETH: hiç open order yok
    async def open_orders_side_effect(symbol):
        if symbol == "BTCUSDT":
            return [btc_sl]
        return []

    async def algo_side_effect(endpoint, params=""):
        if "BTCUSDT" in params:
            return [btc_tp]
        return []

    bot._get_open_orders_async = AsyncMock(side_effect=open_orders_side_effect)
    bot._fetch_binance_signed = AsyncMock(side_effect=algo_side_effect)

    # fetch_position'u sembole göre doğru pozisyonu döndürecek şekilde override et
    async def fetch_pos_side_effect(symbol):
        if symbol == "ETHUSDT":
            return make_position(symbol="ETHUSDT", mark_price=2000.0, unrealized_pnl=0.5)
        return make_position()

    bot.executor.client.fetch_position = AsyncMock(side_effect=fetch_pos_side_effect)

    bot._last_protection_check = {}  # cooldown yok

    bot.active_trades["BTCUSDT"] = make_trade(sl_order_id="old_sl", tp_order_id="old_tp")
    bot.active_trades["ETHUSDT"] = make_trade(
        symbol="ETHUSDT",
        entry=2000.0,
        sl=1950.0,
        tp=2100.0,
    )

    bar = make_current_bar()
    await bot._sync_positions(bar)

    # BTC: tam koruma güncellenmeli
    btc_trade = bot.active_trades["BTCUSDT"]
    assert btc_trade["sl_order_id"] == "algo_sl_1"
    assert btc_trade["tp_order_id"] == "algo_tp_2"

    # ETH: eksik (0 SL + 0 TP) → _create_protection çalıştı
    # create_stop_order SL+TP için en az 2 kere çağrılmış olmalı
    assert bot.executor.client.create_stop_order.await_count >= 2
    eth_trade = bot.active_trades["ETHUSDT"]
    assert eth_trade.get("protection_missing") is False
    assert eth_trade["status"] == "open"


# ═══════════════════════════════════════════════════════════════════════════════
# TEST 15: Algo Order Format — _get_order_type / _get_order_price
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrderHelpers:
    """_get_order_type ve _get_order_price statik metodlarının karakterizasyonu."""

    def test_get_order_type_standard(self):
        """Standard endpoint: 'type' alanı."""
        from main import LiveTradingBot

        assert LiveTradingBot._get_order_type({"type": "STOP_MARKET"}) == "STOP_MARKET"
        assert LiveTradingBot._get_order_type({"type": "TAKE_PROFIT_MARKET"}) == "TAKE_PROFIT_MARKET"

    def test_get_order_type_algo(self):
        """Algo endpoint: 'orderType' alanı."""
        from main import LiveTradingBot

        assert LiveTradingBot._get_order_type({"orderType": "STOP_MARKET"}) == "STOP_MARKET"
        assert LiveTradingBot._get_order_type({"orderType": "TAKE_PROFIT_MARKET"}) == "TAKE_PROFIT_MARKET"

    def test_get_order_type_fallback(self):
        """Her iki alan da yoksa → boş string."""
        from main import LiveTradingBot

        assert LiveTradingBot._get_order_type({}) == ""

    def test_get_order_price_algo(self):
        """Algo endpoint: 'triggerPrice' alanı."""
        from main import LiveTradingBot

        assert LiveTradingBot._get_order_price({"triggerPrice": "50000.0"}) == 50000.0

    def test_get_order_price_standard(self):
        """Standard endpoint: 'stopPrice' alanı."""
        from main import LiveTradingBot

        assert LiveTradingBot._get_order_price({"stopPrice": "49500.0"}) == 49500.0

    def test_get_order_price_fallback(self):
        """Her iki alan da yoksa → 0.0."""
        from main import LiveTradingBot

        assert LiveTradingBot._get_order_price({}) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Module-Level Helper Fonksiyon Testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestModuleHelpers:
    """main.py modül seviyesindeki yardımcı fonksiyonlar."""

    def test_fmt_bool_true(self):
        """True → ✅"""
        from main import fmt_bool

        assert fmt_bool(True) == "✅"

    def test_fmt_bool_false(self):
        """False → ❌"""
        from main import fmt_bool

        assert fmt_bool(False) == "❌"

    def test_round_price_positive_tick(self):
        """Geçerli tick ile yuvarlama."""
        from main import _round_price

        result = _round_price(50001.5, 1.0)
        assert result == 50002.0

        result = _round_price(50001.2, 0.1)
        assert result == 50001.2

    def test_round_price_zero_tick(self):
        """Tick 0 veya negatifse → değişiklik yok."""
        from main import _round_price

        assert _round_price(50000.123, 0) == 50000.123
        assert _round_price(50000.123, -1) == 50000.123

    def test_safe_order_timestamp_normal(self):
        """Normal updateTime."""
        from main import LiveTradingBot

        assert LiveTradingBot._safe_order_timestamp({"updateTime": 123456789}) == 123456789
        assert LiveTradingBot._safe_order_timestamp({"time": 987654321}) == 987654321

    def test_safe_order_timestamp_fallback(self):
        """updateTime ve time yoksa → 0."""
        from main import LiveTradingBot

        assert LiveTradingBot._safe_order_timestamp({}) == 0

    def test_safe_order_timestamp_invalid(self):
        """Geçersiz değerlerde 0 döner, exception patlamaz."""
        from main import LiveTradingBot

        assert LiveTradingBot._safe_order_timestamp({"updateTime": None}) == 0
        assert LiveTradingBot._safe_order_timestamp({"updateTime": "invalid"}) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# LiveTradingBot Internal Metod Testleri
# ═══════════════════════════════════════════════════════════════════════════════


class TestBotInternals:
    """_get_open_orders_async ve benzeri internal metodlar."""

    @pytest.mark.asyncio
    async def test_get_open_orders_async_success(self, bot):
        """_get_open_orders_async: _fetch_binance_signed'den list dönerse direkt return."""
        # Fixture'ın mock'unu kaldır → gerçek class metodu çalışsın
        if "_get_open_orders_async" in bot.__dict__:
            del bot.__dict__["_get_open_orders_async"]
        bot._fetch_binance_signed = AsyncMock(return_value=[{"symbol": "BTCUSDT", "orderId": 1}])

        result = await bot._get_open_orders_async("BTCUSDT")

        assert len(result) == 1
        assert result[0]["orderId"] == 1

    @pytest.mark.asyncio
    async def test_get_open_orders_async_not_list(self, bot):
        """_get_open_orders_async: response list değilse → []."""
        if "_get_open_orders_async" in bot.__dict__:
            del bot.__dict__["_get_open_orders_async"]
        bot._fetch_binance_signed = AsyncMock(return_value={"error": "msg"})

        result = await bot._get_open_orders_async("BTCUSDT")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_open_orders_async_exception(self, bot):
        """_get_open_orders_async: exception → []."""
        if "_get_open_orders_async" in bot.__dict__:
            del bot.__dict__["_get_open_orders_async"]
        bot._fetch_binance_signed = AsyncMock(side_effect=RuntimeError("API error"))

        result = await bot._get_open_orders_async("BTCUSDT")

        assert result == []

    # ── _clear_state ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_clear_state_removes_trade(self, bot):
        """_clear_state: active_trades'ten pop yapar, state_machine.clear çağrılır."""
        bot.active_trades["BTCUSDT"] = make_trade()
        bot.state_machine.clear = MagicMock()
        bot._flush_state = MagicMock()

        bot._clear_state("BTCUSDT")

        assert "BTCUSDT" not in bot.active_trades
        bot.state_machine.clear.assert_called_once_with("BTCUSDT")
        bot._flush_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_state_unknown_symbol(self, bot):
        """_clear_state: bilinmeyen sembol → hata yok."""
        bot.state_machine.clear = MagicMock()
        bot._flush_state = MagicMock()

        # Exception patlamamalı
        bot._clear_state("UNKNOWNSYMBOL")
        bot.state_machine.clear.assert_called_once_with("UNKNOWNSYMBOL")
        bot._flush_state.assert_called_once()

    # ── _cancel_order_by_id ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_cancel_order_by_id_standard(self, bot):
        """_cancel_order_by_id: normal order → /fapi/v1/order endpoint."""
        bot._fetch_binance_signed_delete = AsyncMock(return_value={})

        result = await bot._cancel_order_by_id(42, "BTCUSDT", reason="test", is_algo=False)

        assert result is True
        bot._fetch_binance_signed_delete.assert_awaited_once_with("/fapi/v1/order", "symbol=BTCUSDT&orderId=42")

    @pytest.mark.asyncio
    async def test_cancel_order_by_id_algo(self, bot):
        """_cancel_order_by_id: algo order → /fapi/v1/algoOrder endpoint."""
        bot._fetch_binance_signed_delete = AsyncMock(return_value={})

        result = await bot._cancel_order_by_id("algo_42", "BTCUSDT", reason="test", is_algo=True)

        assert result is True
        bot._fetch_binance_signed_delete.assert_awaited_once_with("/fapi/v1/algoOrder", "symbol=BTCUSDT&algoId=algo_42")

    # ── _cancel_order_by_id: Unknown order handling ──────────────────

    @pytest.mark.asyncio
    async def test_cancel_order_by_id_unknown_order(self, bot):
        """_cancel_order_by_id: "Unknown order" hatası → True döner (zaten silinmiş)."""
        bot._fetch_binance_signed_delete = AsyncMock(side_effect=Exception("Unknown order -2011"))

        result = await bot._cancel_order_by_id(42, "BTCUSDT", reason="test", is_algo=False)

        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_order_by_id_standard_fail_algo_fallback(self, bot):
        """_cancel_order_by_id: normal endpoint fail → algo fallback dener."""
        call_count = 0

        async def delete_side_effect(endpoint, params=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("HTTP 400: some error")
            return {}

        bot._fetch_binance_signed_delete = AsyncMock(side_effect=delete_side_effect)

        result = await bot._cancel_order_by_id(42, "BTCUSDT", reason="test", is_algo=False)

        assert result is True
        # 2 calls: 1st normal fail, 2nd algo fallback
        assert bot._fetch_binance_signed_delete.await_count == 2

    # ── _wait_for_position ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_wait_for_position_found(self, bot):
        """_wait_for_position: pozisyon bulunursa direkt döner."""
        bot.executor.get_position = AsyncMock(return_value={"symbol": "BTCUSDT", "contracts": 0.01})

        result = await bot._wait_for_position("BTCUSDT", timeout=0.5)

        assert result is not None
        assert result["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_wait_for_position_not_found(self, bot):
        """_wait_for_position: pozisyon bulunamazsa None döner."""
        bot.executor.get_position = AsyncMock(return_value=None)

        result = await bot._wait_for_position("BTCUSDT", timeout=0.3)

        assert result is None


class TestExportOhlc:
    """export_ohlc_15m / export_ohlc_1m fonksiyonları."""

    def make_bar(self, close=50000.0):
        from models import Bar

        return Bar(
            index=0,
            open=49900.0,
            high=50100.0,
            low=49800.0,
            close=close,
            volume=1000.0,
            is_closed=True,
            timestamp=1700000000000,
        )

    def test_export_ohlc_15m(self, tmp_path):
        """export_ohlc_15m: csv dosyası oluşturur."""
        import os

        import main as main_module

        bar = self.make_bar()
        symbol = "TESTBTC"

        main_module.export_ohlc_15m(bar, symbol)

        filepath = os.path.join("output/live_ohlc", f"{symbol}_15m.csv")
        assert os.path.exists(filepath)
        # Temizlik
        os.remove(filepath)

    def test_export_ohlc_1m(self, tmp_path):
        """export_ohlc_1m: csv dosyası oluşturur."""
        import os

        import main as main_module

        bar = self.make_bar()
        symbol = "TESTBTC"

        main_module.export_ohlc_1m(bar, symbol)

        filepath = os.path.join("output/live_ohlc", f"{symbol}_1m.csv")
        assert os.path.exists(filepath)
        # Temizlik
        os.remove(filepath)


class TestRateLimiter:
    """_RateLimiter modül seviyesi sınıfı."""

    @pytest.mark.asyncio
    async def test_rate_limiter_acquire(self):
        """_RateLimiter.acquire: ilk çağrı beklememeli."""
        from main import _RateLimiter

        rl = _RateLimiter(max_per_minute=6000)
        await rl.acquire()
        # İlk çağrı her zaman geçer
        assert True

    @pytest.mark.asyncio
    async def test_rate_limiter_consecutive(self):
        """_RateLimiter: peş peşe çağrılar interval kadar bekler."""
        from main import _RateLimiter

        rl = _RateLimiter(max_per_minute=6000)  # 60/6000 = 0.01sn interval
        import time as _time

        t0 = _time.time()
        await rl.acquire()
        await rl.acquire()
        elapsed = _time.time() - t0
        # En az interval kadar geçmiş olmalı
        assert elapsed >= 0.009  # 0.01sn - tolerance


class TestGetLock:
    """get_lock modül fonksiyonu."""

    def test_get_lock_creates_new(self):
        """get_lock: yeni sembol için Lock oluşturur."""
        from main import get_lock, trade_locks

        trade_locks.clear()
        lock = get_lock("TESTUSDT")
        assert lock is not None
        assert "TESTUSDT" in trade_locks

    def test_get_lock_reuses_existing(self):
        """get_lock: mevcut Lock'u yeniden kullanır."""
        from main import get_lock, trade_locks

        trade_locks.clear()
        lock1 = get_lock("TESTUSDT")
        lock2 = get_lock("TESTUSDT")
        assert lock1 is lock2


class TestDailyDataCache:
    """DailyDataCache sınıfı."""

    @pytest.mark.asyncio
    async def test_daily_cache_creation(self):
        """DailyDataCache: yeni instance."""
        from main import DailyDataCache

        cache = DailyDataCache()
        assert cache._cache == {}
        assert cache._last_update == {}

    @pytest.mark.asyncio
    async def test_daily_cache_get_cached(self):
        """DailyDataCache.get: cache'te varsa direkt döner."""
        from main import DailyDataCache
        from models import Bar

        cache = DailyDataCache()
        cache._cache["TEST"] = [
            Bar(index=0, open=100, high=101, low=99, close=100, volume=1000, is_closed=True, timestamp=0)
        ]
        cache._last_update["TEST"] = float("inf")  # asla expire olmasın

        result = await cache.get("TEST")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_daily_cache_fetch(self):
        """DailyDataCache.get: cache boşsa http_client'dan çeker."""
        import main as main_module
        from main import DailyDataCache

        cache = DailyDataCache()
        # http_client mock'la
        original_client = main_module.http_client
        main_module.http_client = MagicMock()
        main_module.http_client.get_klines.return_value = [
            [1700000000000, 100.0, 101.0, 99.0, 100.5, 1000.0, 1700000000000 + 86400000, "...", 100, "...", "..."]
        ]

        try:
            result = await cache.get("TEST")
            assert len(result) == 1
        finally:
            main_module.http_client = original_client


class TestGetTickSize:
    """_get_tick_size modül fonksiyonu."""

    def test_get_tick_size_cached(self):
        """Cache'te varsa direkt döner."""
        import main as main_module

        main_module._tick_size_cache["TESTUSDT"] = 0.01

        try:
            result = main_module._get_tick_size("TESTUSDT")
            assert result == 0.01
        finally:
            main_module._tick_size_cache.pop("TESTUSDT", None)

    def test_get_tick_size_fetch(self):
        """Cache'te yoksa http_client'dan çeker."""
        import main as main_module

        main_module._tick_size_cache.pop("TESTUSDT", None)
        original_client = main_module.http_client
        main_module.http_client = MagicMock()
        main_module.http_client.get_tick_size.return_value = 0.001

        try:
            result = main_module._get_tick_size("TESTUSDT")
            assert result == 0.001
            assert main_module._tick_size_cache.get("TESTUSDT") == 0.001
        finally:
            main_module.http_client = original_client
            main_module._tick_size_cache.pop("TESTUSDT", None)

    def test_get_tick_size_exception(self):
        """http_client hata verirse → varsayılan 0.0001 döner."""
        import main as main_module

        main_module._tick_size_cache.pop("TESTUSDT", None)
        original_client = main_module.http_client
        main_module.http_client = MagicMock()
        main_module.http_client.get_tick_size.side_effect = Exception("API error")

        try:
            result = main_module._get_tick_size("TESTUSDT")
            assert result == 0.0001
        finally:
            main_module.http_client = original_client
            main_module._tick_size_cache.pop("TESTUSDT", None)
