#!/usr/bin/env python3
"""
main_live.py Ã¢â‚¬â€ NEXUS V2 CanlÃ„Â± Trading Botu (Production-Ready)
"""

import asyncio
import csv
import hashlib
import hmac
import json
import logging
import logging.handlers
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

import config
import monitor
import performance
import state_logger
from analyzer import MarketAnalyzer
from dotenv import load_dotenv
from event_router import EventRouter
from exchange import BinanceHTTPClient
from models import Bar
from risk_manager import RiskManager
from state_machine import SetupState, StateMachine
from trader import ExchangeClient, LiveExecutor
from websocket import BinanceWSHub

# WEEKLY RANGE SPY removed (5m kaldirildi)

trade_locks: dict[str, asyncio.Lock] = {}


def get_lock(symbol: str) -> asyncio.Lock:
    if symbol not in trade_locks:
        trade_locks[symbol] = asyncio.Lock()
    return trade_locks[symbol]


# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
os.makedirs("output/trading", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s Ã¢â‚¬â€ %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            filename="output/trading/live_trading.log",
            when="midnight",
            backupCount=10,
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("nexus.live")

# -------------------------------------------------------------------
# .env ve HTTP Client (ccxt kullanÃ„Â±lmÃ„Â±yor Ã¢â‚¬â€ direkt REST)
# -------------------------------------------------------------------
load_dotenv()
API_KEY = os.getenv("TESTNET_API_KEY")
API_SECRET = os.getenv("TESTNET_API_SECRET")
TESTNET = os.getenv("TESTNET", "True").lower() == "true"
BASE_URL = os.getenv("BASE_URL", "https://demo-fapi.binance.com") if TESTNET else "https://fapi.binance.com"

WS_BASE_URL = (
    os.getenv("TESTNET_WS_URL", "wss://fstream.binancefuture.com/stream?streams=")
    if TESTNET
    else "wss://fstream.binance.com/stream?streams="
)

if TESTNET:
    log.info("Futures DEMO modu Ã¢â€ â€™ %s", BASE_URL)
else:
    log.warning("Ã¢Å¡Â Ã¯Â¸Â  CANLI FUTURES MODU Ã¢â‚¬â€ DÃ„Â°KKAT!")

# Ã¢â€â‚¬Ã¢â€â‚¬ BinanceHTTPClient (emir/pozisyon/bakiye/OHLCV Ã¢â‚¬â€ tÃƒÂ¼m iÃ…Å¸lemler) Ã¢â€â‚¬Ã¢â€â‚¬
http_client = BinanceHTTPClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    base_url=BASE_URL,
    timeout=30,
    portfolio_margin=False,  # PM hesabÃ„Â± iÃƒÂ§in True, Cross Margin iÃƒÂ§in False
)
log.info("BinanceHTTPClient oluÃ…Å¸turuldu Ã¢â€ â€™ %s", BASE_URL)

# -------------------------------------------------------------------
# Sembol tick size cache
# -------------------------------------------------------------------
_tick_size_cache: dict[str, float] = {}


def _get_tick_size(symbol: str) -> float:
    if symbol in _tick_size_cache:
        return _tick_size_cache[symbol]
    try:
        tick = http_client.get_tick_size(symbol)
        _tick_size_cache[symbol] = tick
        return tick
    except Exception:
        return 0.0001


