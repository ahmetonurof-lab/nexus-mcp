"""
test_p0_bugs.py — NEXUS V3 P0 Bug Characterization Tests

Kapsam:
  - P0-1: _update_sl_order dangling reference (old_id NameError)
  - P0-2: _on_1m_close bars_m1 double fetch (veri tutarsızlığı)
  - P0-3: _startup_cleanup invariant violation (4. guard eksik)
  - P0-4: _safe_manage_open_trades exception handler
  - P0-5: _clear_state → reset_symbol_cache desync

Yöntem: Her bug için önce characterization test → sonra minimal fix.
Referans: test_sync_positions.py (fixture yapısı, AsyncMock pattern)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Test Doubles ──────────────────────────────────────────────────────────────


def make_trade(
    symbol: str = "BTCUSDT",
    direction: str = "long",
    entry: float = 50000.0,
    sl: float = 49500.0,
    tp: float = 51000.0,
    lot: float = 0.01,
    status: str = "open",
    **kwargs,
) -> dict:
    """active_trades trade dict."""
    trade = {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "initial_sl": sl,
        "current_sl": sl,
        "tp": tp,
        "lot": lot,
        "status": status,
        "pnl": 0.0,
        "last_price": entry,
    }
    trade.update(kwargs)
    return trade


def make_current_bar(close: float = 50200.0) -> SimpleNamespace:
    """current_bar parametresi için dummy."""
    return SimpleNamespace(close=close)


# ── Bot Fixture ──────────────────────────────────────────────────────────────


@pytest.fixture
def bot():
    """Partial-mock LiveTradingBot — dış bağımlılıklar mock'lanmış."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import main as main_module
        from exchange import BinanceHTTPClient

    # http_client mock'u
    mock_http = MagicMock(spec=BinanceHTTPClient)
    mock_http.get_positions.return_value = []

    patcher = patch.object(main_module, "http_client", mock_http)
    patcher.start()

    try:
        bot_instance = main_module.LiveTradingBot()

        # Async dış çağrıları mock'la
        bot_instance._get_open_orders_async = AsyncMock(return_value=[])
        bot_instance._fetch_binance_signed = AsyncMock(return_value=[])
        bot_instance._fetch_binance_signed_post = AsyncMock(return_value={})
        bot_instance._fetch_binance_signed_delete = AsyncMock(return_value={})

        # Executor mock
        bot_instance.executor.get_position = AsyncMock(return_value={"symbol": "BTCUSDT", "contracts": 0.01})
        bot_instance.executor.client.fetch_position = AsyncMock(return_value={"symbol": "BTCUSDT", "contracts": 0.01})
        bot_instance.executor.client.create_stop_order = AsyncMock(
            return_value={"algoId": "algo_sl_new", "orderId": 999}
        )
        bot_instance.executor.client.cancel_all_orders = AsyncMock(return_value=0)
        bot_instance.executor.reset_cooldown = MagicMock()
        bot_instance.executor.close_position = AsyncMock(return_value=True)

        # State machine mock
        bot_instance.state_machine.clear = MagicMock()
        bot_instance.state_machine.get = MagicMock()
        bot_instance._flush_state = MagicMock()

        # Risk manager mock
        bot_instance._get_risk_manager = MagicMock()

        # Hub mock
        bot_instance.hub.get_bars = MagicMock(return_value=[])

        # Analyzer mock'ları — reset_symbol_cache sayacı
        for sym in list(bot_instance.analyzers.keys()):
            bot_instance.analyzers[sym].reset_symbol_cache = MagicMock()

        # Zaman frenini sıfırla
        bot_instance._last_pos_sync_time = 0.0

        yield bot_instance
    finally:
        patcher.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# P0-1: _update_sl_order — Dangling Reference (old_id NameError)
# ═══════════════════════════════════════════════════════════════════════════════


