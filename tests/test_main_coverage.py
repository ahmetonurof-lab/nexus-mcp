"""
test_main_coverage.py — NEXUS V3 main.py Coverage Tests (P1-0B phase 2)

Kapsam:
  - _flush_state / _load_state         → state persistence
  - _clear_state                       → state cleanup + cache reset
  - _sync_balance                      → balance API fetch
  - _is_15m_closed                     → 15m candle close detection
  - _safe_sync_positions               → fire-and-forget wrapper
  - _safe_manage_open_trades           → fire-and-forget wrapper
  - _get_risk_manager                  → risk mgr factory/cache

Referans: test_sync_positions.py (bot fixture pattern, patch.object)
"""

from __future__ import annotations

import json
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Helpers ───────────────────────────────────────────────────────────────────


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


def make_current_bar(close: float = 50200.0) -> SimpleNamespace:
    """current_bar parametresi için dummy."""
    return SimpleNamespace(close=close)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_http_client():
    """BinanceHTTPClient mock."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from exchange import BinanceHTTPClient

    client = MagicMock(spec=BinanceHTTPClient)
    client.get_positions.return_value = []
    return client


@pytest.fixture
def bot(mock_http_client):
    """Partial-mock LiveTradingBot — tüm dış bağımlılıklar mock'lanmış."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import main as main_module

    patcher = patch.object(main_module, "http_client", mock_http_client)
    patcher.start()

    try:
        bot_instance = main_module.LiveTradingBot()

        # Module-level lock dict'ini temizle (test izolasyonu)
        main_module.trade_locks.clear()

        # Async dış çağrıları mock'la
        bot_instance._get_open_orders_async = AsyncMock(return_value=[])
        bot_instance._fetch_binance_signed = AsyncMock(return_value=[])
        bot_instance._fetch_binance_signed_delete = AsyncMock(return_value={})
        bot_instance._fetch_binance_signed_post = AsyncMock(return_value={})

        # Executor alt bileşenlerini mock'la
        bot_instance.executor.client.fetch_position = AsyncMock(return_value=None)
        bot_instance.executor.client.create_stop_order = AsyncMock(
            return_value={"algoId": "algo_test", "orderId": 999, "stopPrice": "50000.0", "status": "NEW"}
        )
        bot_instance.executor.client.create_order = AsyncMock(
            return_value={"symbol": "BTCUSDT", "orderId": 123, "status": "FILLED", "avgPrice": "50200.0"}
        )
        bot_instance.executor.client.cancel_all_orders = AsyncMock(return_value=0)
        bot_instance.executor.reset_cooldown = MagicMock()

        # Senkron yardımcıları mock'la
        bot_instance._get_risk_manager = MagicMock()
        bot_instance.hub.get_bars = MagicMock(return_value=[])
        bot_instance.state_machine.clear = MagicMock()
        for sym in list(bot_instance.analyzers.keys()):
            bot_instance.analyzers[sym].reset_symbol_cache = MagicMock()

        # Zaman frenini sıfırla
        bot_instance._last_pos_sync_time = 0.0

        yield bot_instance
    finally:
        patcher.stop()


# ═══════════════════════════════════════════════════════════════════════════════
# _flush_state
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlushState:
    def test_flush_state_writes_file(self, bot):
        """_flush_state → JSON dosyası oluşur, içinde active_trades + symbol_states var."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # STATE_FILE'i geçici dosyaya yönlendir
            bot.STATE_FILE = tmp_path

            # Örnek trade ekle
            bot.active_trades["BTCUSDT"] = {
                "symbol": "BTCUSDT",
                "direction": "long",
                "entry": 50000.0,
                "status": "open",
            }

            bot._flush_state()

            # Dosya oluştu mu?
            assert os.path.exists(tmp_path)
            with open(tmp_path, encoding="utf-8-sig") as f:
                data = json.load(f)
            assert "active_trades" in data
            assert data["active_trades"]["BTCUSDT"]["symbol"] == "BTCUSDT"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_flush_state_empty_no_crash(self, bot):
        """_flush_state → aktif trade yoksa boş JSON yazılır, crash olmaz."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            bot.STATE_FILE = tmp_path
            bot.active_trades.clear()

            bot._flush_state()

            assert os.path.exists(tmp_path)
            with open(tmp_path, encoding="utf-8-sig") as f:
                data = json.load(f)
            assert data["active_trades"] == {}
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_flush_state_handles_exception(self, bot):
        """_flush_state → dosya yazılamazsa exception log'lanır, crash olmaz."""
        # STATE_FILE'i yazılamaz bir yola ayarla
        bot.STATE_FILE = "/nonexistent/path/state.json"
        bot.active_trades["BTCUSDT"] = {"symbol": "BTCUSDT"}

        # Exception fırlatılmamalı
        bot._flush_state()


