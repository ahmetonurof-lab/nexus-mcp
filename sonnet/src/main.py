"""
main.py — NEXUS V4 Compatibility Shim
───────────────────────────────────────
Mevcut testler `import main` veya `from main import ...` yapıyor.
Bu shim, tüm public API'leri yeni modüllerden re-export eder.

Test'lerin hiçbiri değişmeden çalışmaya devam eder.

Gerçek kod: bot.py / bot_infra.py / bot_binance.py /
             bot_positions.py / bot_pipeline.py

NOT: Bu dosya SADECE backward compatibility için vardır.
     Yeni kod doğrudan bot_*.py modüllerini import etmeli.
"""

from __future__ import annotations

# ── Geriye dönük uyumluluk için eski metod adları ───────────────────
# Test'ler LiveTradingBot üzerinde şu private metod adlarını kullanıyor:
#   bot._fetch_binance_signed          → bot.rest.get
#   bot._fetch_binance_signed_post     → bot.rest.post
#   bot._fetch_binance_signed_delete   → bot.rest.delete
#   bot._get_open_orders_async         → bot.rest.get_open_orders
#   bot._cancel_order_by_id            → bot.rest.cancel_order
#   bot._sync_positions                → bot.positions.sync
#   bot._safe_sync_positions           → bot.positions.safe_sync
#   bot._manage_open_trades            → bot.positions.manage_open_trades
#   bot._safe_manage_open_trades       → bot.positions.safe_manage_open_trades
#   bot._repair_protection             → bot.positions.repair_protection
#   bot._create_protection             → bot.positions.create_protection
#   bot._update_sl_order               → bot.positions.update_sl_order
#   bot._startup_cleanup               → bot.positions.startup_cleanup
#   bot._load_existing_positions       → bot.positions.load_existing_positions
#   bot._sync_balance                  → bot.positions.sync_balance
#   bot._flush_state                   → bot.positions.flush_state
#   bot._load_state                    → bot.positions.load_state
#   bot._clear_state                   → bot.positions.clear_state
#   bot._get_risk_manager              → bot.positions.get_risk_manager
#   bot._prefill_buffers               → bot.positions.prefill_buffers
#   bot._on_1m_close                   → bot.pipeline.on_1m_close
#   bot._is_15m_closed                 → bot.pipeline._is_15m_closed
#
# Bu proxy'ler test fixture'ındaki `bot` instance'ına eklenir.
# LiveTradingBot.__init_subclass__ yerine monkey-patch kullanıyoruz
# çünkü fixture zaten mock'ları override ediyor.
#
# Proxy'ler test fixture'ında patch.object ile mock'lanıyor olduğundan
# burada sadece isim eşlemesini tanımlıyoruz; gerçek çağrılar
# PositionManager / TradingPipeline'a gidiyor.
import functools

# ── bot.py (LiveTradingBot + globals) ───────────────────────────────
from bot import (
    LiveTradingBot,
    log,
)

# ── bot_infra ───────────────────────────────────────────────────────
from bot_infra import (
    _close_ohlc_writers,
)