class TestP01UpdateSlOrderDanglingRef:
    """_update_sl_order: _get_open_orders_async exception → except'te old_id NameError."""

    @pytest.mark.asyncio
    async def test_network_error_does_not_cause_nameerror(self, bot):
        """_get_open_orders_async exception → except bloğu old_id NameError patlatmaz."""
        # _get_open_orders_async exception fırlatsın → old_sl=None kalır
        bot._get_open_orders_async = AsyncMock(side_effect=RuntimeError("API timeout"))
        bot.active_trades["BTCUSDT"] = make_trade()

        # NameError patlamamalı — init edilmemiş old_id referansı yok
        await bot._update_sl_order("BTCUSDT", bot.active_trades["BTCUSDT"], 49000.0)
        assert True  # reached without NameError

    @pytest.mark.asyncio
    async def test_fallback_creates_new_sl_when_old_sl_found(self, bot):
        """cancelReplace exception → fallback path çalışır, old_id NameError olmaz."""
        trade = make_trade()
        bot.active_trades["BTCUSDT"] = trade

        # İlk fetch başarılı, SL emri bulundu
        bot._get_open_orders_async = AsyncMock(
            return_value=[{"orderId": 1, "type": "STOP_MARKET", "stopPrice": "49500.0"}]
        )
        # cancelReplace exception fırlatsın
        bot._fetch_binance_signed_post = AsyncMock(side_effect=RuntimeError("cancelReplace failed"))
        # _cancel_order_by_id başarılı
        bot._cancel_order_by_id = AsyncMock(return_value=True)

        await bot._update_sl_order("BTCUSDT", trade, 49000.0)
        # Fallback path: cancel + create_stop_order çağrılmalı
        assert bot._cancel_order_by_id.called
        assert bot.executor.client.create_stop_order.called

    @pytest.mark.asyncio
    async def test_old_sl_none_does_not_crash_fallback(self, bot):
        """old_sl=None iken except'e düşülürse, old_id NameError olmaz — fallback atlanır."""
        trade = make_trade()
        bot.active_trades["BTCUSDT"] = trade

        # _get_open_orders_async exception fırlatsın (old_sl=None kalır)
        bot._get_open_orders_async = AsyncMock(side_effect=RuntimeError("API error"))
        # cancelReplace de exception (zaten çağrılmaz, ama olsun)
        bot._fetch_binance_signed_post = AsyncMock(side_effect=RuntimeError("never called"))

        # Bu çağrı NameError ile çökmemeli
        await bot._update_sl_order("BTCUSDT", trade, 49000.0)
        assert True


# ═══════════════════════════════════════════════════════════════════════════════
# P0-2: _on_1m_close — bars_m1 Double Fetch
# ═══════════════════════════════════════════════════════════════════════════════