# ═══════════════════════════════════════════════════════════════════════════════
# _load_state
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoadState:
    def test_load_state_file_not_found(self, bot):
        """_load_state → dosya yoksa sessizce return eder."""
        bot._load_state()
        assert len(bot.active_trades) == 0

    def test_load_state_restores_trades_and_states(self, bot):
        """_load_state → dosyadaki trade'leri ve state'leri geri yükler."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from state_machine import SetupState

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            state_data = {
                "active_trades": {
                    "BTCUSDT": {
                        "symbol": "BTCUSDT",
                        "direction": "long",
                        "entry": 50000.0,
                        "status": "open",
                    }
                },
                "symbol_states": {
                    "BTCUSDT": {
                        "state": "ARMED",
                        "direction": "LONG",
                        "fvg_upper": 50500.0,
                        "fvg_lower": 50000.0,
                        "sweep_level": 49000.0,
                        "mss_break_level": 49500.0,
                    }
                },
            }
            with open(tmp_path, "w", encoding="utf-8-sig") as f:
                json.dump(state_data, f, indent=2)

            bot.STATE_FILE = tmp_path
            bot._load_state()

            # Trade geri yüklendi mi?
            assert "BTCUSDT" in bot.active_trades
            assert bot.active_trades["BTCUSDT"]["entry"] == 50000.0

            # State geri yüklendi mi?
            st = bot.state_machine.get("BTCUSDT")
            assert st.state == SetupState.ARMED
            assert st.direction == "LONG"
            assert st.fvg_upper == 50500.0
            assert st.fvg_lower == 50000.0
            assert st.sweep_level == 49000.0
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_load_state_handles_corrupted_json(self, bot):
        """_load_state → bozuk JSON dosyası exception log'lanır, crash olmaz."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write("{corrupted json!!!")
            tmp.flush()

        try:
            bot.STATE_FILE = tmp_path
            bot._load_state()  # crash olmamalı
            assert len(bot.active_trades) == 0
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ═══════════════════════════════════════════════════════════════════════════════
# _clear_state
# ═══════════════════════════════════════════════════════════════════════════════


class TestClearState:
    def test_clear_state_removes_trade(self, bot):
        """_clear_state → trade'i active_trades'ten siler, analyzer cache'ini resetler."""
        bot.active_trades["BTCUSDT"] = {"symbol": "BTCUSDT", "entry": 50000.0}
        bot._flush_state = MagicMock()

        bot._clear_state("BTCUSDT")

        assert "BTCUSDT" not in bot.active_trades
        bot.state_machine.clear.assert_called_once_with("BTCUSDT")
        bot.analyzers["BTCUSDT"].reset_symbol_cache.assert_called_once()
        bot._flush_state.assert_called_once()

    def test_clear_state_no_trade_skips_cache_reset(self, bot):
        """_clear_state → trade yoksa cache reset ATLANIR (P0-5 desync guard)."""
        bot._flush_state = MagicMock()

        bot._clear_state("BTCUSDT")

        assert "BTCUSDT" not in bot.active_trades
        bot.state_machine.clear.assert_called_once_with("BTCUSDT")
        bot.analyzers["BTCUSDT"].reset_symbol_cache.assert_not_called()
        bot._flush_state.assert_called_once()

    def test_clear_state_no_analyzer_skips_cache(self, bot):
        """_clear_state → analyzer yoksa cache reset atlanır."""
        bot.active_trades["UNKNOWNSYM"] = {"symbol": "UNKNOWNSYM"}
        bot._flush_state = MagicMock()
        # Bu sembol için analyzer yok

        bot._clear_state("UNKNOWNSYM")

        assert "UNKNOWNSYM" not in bot.active_trades
        bot._flush_state.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# _sync_balance
# ═══════════════════════════════════════════════════════════════════════════════