def _round_price(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    import math

    decimals = max(0, -int(math.floor(math.log10(tick))))
    return round(round(price / tick) * tick, decimals)


def fmt_bool(val: bool) -> str:
    """Ã¢Å“â€¦ / Ã¢ÂÅ’ Ã¢â‚¬â€ boolean deÃ„Å¸erleri gÃƒÂ¶rsel log iÃƒÂ§in formatla."""
    return "Ã¢Å“â€¦" if val else "Ã¢ÂÅ’"


# -------------------------------------------------------------------
# VISUALIZER DATA EXPORT (OHLC)
# -------------------------------------------------------------------
def export_ohlc_15m(bar: Bar, symbol: str):
    out_dir = "output/live_ohlc"
    os.makedirs(out_dir, exist_ok=True)
    filepath = os.path.join(out_dir, f"{symbol}_15m.csv")
    with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        ts = datetime.fromtimestamp(bar.timestamp / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([ts, bar.open, bar.high, bar.low, bar.close, bar.volume])


def export_ohlc_1m(bar: Bar, symbol: str):
    out_dir = "output/live_ohlc"
    os.makedirs(out_dir, exist_ok=True)
    filepath = os.path.join(out_dir, f"{symbol}_1m.csv")
    with open(filepath, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if f.tell() == 0:
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        ts = datetime.fromtimestamp(bar.timestamp / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([ts, bar.open, bar.high, bar.low, bar.close, bar.volume])


# -------------------------------------------------------------------
# D1 Cache
# -------------------------------------------------------------------
class DailyDataCache:
    def __init__(self):
        self._cache: dict[str, list[Bar]] = {}
        self._last_update: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def get(self, symbol: str) -> list[Bar]:
        now = datetime.now().timestamp()
        async with self._lock:
            if symbol not in self._cache or now - self._last_update.get(symbol, 0) > 86400:
                await self._fetch(symbol)
            return self._cache.get(symbol, [])

    async def _fetch(self, symbol: str):
        try:
            loop = asyncio.get_running_loop()
            ohlcv = await loop.run_in_executor(
                None,
                lambda: http_client.get_klines(symbol, interval="1d", limit=config.D1_BARS),
            )
            bars = [
                Bar(
                    index=i,
                    open=k[1],
                    high=k[2],
                    low=k[3],
                    close=k[4],
                    volume=k[5],
                    timestamp=int(k[0]),
                )
                for i, k in enumerate(ohlcv)
            ]
            self._cache[symbol] = bars
            self._last_update[symbol] = datetime.now().timestamp()
            log.info(f"D1 cache yenilendi: {symbol} ({len(bars)} bar)")
        except Exception as e:
            log.error(f"D1 verisi alÃ„Â±namadÃ„Â± {symbol}: {e}")


# -------------------------------------------------------------------
# Global Rate Limiter Ã¢â‚¬â€ Binance IP limiti: 6000 req/min
# -------------------------------------------------------------------
class _RateLimiter:
    """Token bucket: dakikada max N istek, asyncio-safe."""

    def __init__(self, max_per_minute: int = 5000):
        self._interval = 60.0 / max_per_minute  # istekler arasÃ„Â± min sÃƒÂ¼re (sn)
        self._last: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.time()
            wait = self._interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.time()


# -------------------------------------------------------------------
# Ana Live Bot
# -------------------------------------------------------------------
class LiveTradingBot:
    def __init__(self):
        self.hub = BinanceWSHub(
            symbols=config.SYMBOLS,
            timeframes=["1m", "15m", "1h", "4h"],
            max_bars=500,
            base_url=WS_BASE_URL,
        )
        self.daily_cache = DailyDataCache()
        self._last_protection_check: dict[str, float] = {}
        self._last_global_cleanup: float = 0.0  # periyodik temizlik timestamp'i
        self.state_machine = StateMachine()
        self.event_router = EventRouter(self.state_machine)
        self.analyzers = {sym: MarketAnalyzer(sym) for sym in config.SYMBOLS}
        self.risk_managers: dict[str, RiskManager] = {}
        self.exchange_client = ExchangeClient(http_client)
        self.executor = LiveExecutor(self.exchange_client)
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._balance = 0.0
        self._wallet_balance = 0.0
        self._unrealized_pnl = 0.0
        self._margin_balance = 0.0
        self._available_balance = 0.0
        self._used_margin = 0.0
        self.active_trades: dict[str, dict] = {}

        # Ã¢â€â‚¬Ã¢â€â‚¬ Global API Semaphore: maks 5 eÃ…Å¸zamanlÃ„Â± istek Ã¢â€â‚¬Ã¢â€â‚¬
        # TÃƒÂ¼m _fetch_binance_signed, _signed_post, _signed_delete ÃƒÂ§aÃ„Å¸rÃ„Â±larÃ„Â±
        # bu semafor ÃƒÂ¼zerinden geÃƒÂ§er. 20 sembol aynÃ„Â± anda patlasa bile
        # sadece 5 tanesi API'ye vurur, kalanÃ„Â± kuyruÃ„Å¸a girer.
        self._api_semaphore = asyncio.Semaphore(5)
        # Ã¢â€â‚¬Ã¢â€â‚¬ Global Rate Limiter: dakikada max 5000 istek (6000 limit korumasÃ„Â±) Ã¢â€â‚¬Ã¢â€â‚¬
        self._rate_limiter = _RateLimiter(max_per_minute=5000)

        self._breakeven_log: dict[str, dict] = {}  # {symbol: {"count": int, "adx_gt_35": int, "last_time": ms}}
        self._last_be_summary: float = 0.0  # son ÃƒÂ¶zet log zamanÃ„Â± (unix timestamp)

    # ------------------------------------------------------------------
    # State persistence (VS koparsa / bot resize Ã¢â‚¬â€ kaldÃ„Â±Ã„Å¸Ã„Â± yerden devam)
    # ------------------------------------------------------------------
    STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "nexus_state.json")

    def _flush_state(self):
        """active_trades + symbol_states Ã¢â€ â€™ nexus_state.json yaz."""
        try:
            os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)
            symbol_states = {}
            for sym in config.SYMBOLS:
                st = self.state_machine.get(sym)
                if st and st.state and st.state.value != "IDLE":
                    symbol_states[sym] = {
                        "setup_id": f"{sym}_{st.created_at}_{st.direction}",
                        "state": st.state.value,
                        "direction": st.direction,
                        "fvg_upper": st.fvg_upper,
                        "fvg_lower": st.fvg_lower,
                        "fvg_time": st.fvg_time,
                        "sweep_level": st.sweep_level,
                        "mss_break_level": st.mss_level,
                        "created_at": st.created_at,
                        "expires_at": st.expires_at,
                        "htf_bias": st.htf_bias,
                        "h4_swing_level": st.h4_swing_level,
                        "h1_liquidity_level": st.h1_liquidity_level,
                        "entry_price": st.entry_price,
                        "fvg_missed": st.fvg_missed,
                        "displacement_origin": st.displacement_origin,
                        "poi_anchor": st.poi_anchor,
                    }
            data = {
                "active_trades": self.active_trades,
                "symbol_states": symbol_states,
            }
            with open(self.STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log.debug("[STATE] Flush: %d trade, %d state", len(self.active_trades), len(symbol_states))
        except Exception as e:
            log.error("[STATE] _flush_state hatasÃ„Â±: %s", e)

    def _load_state(self):
        """nexus_state.json Ã¢â€ â€™ active_trades + symbol_states yÃƒÂ¼kle (startup)."""
        if not os.path.exists(self.STATE_FILE):
            log.info("[STATE] nexus_state.json yok, temiz baÃ…Å¸langÃ„Â±ÃƒÂ§")
            return
        try:
            with open(self.STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            # Ã¢â€â‚¬Ã¢â€â‚¬ active_trades Ã¢â€â‚¬Ã¢â€â‚¬
            trades = data.get("active_trades", {})
            if trades:
                self.active_trades.update(trades)
                log.info("[STATE] %d trade geri yÃƒÂ¼klendi", len(trades))
            # Ã¢â€â‚¬Ã¢â€â‚¬ symbol_states Ã¢â€â‚¬Ã¢â€â‚¬
            states = data.get("symbol_states", {})
            restored = 0
            for sym, s in states.items():
                try:
                    st = self.state_machine.get(sym)
                    st.state = SetupState(s.get("state", "IDLE"))
                    st.direction = s.get("direction")
                    st.fvg_upper = s.get("fvg_upper")
                    st.fvg_lower = s.get("fvg_lower")
                    st.fvg_time = s.get("fvg_time")
                    st.sweep_level = s.get("sweep_level")
                    st.mss_level = s.get("mss_break_level")
                    st.created_at = s.get("created_at", int(time.time()))
                    st.expires_at = s.get("expires_at")
                    st.htf_bias = s.get("htf_bias")
                    st.h4_swing_level = s.get("h4_swing_level")
                    st.h1_liquidity_level = s.get("h1_liquidity_level")
                    st.entry_price = s.get("entry_price")
                    st.fvg_missed = s.get("fvg_missed", False)
                    st.displacement_origin = s.get("displacement_origin")
                    st.poi_anchor = s.get("poi_anchor")
                    restored += 1
                except Exception as e:
                    log.warning("[STATE] %s state yÃƒÂ¼klenemedi: %s", sym, e)
            if restored:
                log.info("[STATE] %d symbol state geri yÃƒÂ¼klendi", restored)
        except Exception as e:
            log.error("[STATE] _load_state hatasÃ„Â±: %s", e)

    def _clear_state(self, symbol: str):
        """Trade kapanÃ„Â±nca sembolÃƒÂ¼ state'ten sil ve flush et."""
        self.active_trades.pop(symbol, None)
        self.state_machine.clear(symbol)
        # [FIX-3] Analyzer cache'ini state machine ile sync et.
        # State machine IDLE'a dÃƒÂ¶ndÃƒÂ¼Ã„Å¸ÃƒÂ¼nde _emitted_fvg_ids ve _seen_mss
        # temizlenmezse aynÃ„Â± sembol iÃƒÂ§in yeni setup oluÃ…Å¸tuÃ„Å¸unda FVG/MSS
        # eventleri "already emitted" filtresinden geÃƒÂ§emez, fvg_upper=None
        # ile WAIT_RETRACE'de mahsur kalÃ„Â±r.
        if symbol in self.analyzers:
            self.analyzers[symbol].reset_symbol_cache()
        self._flush_state()

    @staticmethod
    def _get_order_type(order: dict) -> str:
        """Standard endpoint (`type`) ve algo endpoint (`orderType`) response alanÃ„Â±nÃ„Â± birleÃ…Å¸tirir."""
        return order.get("type") or order.get("orderType") or ""

    @staticmethod
    def _get_order_price(order: dict) -> float:
        """Algo emirlerinde `triggerPrice`, normal emirlerde `stopPrice` kullanÃ„Â±lÃ„Â±r."""
        return float(order.get("triggerPrice") or order.get("stopPrice") or 0)

    @staticmethod
    def _safe_order_timestamp(order: dict) -> int:
        """GÃƒÂ¼venli timestamp ÃƒÂ§Ã„Â±karma. None/geÃƒÂ§ersiz deÃ„Å¸erlerde 0 dÃƒÂ¶ner, ValueError patlamaz."""
        try:
            raw = order.get("updateTime") or order.get("time") or 0
            return int(raw)
        except (ValueError, TypeError):
            return 0

    async def _wait_for_position(self, symbol: str, timeout: float = 2.0) -> dict | None:
        """Pozisyonun borsada oluÃ…Å¸masÃ„Â±nÃ„Â± bekle."""
        start = time.time()
        while time.time() - start < timeout:
            pos = await self.executor.get_position(symbol)
            if pos and abs(float(pos.get("contracts", 0))) > 0:
                return pos
            await asyncio.sleep(0.1)
        return None

        # Ã¢â€â‚¬Ã¢â€â‚¬ Merkezi async imzalÃ„Â± istek yardÃ„Â±mcÃ„Â±sÃ„Â± (retry + backoff + semaphore) Ã¢â€â‚¬Ã¢â€â‚¬

    async def _fetch_binance_signed(self, endpoint: str, params: str = "", max_retries: int = 3) -> dict:
        await self._rate_limiter.acquire()  # RATE LIMIT: dakikada max 5000 istek
        async with self._api_semaphore:  # RATE LIMIT: maks 5 eÃ…Å¸zamanlÃ„Â± istek
            key = API_KEY
            secret = API_SECRET
            last_error = None
            for attempt in range(max_retries):
                ts = int(time.time() * 1000)
                full_params = f"{params}&timestamp={ts}" if params else f"timestamp={ts}"
                sig = hmac.new(secret.encode(), full_params.encode(), hashlib.sha256).hexdigest()
                url = f"{BASE_URL}{endpoint}?{full_params}&signature={sig}"
                req = urllib.request.Request(url, headers={"X-MBX-APIKEY": key})
                loop = asyncio.get_running_loop()
                try:
                    raw = await loop.run_in_executor(
                        None,
                        lambda req=req: urllib.request.urlopen(req).read().decode(),
                    )
                    return json.loads(raw)
                except urllib.error.HTTPError as e:
                    body = e.read().decode() if hasattr(e, "read") else str(e)
                    last_error = f"HTTP {e.code}: {body[:200]}"
                    log.warning(
                        "[HTTP] %s Ã¢â€ â€™ %s (attempt %d/%d, url=%s)",
                        endpoint,
                        last_error,
                        attempt + 1,
                        max_retries,
                        url[:120],
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))
                except Exception as e:
                    last_error = str(e)[:200]
                    log.warning(
                        "[HTTP] %s Ã¢â€ â€™ %s (attempt %d/%d)",
                        endpoint,
                        last_error,
                        attempt + 1,
                        max_retries,
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1.0 * (attempt + 1))
            raise Exception(last_error or "unknown HTTP error")

    async def _fetch_binance_signed_post(self, endpoint: str, params: dict) -> dict:
        await self._rate_limiter.acquire()  # RATE LIMIT: dakikada max 5000 istek
        async with self._api_semaphore:  # RATE LIMIT: maks 5 eÃ…Å¸zamanlÃ„Â± istek
            key = API_KEY
            secret = API_SECRET
            params["timestamp"] = int(time.time() * 1000)
            query_string = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
            sig = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
            query_string += f"&signature={sig}"
            url = f"{BASE_URL}{endpoint}"
            data = query_string.encode()
            req = urllib.request.Request(url, data=data, headers={"X-MBX-APIKEY": key})
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req).read().decode())
            return json.loads(raw)

    async def _get_open_orders_async(self, symbol: str) -> list:
        try:
            result = await self._fetch_binance_signed("/fapi/v1/openOrders", f"symbol={symbol}")
            return result if isinstance(result, list) else []
        except Exception as e:
            log.error("[ORDERS] AÃƒÂ§Ã„Â±k emirler alÃ„Â±namadÃ„Â± %s: %s", symbol, e)
            return []

    # ------------------------------------------------------------------
    # Bakiye senkronizasyonu
    # ------------------------------------------------------------------
    async def _sync_balance(self):
        try:
            acc = await self._fetch_binance_signed("/fapi/v2/account")
            self._wallet_balance = float(acc.get("totalWalletBalance", 0))
            self._unrealized_pnl = float(acc.get("totalUnrealizedProfit", 0))
            self._margin_balance = float(acc.get("totalMarginBalance", 0))
            self._available_balance = float(acc.get("availableBalance", 0))
            self._used_margin = float(acc.get("totalInitialMargin", 0))
            self._balance = self._available_balance

            for rm in self.risk_managers.values():
                rm.balance = self._balance
                rm.available_margin = self._available_balance

            log.info(
                "Bakiye Ã¢â‚¬â€ wallet=%.2f margin=%.2f uPnL=%.2f available=%.2f used_margin=%.2f",
                self._wallet_balance,
                self._margin_balance,
                self._unrealized_pnl,
                self._available_balance,
                self._used_margin,
            )
        except Exception as e:
            log.error("Bakiye alÃ„Â±namadÃ„Â±: %s", e)

    # ------------------------------------------------------------------
    # Buffer ÃƒÂ¶n doldurma
    # ------------------------------------------------------------------
    async def _prefill_buffers(self):
        loop = asyncio.get_running_loop()

        # Ã¢â€â‚¬Ã¢â€â‚¬ Tick size cache'leri ÃƒÂ¶nceden doldur Ã¢â€â‚¬Ã¢â€â‚¬
        for sym in config.SYMBOLS:
            await loop.run_in_executor(None, lambda s=sym: _get_tick_size(s))

            # Ã¢â€â‚¬Ã¢â€â‚¬ RATE LIMIT FIX: Semaphore ile maks 3 eÃ…Å¸zamanlÃ„Â± istek Ã¢â€â‚¬Ã¢â€â‚¬
        prefill_sem = asyncio.Semaphore(3)

        async def _prefill_one(s: str, t: str, limit: int):
            async with prefill_sem:
                try:
                    ohlcv = await loop.run_in_executor(None, lambda: http_client.get_klines(s, interval=t, limit=limit))
                    bars = [
                        Bar(
                            index=i,
                            open=k[1],
                            high=k[2],
                            low=k[3],
                            close=k[4],
                            volume=k[5],
                            timestamp=k[0],
                        )
                        for i, k in enumerate(ohlcv)
                    ]
                    buf = self.hub._get_buffer(s, t)
                    buf._bars = bars
                    log.info(f"[PREFILL] {s} {t} {len(bars)} bar yÃƒÂ¼klendi")
                except Exception as e:
                    log.error(f"[PREFILL] {s} {t} hata: {e}")
                finally:
                    # Her istek arasÃ„Â± 200ms bekle (rate limit korumasÃ„Â±)
                    await asyncio.sleep(0.2)

        prefill_tasks = [
            _prefill_one(sym, tf, limit)
            for tf, limit in [
                ("4h", 210),
                ("1h", config.H1_BARS),
                ("15m", config.M15_BARS),
                ("1m", config.M1_BARS),
            ]
            for sym in config.SYMBOLS
        ]
        results = await asyncio.gather(*prefill_tasks, return_exceptions=True)

        errors = [r for r in results if isinstance(r, Exception)]
        if errors:
            log.warning(f"[PREFILL] {len(errors)} sembol/timeframe yÃƒÂ¼klenemedi")
        else:
            log.info("[PREFILL] TÃƒÂ¼m buffer'lar baÃ…Å¸arÃ„Â±yla yÃƒÂ¼klendi")

    # ------------------------------------------------------------------
    # STARTUP CLEANUP Ã¢â‚¬â€ yetim/duplicate emir temizliÃ„Å¸i
    # ------------------------------------------------------------------
    async def _startup_cleanup(self):
        """
        Ã°Å¸Â§Â¹ SORGUSUZ Ã„Â°NFAZ PROTOKOLÃƒÅ“
        Binance'teki tÃƒÂ¼m aÃƒÂ§Ã„Â±k emirleri tara, TEK GERÃƒâ€¡EKLÃ„Â°K KAYNAÃ„Å¾I: Binance API.
          Ã¢â‚¬Â¢ Pozisyonu OLMAYAN semboldeki emirler Ã¢â€ â€™ komple iptal (orphan)
          Ã¢â‚¬Â¢ Duplicate SL/TP (>1 SL veya >1 TP) Ã¢â€ â€™ TÃƒÅ“M koruma (SL+TP) SÃ„Â°LÃ„Â°NÃ„Â°R
            "En yeniyi tut" YOK. Safe Mode sÃ„Â±fÃ„Â±rdan dizecek.
        """
        log.info("Ã°Å¸Â§Â¹ STARTUP CLEANUP | tÃƒÂ¼m aÃƒÂ§Ã„Â±k emirler taranÃ„Â±yor...")

        try:
            # Ã¢â€â‚¬Ã¢â€â‚¬ TÃƒÂ¼m pozisyonlarÃ„Â± ÃƒÂ§ek Ã¢â€â‚¬Ã¢â€â‚¬
            loop = asyncio.get_running_loop()
            positions_raw = await loop.run_in_executor(None, lambda: http_client.get_positions())
            positions_list = positions_raw if isinstance(positions_raw, list) else []

            # Ã°Å¸â€Â´ FIX: positions_list boÃ…Å¸ ise (API hatasÃ„Â± / rate limit) cleanup ATLANIR
            # Aksi halde TÃƒÅ“M emirler "orphan" sanÃ„Â±lÃ„Â±p silinir!
            if not positions_list:
                log.warning("Ã°Å¸Â§Â¹ CLEANUP | positions_list BOÃ…Å¾ (API hatasÃ„Â±/rate limit) Ã¢â‚¬â€ hiÃƒÂ§bir emir silinmeyecek")
                return

            symbols_with_position = set()
            for p in positions_list:
                amt = float(p.get("positionAmt", 0))
                if amt != 0:
                    symbols_with_position.add(p["symbol"])

            # Ã¢â€â‚¬Ã¢â€â‚¬ KÃ„Â±smi API response retry: active_trades'te olup symbols_with_position'da OLMAYAN sembolleri tara Ã¢â€â‚¬Ã¢â€â‚¬
            missing_symbols = [s for s in self.active_trades if s not in symbols_with_position]
            if missing_symbols:
                log.warning(
                    "Ã°Å¸Â§Â¹ CLEANUP | %d sembol API'de eksik (kÃ„Â±smi response?) Ã¢â€ â€™ 1sn bekleyip tekrar sorgulanÃ„Â±yor: %s",
                    len(missing_symbols),
                    missing_symbols,
                )
                await asyncio.sleep(1)
                retry_pos = await loop.run_in_executor(None, lambda: http_client.get_positions())
                retry_list = retry_pos if isinstance(retry_pos, list) else []
                for p in retry_list:
                    p_amt = float(p.get("positionAmt", 0))
                    if p_amt != 0:
                        symbols_with_position.add(p["symbol"])

            # Ã°Å¸â€Â´ FIX: API'de pozisyon yok ama local state'te trade var Ã¢â€ â€™ cleanup ATLANIR
            if not symbols_with_position and self.active_trades:
                log.warning(
                    "Ã°Å¸Â§Â¹ CLEANUP | API'de pozisyon bulunamadÃ„Â± ama local state'te %d trade var Ã¢â‚¬â€ cleanup ATLANIYOR",
                    len(self.active_trades),
                )
                return

            total_cancelled = 0

            # Ã¢â€â‚¬Ã¢â€â‚¬ TÃƒÅ“M aÃƒÂ§Ã„Â±k emirleri TEK SEFERDE ÃƒÂ§ek (normal + algo) Ã¢â€â‚¬Ã¢â€â‚¬
            all_orders_raw = await self._fetch_binance_signed("/fapi/v1/openOrders")
            all_orders = all_orders_raw if isinstance(all_orders_raw, list) else []

            # Algo emirlerini de ÃƒÂ§ek (SL/TP orphan'larÃ„Â± iÃƒÂ§in kritik!)
            try:
                algo_raw = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders")
                algo_orders = algo_raw if isinstance(algo_raw, list) else []
                all_orders.extend(algo_orders)
                log.info(
                    "Ã°Å¸Â§Â¹ CLEANUP | %d normal + %d algo = %d toplam emir",
                    len(all_orders) - len(algo_orders),
                    len(algo_orders),
                    len(all_orders),
                )
            except Exception as e:
                log.warning("Ã°Å¸Â§Â¹ CLEANUP | algoOrders alÃ„Â±namadÃ„Â± (devam): %s", e)
            log.info(
                "Ã°Å¸Â§Â¹ CLEANUP | toplam %d aÃƒÂ§Ã„Â±k emir bulundu (tÃƒÂ¼m semboller)",
                len(all_orders),
            )

            # Sembole gÃƒÂ¶re grupla
            orders_by_symbol: dict = {}
            for o in all_orders:
                sym = o.get("symbol", "")
                if sym not in orders_by_symbol:
                    orders_by_symbol[sym] = []
                orders_by_symbol[sym].append(o)

            # Ã¢â€â‚¬Ã¢â€â‚¬ Config sembolleri + aÃƒÂ§Ã„Â±k emri olan tÃƒÂ¼m semboller Ã¢â€â‚¬Ã¢â€â‚¬
            all_symbols_to_check = set(config.SYMBOLS) | set(orders_by_symbol.keys())

            for symbol in sorted(all_symbols_to_check):
                orders = orders_by_symbol.get(symbol, [])
                if not orders:
                    continue

                try:
                    if symbol not in symbols_with_position:
                        # Ã°Å¸â€ºÂ¡Ã¯Â¸Â FIX: Local state'te trade varsa API eksik dÃƒÂ¶nmÃƒÂ¼Ã…Å¸ olabilir Ã¢â€ â€™ ATLA
                        if symbol in self.active_trades:
                            log.warning(
                                "Ã°Å¸Â§Â¹ [ORPHAN-GUARD] %s API'de pozisyon yok ama local state'te trade var Ã¢â‚¬â€ ATLANIYOR",
                                symbol,
                            )
                            continue
                        # Ã¢ÂÅ’ ORPHAN: emir var ama pozisyon yok Ã¢â€ â€™ hepsini iptal
                        log.warning(
                            "Ã°Å¸Â§Â¹ [ORPHAN] %s | %d emir var ama POZÃ„Â°SYON YOK Ã¢â€ â€™ iptal ediliyor",
                            symbol,
                            len(orders),
                        )
                        for o in orders:
                            order_id = o.get("algoId") or o.get("orderId")
                            is_algo = "algoId" in o
                            if order_id:
                                await self._cancel_order_by_id(order_id, symbol, reason="orphan", is_algo=is_algo)
                                total_cancelled += 1
                            await asyncio.sleep(0.15)  # rate limit
                    else:
                        # Ã¢Å“â€¦ Pozisyon var Ã¢â€ â€™ duplicate kontrolÃƒÂ¼
                        # Algo emirlerinde type="STOP"/"TAKE_PROFIT", normalde "STOP_MARKET"/"TAKE_PROFIT_MARKET"
                        sl_orders = [
                            o
                            for o in orders
                            if self._get_order_type(o) in ("STOP_MARKET", "STOP", "STOP_LIMIT")
                            and o.get("reduceOnly") in (True, "true", "True")
                        ]
                        tp_orders = [
                            o
                            for o in orders
                            if self._get_order_type(o)
                            in (
                                "TAKE_PROFIT_MARKET",
                                "TAKE_PROFIT",
                                "TAKE_PROFIT_LIMIT",
                            )
                            and o.get("reduceOnly") in (True, "true", "True")
                        ]

                        # Ã¢â€â‚¬Ã¢â€â‚¬ SORGUSUZ Ã„Â°NFAZ (V2 Ã¢â‚¬â€ Atomic Swap) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
                        # ESKÃ„Â°: >1 SL veya >1 TP Ã¢â€ â€™ TÃƒÅ“M koruma SÃ„Â°LÃ„Â°NÃ„Â°R, Safe Mode sÃ„Â±fÃ„Â±rdan dizecek.
                        # YENÃ„Â°: En az 1 SL + 1 TP korunur, sadece fazlalÃ„Â±klar iptal edilir.
                        # Ãƒâ€¡IPLAK PENCERE YOK Ã¢â‚¬â€ pozisyon asla stopsuz kalmaz.
                        # Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
                        if len(sl_orders) > 1 or len(tp_orders) > 1:
                            log.critical(
                                "Ã°Å¸Â§Â¹ [SORGUSUZ Ã„Â°NFAZ] %s | SL=%d TP=%d Ã¢â€ â€™ "
                                "fazlalÃ„Â±klar temizleniyor, EN AZ 1 SL + 1 TP KORUNUYOR",
                                symbol,
                                len(sl_orders),
                                len(tp_orders),
                            )

                            if len(sl_orders) > 1:
                                sl_orders.sort(key=lambda o: self._safe_order_timestamp(o), reverse=True)
                                for o in sl_orders[1:]:
                                    order_id = o.get("algoId") or o.get("orderId")
                                    if order_id:
                                        try:
                                            await self._cancel_order_by_id(
                                                order_id,
                                                symbol,
                                                reason="duplicate_sl_startup",
                                                is_algo="algoId" in o,
                                            )
                                            total_cancelled += 1
                                        except Exception as cancel_err:
                                            log.warning(
                                                "Ã°Å¸Â§Â¹ [INFAZ-SL] %s | orderId=%s iptal BAÃ…Å¾ARISIZ (tetiklenmiÃ…Å¸ olabilir): %s",
                                                symbol,
                                                order_id,
                                                cancel_err,
                                            )
                                    await asyncio.sleep(0.15)
                                log.info(
                                    "Ã°Å¸Â§Â¹ [INFAZ-SL] %s | %d fazla SL iptal edildi",
                                    symbol,
                                    len(sl_orders) - 1,
                                )

                            if len(tp_orders) > 1:
                                tp_orders.sort(key=lambda o: self._safe_order_timestamp(o), reverse=True)
                                for o in tp_orders[1:]:
                                    order_id = o.get("algoId") or o.get("orderId")
                                    if order_id:
                                        try:
                                            await self._cancel_order_by_id(
                                                order_id,
                                                symbol,
                                                reason="duplicate_tp_startup",
                                                is_algo="algoId" in o,
                                            )
                                            total_cancelled += 1
                                        except Exception as cancel_err:
                                            log.warning(
                                                "Ã°Å¸Â§Â¹ [INFAZ-TP] %s | orderId=%s iptal BAÃ…Å¾ARISIZ (tetiklenmiÃ…Å¸ olabilir): %s",
                                                symbol,
                                                order_id,
                                                cancel_err,
                                            )
                                    await asyncio.sleep(0.15)
                                log.info(
                                    "Ã°Å¸Â§Â¹ [INFAZ-TP] %s | %d fazla TP iptal edildi",
                                    symbol,
                                    len(tp_orders) - 1,
                                )

                except Exception as e:
                    log.warning("Ã°Å¸Â§Â¹ CLEANUP | %s taranÃ„Â±rken hata: %s", symbol, e)
                    continue

            if total_cancelled:
                log.warning("Ã°Å¸Â§Â¹ STARTUP CLEANUP | TOPLAM %d EMÃ„Â°R Ã„Â°PTAL EDÃ„Â°LDÃ„Â°", total_cancelled)
            else:
                log.info("Ã°Å¸Â§Â¹ STARTUP CLEANUP | temiz, iptal gereken emir yok")

        except Exception as e:
            log.error("Ã°Å¸Â§Â¹ STARTUP CLEANUP hatasÃ„Â±: %s", e)

    async def _cancel_order_by_id(self, order_id, symbol: str, reason: str = "", is_algo: bool = False) -> bool:
        """Tek bir emri Binance REST API ile iptal et (DELETE)."""
        if is_algo:
            try:
                params = f"symbol={symbol}&algoId={order_id}"
                await self._fetch_binance_signed_delete("/fapi/v1/algoOrder", params)
                log.info("Ã°Å¸Â§Â¹ Ã„Â°PTAL (algo) | %s algoId=%s reason=%s", symbol, order_id, reason)
                return True
            except Exception as e:
                err = str(e)
                if "Unknown order" in err or "-2011" in err:
                    log.info(
                        "Ã°Å¸Â§Â¹ Ã„Â°PTAL (algo) | %s algoId=%s zaten yok (ok)",
                        symbol,
                        order_id,
                    )
                    return True
                log.warning("Ã°Å¸Â§Â¹ Ã„Â°PTAL hatasÃ„Â± (algo) %s algoId=%s: %s", symbol, order_id, e)
                return False
        else:
            try:
                params = f"symbol={symbol}&orderId={order_id}"
                await self._fetch_binance_signed_delete("/fapi/v1/order", params)
                log.info("Ã°Å¸Â§Â¹ Ã„Â°PTAL | %s orderId=%s reason=%s", symbol, order_id, reason)
                return True
            except Exception as e:
                err = str(e)
                if "Unknown order" in err or "-2011" in err:
                    log.info("Ã°Å¸Â§Â¹ Ã„Â°PTAL | %s orderId=%s zaten yok (ok)", symbol, order_id)
                    return True
                # Algo order olabilir, onun endpoint'iyle dene
                try:
                    params = f"symbol={symbol}&algoId={order_id}"
                    await self._fetch_binance_signed_delete("/fapi/v1/algoOrder", params)
                    log.info(
                        "Ã°Å¸Â§Â¹ Ã„Â°PTAL (algo fallback) | %s algoId=%s reason=%s",
                        symbol,
                        order_id,
                        reason,
                    )
                    return True
                except Exception as e2:
                    log.warning(
                        "Ã°Å¸Â§Â¹ Ã„Â°PTAL hatasÃ„Â± %s orderId=%s (normal+algo): %s / %s",
                        symbol,
                        order_id,
                        e,
                        e2,
                    )
                    return False

    async def _fetch_binance_signed_delete(self, endpoint: str, params: str = "") -> dict:
        """DELETE isteÃ„Å¸i iÃƒÂ§in ÃƒÂ¶zel metod."""
        await self._rate_limiter.acquire()  # RATE LIMIT: dakikada max 5000 istek
        async with self._api_semaphore:  # RATE LIMIT: maks 5 eÃ…Å¸zamanlÃ„Â± istek
            key = API_KEY
            secret = API_SECRET
            ts = int(time.time() * 1000)
            full_params = f"{params}&timestamp={ts}" if params else f"timestamp={ts}"
            sig = hmac.new(secret.encode(), full_params.encode(), hashlib.sha256).hexdigest()
            url = f"{BASE_URL}{endpoint}?{full_params}&signature={sig}"
            req = urllib.request.Request(url, headers={"X-MBX-APIKEY": key}, method="DELETE")
            loop = asyncio.get_running_loop()
            try:
                raw = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req).read().decode())
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                log.debug("DELETE %s Ã¢â€ â€™ HTTP %s: %s", endpoint, e.code, body)
                raise Exception(f"HTTP {e.code}: {body}") from e

    # ------------------------------------------------------------------
    # Restart sonrasÃ„Â± aÃƒÂ§Ã„Â±k pozisyonlarÃ„Â± yÃƒÂ¼kle (TEK KAYNAK: API)
    # ------------------------------------------------------------------
    async def _load_existing_positions(self):
        """
        Cleanup sonrasÃ„Â± kalan pozisyonlarÃ„Â± API'den okuyup envantere al.
        Koruma durumu API'den sorgulanÃ„Â±r Ã¢â‚¬â€ local state'e gÃƒÂ¼venilmez.
        """
        try:
            log.info("Ã°Å¸â€â€ž RESTART | pozisyonlar yÃƒÂ¼kleniyor (API)...")
            loop = asyncio.get_running_loop()
            positions_raw = await loop.run_in_executor(None, lambda: http_client.get_positions())
            positions = positions_raw if isinstance(positions_raw, list) else []

            for pos in positions:
                amt = float(pos.get("positionAmt", 0))
                if amt == 0:
                    continue

                symbol = pos["symbol"]
                direction = "long" if amt > 0 else "short"
                entry = float(pos.get("entryPrice", 0))
                pnl = float(pos.get("unRealizedProfit", 0))
                mark_price = float(pos.get("markPrice", 0))

                # Ã¢â€â‚¬Ã¢â€â‚¬ API'den aÃƒÂ§Ã„Â±k emirleri ÃƒÂ§ek (retry, normal + algo) Ã¢â€â‚¬Ã¢â€â‚¬
                open_orders = []
                for attempt in range(3):
                    open_orders = await self._get_open_orders_async(symbol)
                    # Algo emirlerini de ekle
                    try:
                        algo_raw = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders", f"symbol={symbol}")
                        if isinstance(algo_raw, list):
                            open_orders.extend(algo_raw)
                    except Exception as e:
                        log.debug(
                            "[RECOVER] %s openAlgoOrders hatasÃ„Â± (ÃƒÂ¶nemsiz): %s",
                            symbol,
                            e,
                        )

                    if open_orders:
                        break

                    if attempt < 2:
                        log.warning(
                            "[RECOVER] %s openOrders BOÃ…Å¾ (attempt %d/3) Ã¢â‚¬â€ 1.5s",
                            symbol,
                            attempt + 1,
                        )
                await asyncio.sleep(1.5)

                # Ã¢â€â‚¬Ã¢â€â‚¬ Koruma emirlerini API'den say Ã¢â€â‚¬Ã¢â€â‚¬
                sl_orders = [
                    o
                    for o in open_orders
                    if self._get_order_type(o) in ("STOP_MARKET", "STOP", "STOP_LIMIT")
                    and o.get("reduceOnly") in (True, "true", "True")
                ]

                tp_orders = [
                    o
                    for o in open_orders
                    if self._get_order_type(o) in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT")
                    and o.get("reduceOnly") in (True, "true", "True")
                ]

                n_sl = len(sl_orders)
                n_tp = len(tp_orders)

                log.info(
                    "[RECOVER] %s pozisyon=%s giriÃ…Å¸=%.4f SL=%d TP=%d",
                    symbol,
                    direction,
                    entry,
                    n_sl,
                    n_tp,
                )

                if n_sl == 1 and n_tp == 1:
                    # Ã¢Å“â€¦ TAM KORUMA Ã¢â‚¬â€ API'den al
                    # NOT: Algo emirleri triggerPrice, normal emirler stopPrice kullanÃ„Â±r
                    sl_price = self._get_order_price(sl_orders[0])
                    tp_price = self._get_order_price(tp_orders[0])
                    sl_id = sl_orders[0].get("algoId") or sl_orders[0].get("orderId") or ""
                    tp_id = tp_orders[0].get("algoId") or tp_orders[0].get("orderId") or ""
                    self.active_trades[symbol] = {
                        "symbol": symbol,
                        "direction": direction,
                        "entry": entry,
                        "initial_sl": sl_price,
                        "current_sl": sl_price,
                        "tp": tp_price,
                        "sl_order_id": sl_id,
                        "tp_order_id": tp_id,
                        "lot": abs(amt),
                        "open_time": None,
                        "status": "open",
                        "pnl": pnl,
                        "last_price": mark_price,
                        "breakeven_done": False,
                    }
                    log.info(
                        "[RECOVER] %s Ã¢Å“â€œ SL+TP mevcut Ã¢â‚¬â€ devam (sl=%s tp=%s)",
                        symbol,
                        sl_id,
                        tp_id,
                    )
                elif n_sl > 1 or n_tp > 1:
                    # Ã¢Å¡Â Ã¯Â¸Â Duplicate kalmÃ„Â±Ã…Å¸ olmamalÃ„Â± (cleanup halletmiÃ…Å¸ti).
                    # Yine de rastlanÃ„Â±rsa: korumasÃ„Â±z al, sync dÃƒÂ¼zeltecek.
                    log.critical(
                        "Ã°Å¸Å¡Â¨ [RECOVER] %s BEKLENMEYEN DUPLICATE SL=%d TP=%d Ã¢â€ â€™ "
                        "korumasÃ„Â±z envantere alÃ„Â±ndÃ„Â±, sync dÃƒÂ¼zeltecek",
                        symbol,
                        n_sl,
                        n_tp,
                    )
                    self.active_trades[symbol] = {
                        "symbol": symbol,
                        "direction": direction,
                        "entry": entry,
                        "lot": abs(amt),
                        "status": "recovered_unprotected",
                        "protection_missing": True,
                        "pnl": pnl,
                        "last_price": mark_price,
                    }
                else:
                    # Eksik koruma Ã¢â€ â€™ Safe Mode
                    log.warning(
                        "Ã°Å¸Å¡Â¨ [RECOVER] %s KORUMASIZ SL=%d TP=%d Ã¢â€ â€™ SAFE MODE",
                        symbol,
                        n_sl,
                        n_tp,
                    )
                    self.active_trades[symbol] = {
                        "symbol": symbol,
                        "direction": direction,
                        "entry": entry,
                        "lot": abs(amt),
                        "status": "recovered_unprotected",
                        "protection_missing": True,
                        "pnl": pnl,
                        "last_price": mark_price,
                    }

                if self.active_trades:
                    log.info(
                        "[RECOVER] %d pozisyon envantere alÃ„Â±ndÃ„Â±",
                        len(self.active_trades),
                    )
                else:
                    log.info("[RECOVER] Envantere alÃ„Â±nan aÃƒÂ§Ã„Â±k pozisyon yok")
        except Exception as e:
            log.error(f"Pozisyon yÃƒÂ¼kleme hatasÃ„Â±: {e}")

    # ------------------------------------------------------------------
    # Pozisyon senkronizasyonu (TEK GERÃƒâ€¡EKLÃ„Â°K: Binance API)
    # ------------------------------------------------------------------
    async def _sync_positions(self, current_bar: Bar):
        """
        Her dÃƒÂ¶ngÃƒÂ¼de ÃƒÂ§aÃ„Å¸rÃ„Â±lÃ„Â±r.
        Koruma durumunu LOKAL state'ten DEÃ„Å¾Ã„Â°L, Binance API'den sorgular.
        Duplicate varsa Ã¢â€ â€™ SORGUSUZ Ã„Â°NFAZ (tÃƒÂ¼m koruma sil, sÃ„Â±fÃ„Â±rdan kur).
        Eksik varsa Ã¢â€ â€™ Safe Mode onar.
        """
        import time

        now = time.time()
        # ZAMAN FRENÃ„Â°: Bu fonksiyon 5 saniyede sadece 1 kez ÃƒÂ§alÃ„Â±Ã…Å¸abilir
        if hasattr(self, "_last_pos_sync_time") and (now - self._last_pos_sync_time < 5.0):
            return
        self._last_pos_sync_time = now
        try:
            # PM uyumlu pozisyon sorgusu: http_client ÃƒÂ¼zerinden (PM mapping'li)
            loop = asyncio.get_running_loop()
            positions_raw = await loop.run_in_executor(None, lambda: http_client.get_positions())
            positions = positions_raw if isinstance(positions_raw, list) else []
            log.info("[SYNC-POSITIONS] %d pozisyon ÃƒÂ§ekildi", len(positions))

            # PM guard: pozisyon listesi boÃ…Å¸sa trade'leri KAPATMA
            if not positions:
                log.warning("[SYNC-POSITIONS] pozisyon listesi boÃ…Å¸ Ã¢â‚¬â€ trade'ler korunuyor, kapatma YOK")
                return

            exchange_positions = {pos["symbol"]: pos for pos in positions if float(pos.get("positionAmt", 0)) != 0}
            total_upnl = 0.0

            for symbol, trade in list(self.active_trades.items()):
                if symbol not in exchange_positions:
                    continue

                pos = exchange_positions[symbol]
                trade["pnl"] = float(pos.get("unRealizedProfit", 0))
                trade["last_price"] = float(pos.get("markPrice", 0))
                total_upnl += trade["pnl"]

                # Ã¢â€â‚¬Ã¢â€â‚¬ API'DEN sorgula: TEK GERÃƒâ€¡EKLÃ„Â°K KAYNAÃ„Å¾I (normal + algo) Ã¢â€â‚¬Ã¢â€â‚¬
                open_orders = await self._get_open_orders_async(symbol)
                try:
                    algo_raw = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders", f"symbol={symbol}")
                    if isinstance(algo_raw, list):
                        open_orders.extend(algo_raw)
                except Exception:
                    pass

                sl_orders = [
                    o
                    for o in open_orders
                    if self._get_order_type(o) in ("STOP_MARKET", "STOP", "STOP_LIMIT")
                    and o.get("reduceOnly") in (True, "true", "True")
                ]
                tp_orders = [
                    o
                    for o in open_orders
                    if self._get_order_type(o) in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT")
                    and o.get("reduceOnly") in (True, "true", "True")
                ]

                n_sl = len(sl_orders)
                n_tp = len(tp_orders)

                # Ã¢â€â‚¬Ã¢â€â‚¬ SORGUSUZ Ã„Â°NFAZ (V2 Ã¢â‚¬â€ Atomic Swap): duplicate varsa ÃƒÂ¶nce koru, sonra temizle Ã¢â€â‚¬Ã¢â€â‚¬
                # ESKÃ„Â°: cancel ALL Ã¢â€ â€™ create new  (Ãƒâ€¡IPLAK PENCERE Ã¢â‚¬â€ pozisyon stopsuz kalÃ„Â±rdÃ„Â±)
                # YENÃ„Â°: keep 1 SL + 1 TP Ã¢â€ â€™ cancel extras Ã¢â€ â€™ repair missing
                if n_sl > 1 or n_tp > 1:
                    log.critical(
                        "Ã°Å¸Å¡Â¨ [SORGUSUZ Ã„Â°NFAZ] %s | SL=%d TP=%d Ã¢â€ â€™ fazlalÃ„Â±klar temizleniyor, EN AZ 1 SL + 1 TP KORUNUYOR",
                        symbol,
                        n_sl,
                        n_tp,
                    )

                    # Ã¢â€â‚¬Ã¢â€â‚¬ SL: en gÃƒÂ¼nceli tut, fazlalarÃ„Â± iptal et Ã¢â€â‚¬Ã¢â€â‚¬
                    if n_sl > 1:
                        sl_orders.sort(key=lambda o: self._safe_order_timestamp(o), reverse=True)
                        for o in sl_orders[1:]:  # ilk (en gÃƒÂ¼ncel) hariÃƒÂ§ hepsini iptal
                            order_id = o.get("algoId") or o.get("orderId")
                            if order_id:
                                try:
                                    await self._cancel_order_by_id(
                                        order_id,
                                        symbol,
                                        reason="duplicate_sl_extra",
                                        is_algo="algoId" in o,
                                    )
                                except Exception as cancel_err:
                                    log.warning(
                                        "Ã°Å¸â€ºÂ¡Ã¯Â¸Â [INFAZ-SL] %s | orderId=%s iptal BAÃ…Å¾ARISIZ (tetiklenmiÃ…Å¸ olabilir): %s",
                                        symbol,
                                        order_id,
                                        cancel_err,
                                    )
                            await asyncio.sleep(0.1)
                        # Kalan SL bilgilerini trade'e yaz
                        trade["sl_order_id"] = str(sl_orders[0].get("algoId") or sl_orders[0].get("orderId") or "")
                        trade["current_sl"] = self._get_order_price(sl_orders[0]) or trade.get("current_sl", 0)
                        log.info(
                            "Ã°Å¸â€ºÂ¡Ã¯Â¸Â [INFAZ-SL] %s | %d fazla SL iptal edildi, 1 SL korundu (id=%s)",
                            symbol,
                            n_sl - 1,
                            trade["sl_order_id"],
                        )

                    # Ã¢â€â‚¬Ã¢â€â‚¬ TP: en gÃƒÂ¼nceli tut, fazlalarÃ„Â± iptal et Ã¢â€â‚¬Ã¢â€â‚¬
                    if n_tp > 1:
                        tp_orders.sort(key=lambda o: self._safe_order_timestamp(o), reverse=True)
                        for o in tp_orders[1:]:
                            order_id = o.get("algoId") or o.get("orderId")
                            if order_id:
                                try:
                                    await self._cancel_order_by_id(
                                        order_id,
                                        symbol,
                                        reason="duplicate_tp_extra",
                                        is_algo="algoId" in o,
                                    )
                                except Exception as cancel_err:
                                    log.warning(
                                        "Ã°Å¸â€ºÂ¡Ã¯Â¸Â [INFAZ-TP] %s | orderId=%s iptal BAÃ…Å¾ARISIZ (tetiklenmiÃ…Å¸ olabilir): %s",
                                        symbol,
                                        order_id,
                                        cancel_err,
                                    )
                            await asyncio.sleep(0.1)
                        trade["tp_order_id"] = str(tp_orders[0].get("algoId") or tp_orders[0].get("orderId") or "")
                        trade["tp"] = self._get_order_price(tp_orders[0]) or trade.get("tp", 0)
                        log.info(
                            "Ã°Å¸â€ºÂ¡Ã¯Â¸Â [INFAZ-TP] %s | %d fazla TP iptal edildi, 1 TP korundu (id=%s)",
                            symbol,
                            n_tp - 1,
                            trade["tp_order_id"],
                        )

                    # Eksik kalan varsa (ÃƒÂ¶rn. SL>1 ama TP=0) onar
                    n_sl_now = 1 if n_sl >= 1 else 0
                    n_tp_now = 1 if n_tp >= 1 else 0
                    if n_sl_now == 0 or n_tp_now == 0:
                        trade["protection_repairing"] = True
                        try:
                            await self._repair_protection(symbol, trade, n_sl_now > 0, n_tp_now > 0)
                        except Exception as e:
                            log.critical(
                                "Ã°Å¸Å¡Â¨ [SYNC] %s infaz sonrasÃ„Â± onarÃ„Â±m hatasÃ„Â±: %s",
                                symbol,
                                e,
                            )
                        finally:
                            trade["protection_repairing"] = False
                    else:
                        trade["protection_missing"] = False
                        trade["status"] = "open"
                        log.info(
                            "Ã¢Å“â€¦ [INFAZ] %s koruma saÃ„Å¸lam: SL=%s TP=%s",
                            symbol,
                            trade.get("sl_order_id", "?")[:12],
                            trade.get("tp_order_id", "?")[:12],
                        )

                elif n_sl == 1 and n_tp == 1:
                    # Ã¢Å“â€¦ TAM KORUMA Ã¢â‚¬â€ API'den ID'leri ve fiyatlarÃ„Â± gÃƒÂ¼ncelle
                    # NOT: Algo emirlerinde triggerPrice, normalde stopPrice
                    trade["sl_order_id"] = str(sl_orders[0].get("algoId") or sl_orders[0].get("orderId") or "")
                    trade["tp_order_id"] = str(tp_orders[0].get("algoId") or tp_orders[0].get("orderId") or "")
                    trade["current_sl"] = self._get_order_price(sl_orders[0]) or trade.get("current_sl", 0)
                    trade["tp"] = self._get_order_price(tp_orders[0]) or trade.get("tp", 0)
                    if trade.get("protection_missing"):
                        trade["protection_missing"] = False
                        trade["status"] = "open"
                        log.info(
                            "Ã¢Å“â€¦ [REPAIR] %s koruma API'den doÃ„Å¸rulandÃ„Â±, SAFE MODE kaldÃ„Â±rÃ„Â±ldÃ„Â±",
                            symbol,
                        )

                else:
                    # Ã¢Å¡Â Ã¯Â¸Â Eksik koruma (0 SL veya 0 TP) Ã¢â‚¬â€ Safe Mode onar
                    now = time.time()
                    last_check = self._last_protection_check.get(symbol, 0)
                    if now - last_check < 300:
                        continue
                    self._last_protection_check[symbol] = now

                    log.warning(
                        "Ã¢Å¡Â Ã¯Â¸Â MISSING PROTECTION | %s | SL=%d TP=%d Ã¢â€ â€™ Safe Mode onarÃ„Â±m",
                        symbol,
                        n_sl,
                        n_tp,
                    )
                    trade["protection_repairing"] = True
                    try:
                        if n_sl == 0 and n_tp == 0:
                            await self._create_protection(symbol, trade)
                        else:
                            await self._repair_protection(symbol, trade, n_sl > 0, n_tp > 0)
                    except Exception as e:
                        log.critical(
                            "Ã°Å¸Å¡Â¨ [SYNC] %s protection/repair iÃ…Å¸lemi sÃ„Â±rasÃ„Â±nda KRÃ„Â°TÃ„Â°K HATA: %s",
                            symbol,
                            e,
                        )
                    finally:
                        trade["protection_repairing"] = False  # KÃ„Â°LÃ„Â°T HER HALÃƒÅ“KARDA KIRILDI

            self._unrealized_pnl = total_upnl

            # Ã¢â€â‚¬Ã¢â€â‚¬ KapanmÃ„Â±Ã…Å¸ pozisyonlarÃ„Â± temizle Ã¢â€â‚¬Ã¢â€â‚¬
            for symbol, trade in list(self.active_trades.items()):
                if symbol not in exchange_positions:
                    # Ã°Å¸â€Â´ CROSS-SYMBOL FIX: ASLA baÃ…Å¸ka sembolÃƒÂ¼n current_bar.close'unu kullanma!
                    # fallback zinciri: last_price Ã¢â€ â€™ kendi 5m close'u Ã¢â€ â€™ entry Ã¢â€ â€™ 0
                    symbol_bars = self.hub.get_bars(symbol, "1m")
                    symbol_close = symbol_bars[-1].close if symbol_bars else None
                    fallback_price = trade.get("last_price") or symbol_close or trade.get("entry") or 0
                    exit_price = float(fallback_price)
                    pnl = trade.get("pnl", 0)
                    self._balance += pnl
                    risk_mgr = self._get_risk_manager(symbol)
                    risk_mgr.balance = self._balance
                    # Ã¢â€â‚¬Ã¢â€â‚¬ TP mi SL mi ayrÃ„Â±mÃ„Â± Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
                    direction = trade.get("direction", "long")
                    tp_price = trade.get("tp", 0) or trade.get("tp_val", 0) or 0
                    sl_price = trade.get("current_sl") or trade.get("initial_sl") or trade.get("sl", 0) or 0

                    if tp_price and sl_price:
                        if direction == "long":
                            close_reason = "TP" if exit_price >= tp_price * 0.995 else "SL"
                        else:
                            close_reason = "TP" if exit_price <= tp_price * 1.005 else "SL"
                    elif tp_price:
                        close_reason = (
                            "TP"
                            if (direction == "long" and exit_price >= tp_price * 0.995)
                            or (direction == "short" and exit_price <= tp_price * 1.005)
                            else "SL"
                        )
                    else:
                        close_reason = "closed"

                    trade["exit_price"] = exit_price
                    trade["exit"] = exit_price  # alias Ã¢â‚¬â€ dashboard/performance iÃƒÂ§in
                    trade["close_time"] = int(time.time() * 1000)
                    trade["status"] = close_reason  # "TP" | "SL" | "closed"

                    if not trade.get("protection_missing"):
                        performance.record_trade(trade)
                    else:
                        # protection_missing path Ã¢â‚¬â€ aynÃ„Â± alanlar zaten set edildi
                        trade.setdefault("direction", "unknown")
                        performance.record_trade(trade)
                        log.warning(
                            "Ã°Å¸Å¸Â¡ SAFE MODE | %s kapandÃ„Â± | eksik bilgiyle kaydedildi",
                            symbol,
                        )
                    # Ã¢â€â‚¬Ã¢â€â‚¬ Pozisyon kapanÃ„Â±rken kalan tÃƒÂ¼m emirleri iptal et Ã¢â€â‚¬Ã¢â€â‚¬
                    try:
                        await self.executor.client.cancel_all_orders(symbol)
                    except Exception as cancel_err:
                        log.warning(
                            "[SYNC] %s cancel_all_orders hatasÃ„Â± (ÃƒÂ¶nemsiz): %s",
                            symbol,
                            cancel_err,
                        )
                    del self.active_trades[symbol]
                    self._clear_state(symbol)
                    self.executor.reset_cooldown(symbol)
                    log.info(f"EXCHANGE SYNC: {symbol} kapandÃ„Â± | Ã°Å¸â€Â´ CIKIS={exit_price:.4f} pnl={pnl:.2f} USDT")

        except Exception as e:
            err_msg = str(e)
            if "-1109" in err_msg:
                pass
            else:
                log.error("Pozisyon sync hatasÃ„Â±: %s", err_msg, exc_info=True)

    async def _repair_protection(self, symbol: str, trade: dict, has_sl: bool, has_tp: bool):
        """Eksik TP/SL'yi tamamla. Order ID'leri API yanÃ„Â±tÃ„Â±ndan yakalar."""
        try:
            # POZÃ„Â°SYON KONTROLÃƒÅ“
            pos = await self.executor.client.fetch_position(symbol)
            if not pos or abs(float(pos.get("contracts", 0))) == 0:
                log.warning("Ã°Å¸â€Â§ [REPAIR] %s pozisyon yok, atlanÃ„Â±yor", symbol)
                return

            # Ã°Å¸â€ºÂ¡Ã¯Â¸Â FIX: TP zaten geÃƒÂ§ilmiÃ…Å¸se pozisyonu market kapat (tp_already_hit)
            if not has_tp and trade.get("tp"):
                mark_price = float(pos.get("markPrice", 0))
                direction = trade.get("direction", "long")
                tp_price = trade["tp"]

                if (direction == "long" and mark_price >= tp_price) or (
                    direction == "short" and mark_price <= tp_price
                ):
                    log.critical(
                        "Ã°Å¸Å¡Ëœ [SORGUSUZ Ã„Â°NFAZ] %s TP (%.5f) zaten geÃƒÂ§ildi (mark=%.5f) Ã¢â‚¬â€ MARKET kapatÃ„Â±lÃ„Â±yor!",
                        symbol,
                        tp_price,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="tp_already_hit_repair")
                    return

            if not has_sl:
                # Ã°Å¸â€ºÂ¡Ã¯Â¸Â FIX: initial_sl trade'de yoksa risk_manager'dan hesapla
                if not trade.get("initial_sl"):
                    log.warning(
                        "Ã°Å¸â€Â§ [REPAIR] %s trade'de initial_sl yok Ã¢â‚¬â€ entry + risk_mgr ile hesaplanÃ„Â±yor",
                        symbol,
                    )
                    risk_mgr = self._get_risk_manager(symbol)
                    direction = trade.get("direction", "long")
                    entry = trade.get("entry", 0)
                    tier = risk_mgr._tier(symbol)
                    buf = tier["sl_buffer"]
                    min_dist = entry * tier["min_sl_pct"]
                    if direction == "long":
                        sl_candidate = entry * (1 - buf)
                        sl_candidate = min(sl_candidate, entry - min_dist)
                    else:
                        sl_candidate = entry * (1 + buf)
                        sl_candidate = max(sl_candidate, entry + min_dist)
                    trade["initial_sl"] = round(sl_candidate, 5)
                    trade["current_sl"] = trade["initial_sl"]
                    log.info(
                        "Ã°Å¸â€Â§ [REPAIR] %s initial_sl hesaplandÃ„Â±: entry=%.5f sl=%.5f",
                        symbol,
                        entry,
                        trade["initial_sl"],
                    )

                sl_side = "sell" if trade["direction"] == "long" else "buy"
                sl_result = await self.executor.client.create_stop_order(
                    symbol=symbol,
                    side=sl_side,
                    amount=trade.get("lot"),
                    stop_price=trade.get("initial_sl"),
                    order_type="STOP_MARKET",
                )
                trade["sl_order_id"] = str(
                    (sl_result or {}).get("algoId")
                    or (sl_result or {}).get("orderId")
                    or (sl_result or {}).get("id")
                    or ""
                )
                log.info(
                    "Ã°Å¸â€Â§ [REPAIR] %s SL yeniden kuruldu: %.8f (id=%s)",
                    symbol,
                    trade["initial_sl"],
                    trade["sl_order_id"],
                )

            if not has_tp and trade.get("tp"):
                tp_side = "sell" if trade["direction"] == "long" else "buy"
                tp_result = await self.executor.client.create_stop_order(
                    symbol=symbol,
                    side=tp_side,
                    amount=trade.get("lot"),
                    stop_price=trade["tp"],
                    order_type="TAKE_PROFIT_MARKET",
                )
                trade["tp_order_id"] = str(
                    (tp_result or {}).get("algoId")
                    or (tp_result or {}).get("orderId")
                    or (tp_result or {}).get("id")
                    or ""
                )
                log.info(
                    "Ã°Å¸â€Â§ [REPAIR] %s TP yeniden kuruldu: %.8f (id=%s)",
                    symbol,
                    trade["tp"],
                    trade["tp_order_id"],
                )

                # API'den doÃ„Å¸rula (normal + algo)
            await asyncio.sleep(0.3)
            open_orders = await self._get_open_orders_async(symbol)
            try:
                algo_raw = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders", f"symbol={symbol}")
                if isinstance(algo_raw, list):
                    open_orders.extend(algo_raw)
            except Exception:
                pass
            sl_ok = any(
                self._get_order_type(o) in ("STOP_MARKET", "STOP", "STOP_LIMIT")
                and o.get("reduceOnly") in (True, "true", "True")
                for o in open_orders
            )
            tp_ok = any(
                self._get_order_type(o) in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT")
                and o.get("reduceOnly") in (True, "true", "True")
                for o in open_orders
            )

            if sl_ok and tp_ok:
                trade["protection_missing"] = False
                trade["status"] = "open"
                log.info("Ã¢Å“â€¦ [REPAIR] %s koruma API'den doÃ„Å¸rulandÃ„Â±", symbol)
            else:
                log.warning(
                    "Ã¢Å¡Â Ã¯Â¸Â [REPAIR] %s doÃ„Å¸rulama baÃ…Å¸arÃ„Â±sÃ„Â±z SL_ok=%s TP_ok=%s Ã¢â‚¬â€ sonraki dÃƒÂ¶ngÃƒÂ¼de tekrar denenecek",
                    symbol,
                    sl_ok,
                    tp_ok,
                )
        except urllib.error.HTTPError as e:
            if "-4130" in str(e):
                log.info("[REPAIR] %s zaten aktif koruma emri mevcut, senkronizasyon gÃƒÂ¼ncel.", symbol)
                return  # baÃ…Å¸arÃ„Â±lÃ„Â± say, REPAIR MODE tetikleme
            raise  # diÃ„Å¸er hatalar yukarÃ„Â± fÃ„Â±rlat
        except Exception:
            log.exception("Ã°Å¸â€Â§ REPAIR_PROTECTION FAILED | %s", symbol)

    async def _create_protection(self, symbol: str, trade: dict):
        """SÃ„Â±fÃ„Â±rdan TP/SL oluÃ…Å¸tur. Order ID'leri API yanÃ„Â±tÃ„Â±ndan yakalar."""
        try:
            # POZÃ„Â°SYON KONTROLÃƒÅ“
            pos = await self.executor.client.fetch_position(symbol)
            if not pos or abs(float(pos.get("contracts", 0))) == 0:
                log.warning("Ã°Å¸â€ â€¢ [CREATE] %s pozisyon yok, atlanÃ„Â±yor", symbol)
                return
            risk_mgr = self._get_risk_manager(symbol)
            entry = trade["entry"]
            direction = trade["direction"]

            # Mevcut piyasa fiyatÃ„Â± Ã¢â€ â€™ TP/SL'nin hemen tetiklenip tetiklenmeyeceÃ„Å¸ini kontrol et
            mark_price = float(pos.get("markPrice", 0))
            if mark_price == 0:
                mark_price = trade.get("last_price", entry)

            tier = risk_mgr._tier(symbol)
            buf = tier["sl_buffer"]
            min_dist = entry * tier["min_sl_pct"]

            sl = tp = None
            if direction == "long":
                sl_candidate = entry * (1 - buf)
                sl_candidate = min(sl_candidate, entry - min_dist)
                tp_candidate = entry + (entry - sl_candidate) * risk_mgr.default_rr
                # LONG TP (SELL) Ã¢â€ â€™ mark_price >= tp_candidate ise SORGUSUZ Ã„Â°NFAZ
                if mark_price >= tp_candidate:
                    log.critical(
                        "Ã°Å¸Å¡Ëœ [SORGUSUZ Ã„Â°NFAZ] %s TP (%.5f) zaten geÃƒÂ§ildi (mark=%.5f) Ã¢â‚¬â€ MARKET kapatÃ„Â±lÃ„Â±yor!",
                        symbol,
                        tp_candidate,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="tp_already_hit")
                    return
                else:
                    tp = tp_candidate
                # LONG SL (SELL) Ã¢â€ â€™ mark_price <= sl_candidate ise hemen tetiklenir
                if mark_price <= sl_candidate:
                    log.critical(
                        "Ã°Å¸Å¡Â¨ [CREATE] %s SL (%.5f) zaten geÃƒÂ§ildi (mark=%.5f) Ã¢â‚¬â€ EMERGENCY kapatÃ„Â±lÃ„Â±yor!",
                        symbol,
                        sl_candidate,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="sl_already_hit")
                    return
                sl = sl_candidate
            else:
                sl_candidate = entry * (1 + buf)
                sl_candidate = max(sl_candidate, entry + min_dist)
                tp_candidate = entry - (sl_candidate - entry) * risk_mgr.default_rr
                # SHORT TP (BUY) Ã¢â€ â€™ mark_price <= tp_candidate ise SORGUSUZ Ã„Â°NFAZ
                if mark_price <= tp_candidate:
                    log.critical(
                        "Ã°Å¸Å¡Ëœ [SORGUSUZ Ã„Â°NFAZ] %s TP (%.5f) zaten geÃƒÂ§ildi (mark=%.5f) Ã¢â‚¬â€ MARKET kapatÃ„Â±lÃ„Â±yor!",
                        symbol,
                        tp_candidate,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="tp_already_hit")
                    return
                else:
                    tp = tp_candidate
                # SHORT SL (BUY) Ã¢â€ â€™ mark_price >= sl_candidate ise hemen tetiklenir
                if mark_price >= sl_candidate:
                    log.critical(
                        "Ã°Å¸Å¡Â¨ [CREATE] %s SL (%.5f) zaten geÃƒÂ§ildi (mark=%.5f) Ã¢â‚¬â€ EMERGENCY kapatÃ„Â±lÃ„Â±yor!",
                        symbol,
                        sl_candidate,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="sl_already_hit")
                    return
                sl = sl_candidate

            sl_side = "sell" if direction == "long" else "buy"

            # SL emri
            sl_resp = await self.executor.client.create_stop_order(
                symbol=symbol,
                side=sl_side,
                amount=trade.get("lot"),
                stop_price=round(sl, 5),
                order_type="STOP_MARKET",
            )
            sl_id = str(
                (sl_resp or {}).get("algoId") or (sl_resp or {}).get("orderId") or (sl_resp or {}).get("id") or ""
            )

            # TP emri (sadece tp hesaplanmÃ„Â±Ã…Å¸sa)
            tp_id = ""
            if tp is not None:
                try:
                    tp_resp = await self.executor.client.create_stop_order(
                        symbol=symbol,
                        side=sl_side,
                        amount=trade.get("lot"),
                        stop_price=round(tp, 5),
                        order_type="TAKE_PROFIT_MARKET",
                    )
                    tp_id = str(
                        (tp_resp or {}).get("algoId")
                        or (tp_resp or {}).get("orderId")
                        or (tp_resp or {}).get("id")
                        or ""
                    )
                except Exception as tp_e:
                    err_str = str(tp_e)
                    if "-2021" in err_str:
                        log.warning(
                            "Ã°Å¸Å¸Â¡ [CREATE] %s TP (%.5f) hemen tetiklenirdi (mark=%.5f) Ã¢â‚¬â€ atlanÃ„Â±yor",
                            symbol,
                            tp,
                            mark_price,
                        )
                    elif "-4130" in err_str:
                        log.warning(
                            "Ã°Å¸Å¸Â¡ [CREATE] %s TP/SL zaten mevcut, SAFE MODE kaldÃ„Â±rÃ„Â±lÃ„Â±yor",
                            symbol,
                        )
                    else:
                        raise

            trade["initial_sl"] = round(sl, 5)
            trade["current_sl"] = round(sl, 5)
            trade["tp"] = round(tp, 5) if tp is not None else 0.0
            trade["sl_order_id"] = sl_id
            trade["tp_order_id"] = tp_id
            trade["protection_missing"] = False
            trade["status"] = "open"
            log.info(
                "Ã°Å¸â€ â€¢ [CREATE] %s TP/SL kuruldu: SL=%.5f (%s) TP=%s (%s)",
                symbol,
                sl,
                sl_id,
                f"{tp:.5f}" if tp is not None else "ATLANDI",
                tp_id or "-",
            )
        except Exception as e:
            if "-4130" in str(e):
                log.warning("Ã°Å¸Å¸Â¡ [CREATE] %s TP/SL zaten mevcut, SAFE MODE kaldÃ„Â±rÃ„Â±lÃ„Â±yor", symbol)
                trade["protection_missing"] = False
                trade["status"] = "open"
                if "initial_sl" not in trade:
                    trade["initial_sl"] = 0.0
                if "current_sl" not in trade:
                    trade["current_sl"] = 0.0
                if "tp" not in trade:
                    trade["tp"] = 0.0
            else:
                log.exception("Ã°Å¸â€ Ëœ CREATE_PROTECTION FAILED | %s", symbol)

    # ------------------------------------------------------------------
    # Risk manager factory
    # ------------------------------------------------------------------
    def _get_risk_manager(self, symbol: str) -> RiskManager:
        if symbol not in self.risk_managers:
            self.risk_managers[symbol] = RiskManager(
                balance=self._balance,
                available_margin=self._available_balance,
                risk_pct=config.RISK_PER_TRADE_MAP.get(symbol, config.RISK_PER_TRADE),
                min_rr=config.MIN_RR_MAP.get(symbol, config.MIN_RR),
                min_net_rr=config.MIN_NET_RR,
                default_rr=config.DEFAULT_RR,
                taker_fee=config.TAKER_FEE,
                spread_pct=config.SPREAD_PCT,
            )
        return self.risk_managers[symbol]

        # ------------------------------------------------------------------

    # AÃƒÂ§Ã„Â±k pozisyon yÃƒÂ¶netimi (trailing + breakeven)
    # ------------------------------------------------------------------
    async def _manage_open_trades(self, current_bar: Bar):
        current_time_ms = int(time.time() * 1000)  # AnlÃ„Â±k sistem zamanÃ„Â± (ms)
        for symbol, trade in list(self.active_trades.items()):
            # Ã°Å¸â€Â´ RACE CONDITION FIX: _sync_positions() ÃƒÂ¶ncesi lokal state gÃƒÂ¼ncel olmayabilir.
            # TP zaten geÃƒÂ§ilmiÃ…Å¸ ve pozisyon Binance'te kapanmÃ„Â±Ã…Å¸ olabilir.
            # Bu durumda SL gÃƒÂ¼ncellemesi yapmak "Unknown order sent" hatasÃ„Â±na yol aÃƒÂ§ar.
            # Ãƒâ€¡ÃƒÂ¶zÃƒÂ¼m: Her _manage_open_trades() dÃƒÂ¶ngÃƒÂ¼sÃƒÂ¼nde pozisyonu Binance API'den doÃ„Å¸rula.
            try:
                pos = await self.executor.get_position(symbol)
                if not pos or abs(float(pos.get("contracts", 0))) == 0:
                    log.warning(
                        "[MANAGE-RACE] %s pozisyon API'de bulunamadÃ„Â± (zaten kapanmÃ„Â±Ã…Å¸) Ã¢â‚¬â€ SL gÃƒÂ¼ncellemesi ATLANIYOR",
                        symbol,
                    )
                    continue
            except Exception as e:
                log.warning(
                    "[MANAGE-RACE] %s pozisyon sorgusu baÃ…Å¸arÃ„Â±sÃ„Â±z: %s Ã¢â‚¬â€ gÃƒÂ¼venlik iÃƒÂ§in atlanÃ„Â±yor",
                    symbol,
                    e,
                )
                continue

            if trade.get("protection_missing"):
                log.warning("Ã°Å¸Å¸Â¡ SAFE MODE | %s | sadece izleme, iÃ…Å¸lem yok", symbol)
                continue
            if trade.get("protection_repairing"):
                log.warning("Ã°Å¸Å¸Â¡ REPAIR MODE | %s | sadece izleme, iÃ…Å¸lem yok", symbol)
                continue
            if trade["status"] != "open":
                continue

            # Ã°Å¸â€Â´ FIX: Minimum YaÃ…Å¸am SÃƒÂ¼resi KorumasÃ„Â± (En az 5 dakika/300.000 ms geÃƒÂ§meli)
            open_time = trade.get("open_time", 0)
            if open_time and (current_time_ms - open_time) < 300_000:
                remaining = int((300_000 - (current_time_ms - open_time)) / 1000)
                log.info(
                    "[MANAGE] %s iÃ…Å¸lemi henÃƒÂ¼z ÃƒÂ§ok taze (kalan sÃƒÂ¼re: %dsn) Ã¢â‚¬â€ Breakeven/Trailing atlandÃ„Â±.",
                    symbol,
                    remaining,
                )
                continue

            try:
                risk_mgr = self._get_risk_manager(symbol)
                # Ã°Å¸â€Â´ CROSS-SYMBOL FIX: Kendi sembolÃƒÂ¼nÃƒÂ¼n 5m bar fiyatÃ„Â±nÃ„Â± kullan
                symbol_bars = self.hub.get_bars(symbol, "1m")
                symbol_close = symbol_bars[-1].close if symbol_bars else None
                current_price = trade.get("last_price") or symbol_close or trade.get("entry", 0)
                sl_current = trade.get("current_sl", trade["initial_sl"])
                if not trade.get("breakeven_done", False) and risk_mgr.should_move_to_breakeven(trade, current_price):
                    new_sl = risk_mgr.breakeven_sl(trade)
                    trade["current_sl"] = new_sl
                    trade["breakeven_done"] = True
                    # Ã¢â€â‚¬Ã¢â€â‚¬ Breakeven logging (ADX > 35 korelasyon izleme) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
                    if config.BREAKEVEN_LOG_ENABLED:
                        d1_adx = trade.get("d1_adx_at_entry", 0)
                        adx_flag = "Ã¢Å¡Â Ã¯Â¸Â ADX>35" if d1_adx >= config.ADX_HIGH_TP_THRESHOLD else "OK"
                        log.info(
                            f"[BE] {symbol} breakeven'a alÃ„Â±ndÃ„Â± | "
                            f"yeni SL={new_sl:.8f} | "
                            f"entry={trade['entry']:.6f} | "
                            f"current_price={current_price:.6f} | "
                            f"d1_adx_at_entry={d1_adx:.1f} ({adx_flag}) | "
                            f"direction={trade['direction']} | "
                            f"fvg_score={trade.get('fvg_score', '?'):.3f}"
                        )
                    else:
                        log.info(f"[BE] {symbol} breakeven'a alÃ„Â±ndÃ„Â±, yeni SL={new_sl:.8f}")
                    # Ã¢â€â‚¬Ã¢â€â‚¬ Breakeven istatistik takibi Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
                    if symbol not in self._breakeven_log:
                        self._breakeven_log[symbol] = {
                            "count": 0,
                            "adx_gt_35": 0,
                            "last_time": current_time_ms,
                        }
                    self._breakeven_log[symbol]["count"] += 1
                    self._breakeven_log[symbol]["last_time"] = current_time_ms
                    d1_adx = trade.get("d1_adx_at_entry", 0)
                    if d1_adx >= config.ADX_HIGH_TP_THRESHOLD:
                        self._breakeven_log[symbol]["adx_gt_35"] += 1
                    # Ã¢â€â‚¬Ã¢â€â‚¬ Periyodik ÃƒÂ¶zet log (her 30 dk) Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
                    if config.BREAKEVEN_LOG_ENABLED and current_time_ms - self._last_be_summary > 1_800_000:  # 30 dk
                        self._last_be_summary = current_time_ms
                        total_be = sum(v["count"] for v in self._breakeven_log.values())
                        total_adx35 = sum(v["adx_gt_35"] for v in self._breakeven_log.values())
                        corr_pct = (total_adx35 / total_be * 100) if total_be > 0 else 0.0
                        log.info(
                            f"[BE-SUMMARY] Breakeven Ãƒâ€“zeti | "
                            f"toplam={total_be} | "
                            f"ADX>35'te BE={total_adx35} ({corr_pct:.1f}%) | "
                            f"sembol sayÃ„Â±sÃ„Â±={len(self._breakeven_log)}"
                        )
                    await self._update_sl_order(symbol, trade, new_sl)

                elif trade.get("breakeven_done", False):
                    new_sl = risk_mgr.trailing_sl(
                        trade,
                        current_price,
                        sl_current,
                        step_ratio=config.TRAILING_STEP_RATIO,
                    )
                    if new_sl != sl_current:
                        trade["current_sl"] = new_sl
                        log.info(f"[TRAIL] {symbol} SL gÃƒÂ¼ncellendi: {sl_current:.8f} Ã¢â€ â€™ {new_sl:.8f}")
                        await self._update_sl_order(symbol, trade, new_sl)

            except Exception as e:
                log.error(f"[MANAGE] {symbol} yÃƒÂ¶netim hatasÃ„Â±: {e}")

    # ------------------------------------------------------------------
    # SL gÃƒÂ¼ncelleme
    # ------------------------------------------------------------------
    async def _update_sl_order(self, symbol: str, trade: dict, new_sl: float):
        """SL gÃƒÂ¼ncelle. API'den mevcut SL emrini bulur, cancelReplace yapar."""
        try:
            open_orders = await self._get_open_orders_async(symbol)
            # Algo emirlerini de ekle (SL algo order ise bulunamaz)
            try:
                algo_raw = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders", f"symbol={symbol}")
                if isinstance(algo_raw, list):
                    open_orders.extend(algo_raw)
            except Exception:
                pass
            old_sl = next(
                (o for o in open_orders if self._get_order_type(o) in ("STOP_MARKET", "STOP", "STOP_LIMIT")),
                None,
            )
            if not old_sl:
                sl_side = "sell" if trade["direction"] == "long" else "buy"
                sl_resp = await self.executor.client.create_stop_order(
                    symbol=symbol,
                    side=sl_side,
                    amount=trade.get("lot"),
                    stop_price=new_sl,
                    order_type="STOP_MARKET",
                )
                new_id = str(
                    (sl_resp or {}).get("algoId") or (sl_resp or {}).get("orderId") or (sl_resp or {}).get("id") or ""
                )
                trade["sl_order_id"] = new_id
                log.info("Ã°Å¸â€ºÂ¡Ã¯Â¸Â SL UPDATE | %s | yeni SL=%.8f (id=%s)", symbol, new_sl, new_id)
                return

            # Algo order ise cancelReplace KULLANMA (algoId'si vardÃ„Â±r, orderId'si yoktur)
            if "algoId" in old_sl:
                old_id = old_sl["algoId"]
                await self._cancel_order_by_id(old_id, symbol, reason="sl_update", is_algo=True)
                await asyncio.sleep(0.2)
                sl_side = "sell" if trade["direction"] == "long" else "buy"
                sl_resp = await self.executor.client.create_stop_order(
                    symbol=symbol,
                    side=sl_side,
                    amount=trade.get("lot"),
                    stop_price=new_sl,
                    order_type="STOP_MARKET",
                )
                new_id = str(
                    (sl_resp or {}).get("algoId") or (sl_resp or {}).get("orderId") or (sl_resp or {}).get("id") or ""
                )
                trade["sl_order_id"] = new_id
                trade["current_sl"] = new_sl
                log.info(
                    "Ã°Å¸â€ºÂ¡Ã¯Â¸Â SL ALGO UPDATE | %s | yeni SL=%.8f (id=%s)",
                    symbol,
                    new_sl,
                    new_id,
                )
                return

            # Standard order Ã¢â€ â€™ cancelReplace dene
            result = await self._fetch_binance_signed_post(
                "/fapi/v1/order/cancelReplace",
                {
                    "symbol": symbol,
                    "cancelReplaceMode": "STOP_ON_FAILURE",
                    "cancelOrderId": old_sl["orderId"],
                    "side": "SELL" if trade["direction"] == "long" else "BUY",
                    "type": "STOP_MARKET",
                    "stopPrice": new_sl,
                    "quantity": str(abs(trade["lot"])),
                    "reduceOnly": "true",
                },
            )
            new_id = str(result.get("algoId") or result.get("orderId") or result.get("id") or "")
            if new_id:
                trade["sl_order_id"] = new_id

            log.info(
                "Ã°Å¸â€ºÂ¡Ã¯Â¸Â SL REPLACED | %s | %.8f Ã¢â€ â€™ %.8f (new_id=%s)",
                symbol,
                float(old_sl.get("stopPrice", 0)),
                new_sl,
                new_id,
            )

        except Exception as e:
            log.critical(
                "[SL_UPDATE] %s cancelReplace baÃ…Å¸arÃ„Â±sÃ„Â±z: %s Ã¢â‚¬â€ EMERGENCY FALLBACK",
                symbol,
                e,
            )
            try:
                # ADIM 1: Eski SL emrini iptal et
                if old_sl:
                    old_id = old_sl.get("algoId") or old_sl.get("orderId")
                if old_id:
                    await self._cancel_order_by_id(
                        old_id,
                        symbol,
                        reason="sl_update_fallback_cancel",
                        is_algo="algoId" in old_sl,
                    )
                await asyncio.sleep(0.2)

                # ADIM 2: Yeni SL emri gÃƒÂ¶nder
                sl_side = "sell" if trade["direction"] == "long" else "buy"
                sl_resp = await self.executor.client.create_stop_order(
                    symbol=symbol,
                    side=sl_side,
                    amount=trade.get("lot"),
                    stop_price=new_sl,
                    order_type="STOP_MARKET",
                )
                new_id = str(
                    (sl_resp or {}).get("algoId") or (sl_resp or {}).get("orderId") or (sl_resp or {}).get("id") or ""
                )
                trade["sl_order_id"] = new_id
                trade["current_sl"] = new_sl
                log.info(
                    "Ã°Å¸â€ºÂ¡Ã¯Â¸Â SL FALLBACK OK | %s | yeni SL=%.8f (id=%s)",
                    symbol,
                    new_sl,
                    new_id,
                )
            except Exception as fallback_err:
                log.critical(
                    "Ã°Å¸Å¡Â¨ SL FALLBACK BAÃ…Å¾ARISIZ | %s | EMERGENCY CLOSE tetikleniyor: %s",
                    symbol,
                    fallback_err,
                )
                try:
                    await self.executor.close_position(symbol, reason="emergency_sl_update_fail")
                    log.critical("Ã°Å¸Å¡Â¨ EMERGENCY CLOSE BAÃ…Å¾ARILI | %s | pozisyon kapatÃ„Â±ldÃ„Â±", symbol)
                except Exception as close_err:
                    log.critical(
                        "Ã°Å¸Å¡Â¨ EMERGENCY CLOSE BAÃ…Å¾ARISIZ | %s | manuel mÃƒÂ¼dahale gerekli! hata=%s",
                        symbol,
                        close_err,
                    )

    # ------------------------------------------------------------------
    # 5m bar kapanÃ„Â±Ã…Å¸ handler
    # ------------------------------------------------------------------
    def _is_15m_closed(self, symbol: str, current_bar: Bar) -> bool:
        """15m mumun kapandÃ„Â±Ã„Å¸Ã„Â±nÃ„Â± timestamp ile tespit et."""
        ts_cache = getattr(self, "_15m_close_cache", {})
        bars_15m = self.hub.get_bars(symbol, "15m")
        if not bars_15m:
            return False
        last_15m_ts = bars_15m[-1].timestamp
        prev = ts_cache.get(symbol)
        if prev is not None and prev == last_15m_ts:
            return False  # aynÃ„Â± 15m, daha ÃƒÂ¶nce iÃ…Å¸lendi
        ts_cache[symbol] = last_15m_ts
        self._15m_close_cache = ts_cache
        return True

    async def _on_1m_close(self, symbol: str, bars_m1: list[Bar]):
        try:
            current_bar = bars_m1[-1]

            monitor.update_tick(symbol)

            await self._manage_open_trades(current_bar)
            asyncio.create_task(self._sync_positions(current_bar))

            bars_h4 = self.hub.get_bars(symbol, "4h")
            bars_h1 = self.hub.get_bars(symbol, "1h")
            bars_15m = self.hub.get_bars(symbol, "15m")
            bars_d1 = await self.daily_cache.get(symbol)

            # --- WEEKLY RANGE SPY: 5m kaldirildi ---
            # H4 "None" kontrolÃƒÂ¼ eklendi
            if bars_h4 is None or bars_h1 is None or bars_15m is None or bars_d1 is None:
                log.warning(
                    "[SKIP] %s bar buffer None: h4=%s h1=%s 15m=%s d1=%s",
                    symbol,
                    bars_h4 is not None,
                    bars_h1 is not None,
                    bars_15m is not None,
                    bars_d1 is not None,
                )
                return

            if len(bars_d1) < 110 or len(bars_h4) < 200 or len(bars_h1) < 10 or len(bars_15m) < 5:
                log.warning(
                    "[SKIP] %s yetersiz bar: d1=%d h4=%d h1=%d m15=%d",
                    symbol,
                    len(bars_d1),
                    len(bars_h4),
                    len(bars_h1),
                    len(bars_15m),
                )
                return

            # Ã¢â€â‚¬Ã¢â€â‚¬ 15m bar kapanÃ„Â±Ã…Å¸Ã„Â±nda: sadece snapshot export Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
            if self._is_15m_closed(symbol, current_bar):
                export_ohlc_15m(bars_15m[-1], symbol)
                state_logger.write_snapshot(
                    symbol=symbol,
                    state=self.state_machine.get(symbol),
                    killzone_utc=current_bar.timestamp // 3600000 % 24,
                    in_killzone=getattr(self.state_machine.get(symbol), "in_killzone", False),
                )

            # Ã¢â€â‚¬Ã¢â€â‚¬ Her 1m: state check'ler + emir kapÃ„Â±sÃ„Â± Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
            if symbol not in self.active_trades:
                from datetime import datetime

                self.state_machine.check_retrace(symbol, current_bar)
                self.state_machine.check_ltf_fvg_validity(symbol, current_bar)
                self.state_machine.check_poi_retrace(symbol, current_bar)

                _state_before = self.state_machine.get(symbol).state
                self.state_machine._evaluate(
                    self.state_machine.get(symbol),
                    current_time=datetime.now(),
                    last_closed_bar=current_bar,
                )
                _state_after = self.state_machine.get(symbol).state
                if _state_before != _state_after and _state_after == SetupState.IDLE:
                    if symbol in self.analyzers:
                        self.analyzers[symbol].reset_symbol_cache()
                    log.debug("[CACHE-RESET] %s Ã¢â€ â€™ IDLE, analyzer cache temizlendi", symbol)

                # --- Time-boxed partial entry in WAIT_CONFIRM (no LTF) ---
                current_state = self.state_machine.get(symbol)
                if current_state.state == SetupState.WAIT_CONFIRM:
                    try:
                        tc_min = getattr(config, "WAIT_CONFIRM_TIMEBOX_MIN", 0)
                        scale = getattr(config, "PARTIAL_RISK_SCALE", 0.0)
                        if tc_min > 0 and scale > 0:
                            since = getattr(current_state, "wait_confirm_since_ts", None)
                            if since:
                                elapsed_min = max(0.0, (current_bar.timestamp - since) / 60000.0)
                                if elapsed_min >= tc_min and current_state.fvg_upper and current_state.fvg_lower:
                                    from state_machine import PenetrationEngine

                                    engine = PenetrationEngine(
                                        current_state.fvg_upper, current_state.fvg_lower, current_state.direction
                                    )
                                    pen = engine.get_penetration(current_bar.close)
                                    pen_min_partial = getattr(config, "FVG_PENETRATION_MIN", 0.15)
                                    pen_max_partial = getattr(config, "FVG_PENETRATION_MAX", 0.70)
                                    if pen_min_partial <= pen <= pen_max_partial and symbol not in self.active_trades:
                                        async with get_lock(symbol):
                                            if symbol in self.active_trades:
                                                pass
                                            else:
                                                risk_mgr = self._get_risk_manager(symbol)
                                                tp = risk_mgr.build_trade(
                                                    state=current_state,
                                                    entry_price=bars_m1[-1].close,
                                                    h4_swing_level=current_state.h4_swing_level,
                                                    h1_liquidity_level=current_state.h1_liquidity_level,
                                                )
                                                if tp is None:
                                                    log.warning("[PARTIAL] %s build_trade rejected", symbol)
                                                else:
                                                    scaled_lot = max(0.0, tp.lot * scale)
                                                    try:
                                                        scaled_lot = risk_mgr._round_lot(symbol, scaled_lot)
                                                    except Exception:
                                                        pass
                                                    if scaled_lot <= 0:
                                                        log.warning("[PARTIAL] %s scaled lot <=0; skip", symbol)
                                                    else:
                                                        risk_dist = abs(tp.entry - tp.sl)
                                                        tp.lot = scaled_lot
                                                        tp.risk_usd = round(risk_dist * scaled_lot, 4)
                                                        entry_type = getattr(config, "ENTRY_ORDER_TYPE", "MARKET")
                                                        order = await self.executor.send_order(
                                                            tp,
                                                            entry_order_type=entry_type,
                                                            current_price=bars_m1[-1].close,
                                                            stop_offset_pct=getattr(
                                                                config, "ENTRY_STOP_OFFSET_PCT", 0.0
                                                            ),
                                                            partial=True,
                                                        )
                                                        if order is not None:
                                                            self.active_trades[symbol] = {
                                                                "symbol": symbol,
                                                                "direction": tp.direction,
                                                                "entry": tp.entry,
                                                                "initial_sl": tp.initial_sl,
                                                                "current_sl": tp.initial_sl,
                                                                "tp": tp.tp,
                                                                "lot": tp.lot,
                                                                "risk_usd": tp.risk_usd,
                                                                "breakeven_level": tp.breakeven_level,
                                                                "trailing_level": tp.trailing_level,
                                                                "breakeven_done": False,
                                                                "trailing_done": False,
                                                                "open_time": int(time.time() * 1000),
                                                                "status": "open",
                                                                "pnl": 0.0,
                                                                "last_price": tp.entry,
                                                                "d1_bias": current_state.htf_bias,
                                                                "h4_bias": current_state.htf_bias,
                                                                "bias_strength": current_state.htf_strength,
                                                                "h4_sl": current_state.h4_swing_level,
                                                                "h1_tp": current_state.h1_liquidity_level,
                                                                "sweep": current_state.sweep_detected,
                                                                "sweep_side": "SSL"
                                                                if current_state.direction == "LONG"
                                                                else "BSL",
                                                                "sweep_level": current_state.sweep_level,
                                                                "sweep_bar_index": current_state.sweep_bar_index,
                                                                "mss": current_state.mss_confirmed,
                                                                "mss_level": current_state.mss_level,
                                                                "mss_bar_index": current_state.mss_bar_index,
                                                                "mss_direction": current_state.direction,
                                                                "impulse_origin": getattr(
                                                                    current_state, "displacement_origin", None
                                                                ),
                                                                "fvg_upper": current_state.fvg_upper,
                                                                "fvg_lower": current_state.fvg_lower,
                                                                "fvg_bar_index": current_state.fvg_entry_bar_index,
                                                                "fvg_direction": "bearish"
                                                                if current_state.direction == "SHORT"
                                                                else "bullish",
                                                                "retrace": current_state.retrace_seen,
                                                                "ltf": current_state.ltf_confirmed,
                                                                "fvg_missed": current_state.fvg_missed,
                                                                "state": current_state.state.value,
                                                                "partial": True,
                                                            }
                                                            self.state_machine.set_state(symbol, SetupState.ENTERED)
                                                            self._flush_state()
                                                            log.info(
                                                                "[PARTIAL] %s entry sent (scale=%.2f pen=%.2f)",
                                                                symbol,
                                                                scale,
                                                                pen,
                                                            )
                    except Exception as e:
                        log.warning("[PARTIAL] %s error: %s", symbol, e)

                current_state = self.state_machine.get(symbol)
                if current_state.state == SetupState.READY_TO_ENTER:
                    async with get_lock(symbol):
                        if symbol in self.active_trades:
                            log.warning("[EXECUTE] %s zaten aktif trade var Ã¢â‚¬â€ atlandÃ„Â±", symbol)
                        else:
                            risk_mgr = self._get_risk_manager(symbol)
                            trade_params = risk_mgr.build_trade(
                                state=current_state,
                                entry_price=bars_m1[-1].close,
                                h4_swing_level=current_state.h4_swing_level,
                                h1_liquidity_level=current_state.h1_liquidity_level,
                            )
                            if trade_params is None:
                                log.warning("[EXECUTE] %s build_trade reddetti Ã¢â€ â€™ atlanÃ„Â±yor", symbol)
                                self.state_machine.invalidate(symbol)
                            else:
                                order = await self.executor.send_order(
                                    trade_params,
                                    entry_order_type=getattr(config, "ENTRY_ORDER_TYPE", "MARKET"),
                                    current_price=bars_m1[-1].close,
                                    stop_offset_pct=getattr(config, "ENTRY_STOP_OFFSET_PCT", 0.0),
                                    partial=False,
                                )
                                if order is not None:
                                    self.active_trades[symbol] = {
                                        "symbol": symbol,
                                        "direction": trade_params.direction,
                                        "entry": trade_params.entry,
                                        "initial_sl": trade_params.initial_sl,
                                        "current_sl": trade_params.initial_sl,
                                        "tp": trade_params.tp,
                                        "lot": trade_params.lot,
                                        "risk_usd": trade_params.risk_usd,
                                        "breakeven_level": trade_params.breakeven_level,
                                        "trailing_level": trade_params.trailing_level,
                                        "breakeven_done": False,
                                        "trailing_done": False,
                                        "open_time": int(time.time() * 1000),
                                        "status": "open",
                                        "pnl": 0.0,
                                        "last_price": trade_params.entry,
                                        "d1_bias": current_state.htf_bias,
                                        "h4_bias": current_state.htf_bias,
                                        "bias_strength": current_state.htf_strength,
                                        "h4_sl": current_state.h4_swing_level,
                                        "h1_tp": current_state.h1_liquidity_level,
                                        "sweep": current_state.sweep_detected,
                                        "sweep_side": "SSL" if current_state.direction == "LONG" else "BSL",
                                        "sweep_level": current_state.sweep_level,
                                        "sweep_bar_index": current_state.sweep_bar_index,
                                        "mss": current_state.mss_confirmed,
                                        "mss_level": current_state.mss_level,
                                        "mss_bar_index": current_state.mss_bar_index,
                                        "mss_direction": current_state.direction,
                                        "impulse_origin": getattr(current_state, "displacement_origin", None),
                                        "fvg_upper": current_state.fvg_upper,
                                        "fvg_lower": current_state.fvg_lower,
                                        "fvg_bar_index": current_state.fvg_entry_bar_index,
                                        "fvg_direction": "bearish" if current_state.direction == "SHORT" else "bullish",
                                        "retrace": current_state.retrace_seen,
                                        "ltf": current_state.ltf_confirmed,
                                        "fvg_missed": current_state.fvg_missed,
                                        "state": current_state.state.value,
                                        "sl": trade_params.sl,
                                        "tp_val": trade_params.tp,
                                        "rr": trade_params.gross_rr,
                                        "exit": None,
                                        "lot_val": trade_params.lot,
                                    }
                                    self.state_machine.set_state(symbol, SetupState.ENTERED)
                                    self._flush_state()
                                    log.info(
                                        "[EXECUTE] %s Ã¢Å“â€¦ emir gÃƒÂ¶nderildi Ã¢â‚¬â€ entry=%.5f sl=%.5f tp=%.5f RR=%.2f",
                                        symbol,
                                        trade_params.entry,
                                        trade_params.sl,
                                        trade_params.tp,
                                        trade_params.gross_rr,
                                    )

            # Ã¢â€â‚¬Ã¢â€â‚¬ AÃƒÂ§Ã„Â±k pozisyon varsa yeni sinyal alma (analyzer atlanÃ„Â±r) Ã¢â€â‚¬Ã¢â€â‚¬
            if symbol in self.active_trades:
                existing = self.active_trades[symbol]
                if existing.get("protection_missing"):
                    log.warning("Ã°Å¸Å¸Â¡ SAFE MODE | %s | yeni sinyal ENGELLENDÃ„Â°", symbol)
                if existing.get("protection_repairing"):
                    log.warning("Ã°Å¸Å¸Â¡ REPAIR MODE | %s | yeni sinyal ENGELLENDÃ„Â°", symbol)
                return

            # Ã¢â€â‚¬Ã¢â€â‚¬ V3 event-driven flow: analyzer Ã¢â€ â€™ event_router Ã¢â€ â€™ state_machine Ã¢â€â‚¬Ã¢â€â‚¬
            bars_m1 = self.hub.get_bars(symbol, "1m")
            if bars_m1 is None or len(bars_m1) < 5:
                log.warning("[SKIP] %s yetersiz 1m bar: %d", symbol, len(bars_m1) if bars_m1 else 0)
                return

            events = self.analyzers[symbol].analyze(
                bars_d1=bars_d1,
                bars_h4=bars_h4,
                bars_h1=bars_h1,
                bars_15m=bars_15m,
                bars_m1=bars_m1,
            )
            if events:
                for event in events:
                    self.event_router.publish(symbol, event)

                # State logging
                current_state = self.state_machine.get(symbol)

                # Boolean deÃ„Å¸erleri fmt_bool ile gÃƒÂ¶rsel log
                s_sweep = fmt_bool(current_state.sweep_detected)
                s_mss = fmt_bool(current_state.mss_confirmed)
                s_retrace = fmt_bool(current_state.retrace_seen)
                s_ltf = fmt_bool(current_state.ltf_confirmed)

                # TÃƒÂ¼m flag'ler emoji formatÃ„Â±nda
                s_sweep = "Ã°Å¸Å¸Â©" if current_state.sweep_detected else "Ã°Å¸Å¸Â¥"
                s_mss = "Ã°Å¸Å¸Â©" if current_state.mss_confirmed else "Ã°Å¸Å¸Â¥"
                s_retrace = "Ã°Å¸Å¸Â©" if current_state.retrace_seen else "Ã°Å¸Å¸Â¥"
                s_ltf = "Ã°Å¸Å¸Â©" if current_state.ltf_confirmed else "Ã°Å¸Å¸Â¥"

                # FVG dinamik alan
                if current_state.fvg_upper is None or current_state.fvg_lower is None:
                    fvg_display = "Ã°Å¸Å¸Â¥"
                elif current_state.retrace_seen:
                    fvg_display = "fvg_a Ã°Å¸Å¸Â©"
                elif current_state.fvg_missed:
                    fvg_display = "fvg_c Ã°Å¸Å¸Â©"
                elif getattr(current_state, "invalidated", False):
                    fvg_display = "Ã¢Â¬â€º"
                else:
                    fvg_display = "Ã°Å¸Å¸Â¨"

                log.info(
                    "[STATE-DEBUG] %s | state=%s | sweep=%s | mss=%s | fvg=%s | retrace=%s | ltf=%s",
                    symbol,
                    current_state.state,
                    s_sweep,
                    s_mss,
                    fvg_display,
                    s_retrace,
                    s_ltf,
                )

        except Exception as e:
            log.error("[_on_1m_close] %s | Hata: %s", symbol, str(e), exc_info=True)

    # ------------------------------------------------------------------
    # API Server Ã¢â‚¬â€ dashboard iÃƒÂ§in
    # ------------------------------------------------------------------
    async def _start_api_server(self):
        from aiohttp import web

        async def api_health(request):
            return web.json_response(monitor.get_health())

        async def api_balance(request):
            return web.json_response(
                {
                    "balance": self._balance,
                    "wallet_balance": self._wallet_balance,
                    "unrealized_pnl": self._unrealized_pnl,
                    "margin_balance": self._margin_balance,
                    "available_balance": self._available_balance,
                    "used_margin": self._used_margin,
                    "currency": "USDT/FDUSD",
                    "updated": datetime.now(UTC).isoformat(),
                }
            )

        async def api_positions(request):
            trades = []
            for sym, t in self.active_trades.items():
                trades.append(
                    {
                        "symbol": sym,
                        "direction": t.get("direction", "").upper(),
                        "entry": t.get("entry"),
                        "sl": t.get("current_sl", t.get("initial_sl")),
                        "tp": t.get("tp"),
                        "lot": t.get("lot"),
                        "pnl": round(t.get("pnl", 0), 4),
                        "last_price": t.get("last_price"),
                        "leverage": config.LEVERAGE,
                    }
                )
            return web.json_response(trades)

        async def api_prices(request):
            prices = {}
            for sym in config.SYMBOLS:
                bars = self.hub.get_bars(sym, "5m")
                if bars:
                    b = bars[-1]
                    prices[sym] = {
                        "close": b.close,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "volume": b.volume,
                    }
            return web.json_response(prices)

        async def api_stats(request):
            h = monitor.get_health()
            total_signals = sum(v.get("signal_count", 0) for v in h.get("symbols", {}).values())
            total_rejects = sum(v.get("rejected_count", 0) for v in h.get("symbols", {}).values())
            total_orders = sum(v.get("order_count", 0) for v in h.get("symbols", {}).values())
            total_fills = sum(v.get("fill_count", 0) for v in h.get("symbols", {}).values())
            live_count = sum(1 for v in h.get("symbols", {}).values() if v.get("status") == "LIVE")
            return web.json_response(
                {
                    "total_signals": total_signals,
                    "total_rejects": total_rejects,
                    "total_orders": total_orders,
                    "total_fills": total_fills,
                    "live_symbols": live_count,
                    "total_symbols": len(config.SYMBOLS),
                    "active_trades": len(self.active_trades),
                    "balance": self._balance,
                }
            )

        async def api_breakeven_stats(request):
            """Breakeven ADX>35 korelasyon istatistikleri."""
            total_be = sum(v["count"] for v in self._breakeven_log.values())
            total_adx35 = sum(v["adx_gt_35"] for v in self._breakeven_log.values())
            corr_pct = (total_adx35 / total_be * 100) if total_be > 0 else 0.0
            return web.json_response(
                {
                    "total_breakeven": total_be,
                    "adx_gt_35_breakeven": total_adx35,
                    "correlation_pct": round(corr_pct, 1),
                    "symbols": {
                        sym: {
                            "count": info["count"],
                            "adx_gt_35": info["adx_gt_35"],
                            "adx_pct": round((info["adx_gt_35"] / info["count"]) * 100, 1)
                            if info["count"] > 0
                            else 0.0,
                        }
                        for sym, info in self._breakeven_log.items()
                    },
                }
            )

        async def api_performance(request):
            return web.json_response(performance.get_leaderboard())

        async def api_trades(request):
            trades = performance.get_trade_log()
            formatted_trades = []
            for t in trades:
                row = t.copy()
                ts_str = row.get("ts", "")
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        row["close_time"] = int(dt.timestamp() * 1000)
                    except Exception:
                        row["close_time"] = None
                else:
                    row["close_time"] = None

                row["exit_price"] = row.get("exit")
                row["gross_rr"] = row.get("rr")
                formatted_trades.append(row)

            return web.json_response(formatted_trades)

        async def dashboard(request):
            filepath = os.path.join(os.path.dirname(__file__), "..", "web", "dashboard.html")
            if os.path.exists(filepath):
                return web.FileResponse(filepath)
            return web.Response(text="dashboard.html bulunamadÃ„Â±", status=404)

        app = web.Application()
        app.router.add_get("/", dashboard)
        app.router.add_get("/api/health", api_health)
        app.router.add_get("/api/balance", api_balance)
        app.router.add_get("/api/positions", api_positions)
        app.router.add_get("/api/prices", api_prices)
        app.router.add_get("/api/stats", api_stats)
        app.router.add_get("/api/performance", api_performance)
        app.router.add_get("/api/breakeven", api_breakeven_stats)
        app.router.add_get("/api/trades", api_trades)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()
        log.info("Dashboard API baÃ…Å¸latÃ„Â±ldÃ„Â± Ã¢â€ â€™ http://0.0.0.0:8080 (sadece local)")

    # ------------------------------------------------------------------
    # Ana dÃƒÂ¶ngÃƒÂ¼
    # ------------------------------------------------------------------
    async def run(self):
        # Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â
        # MEKANÃ„Â°K AKIÃ…Å¾: Cleanup Ã¢â€ â€™ Sync Ã¢â€ â€™ Safe Mode Ã¢â€ â€™ Run
        # TÃƒÂ¼m adÃ„Â±mlar baÃ„Å¸Ã„Â±msÃ„Â±z: biri hata verirse diÃ„Å¸eri ÃƒÂ§alÃ„Â±Ã…Å¸Ã„Â±r.
        # Ã¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢ÂÃ¢â€¢Â

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 0: Bakiye (hatada varsayÃ„Â±lanla devam) Ã¢â€â‚¬Ã¢â€â‚¬
        try:
            await self._sync_balance()
        except Exception as e:
            log.critical("Ã¢Å¡Â Ã¯Â¸Â Bakiye alÃ„Â±namadÃ„Â±: %s Ã¢â‚¬â€ varsayÃ„Â±lan 1000 USDT ile devam", e)
            self._balance = 1000.0
            for rm in self.risk_managers.values():
                rm.balance = self._balance

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 0.5: State dosyasÃ„Â±ndan kaldÃ„Â±Ã„Å¸Ã„Â± yerden devam Ã¢â€â‚¬Ã¢â€â‚¬
        try:
            self._load_state()
        except Exception as e:
            log.warning("[STATE] _load_state hatasÃ„Â± Ã¢â‚¬â€ temiz baÃ…Å¸langÃ„Â±ÃƒÂ§: %s", e)

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 1: PozisyonlarÃ„Â± yÃƒÂ¼kle (API'den) Ã¢â‚¬â€ CLEANUP'TAN Ãƒâ€“NCE!
        # Ãƒâ€“NEMLÃ„Â°: Ãƒâ€“nce pozisyon yÃƒÂ¼klenir ki _startup_cleanup, active_trades listesini
        # kullanarak "ORPHAN-GUARD" korumasÃ„Â± yapabilsin.
        # Aksi halde active_trades boÃ…Å¸ olur, API kÃ„Â±smi response dÃƒÂ¶ndÃƒÂ¼Ã„Å¸ÃƒÂ¼nde
        # tÃƒÂ¼m SL/TP'ler "orphan" sanÃ„Â±lÃ„Â±p silinir. (Bkz. F11 Ã¢â‚¬â€ F13 arasÃ„Â± fix'ler)
        try:
            await self._load_existing_positions()
        except Exception as e:
            log.critical("Ã¢Å¡Â Ã¯Â¸Â Pozisyon yÃƒÂ¼kleme baÃ…Å¸arÃ„Â±sÃ„Â±z: %s Ã¢â‚¬â€ boÃ…Å¸ envanterle devam", e)

        # Ã¢â€â‚¬Ã¢â€â‚¬ State'i diske yaz (startup sonrasÃ„Â±) Ã¢â€â‚¬Ã¢â€â‚¬
        self._flush_state()

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 2: STARTUP CLEANUP (Sorgusuz Ã„Â°nfaz)
        # Bu noktada active_trades dolu olduÃ„Å¸u iÃƒÂ§in ORPHAN-GUARD korumasÃ„Â± ÃƒÂ§alÃ„Â±Ã…Å¸Ã„Â±r:
        # API'de pozisyon gÃƒÂ¶rÃƒÂ¼nmese bile local state'te trade varsa emirler SÃ„Â°LÃ„Â°NMEZ.
        try:
            await self._startup_cleanup()
        except Exception as e:
            log.critical("Ã¢Å¡Â Ã¯Â¸Â Cleanup baÃ…Å¸arÃ„Â±sÃ„Â±z: %s Ã¢â‚¬â€ temizlik atlanarak devam", e)

        # Ã¢â€â‚¬Ã¢â€â‚¬ Cleanup sonrasÃ„Â± state'i gÃƒÂ¼ncelle Ã¢â€â‚¬Ã¢â€â‚¬
        self._flush_state()

        # Ã¢â€â‚¬Ã¢â€â‚¬ Startup tamamlandÃ„Â± iÃ…Å¸areti Ã¢â€â‚¬Ã¢â€â‚¬
        self.executor.mark_startup_complete()

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 2.5: User Data Stream (listenKey) Ã¢â€â‚¬Ã¢â€â‚¬
        try:
            listen_key = http_client.new_listen_key()
            if listen_key:
                # WS_BASE_URL'den user data WS base URL'ini tÃƒÂ¼ret
                # "wss://stream.binancefuture.com/stream?streams=" Ã¢â€ â€™ "wss://stream.binancefuture.com"
                from urllib.parse import urlparse

                parsed = urlparse(WS_BASE_URL)
                ws_base = f"{parsed.scheme}://{parsed.netloc}"
                self.hub.set_user_data_listen_key(listen_key, ws_base_url=ws_base)
                log.info("[USER_DATA] Listen key oluÃ…Å¸turuldu: %s...", listen_key[:10])

                # ORDER_TRADE_UPDATE callback Ã¢â‚¬â€ anlÃ„Â±k emir durumu
                @self.hub.on_user_data("ORDER_TRADE_UPDATE")
                async def on_order_update(msg: dict):
                    order_data = msg.get("o", {})
                    sym = order_data.get("s", "")
                    status = order_data.get("X", "")
                    log.info(
                        "[USER_DATA] ORDER_TRADE_UPDATE | %s | status=%s | type=%s",
                        sym,
                        status,
                        order_data.get("o", ""),
                    )

                # ACCOUNT_UPDATE callback Ã¢â‚¬â€ anlÃ„Â±k pozisyon/bakiye gÃƒÂ¼ncellemesi
                @self.hub.on_user_data("ACCOUNT_UPDATE")
                async def on_account_update(msg: dict):
                    update_data = msg.get("a", {})
                    reason = update_data.get("m", "")
                    balances = update_data.get("B", [])
                    positions = update_data.get("P", [])

                    # Real-time bakiye gÃƒÂ¼ncellemesi (60sn polling'e alternatif)
                    for bal in balances:
                        asset = bal.get("a", "")
                        if asset in ("USDT", "FDUSD", "USDC"):
                            self._wallet_balance = float(bal.get("wb", self._wallet_balance))
                            self._available_balance = float(bal.get("bc", self._available_balance))
                            self._balance = self._available_balance
                    if balances:
                        log.debug(
                            "[USER_DATA] ACCOUNT_UPDATE | reason=%s | %d balance gÃƒÂ¼ncellendi", reason, len(balances)
                        )

                    for pos in positions:
                        sym = pos.get("s", "")
                        if sym in self.active_trades:
                            self.active_trades[sym]["pnl"] = float(pos.get("up", 0))
                            self.active_trades[sym]["last_price"] = float(pos.get("ep", 0))
                    if positions:
                        log.debug(
                            "[USER_DATA] ACCOUNT_UPDATE | reason=%s | %d pozisyon gÃƒÂ¼ncellendi", reason, len(positions)
                        )
        except Exception as e:
            log.warning("[USER_DATA] Listen key oluÃ…Å¸turulamadÃ„Â± (devam): %s", e)

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 3: Buffer'larÃ„Â± ÃƒÂ¶n doldur Ã¢â€â‚¬Ã¢â€â‚¬
        await self._prefill_buffers()

        async def _wrapper(bars, sym):
            await self._on_1m_close(sym, bars)

        for sym in config.SYMBOLS:

            def make_callback(s):
                async def cb(bars):
                    if bars:
                        export_ohlc_1m(bars[-1], s)
                    await _wrapper(bars, s)

                return cb

            self.hub.register_callback(sym, "1m", make_callback(sym))

        await asyncio.gather(*[self.daily_cache.get(sym) for sym in config.SYMBOLS])
        log.info("BaÃ…Å¸langÃ„Â±ÃƒÂ§ tamamlandÃ„Â±, WebSocket hub baÃ…Å¸latÃ„Â±lÃ„Â±yor...")

        async def _health_loop():
            while True:
                await asyncio.sleep(60)
                try:
                    await self._sync_balance()
                except Exception as e:
                    log.warning("[HEALTH] Bakiye sync hatasÃ„Â± (sonraki denenecek): %s", e)
                try:
                    h = monitor.get_health()
                    log.info(f"[HEALTH] {json.dumps(h)}")
                except Exception:
                    pass

        # Ã¢â€â‚¬Ã¢â€â‚¬ ADIM 4: RUN Ã¢â‚¬â€ tÃƒÂ¼m arka plan task'larÃ„Â± baÃ…Å¸lat Ã¢â€â‚¬Ã¢â€â‚¬
        asyncio.create_task(_health_loop())
        asyncio.create_task(self._start_api_server())
        await self.hub.run()


# -------------------------------------------------------------------
# Entry
# -------------------------------------------------------------------
if __name__ == "__main__":
    performance.initialize()
    bot = LiveTradingBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        log.info("KullanÃ„Â±cÃ„Â± tarafÃ„Â±ndan durduruldu.")
        bot.hub.stop()