class TestP02On1mCloseDoubleFetch:
    """_on_1m_close: bars_m1 parametresi kullanılır, ikinci fetch YAPILMAZ."""

    @pytest.mark.asyncio
    async def test_no_second_get_bars_call(self, bot):
        """_on_1m_close içinde self.hub.get_bars(symbol, '1m') sadece 1 kere çağrılır."""
        # Hub mock: tüm get_bars çağrıları kaydedilsin
        call_log = []

        def tracking_get_bars(symbol, tf):
            call_log.append((symbol, tf))
            # 1m için 6 bar döndür
            if tf == "1m":
                return [
                    SimpleNamespace(
                        timestamp=i * 60000,
                        close=50000.0 + i,
                        open=50000.0,
                        high=50100.0,
                        low=49900.0,
                        volume=100.0,
                        is_closed=True,
                    )
                    for i in range(6)
                ]
            return []

        bot.hub.get_bars = MagicMock(side_effect=tracking_get_bars)
        bot.daily_cache = AsyncMock()
        bot.daily_cache.get = AsyncMock(return_value=[])
        bot.analyzers["BTCUSDT"].analyze = MagicMock(return_value=[])
        bot.state_machine.get = MagicMock()
        state_mock = MagicMock()
        state_mock.state = None
        bot.state_machine.get.return_value = state_mock
        bot._is_15m_closed = MagicMock(return_value=False)
        bot._safe_manage_open_trades = AsyncMock()
        bot._safe_sync_positions = AsyncMock()

        bars_m1 = [
            SimpleNamespace(
                timestamp=i * 60000,
                close=50000.0 + i,
                open=50000.0,
                high=50100.0,
                low=49900.0,
                volume=100.0,
                is_closed=True,
            )
            for i in range(5)
        ]

        await bot._on_1m_close("BTCUSDT", bars_m1)

        # 1m get_bars çağrılarını say
        m1_calls = [(s, tf) for s, tf in call_log if tf == "1m"]
        assert len(m1_calls) <= 1, (
            f"get_bars(symbol, '1m') {len(m1_calls)} kere çağrıldı " f"(beklenen: ≤1). call_log={call_log}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# P0-3: _startup_cleanup — Invariant Violation (4. Guard)
# ═══════════════════════════════════════════════════════════════════════════════


class TestP03StartupCleanupGuard:
    """_startup_cleanup: 4 guard da doğru çalışır, emirler yanlışlıkla silinmez."""

    @pytest.mark.asyncio
    async def test_guard4_both_empty_skips_cleanup(self, bot):
        """4. guard: API'de pozisyon yok VE local state boş → cleanup atlanır."""
        # http_client.get_positions boş dönsün (no positions)
        bot._fetch_binance_signed = AsyncMock(side_effect=RuntimeError("Should not be called - cleanup skipped"))

        await bot._startup_cleanup()
        # _fetch_binance_signed (open orders fetch) çağrılmamalı
        assert True

    @pytest.mark.asyncio
    async def test_guard1_empty_positions_list_skips_cleanup(self, bot):
        """1. guard: positions_list boş (API hatası) → cleanup atlanır."""
        bot.active_trades["BTCUSDT"] = make_trade()

        # http_client.get_positions boş dizi dönsün
        bot._fetch_binance_signed = AsyncMock(side_effect=RuntimeError("Should not be called"))
        bot._fetch_binance_signed_delete = AsyncMock(side_effect=RuntimeError("Should not be called"))

        await bot._startup_cleanup()
        assert True

    @pytest.mark.asyncio
    async def test_guard3_local_empty_api_has_positions(self, bot):
        """3. guard: local boş ama API'de pozisyon var → cleanup atlanır."""
        # http_client.get_positions pozisyon dönsün
        from unittest.mock import patch

        import main as main_module

        with patch.object(
            main_module.http_client, "get_positions", return_value=[{"symbol": "BTCUSDT", "positionAmt": "0.01"}]
        ):
            # active_trades boş
            bot.active_trades.clear()
            bot._fetch_binance_signed = AsyncMock(side_effect=RuntimeError("Should not be called"))

            await bot._startup_cleanup()
            assert True


# ═══════════════════════════════════════════════════════════════════════════════
# P0-4: _safe_manage_open_trades — Exception Handler
# ═══════════════════════════════════════════════════════════════════════════════


class TestP04SafeManageOpenTrades:
    """_safe_manage_open_trades: _manage_open_trades hatalarını yakalar."""

    @pytest.mark.asyncio
    async def test_safe_wrapper_catches_exception(self, bot):
        """_safe_manage_open_trades, _manage_open_trades exception'ını yutar, crash olmaz."""
        bot._manage_open_trades = AsyncMock(side_effect=RuntimeError("crash"))

        # Exception patlamamalı
        await bot._safe_manage_open_trades(make_current_bar())
        assert True

    @pytest.mark.asyncio
    async def test_safe_wrapper_passes_through_success(self, bot):
        """_safe_manage_open_trades, _manage_open_trades başarılı çalışmasını geçirir."""
        bot._manage_open_trades = AsyncMock(return_value=None)

        await bot._safe_manage_open_trades(make_current_bar())
        assert bot._manage_open_trades.called

    @pytest.mark.asyncio
    async def test_on_1m_close_uses_safe_wrapper(self, bot):
        """_on_1m_close, _manage_open_trades yerine _safe_manage_open_trades çağırır."""
        bot._safe_manage_open_trades = AsyncMock()
        bot._safe_sync_positions = AsyncMock()
        bot.hub.get_bars = MagicMock(return_value=[])
        bot.daily_cache = AsyncMock()
        bot.daily_cache.get = AsyncMock(return_value=[])
        bot.state_machine.get = MagicMock()
        state_mock = MagicMock()
        state_mock.state = None
        bot.state_machine.get.return_value = state_mock
        bot._is_15m_closed = MagicMock(return_value=False)
        bot.monitor = MagicMock()
        bot.monitor.update_tick = MagicMock()

        bars = [SimpleNamespace(timestamp=0, close=50000.0)]

        await bot._on_1m_close("BTCUSDT", bars)

        assert bot._safe_manage_open_trades.called


# ═══════════════════════════════════════════════════════════════════════════════
# P0-5: _clear_state → reset_symbol_cache Desync
# ═══════════════════════════════════════════════════════════════════════════════


class TestP05ClearStateDesync:
    """_clear_state: reset_symbol_cache sadece trade gerçekten varsa çağrılır."""

    def test_clear_state_resets_cache_when_trade_exists(self, bot):
        """_clear_state: trade aktif → removed not None → reset_symbol_cache çağrılır."""
        bot.active_trades["BTCUSDT"] = make_trade()
        sym_mock = bot.analyzers.get("BTCUSDT")
        if sym_mock:
            sym_mock.reset_symbol_cache.reset_mock()

        bot._clear_state("BTCUSDT")

        if sym_mock:
            assert sym_mock.reset_symbol_cache.called, "reset_symbol_cache çağrılmalı (trade vardı)"
        assert "BTCUSDT" not in bot.active_trades

    def test_clear_state_skips_cache_when_no_trade(self, bot):
        """_clear_state: trade yok → removed None → reset_symbol_cache çağrılmaz."""
        bot.active_trades.clear()
        sym_mock = bot.analyzers.get("BTCUSDT")
        if sym_mock:
            sym_mock.reset_symbol_cache.reset_mock()

        bot._clear_state("BTCUSDT")

        if sym_mock:
            assert not sym_mock.reset_symbol_cache.called, "reset_symbol_cache çağrılmamalı (trade yoktu)"

    def test_clear_state_clears_state_machine_always(self, bot):
        """_clear_state: state_machine.clear her zaman çağrılır (trade olsa da olmasa da)."""
        bot.active_trades["BTCUSDT"] = make_trade()
        bot.state_machine.clear.reset_mock()

        bot._clear_state("BTCUSDT")

        assert bot.state_machine.clear.called
        bot.state_machine.clear.assert_called_with("BTCUSDT")

    def test_clear_state_flushes_state_always(self, bot):
        """_clear_state: _flush_state her zaman çağrılır."""
        bot.active_trades["BTCUSDT"] = make_trade()
        bot._flush_state.reset_mock()

        bot._clear_state("BTCUSDT")

        assert bot._flush_state.called


# ═══════════════════════════════════════════════════════════════════════════════
# P0-6: _update_sl_order — cancelReplace reduceOnly Parametre Tipi
# ═══════════════════════════════════════════════════════════════════════════════


class TestP06CancelReplaceReduceOnlyType:
    """_update_sl_order: cancelReplace POST body'sinde reduceOnly bool olmalı (string değil)."""

    @pytest.mark.asyncio
    async def test_cancelreplace_reduceonly_is_bool(self, bot):
        """cancelReplace çağrısında reduceOnly parametresi bool True olmalı."""
        trade = make_trade()
        bot.active_trades["BTCUSDT"] = trade

        # Standart SL emri bulunsun (algo değil)
        bot._get_open_orders_async = AsyncMock(
            return_value=[{"orderId": 1, "type": "STOP_MARKET", "stopPrice": "49500.0"}]
        )
        # Algo sipariş yok
        bot._fetch_binance_signed = AsyncMock(return_value=[])

        # cancelReplace başarılı
        bot._fetch_binance_signed_post = AsyncMock(return_value={"orderId": 999, "status": "NEW"})

        await bot._update_sl_order("BTCUSDT", trade, 49000.0)

        # _fetch_binance_signed_post çağrıldı mı?
        assert bot._fetch_binance_signed_post.called, "cancelReplace çağrılmadı"

        # POST body'sini yakala
        call_args = bot._fetch_binance_signed_post.call_args
        body = call_args[0][1]  # ikinci positional arg = body dict

        assert "reduceOnly" in body, "reduceOnly parametresi POST body'de olmalı"
        assert body["reduceOnly"] is True, (
            f"reduceOnly bool True olmalı, {type(body['reduceOnly']).__name__} geldi: " f"{body['reduceOnly']!r}"
        )
        assert not isinstance(body["reduceOnly"], str), f"reduceOnly string olmamalı! Değer: {body['reduceOnly']!r}"

    @pytest.mark.asyncio
    async def test_cancelreplace_body_has_required_fields(self, bot):
        """cancelReplace body'si tüm zorunlu alanları içermeli."""
        trade = make_trade()
        bot.active_trades["BTCUSDT"] = trade

        bot._get_open_orders_async = AsyncMock(
            return_value=[{"orderId": 1, "type": "STOP_MARKET", "stopPrice": "50000.0"}]
        )
        bot._fetch_binance_signed = AsyncMock(return_value=[])
        bot._fetch_binance_signed_post = AsyncMock(return_value={"orderId": 999, "status": "NEW"})

        await bot._update_sl_order("BTCUSDT", trade, 49000.0)

        call_args = bot._fetch_binance_signed_post.call_args
        body = call_args[0][1]

        required = [
            "symbol",
            "cancelReplaceMode",
            "cancelOrderId",
            "side",
            "type",
            "stopPrice",
            "quantity",
            "reduceOnly",
        ]
        for field in required:
            assert field in body, f"Zorunlu alan '{field}' POST body'de yok: {list(body.keys())}"

    @pytest.mark.asyncio
    async def test_cancelreplace_reduceonly_not_string_true(self, bot):
        """reduceOnly değeri 'true' (string) değil, True (bool) olmalı."""
        trade = make_trade()
        bot.active_trades["BTCUSDT"] = trade

        bot._get_open_orders_async = AsyncMock(
            return_value=[{"orderId": 1, "type": "STOP_MARKET", "stopPrice": "49500.0"}]
        )
        bot._fetch_binance_signed = AsyncMock(return_value=[])
        bot._fetch_binance_signed_post = AsyncMock(return_value={"orderId": 999})

        await bot._update_sl_order("BTCUSDT", trade, 49000.0)

        body = bot._fetch_binance_signed_post.call_args[0][1]
        # Kesinlikle string "true" olmamalı
        assert body["reduceOnly"] != "true", (
            "reduceOnly='true' (string) Binance API tarafından reddedilir! " "bool True olmalı."
        )
        assert body["reduceOnly"] != "True", "reduceOnly='True' (string) de geçersiz!"
        assert (
            body["reduceOnly"] is True
        ), f"reduceOnly={body['reduceOnly']!r} (type={type(body['reduceOnly']).__name__})"