def _add_compat_proxies(cls: type) -> type:
    """
    LiveTradingBot'a backward-compat async proxy metodlar ekle.
    Test fixture'ları bunları zaten mock'ladığı için sadece
    `cls` üzerinde `hasattr` kontrolü yapan testler için gereklidir.
    """

    # Async proxy factory
    def _make_async_proxy(attr_chain: str):
        async def _proxy(self, *args, **kwargs):
            obj = self
            for part in attr_chain.split("."):
                obj = getattr(obj, part)
            return await obj(*args, **kwargs)

        return _proxy

    def _make_sync_proxy(attr_chain: str):
        def _proxy(self, *args, **kwargs):
            obj = self
            for part in attr_chain.split("."):
                obj = getattr(obj, part)
            return obj(*args, **kwargs)

        return _proxy

    proxies_async = {
        "_fetch_binance_signed": "rest.get",
        "_fetch_binance_signed_post": "rest.post",
        "_fetch_binance_signed_delete": "rest.delete",
        "_get_open_orders_async": "rest.get_open_orders",
        "_cancel_order_by_id": "rest.cancel_order",
        "_sync_positions": "positions.sync",
        "_safe_sync_positions": "positions.safe_sync",
        "_manage_open_trades": "positions.manage_open_trades",
        "_safe_manage_open_trades": "positions.safe_manage_open_trades",
        "_repair_protection": "positions.repair_protection",
        "_create_protection": "positions.create_protection",
        "_update_sl_order": "positions.update_sl_order",
        "_startup_cleanup": "positions.startup_cleanup",
        "_load_existing_positions": "positions.load_existing_positions",
        "_sync_balance": "positions.sync_balance",
        "_prefill_buffers": "positions.prefill_buffers",
        "_on_1m_close": "pipeline.on_1m_close",
    }

    proxies_sync = {
        "_flush_state": "positions.flush_state",
        "_load_state": "positions.load_state",
        "_clear_state": "positions.clear_state",
        "_get_risk_manager": "positions.get_risk_manager",
        "_is_15m_closed": "pipeline._is_15m_closed",
    }

    for name, chain in proxies_async.items():
        if not hasattr(cls, name):
            setattr(cls, name, _make_async_proxy(chain))

    for name, chain in proxies_sync.items():
        if not hasattr(cls, name):
            setattr(cls, name, _make_sync_proxy(chain))

    # Static metodlar — testler LiveTradingBot üzerinden çağırıyor
    from bot_binance import BinanceRESTClient

    if not hasattr(cls, "_get_order_type"):
        cls._get_order_type = staticmethod(BinanceRESTClient.get_order_type)
    if not hasattr(cls, "_get_order_price"):
        cls._get_order_price = staticmethod(BinanceRESTClient.get_order_price)
    if not hasattr(cls, "_safe_order_timestamp"):
        cls._safe_order_timestamp = staticmethod(BinanceRESTClient.get_order_timestamp)

    # _last_protection_check — sync testleri doğrudan erişiyor
    original_init = cls.__init__

    @functools.wraps(original_init)
    def _patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Proxy: test'ler bot._last_protection_check'e erişiyor
        # Gerçek veri positions._last_protection_check'te yaşıyor
        # __getattr__ ile yönlendiriyoruz

    cls.__init__ = _patched_init

    original_getattr = getattr(cls, "__getattr__", None)

    def _compat_getattr(self, name: str):
        # Testlerin doğrudan eriştiği iç state'ler
        compat_map = {
            "_last_protection_check": lambda: self.positions._last_protection_check,
            "_breakeven_log": lambda: self.positions._breakeven_log,
            "_last_be_summary": lambda: self.positions._last_be_summary,
            "_last_pos_sync_time": lambda: self.positions._last_pos_sync_time,
            "_15m_close_cache": lambda: self.pipeline._15m_close_cache,
        }
        if name in compat_map:
            return compat_map[name]()
        if original_getattr:
            return original_getattr(self, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def _compat_setattr(self, name: str, value):
        compat_write = {
            "_last_protection_check": lambda v: setattr(
                self.positions, "_last_protection_check", v
            ),
            "_breakeven_log": lambda v: setattr(self.positions, "_breakeven_log", v),
            "_last_be_summary": lambda v: setattr(
                self.positions, "_last_be_summary", v
            ),
            "_last_pos_sync_time": lambda v: setattr(
                self.positions, "_last_pos_sync_time", v
            ),
        }
        if name in compat_write and hasattr(self, "positions"):
            compat_write[name](value)
        else:
            object.__setattr__(self, name, value)

    cls.__getattr__ = _compat_getattr
    cls.__setattr__ = _compat_setattr

    return cls


# Proxy'leri LiveTradingBot'a ekle
_add_compat_proxies(LiveTradingBot)

# ── Entry point ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio

    import performance

    performance.initialize()
    bot = LiveTradingBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        log.info("Kullanıcı tarafından durduruldu.")
        bot.hub.stop()
        _close_ohlc_writers()