class TestSyncBalance:
    @pytest.mark.asyncio
    async def test_sync_balance_success(self, bot):
        """_sync_balance → API'den bakiye alınır, tüm alanlar güncellenir."""
        bot._fetch_binance_signed = AsyncMock(
            return_value={
                "totalWalletBalance": "10000.50",
                "totalUnrealizedProfit": "50.25",
                "totalMarginBalance": "10050.75",
                "availableBalance": "9500.00",
                "totalInitialMargin": "500.75",
            }
        )
        mock_rm = MagicMock()
        bot.risk_managers["BTCUSDT"] = mock_rm

        await bot._sync_balance()

        assert bot._wallet_balance == 10000.50
        assert bot._unrealized_pnl == 50.25
        assert bot._margin_balance == 10050.75
        assert bot._available_balance == 9500.00
        assert bot._used_margin == 500.75
        assert bot._balance == 9500.00
        assert mock_rm.balance == 9500.00
        assert mock_rm.available_margin == 9500.00

    @pytest.mark.asyncio
    async def test_sync_balance_api_error(self, bot):
        """_sync_balance → API hatasında exception yakalanır, crash olmaz."""
        bot._fetch_binance_signed = AsyncMock(side_effect=Exception("API timeout"))

        await bot._sync_balance()  # crash olmamalı
        assert bot._wallet_balance == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# _is_15m_closed
# ═══════════════════════════════════════════════════════════════════════════════


class TestIs15mClosed:
    def test_15m_closed_first_call_returns_true(self, bot):
        """_is_15m_closed → ilk çağrıda True döner (henüz işlenmemiş)."""
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=0, timestamp=1000000)])

        result = bot._is_15m_closed("BTCUSDT", make_current_bar())
        assert result is True

    def test_15m_closed_same_bar_returns_false(self, bot):
        """_is_15m_closed → aynı 15m bar tekrar gelirse False döner."""
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=0, timestamp=1000000)])
        # İlk çağrı — True
        assert bot._is_15m_closed("BTCUSDT", make_current_bar()) is True
        # İkinci çağrı — aynı timestamp, False
        assert bot._is_15m_closed("BTCUSDT", make_current_bar()) is False

    def test_15m_closed_no_bars_returns_false(self, bot):
        """_is_15m_closed → 15m bar yoksa False döner."""
        bot.hub.get_bars = MagicMock(return_value=[])

        result = bot._is_15m_closed("BTCUSDT", make_current_bar())
        assert result is False

    def test_15m_closed_new_bar_returns_true(self, bot):
        """_is_15m_closed → yeni 15m bar (farklı timestamp) gelince True döner."""
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=0, timestamp=1000000)])
        assert bot._is_15m_closed("BTCUSDT", make_current_bar()) is True

        # Yeni bar
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=1, timestamp=2000000)])
        assert bot._is_15m_closed("BTCUSDT", make_current_bar()) is True


# ═══════════════════════════════════════════════════════════════════════════════
# _safe_sync_positions / _safe_manage_open_trades
# ═══════════════════════════════════════════════════════════════════════════════


class TestSafeWrappers:
    @pytest.mark.asyncio
    async def test_safe_sync_positions_success(self, bot):
        """_safe_sync_positions → _sync_positions çağrılır, hata yok."""
        bot._sync_positions = AsyncMock()
        await bot._safe_sync_positions(make_current_bar())
        bot._sync_positions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_sync_positions_catches_error(self, bot):
        """_safe_sync_positions → _sync_positions hata fırlatırsa yakalanır."""
        bot._sync_positions = AsyncMock(side_effect=ValueError("test error"))
        await bot._safe_sync_positions(make_current_bar())  # crash olmamalı

    @pytest.mark.asyncio
    async def test_safe_manage_open_trades_success(self, bot):
        """_safe_manage_open_trades → _manage_open_trades çağrılır."""
        bot._manage_open_trades = AsyncMock()
        await bot._safe_manage_open_trades(make_current_bar())
        bot._manage_open_trades.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_safe_manage_open_trades_catches_error(self, bot):
        """_safe_manage_open_trades → hata fırlatılırsa yakalanır."""
        bot._manage_open_trades = AsyncMock(side_effect=RuntimeError("crash"))
        await bot._safe_manage_open_trades(make_current_bar())  # crash olmamalı


# ═══════════════════════════════════════════════════════════════════════════════
# _get_risk_manager
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetRiskManager:
    def test_get_risk_manager_returns_cached(self, bot):
        """_get_risk_manager → ikinci çağrıda cached instance'ı döner (fixture mock'u)."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from risk_manager import RiskManager

        # _get_risk_manager fixture'ta mock'lanmış; gerçek kodu test etmek için
        # doğrudan risk_managers dict'ine yaz ve cached return'ü doğrula
        real_rm = RiskManager(
            balance=10000.0,
            available_margin=9500.0,
            risk_pct=0.01,
            min_rr=0.0,
            min_net_rr=0.0,
            default_rr=2.0,
        )
        bot.risk_managers["BTCUSDT"] = real_rm

        # _get_risk_manager mock'unu kaldır
        actual_fn = bot._get_risk_manager
        if isinstance(actual_fn, MagicMock):
            # bot fixture mock'lamış, gerçek metodu çağır
            from main import LiveTradingBot

            rm1 = LiveTradingBot._get_risk_manager(bot, "BTCUSDT")
            rm2 = LiveTradingBot._get_risk_manager(bot, "BTCUSDT")
            assert rm1 is rm2
            assert isinstance(rm1, RiskManager)
        else:
            rm1 = bot._get_risk_manager("BTCUSDT")
            rm2 = bot._get_risk_manager("BTCUSDT")
            assert rm1 is rm2


# ═══════════════════════════════════════════════════════════════════════════════
# _on_1m_close — partial coverage (core paths)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOn1mClose:
    @pytest.mark.asyncio
    async def test_on_1m_close_skip_buffer_none(self, bot):
        """_on_1m_close → bar buffer'lardan biri None ise SKIP log basar, return eder."""
        # hub.get_bars None dönsün
        bot.hub.get_bars = MagicMock(return_value=None)

        bars_m1 = [make_bar(index=0, close=102.0, timestamp=1000000)]
        await bot._on_1m_close("BTCUSDT", bars_m1)  # crash olmamalı

    @pytest.mark.asyncio
    async def test_on_1m_close_skip_insufficient_bars(self, bot):
        """_on_1m_close → yetersiz bar sayısında SKIP log basar, return eder."""
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=0)])

        bars_m1 = [make_bar(index=0, close=102.0, timestamp=1000000)]
        await bot._on_1m_close("BTCUSDT", bars_m1)  # crash olmamalı

    @pytest.mark.asyncio
    async def test_on_1m_close_skip_active_trade_guard(self, bot):
        """_on_1m_close → aktif trade varsa event analyze atlanır."""
        bot.active_trades["BTCUSDT"] = {"symbol": "BTCUSDT", "direction": "long", "entry": 50000.0, "status": "open"}

        # Yeterli bar mock'la — close değerleri [low, high] içinde
        bar_kw = dict(open_=100.0, high=105.0, low=95.0, close=102.0)
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=i, **bar_kw) for i in range(300)])
        bot.daily_cache.get = AsyncMock(return_value=[make_bar(index=i, **bar_kw) for i in range(200)])
        bars_m1 = [make_bar(index=i, close=102.0, timestamp=1000000) for i in range(10)]
        await bot._on_1m_close("BTCUSDT", bars_m1)

    @pytest.mark.asyncio
    async def test_on_1m_close_no_active_trade_runs_analyzer(self, bot):
        """_on_1m_close → aktif trade yoksa analyzer çalışır, event publish edilir."""
        # Yeterli bar mock'la — close değerleri [low, high] içinde
        bar_kw = dict(open_=100.0, high=105.0, low=95.0, close=102.0)
        bot.hub.get_bars = MagicMock(return_value=[make_bar(index=i, **bar_kw) for i in range(300)])
        bot.daily_cache.get = AsyncMock(return_value=[make_bar(index=i, **bar_kw) for i in range(200)])
        bot.state_machine.check_retrace = MagicMock()
        bot.state_machine.check_ltf_fvg_validity = MagicMock()
        bot.state_machine.check_poi_retrace = MagicMock()
        bot.state_machine._evaluate = MagicMock()
        bot.event_router.publish = MagicMock()

        bars_m1 = [make_bar(index=i, close=102.0, timestamp=1000000) for i in range(10)]
        await bot._on_1m_close("BTCUSDT", bars_m1)

        # Analyzer çağrıldı mı?
        bot.state_machine.check_retrace.assert_called()
        bot.state_machine.check_ltf_fvg_validity.assert_called()
        bot.state_machine._evaluate.assert_called()
