#!/usr/bin/env python3
"""
main_live.py ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â NEXUS V2 CanlÃƒâ€žÃ‚Â± Trading Botu (Production-Ready)
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
    format="%(asctime)s [%(levelname)s] %(name)s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.TimedRotatingFileHandler(
            filename="output/trading/live_trading.log",
            when="midnight",
            backupCount=10,
            encoding="utf-8-sig",
        ),
    ],
)
log = logging.getLogger("nexus.live")
# Force UTF-8 console on capable runtimes
try:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# -------------------------------------------------------------------
# .env ve HTTP Client (ccxt kullanÃƒâ€žÃ‚Â±lmÃƒâ€žÃ‚Â±yor ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â direkt REST)
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
    log.info("Futures DEMO modu ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ %s", BASE_URL)
else:
    log.warning("ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â  CANLI FUTURES MODU ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â DÃƒâ€žÃ‚Â°KKAT!")

# ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ BinanceHTTPClient (emir/pozisyon/bakiye/OHLCV ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â tÃƒÆ’Ã‚Â¼m iÃƒâ€¦Ã…Â¸lemler) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
http_client = BinanceHTTPClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    base_url=BASE_URL,
    timeout=30,
    portfolio_margin=False,  # PM hesabÃƒâ€žÃ‚Â± iÃƒÆ’Ã‚Â§in True, Cross Margin iÃƒÆ’Ã‚Â§in False
)
log.info("BinanceHTTPClient oluÃƒâ€¦Ã…Â¸turuldu ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ %s", BASE_URL)

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
    """ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ / ÃƒÂ¢Ã‚ÂÃ…â€™ ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â boolean deÃƒâ€žÃ…Â¸erleri gÃƒÆ’Ã‚Â¶rsel log iÃƒÆ’Ã‚Â§in formatla."""
    return "ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦" if val else "ÃƒÂ¢Ã‚ÂÃ…â€™"


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
            log.error(f"D1 verisi alÃƒâ€žÃ‚Â±namadÃƒâ€žÃ‚Â± {symbol}: {e}")


# -------------------------------------------------------------------
# Global Rate Limiter ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Binance IP limiti: 6000 req/min
# -------------------------------------------------------------------
class _RateLimiter:
    """Token bucket: dakikada max N istek, asyncio-safe."""

    def __init__(self, max_per_minute: int = 5000):
        self._interval = 60.0 / max_per_minute  # istekler arasÃƒâ€žÃ‚Â± min sÃƒÆ’Ã‚Â¼re (sn)
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

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Global API Semaphore: maks 5 eÃƒâ€¦Ã…Â¸zamanlÃƒâ€žÃ‚Â± istek ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        # TÃƒÆ’Ã‚Â¼m _fetch_binance_signed, _signed_post, _signed_delete ÃƒÆ’Ã‚Â§aÃƒâ€žÃ…Â¸rÃƒâ€žÃ‚Â±larÃƒâ€žÃ‚Â±
        # bu semafor ÃƒÆ’Ã‚Â¼zerinden geÃƒÆ’Ã‚Â§er. 20 sembol aynÃƒâ€žÃ‚Â± anda patlasa bile
        # sadece 5 tanesi API'ye vurur, kalanÃƒâ€žÃ‚Â± kuyruÃƒâ€žÃ…Â¸a girer.
        self._api_semaphore = asyncio.Semaphore(5)
        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Global Rate Limiter: dakikada max 5000 istek (6000 limit korumasÃƒâ€žÃ‚Â±) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        self._rate_limiter = _RateLimiter(max_per_minute=5000)

        self._breakeven_log: dict[str, dict] = {}  # {symbol: {"count": int, "adx_gt_35": int, "last_time": ms}}
        self._last_be_summary: float = 0.0  # son ÃƒÆ’Ã‚Â¶zet log zamanÃƒâ€žÃ‚Â± (unix timestamp)

    # ------------------------------------------------------------------
    # State persistence (VS koparsa / bot resize ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â kaldÃƒâ€žÃ‚Â±Ãƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â± yerden devam)
    # ------------------------------------------------------------------
    STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "nexus_state.json")

    def _flush_state(self):
        """active_trades + symbol_states ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ nexus_state.json yaz."""
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
            with open(self.STATE_FILE, "w", encoding="utf-8-sig") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            log.debug("[STATE] Flush: %d trade, %d state", len(self.active_trades), len(symbol_states))
        except Exception as e:
            log.error("[STATE] _flush_state hatasÃƒâ€žÃ‚Â±: %s", e)

    def _load_state(self):
        """nexus_state.json ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ active_trades + symbol_states yÃƒÆ’Ã‚Â¼kle (startup)."""
        if not os.path.exists(self.STATE_FILE):
            log.info("[STATE] nexus_state.json yok, temiz baÃƒâ€¦Ã…Â¸langÃƒâ€žÃ‚Â±ÃƒÆ’Ã‚Â§")
            return
        try:
            with open(self.STATE_FILE, encoding="utf-8-sig") as f:
                data = json.load(f)
            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ active_trades ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            trades = data.get("active_trades", {})
            if trades:
                self.active_trades.update(trades)
                log.info("[STATE] %d trade geri yÃƒÆ’Ã‚Â¼klendi", len(trades))
            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ symbol_states ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                    log.warning("[STATE] %s state yÃƒÆ’Ã‚Â¼klenemedi: %s", sym, e)
            if restored:
                log.info("[STATE] %d symbol state geri yÃƒÆ’Ã‚Â¼klendi", restored)
        except Exception as e:
            log.error("[STATE] _load_state hatasÃƒâ€žÃ‚Â±: %s", e)

    def _clear_state(self, symbol: str):
        """Trade kapanÃƒâ€žÃ‚Â±nca sembolÃƒÆ’Ã‚Â¼ state'ten sil ve flush et."""
        self.active_trades.pop(symbol, None)
        self.state_machine.clear(symbol)
        # [FIX-3] Analyzer cache'ini state machine ile sync et.
        # State machine IDLE'a dÃƒÆ’Ã‚Â¶ndÃƒÆ’Ã‚Â¼Ãƒâ€žÃ…Â¸ÃƒÆ’Ã‚Â¼nde _emitted_fvg_ids ve _seen_mss
        # temizlenmezse aynÃƒâ€žÃ‚Â± sembol iÃƒÆ’Ã‚Â§in yeni setup oluÃƒâ€¦Ã…Â¸tuÃƒâ€žÃ…Â¸unda FVG/MSS
        # eventleri "already emitted" filtresinden geÃƒÆ’Ã‚Â§emez, fvg_upper=None
        # ile WAIT_RETRACE'de mahsur kalÃƒâ€žÃ‚Â±r.
        if symbol in self.analyzers:
            self.analyzers[symbol].reset_symbol_cache()
        self._flush_state()

    @staticmethod
    def _get_order_type(order: dict) -> str:
        """Standard endpoint (`type`) ve algo endpoint (`orderType`) response alanÃƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± birleÃƒâ€¦Ã…Â¸tirir."""
        return order.get("type") or order.get("orderType") or ""

    @staticmethod
    def _get_order_price(order: dict) -> float:
        """Algo emirlerinde `triggerPrice`, normal emirlerde `stopPrice` kullanÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±r."""
        return float(order.get("triggerPrice") or order.get("stopPrice") or 0)

    @staticmethod
    def _safe_order_timestamp(order: dict) -> int:
        """GÃƒÆ’Ã‚Â¼venli timestamp ÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±karma. None/geÃƒÆ’Ã‚Â§ersiz deÃƒâ€žÃ…Â¸erlerde 0 dÃƒÆ’Ã‚Â¶ner, ValueError patlamaz."""
        try:
            raw = order.get("updateTime") or order.get("time") or 0
            return int(raw)
        except (ValueError, TypeError):
            return 0

    async def _wait_for_position(self, symbol: str, timeout: float = 2.0) -> dict | None:
        """Pozisyonun borsada oluÃƒâ€¦Ã…Â¸masÃƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± bekle."""
        start = time.time()
        while time.time() - start < timeout:
            pos = await self.executor.get_position(symbol)
            if pos and abs(float(pos.get("contracts", 0))) > 0:
                return pos
            await asyncio.sleep(0.1)
        return None

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Merkezi async imzalÃƒâ€žÃ‚Â± istek yardÃƒâ€žÃ‚Â±mcÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â± (retry + backoff + semaphore) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬

    async def _fetch_binance_signed(self, endpoint: str, params: str = "", max_retries: int = 3) -> dict:
        await self._rate_limiter.acquire()  # RATE LIMIT: dakikada max 5000 istek
        async with self._api_semaphore:  # RATE LIMIT: maks 5 eÃƒâ€¦Ã…Â¸zamanlÃƒâ€žÃ‚Â± istek
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
                        "[HTTP] %s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ %s (attempt %d/%d, url=%s)",
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
                        "[HTTP] %s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ %s (attempt %d/%d)",
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
        async with self._api_semaphore:  # RATE LIMIT: maks 5 eÃƒâ€¦Ã…Â¸zamanlÃƒâ€žÃ‚Â± istek
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
            log.error("[ORDERS] AÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emirler alÃƒâ€žÃ‚Â±namadÃƒâ€žÃ‚Â± %s: %s", symbol, e)
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
                "Bakiye ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â wallet=%.2f margin=%.2f uPnL=%.2f available=%.2f used_margin=%.2f",
                self._wallet_balance,
                self._margin_balance,
                self._unrealized_pnl,
                self._available_balance,
                self._used_margin,
            )
        except Exception as e:
            log.error("Bakiye alÃƒâ€žÃ‚Â±namadÃƒâ€žÃ‚Â±: %s", e)

    # ------------------------------------------------------------------
    # Buffer ÃƒÆ’Ã‚Â¶n doldurma
    # ------------------------------------------------------------------
    async def _prefill_buffers(self):
        loop = asyncio.get_running_loop()

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Tick size cache'leri ÃƒÆ’Ã‚Â¶nceden doldur ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        for sym in config.SYMBOLS:
            await loop.run_in_executor(None, lambda s=sym: _get_tick_size(s))

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ RATE LIMIT FIX: Semaphore ile maks 3 eÃƒâ€¦Ã…Â¸zamanlÃƒâ€žÃ‚Â± istek ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                    log.info(f"[PREFILL] {s} {t} {len(bars)} bar yÃƒÆ’Ã‚Â¼klendi")
                except Exception as e:
                    log.error(f"[PREFILL] {s} {t} hata: {e}")
                finally:
                    # Her istek arasÃƒâ€žÃ‚Â± 200ms bekle (rate limit korumasÃƒâ€žÃ‚Â±)
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
            log.warning(f"[PREFILL] {len(errors)} sembol/timeframe yÃƒÆ’Ã‚Â¼klenemedi")
        else:
            log.info("[PREFILL] TÃƒÆ’Ã‚Â¼m buffer'lar baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±yla yÃƒÆ’Ã‚Â¼klendi")

    # ------------------------------------------------------------------
    # STARTUP CLEANUP ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â yetim/duplicate emir temizliÃƒâ€žÃ…Â¸i
    # ------------------------------------------------------------------
    async def _startup_cleanup(self):
        """
        ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ PROTOKOLÃƒÆ’Ã…â€œ
        Binance'teki tÃƒÆ’Ã‚Â¼m aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emirleri tara, TEK GERÃƒÆ’Ã¢â‚¬Â¡EKLÃƒâ€žÃ‚Â°K KAYNAÃƒâ€žÃ…Â¾I: Binance API.
          ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ Pozisyonu OLMAYAN semboldeki emirler ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ komple iptal (orphan)
          ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â¢ Duplicate SL/TP (>1 SL veya >1 TP) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ TÃƒÆ’Ã…â€œM koruma (SL+TP) SÃƒâ€žÃ‚Â°LÃƒâ€žÃ‚Â°NÃƒâ€žÃ‚Â°R
            "En yeniyi tut" YOK. Safe Mode sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rdan dizecek.
        """
        log.info("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ STARTUP CLEANUP | tÃƒÆ’Ã‚Â¼m aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emirler taranÃƒâ€žÃ‚Â±yor...")

        try:
            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ TÃƒÆ’Ã‚Â¼m pozisyonlarÃƒâ€žÃ‚Â± ÃƒÆ’Ã‚Â§ek ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            loop = asyncio.get_running_loop()
            positions_raw = await loop.run_in_executor(None, lambda: http_client.get_positions())
            positions_list = positions_raw if isinstance(positions_raw, list) else []

            # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ FIX: positions_list boÃƒâ€¦Ã…Â¸ ise (API hatasÃƒâ€žÃ‚Â± / rate limit) cleanup ATLANIR
            # Aksi halde TÃƒÆ’Ã…â€œM emirler "orphan" sanÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±p silinir!
            if not positions_list:
                log.warning(
                    "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | positions_list BOÃƒâ€¦Ã…Â¾ (API hatasÃƒâ€žÃ‚Â±/rate limit) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â hiÃƒÆ’Ã‚Â§bir emir silinmeyecek"
                )
                return

            symbols_with_position = set()
            for p in positions_list:
                amt = float(p.get("positionAmt", 0))
                if amt != 0:
                    symbols_with_position.add(p["symbol"])

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ KÃƒâ€žÃ‚Â±smi API response retry: active_trades'te olup symbols_with_position'da OLMAYAN sembolleri tara ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            missing_symbols = [s for s in self.active_trades if s not in symbols_with_position]
            if missing_symbols:
                log.warning(
                    "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | %d sembol API'de eksik (kÃƒâ€žÃ‚Â±smi response?) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ 1sn bekleyip tekrar sorgulanÃƒâ€žÃ‚Â±yor: %s",
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

            # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ FIX: API'de pozisyon yok ama local state'te trade var ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ cleanup ATLANIR
            if not symbols_with_position and self.active_trades:
                log.warning(
                    "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | API'de pozisyon bulunamadÃƒâ€žÃ‚Â± ama local state'te %d trade var ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â cleanup ATLANIYOR",
                    len(self.active_trades),
                )
                return

            total_cancelled = 0

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ TÃƒÆ’Ã…â€œM aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emirleri TEK SEFERDE ÃƒÆ’Ã‚Â§ek (normal + algo) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            all_orders_raw = await self._fetch_binance_signed("/fapi/v1/openOrders")
            all_orders = all_orders_raw if isinstance(all_orders_raw, list) else []

            # Algo emirlerini de ÃƒÆ’Ã‚Â§ek (SL/TP orphan'larÃƒâ€žÃ‚Â± iÃƒÆ’Ã‚Â§in kritik!)
            try:
                algo_raw = await self._fetch_binance_signed("/fapi/v1/openAlgoOrders")
                algo_orders = algo_raw if isinstance(algo_raw, list) else []
                all_orders.extend(algo_orders)
                log.info(
                    "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | %d normal + %d algo = %d toplam emir",
                    len(all_orders) - len(algo_orders),
                    len(algo_orders),
                    len(all_orders),
                )
            except Exception as e:
                log.warning("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | algoOrders alÃƒâ€žÃ‚Â±namadÃƒâ€žÃ‚Â± (devam): %s", e)
            log.info(
                "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | toplam %d aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emir bulundu (tÃƒÆ’Ã‚Â¼m semboller)",
                len(all_orders),
            )

            # Sembole gÃƒÆ’Ã‚Â¶re grupla
            orders_by_symbol: dict = {}
            for o in all_orders:
                sym = o.get("symbol", "")
                if sym not in orders_by_symbol:
                    orders_by_symbol[sym] = []
                orders_by_symbol[sym].append(o)

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Config sembolleri + aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emri olan tÃƒÆ’Ã‚Â¼m semboller ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            all_symbols_to_check = set(config.SYMBOLS) | set(orders_by_symbol.keys())

            for symbol in sorted(all_symbols_to_check):
                orders = orders_by_symbol.get(symbol, [])
                if not orders:
                    continue

                try:
                    if symbol not in symbols_with_position:
                        # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â FIX: Local state'te trade varsa API eksik dÃƒÆ’Ã‚Â¶nmÃƒÆ’Ã‚Â¼Ãƒâ€¦Ã…Â¸ olabilir ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ ATLA
                        if symbol in self.active_trades:
                            log.warning(
                                "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [ORPHAN-GUARD] %s API'de pozisyon yok ama local state'te trade var ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â ATLANIYOR",
                                symbol,
                            )
                            continue
                        # ÃƒÂ¢Ã‚ÂÃ…â€™ ORPHAN: emir var ama pozisyon yok ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ hepsini iptal
                        log.warning(
                            "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [ORPHAN] %s | %d emir var ama POZÃƒâ€žÃ‚Â°SYON YOK ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ iptal ediliyor",
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
                        # ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ Pozisyon var ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ duplicate kontrolÃƒÆ’Ã‚Â¼
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

                        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ (V2 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Atomic Swap) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                        # ESKÃƒâ€žÃ‚Â°: >1 SL veya >1 TP ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ TÃƒÆ’Ã…â€œM koruma SÃƒâ€žÃ‚Â°LÃƒâ€žÃ‚Â°NÃƒâ€žÃ‚Â°R, Safe Mode sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rdan dizecek.
                        # YENÃƒâ€žÃ‚Â°: En az 1 SL + 1 TP korunur, sadece fazlalÃƒâ€žÃ‚Â±klar iptal edilir.
                        # ÃƒÆ’Ã¢â‚¬Â¡IPLAK PENCERE YOK ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â pozisyon asla stopsuz kalmaz.
                        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                        if len(sl_orders) > 1 or len(tp_orders) > 1:
                            log.critical(
                                "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ] %s | SL=%d TP=%d ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ "
                                "fazlalÃƒâ€žÃ‚Â±klar temizleniyor, EN AZ 1 SL + 1 TP KORUNUYOR",
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
                                                "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [INFAZ-SL] %s | orderId=%s iptal BAÃƒâ€¦Ã…Â¾ARISIZ (tetiklenmiÃƒâ€¦Ã…Â¸ olabilir): %s",
                                                symbol,
                                                order_id,
                                                cancel_err,
                                            )
                                    await asyncio.sleep(0.15)
                                log.info(
                                    "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [INFAZ-SL] %s | %d fazla SL iptal edildi",
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
                                                "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [INFAZ-TP] %s | orderId=%s iptal BAÃƒâ€¦Ã…Â¾ARISIZ (tetiklenmiÃƒâ€¦Ã…Â¸ olabilir): %s",
                                                symbol,
                                                order_id,
                                                cancel_err,
                                            )
                                    await asyncio.sleep(0.15)
                                log.info(
                                    "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ [INFAZ-TP] %s | %d fazla TP iptal edildi",
                                    symbol,
                                    len(tp_orders) - 1,
                                )

                except Exception as e:
                    log.warning("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ CLEANUP | %s taranÃƒâ€žÃ‚Â±rken hata: %s", symbol, e)
                    continue

            if total_cancelled:
                log.warning("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ STARTUP CLEANUP | TOPLAM %d EMÃƒâ€žÃ‚Â°R Ãƒâ€žÃ‚Â°PTAL EDÃƒâ€žÃ‚Â°LDÃƒâ€žÃ‚Â°", total_cancelled)
            else:
                log.info("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ STARTUP CLEANUP | temiz, iptal gereken emir yok")

        except Exception as e:
            log.error("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ STARTUP CLEANUP hatasÃƒâ€žÃ‚Â±: %s", e)

    async def _cancel_order_by_id(self, order_id, symbol: str, reason: str = "", is_algo: bool = False) -> bool:
        """Tek bir emri Binance REST API ile iptal et (DELETE)."""
        if is_algo:
            try:
                params = f"symbol={symbol}&algoId={order_id}"
                await self._fetch_binance_signed_delete("/fapi/v1/algoOrder", params)
                log.info("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL (algo) | %s algoId=%s reason=%s", symbol, order_id, reason)
                return True
            except Exception as e:
                err = str(e)
                if "Unknown order" in err or "-2011" in err:
                    log.info(
                        "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL (algo) | %s algoId=%s zaten yok (ok)",
                        symbol,
                        order_id,
                    )
                    return True
                log.warning("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL hatasÃƒâ€žÃ‚Â± (algo) %s algoId=%s: %s", symbol, order_id, e)
                return False
        else:
            try:
                params = f"symbol={symbol}&orderId={order_id}"
                await self._fetch_binance_signed_delete("/fapi/v1/order", params)
                log.info("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL | %s orderId=%s reason=%s", symbol, order_id, reason)
                return True
            except Exception as e:
                err = str(e)
                if "Unknown order" in err or "-2011" in err:
                    log.info("ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL | %s orderId=%s zaten yok (ok)", symbol, order_id)
                    return True
                # Algo order olabilir, onun endpoint'iyle dene
                try:
                    params = f"symbol={symbol}&algoId={order_id}"
                    await self._fetch_binance_signed_delete("/fapi/v1/algoOrder", params)
                    log.info(
                        "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL (algo fallback) | %s algoId=%s reason=%s",
                        symbol,
                        order_id,
                        reason,
                    )
                    return True
                except Exception as e2:
                    log.warning(
                        "ÃƒÂ°Ã…Â¸Ã‚Â§Ã‚Â¹ Ãƒâ€žÃ‚Â°PTAL hatasÃƒâ€žÃ‚Â± %s orderId=%s (normal+algo): %s / %s",
                        symbol,
                        order_id,
                        e,
                        e2,
                    )
                    return False

    async def _fetch_binance_signed_delete(self, endpoint: str, params: str = "") -> dict:
        """DELETE isteÃƒâ€žÃ…Â¸i iÃƒÆ’Ã‚Â§in ÃƒÆ’Ã‚Â¶zel metod."""
        await self._rate_limiter.acquire()  # RATE LIMIT: dakikada max 5000 istek
        async with self._api_semaphore:  # RATE LIMIT: maks 5 eÃƒâ€¦Ã…Â¸zamanlÃƒâ€žÃ‚Â± istek
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
                log.debug("DELETE %s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ HTTP %s: %s", endpoint, e.code, body)
                raise Exception(f"HTTP {e.code}: {body}") from e

    # ------------------------------------------------------------------
    # Restart sonrasÃƒâ€žÃ‚Â± aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k pozisyonlarÃƒâ€žÃ‚Â± yÃƒÆ’Ã‚Â¼kle (TEK KAYNAK: API)
    # ------------------------------------------------------------------
    async def _load_existing_positions(self):
        """
        Cleanup sonrasÃƒâ€žÃ‚Â± kalan pozisyonlarÃƒâ€žÃ‚Â± API'den okuyup envantere al.
        Koruma durumu API'den sorgulanÃƒâ€žÃ‚Â±r ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â local state'e gÃƒÆ’Ã‚Â¼venilmez.
        """
        try:
            log.info("ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ¢â‚¬Å¾ RESTART | pozisyonlar yÃƒÆ’Ã‚Â¼kleniyor (API)...")
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

                # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ API'den aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k emirleri ÃƒÆ’Ã‚Â§ek (retry, normal + algo) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                            "[RECOVER] %s openAlgoOrders hatasÃƒâ€žÃ‚Â± (ÃƒÆ’Ã‚Â¶nemsiz): %s",
                            symbol,
                            e,
                        )

                    if open_orders:
                        break

                    if attempt < 2:
                        log.warning(
                            "[RECOVER] %s openOrders BOÃƒâ€¦Ã…Â¾ (attempt %d/3) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â 1.5s",
                            symbol,
                            attempt + 1,
                        )
                await asyncio.sleep(1.5)

                # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Koruma emirlerini API'den say ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                    "[RECOVER] %s pozisyon=%s giriÃƒâ€¦Ã…Â¸=%.4f SL=%d TP=%d",
                    symbol,
                    direction,
                    entry,
                    n_sl,
                    n_tp,
                )

                if n_sl == 1 and n_tp == 1:
                    # ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ TAM KORUMA ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â API'den al
                    # NOT: Algo emirleri triggerPrice, normal emirler stopPrice kullanÃƒâ€žÃ‚Â±r
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
                        "[RECOVER] %s ÃƒÂ¢Ã…â€œÃ¢â‚¬Å“ SL+TP mevcut ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â devam (sl=%s tp=%s)",
                        symbol,
                        sl_id,
                        tp_id,
                    )
                elif n_sl > 1 or n_tp > 1:
                    # ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Duplicate kalmÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸ olmamalÃƒâ€žÃ‚Â± (cleanup halletmiÃƒâ€¦Ã…Â¸ti).
                    # Yine de rastlanÃƒâ€žÃ‚Â±rsa: korumasÃƒâ€žÃ‚Â±z al, sync dÃƒÆ’Ã‚Â¼zeltecek.
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [RECOVER] %s BEKLENMEYEN DUPLICATE SL=%d TP=%d ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ "
                        "korumasÃƒâ€žÃ‚Â±z envantere alÃƒâ€žÃ‚Â±ndÃƒâ€žÃ‚Â±, sync dÃƒÆ’Ã‚Â¼zeltecek",
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
                    # Eksik koruma ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Safe Mode
                    log.warning(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [RECOVER] %s KORUMASIZ SL=%d TP=%d ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ SAFE MODE",
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
                        "[RECOVER] %d pozisyon envantere alÃƒâ€žÃ‚Â±ndÃƒâ€žÃ‚Â±",
                        len(self.active_trades),
                    )
                else:
                    log.info("[RECOVER] Envantere alÃƒâ€žÃ‚Â±nan aÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k pozisyon yok")
        except Exception as e:
            log.error(f"Pozisyon yÃƒÆ’Ã‚Â¼kleme hatasÃƒâ€žÃ‚Â±: {e}")

    # ------------------------------------------------------------------
    # Pozisyon senkronizasyonu (TEK GERÃƒÆ’Ã¢â‚¬Â¡EKLÃƒâ€žÃ‚Â°K: Binance API)
    # ------------------------------------------------------------------
    async def _sync_positions(self, current_bar: Bar):
        """
        Her dÃƒÆ’Ã‚Â¶ngÃƒÆ’Ã‚Â¼de ÃƒÆ’Ã‚Â§aÃƒâ€žÃ…Â¸rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±r.
        Koruma durumunu LOKAL state'ten DEÃƒâ€žÃ…Â¾Ãƒâ€žÃ‚Â°L, Binance API'den sorgular.
        Duplicate varsa ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ (tÃƒÆ’Ã‚Â¼m koruma sil, sÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rdan kur).
        Eksik varsa ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Safe Mode onar.
        """
        import time

        now = time.time()
        # ZAMAN FRENÃƒâ€žÃ‚Â°: Bu fonksiyon 5 saniyede sadece 1 kez ÃƒÆ’Ã‚Â§alÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸abilir
        if hasattr(self, "_last_pos_sync_time") and (now - self._last_pos_sync_time < 5.0):
            return
        self._last_pos_sync_time = now
        try:
            # PM uyumlu pozisyon sorgusu: http_client ÃƒÆ’Ã‚Â¼zerinden (PM mapping'li)
            loop = asyncio.get_running_loop()
            positions_raw = await loop.run_in_executor(None, lambda: http_client.get_positions())
            positions = positions_raw if isinstance(positions_raw, list) else []
            log.info("[SYNC-POSITIONS] %d pozisyon ÃƒÆ’Ã‚Â§ekildi", len(positions))

            # PM guard: pozisyon listesi boÃƒâ€¦Ã…Â¸sa trade'leri KAPATMA
            if not positions:
                log.warning("[SYNC-POSITIONS] pozisyon listesi boÃƒâ€¦Ã…Â¸ ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â trade'ler korunuyor, kapatma YOK")
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

                # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ API'DEN sorgula: TEK GERÃƒÆ’Ã¢â‚¬Â¡EKLÃƒâ€žÃ‚Â°K KAYNAÃƒâ€žÃ…Â¾I (normal + algo) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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

                # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ (V2 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Atomic Swap): duplicate varsa ÃƒÆ’Ã‚Â¶nce koru, sonra temizle ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                # ESKÃƒâ€žÃ‚Â°: cancel ALL ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ create new  (ÃƒÆ’Ã¢â‚¬Â¡IPLAK PENCERE ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â pozisyon stopsuz kalÃƒâ€žÃ‚Â±rdÃƒâ€žÃ‚Â±)
                # YENÃƒâ€žÃ‚Â°: keep 1 SL + 1 TP ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ cancel extras ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ repair missing
                if n_sl > 1 or n_tp > 1:
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ] %s | SL=%d TP=%d ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ fazlalÃƒâ€žÃ‚Â±klar temizleniyor, EN AZ 1 SL + 1 TP KORUNUYOR",
                        symbol,
                        n_sl,
                        n_tp,
                    )

                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ SL: en gÃƒÆ’Ã‚Â¼nceli tut, fazlalarÃƒâ€žÃ‚Â± iptal et ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                    if n_sl > 1:
                        sl_orders.sort(key=lambda o: self._safe_order_timestamp(o), reverse=True)
                        for o in sl_orders[1:]:  # ilk (en gÃƒÆ’Ã‚Â¼ncel) hariÃƒÆ’Ã‚Â§ hepsini iptal
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
                                        "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â [INFAZ-SL] %s | orderId=%s iptal BAÃƒâ€¦Ã…Â¾ARISIZ (tetiklenmiÃƒâ€¦Ã…Â¸ olabilir): %s",
                                        symbol,
                                        order_id,
                                        cancel_err,
                                    )
                            await asyncio.sleep(0.1)
                        # Kalan SL bilgilerini trade'e yaz
                        trade["sl_order_id"] = str(sl_orders[0].get("algoId") or sl_orders[0].get("orderId") or "")
                        trade["current_sl"] = self._get_order_price(sl_orders[0]) or trade.get("current_sl", 0)
                        log.info(
                            "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â [INFAZ-SL] %s | %d fazla SL iptal edildi, 1 SL korundu (id=%s)",
                            symbol,
                            n_sl - 1,
                            trade["sl_order_id"],
                        )

                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ TP: en gÃƒÆ’Ã‚Â¼nceli tut, fazlalarÃƒâ€žÃ‚Â± iptal et ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                                        "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â [INFAZ-TP] %s | orderId=%s iptal BAÃƒâ€¦Ã…Â¾ARISIZ (tetiklenmiÃƒâ€¦Ã…Â¸ olabilir): %s",
                                        symbol,
                                        order_id,
                                        cancel_err,
                                    )
                            await asyncio.sleep(0.1)
                        trade["tp_order_id"] = str(tp_orders[0].get("algoId") or tp_orders[0].get("orderId") or "")
                        trade["tp"] = self._get_order_price(tp_orders[0]) or trade.get("tp", 0)
                        log.info(
                            "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â [INFAZ-TP] %s | %d fazla TP iptal edildi, 1 TP korundu (id=%s)",
                            symbol,
                            n_tp - 1,
                            trade["tp_order_id"],
                        )

                    # Eksik kalan varsa (ÃƒÆ’Ã‚Â¶rn. SL>1 ama TP=0) onar
                    n_sl_now = 1 if n_sl >= 1 else 0
                    n_tp_now = 1 if n_tp >= 1 else 0
                    if n_sl_now == 0 or n_tp_now == 0:
                        trade["protection_repairing"] = True
                        try:
                            await self._repair_protection(symbol, trade, n_sl_now > 0, n_tp_now > 0)
                        except Exception as e:
                            log.critical(
                                "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [SYNC] %s infaz sonrasÃƒâ€žÃ‚Â± onarÃƒâ€žÃ‚Â±m hatasÃƒâ€žÃ‚Â±: %s",
                                symbol,
                                e,
                            )
                        finally:
                            trade["protection_repairing"] = False
                    else:
                        trade["protection_missing"] = False
                        trade["status"] = "open"
                        log.info(
                            "ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ [INFAZ] %s koruma saÃƒâ€žÃ…Â¸lam: SL=%s TP=%s",
                            symbol,
                            trade.get("sl_order_id", "?")[:12],
                            trade.get("tp_order_id", "?")[:12],
                        )

                elif n_sl == 1 and n_tp == 1:
                    # ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ TAM KORUMA ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â API'den ID'leri ve fiyatlarÃƒâ€žÃ‚Â± gÃƒÆ’Ã‚Â¼ncelle
                    # NOT: Algo emirlerinde triggerPrice, normalde stopPrice
                    trade["sl_order_id"] = str(sl_orders[0].get("algoId") or sl_orders[0].get("orderId") or "")
                    trade["tp_order_id"] = str(tp_orders[0].get("algoId") or tp_orders[0].get("orderId") or "")
                    trade["current_sl"] = self._get_order_price(sl_orders[0]) or trade.get("current_sl", 0)
                    trade["tp"] = self._get_order_price(tp_orders[0]) or trade.get("tp", 0)
                    if trade.get("protection_missing"):
                        trade["protection_missing"] = False
                        trade["status"] = "open"
                        log.info(
                            "ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ [REPAIR] %s koruma API'den doÃƒâ€žÃ…Â¸rulandÃƒâ€žÃ‚Â±, SAFE MODE kaldÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±ldÃƒâ€žÃ‚Â±",
                            symbol,
                        )

                else:
                    # ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Eksik koruma (0 SL veya 0 TP) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Safe Mode onar
                    now = time.time()
                    last_check = self._last_protection_check.get(symbol, 0)
                    if now - last_check < 300:
                        continue
                    self._last_protection_check[symbol] = now

                    log.warning(
                        "ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â MISSING PROTECTION | %s | SL=%d TP=%d ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Safe Mode onarÃƒâ€žÃ‚Â±m",
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
                            "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [SYNC] %s protection/repair iÃƒâ€¦Ã…Â¸lemi sÃƒâ€žÃ‚Â±rasÃƒâ€žÃ‚Â±nda KRÃƒâ€žÃ‚Â°TÃƒâ€žÃ‚Â°K HATA: %s",
                            symbol,
                            e,
                        )
                    finally:
                        trade["protection_repairing"] = False  # KÃƒâ€žÃ‚Â°LÃƒâ€žÃ‚Â°T HER HALÃƒÆ’Ã…â€œKARDA KIRILDI

            self._unrealized_pnl = total_upnl

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ KapanmÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸ pozisyonlarÃƒâ€žÃ‚Â± temizle ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            for symbol, trade in list(self.active_trades.items()):
                if symbol not in exchange_positions:
                    # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ CROSS-SYMBOL FIX: ASLA baÃƒâ€¦Ã…Â¸ka sembolÃƒÆ’Ã‚Â¼n current_bar.close'unu kullanma!
                    # fallback zinciri: last_price ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ kendi 5m close'u ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ entry ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ 0
                    symbol_bars = self.hub.get_bars(symbol, "1m")
                    symbol_close = symbol_bars[-1].close if symbol_bars else None
                    fallback_price = trade.get("last_price") or symbol_close or trade.get("entry") or 0
                    exit_price = float(fallback_price)
                    pnl = trade.get("pnl", 0)
                    self._balance += pnl
                    risk_mgr = self._get_risk_manager(symbol)
                    risk_mgr.balance = self._balance
                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ TP mi SL mi ayrÃƒâ€žÃ‚Â±mÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                    trade["exit"] = exit_price  # alias ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â dashboard/performance iÃƒÆ’Ã‚Â§in
                    trade["close_time"] = int(time.time() * 1000)
                    trade["status"] = close_reason  # "TP" | "SL" | "closed"

                    if not trade.get("protection_missing"):
                        performance.record_trade(trade)
                    else:
                        # protection_missing path ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â aynÃƒâ€žÃ‚Â± alanlar zaten set edildi
                        trade.setdefault("direction", "unknown")
                        performance.record_trade(trade)
                        log.warning(
                            "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ SAFE MODE | %s kapandÃƒâ€žÃ‚Â± | eksik bilgiyle kaydedildi",
                            symbol,
                        )
                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Pozisyon kapanÃƒâ€žÃ‚Â±rken kalan tÃƒÆ’Ã‚Â¼m emirleri iptal et ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                    try:
                        await self.executor.client.cancel_all_orders(symbol)
                    except Exception as cancel_err:
                        log.warning(
                            "[SYNC] %s cancel_all_orders hatasÃƒâ€žÃ‚Â± (ÃƒÆ’Ã‚Â¶nemsiz): %s",
                            symbol,
                            cancel_err,
                        )
                    del self.active_trades[symbol]
                    self._clear_state(symbol)
                    self.executor.reset_cooldown(symbol)
                    log.info(f"EXCHANGE SYNC: {symbol} kapandÃƒâ€žÃ‚Â± | ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ CIKIS={exit_price:.4f} pnl={pnl:.2f} USDT")

        except Exception as e:
            err_msg = str(e)
            if "-1109" in err_msg:
                pass
            else:
                log.error("Pozisyon sync hatasÃƒâ€žÃ‚Â±: %s", err_msg, exc_info=True)

    async def _repair_protection(self, symbol: str, trade: dict, has_sl: bool, has_tp: bool):
        """Eksik TP/SL'yi tamamla. Order ID'leri API yanÃƒâ€žÃ‚Â±tÃƒâ€žÃ‚Â±ndan yakalar."""
        try:
            # POZÃƒâ€žÃ‚Â°SYON KONTROLÃƒÆ’Ã…â€œ
            pos = await self.executor.client.fetch_position(symbol)
            if not pos or abs(float(pos.get("contracts", 0))) == 0:
                log.warning("ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ [REPAIR] %s pozisyon yok, atlanÃƒâ€žÃ‚Â±yor", symbol)
                return

            # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â FIX: TP zaten geÃƒÆ’Ã‚Â§ilmiÃƒâ€¦Ã…Â¸se pozisyonu market kapat (tp_already_hit)
            if not has_tp and trade.get("tp"):
                mark_price = float(pos.get("markPrice", 0))
                direction = trade.get("direction", "long")
                tp_price = trade["tp"]

                if (direction == "long" and mark_price >= tp_price) or (
                    direction == "short" and mark_price <= tp_price
                ):
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‹Å“ [SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ] %s TP (%.5f) zaten geÃƒÆ’Ã‚Â§ildi (mark=%.5f) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â MARKET kapatÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor!",
                        symbol,
                        tp_price,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="tp_already_hit_repair")
                    return

            if not has_sl:
                # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â FIX: initial_sl trade'de yoksa risk_manager'dan hesapla
                if not trade.get("initial_sl"):
                    log.warning(
                        "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ [REPAIR] %s trade'de initial_sl yok ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â entry + risk_mgr ile hesaplanÃƒâ€žÃ‚Â±yor",
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
                        "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ [REPAIR] %s initial_sl hesaplandÃƒâ€žÃ‚Â±: entry=%.5f sl=%.5f",
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
                    "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ [REPAIR] %s SL yeniden kuruldu: %.8f (id=%s)",
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
                    "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ [REPAIR] %s TP yeniden kuruldu: %.8f (id=%s)",
                    symbol,
                    trade["tp"],
                    trade["tp_order_id"],
                )

                # API'den doÃƒâ€žÃ…Â¸rula (normal + algo)
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
                log.info("ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ [REPAIR] %s koruma API'den doÃƒâ€žÃ…Â¸rulandÃƒâ€žÃ‚Â±", symbol)
            else:
                log.warning(
                    "ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â [REPAIR] %s doÃƒâ€žÃ…Â¸rulama baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â±z SL_ok=%s TP_ok=%s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â sonraki dÃƒÆ’Ã‚Â¶ngÃƒÆ’Ã‚Â¼de tekrar denenecek",
                    symbol,
                    sl_ok,
                    tp_ok,
                )
        except urllib.error.HTTPError as e:
            if "-4130" in str(e):
                log.info("[REPAIR] %s zaten aktif koruma emri mevcut, senkronizasyon gÃƒÆ’Ã‚Â¼ncel.", symbol)
                return  # baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â± say, REPAIR MODE tetikleme
            raise  # diÃƒâ€žÃ…Â¸er hatalar yukarÃƒâ€žÃ‚Â± fÃƒâ€žÃ‚Â±rlat
        except Exception:
            log.exception("ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â§ REPAIR_PROTECTION FAILED | %s", symbol)

    async def _create_protection(self, symbol: str, trade: dict):
        """SÃƒâ€žÃ‚Â±fÃƒâ€žÃ‚Â±rdan TP/SL oluÃƒâ€¦Ã…Â¸tur. Order ID'leri API yanÃƒâ€žÃ‚Â±tÃƒâ€žÃ‚Â±ndan yakalar."""
        try:
            # POZÃƒâ€žÃ‚Â°SYON KONTROLÃƒÆ’Ã…â€œ
            pos = await self.executor.client.fetch_position(symbol)
            if not pos or abs(float(pos.get("contracts", 0))) == 0:
                log.warning("ÃƒÂ°Ã…Â¸Ã¢â‚¬Â Ã¢â‚¬Â¢ [CREATE] %s pozisyon yok, atlanÃƒâ€žÃ‚Â±yor", symbol)
                return
            risk_mgr = self._get_risk_manager(symbol)
            entry = trade["entry"]
            direction = trade["direction"]

            # Mevcut piyasa fiyatÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ TP/SL'nin hemen tetiklenip tetiklenmeyeceÃƒâ€žÃ…Â¸ini kontrol et
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
                # LONG TP (SELL) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ mark_price >= tp_candidate ise SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ
                if mark_price >= tp_candidate:
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‹Å“ [SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ] %s TP (%.5f) zaten geÃƒÆ’Ã‚Â§ildi (mark=%.5f) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â MARKET kapatÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor!",
                        symbol,
                        tp_candidate,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="tp_already_hit")
                    return
                else:
                    tp = tp_candidate
                # LONG SL (SELL) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ mark_price <= sl_candidate ise hemen tetiklenir
                if mark_price <= sl_candidate:
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [CREATE] %s SL (%.5f) zaten geÃƒÆ’Ã‚Â§ildi (mark=%.5f) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â EMERGENCY kapatÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor!",
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
                # SHORT TP (BUY) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ mark_price <= tp_candidate ise SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ
                if mark_price <= tp_candidate:
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‹Å“ [SORGUSUZ Ãƒâ€žÃ‚Â°NFAZ] %s TP (%.5f) zaten geÃƒÆ’Ã‚Â§ildi (mark=%.5f) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â MARKET kapatÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor!",
                        symbol,
                        tp_candidate,
                        mark_price,
                    )
                    await self.executor.close_position(symbol, reason="tp_already_hit")
                    return
                else:
                    tp = tp_candidate
                # SHORT SL (BUY) ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ mark_price >= sl_candidate ise hemen tetiklenir
                if mark_price >= sl_candidate:
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ [CREATE] %s SL (%.5f) zaten geÃƒÆ’Ã‚Â§ildi (mark=%.5f) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â EMERGENCY kapatÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor!",
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

            # TP emri (sadece tp hesaplanmÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸sa)
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
                            "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ [CREATE] %s TP (%.5f) hemen tetiklenirdi (mark=%.5f) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â atlanÃƒâ€žÃ‚Â±yor",
                            symbol,
                            tp,
                            mark_price,
                        )
                    elif "-4130" in err_str:
                        log.warning(
                            "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ [CREATE] %s TP/SL zaten mevcut, SAFE MODE kaldÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor",
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
                "ÃƒÂ°Ã…Â¸Ã¢â‚¬Â Ã¢â‚¬Â¢ [CREATE] %s TP/SL kuruldu: SL=%.5f (%s) TP=%s (%s)",
                symbol,
                sl,
                sl_id,
                f"{tp:.5f}" if tp is not None else "ATLANDI",
                tp_id or "-",
            )
        except Exception as e:
            if "-4130" in str(e):
                log.warning("ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ [CREATE] %s TP/SL zaten mevcut, SAFE MODE kaldÃƒâ€žÃ‚Â±rÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor", symbol)
                trade["protection_missing"] = False
                trade["status"] = "open"
                if "initial_sl" not in trade:
                    trade["initial_sl"] = 0.0
                if "current_sl" not in trade:
                    trade["current_sl"] = 0.0
                if "tp" not in trade:
                    trade["tp"] = 0.0
            else:
                log.exception("ÃƒÂ°Ã…Â¸Ã¢â‚¬Â Ã‹Å“ CREATE_PROTECTION FAILED | %s", symbol)

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

    # AÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k pozisyon yÃƒÆ’Ã‚Â¶netimi (trailing + breakeven)
    # ------------------------------------------------------------------
    async def _manage_open_trades(self, current_bar: Bar):
        current_time_ms = int(time.time() * 1000)  # AnlÃƒâ€žÃ‚Â±k sistem zamanÃƒâ€žÃ‚Â± (ms)
        for symbol, trade in list(self.active_trades.items()):
            # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ RACE CONDITION FIX: _sync_positions() ÃƒÆ’Ã‚Â¶ncesi lokal state gÃƒÆ’Ã‚Â¼ncel olmayabilir.
            # TP zaten geÃƒÆ’Ã‚Â§ilmiÃƒâ€¦Ã…Â¸ ve pozisyon Binance'te kapanmÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸ olabilir.
            # Bu durumda SL gÃƒÆ’Ã‚Â¼ncellemesi yapmak "Unknown order sent" hatasÃƒâ€žÃ‚Â±na yol aÃƒÆ’Ã‚Â§ar.
            # ÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã‚Â¶zÃƒÆ’Ã‚Â¼m: Her _manage_open_trades() dÃƒÆ’Ã‚Â¶ngÃƒÆ’Ã‚Â¼sÃƒÆ’Ã‚Â¼nde pozisyonu Binance API'den doÃƒâ€žÃ…Â¸rula.
            try:
                pos = await self.executor.get_position(symbol)
                if not pos or abs(float(pos.get("contracts", 0))) == 0:
                    log.warning(
                        "[MANAGE-RACE] %s pozisyon API'de bulunamadÃƒâ€žÃ‚Â± (zaten kapanmÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â SL gÃƒÆ’Ã‚Â¼ncellemesi ATLANIYOR",
                        symbol,
                    )
                    continue
            except Exception as e:
                log.warning(
                    "[MANAGE-RACE] %s pozisyon sorgusu baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â±z: %s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â gÃƒÆ’Ã‚Â¼venlik iÃƒÆ’Ã‚Â§in atlanÃƒâ€žÃ‚Â±yor",
                    symbol,
                    e,
                )
                continue

            if trade.get("protection_missing"):
                log.warning("ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ SAFE MODE | %s | sadece izleme, iÃƒâ€¦Ã…Â¸lem yok", symbol)
                continue
            if trade.get("protection_repairing"):
                log.warning("ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ REPAIR MODE | %s | sadece izleme, iÃƒâ€¦Ã…Â¸lem yok", symbol)
                continue
            if trade["status"] != "open":
                continue

            # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ FIX: Minimum YaÃƒâ€¦Ã…Â¸am SÃƒÆ’Ã‚Â¼resi KorumasÃƒâ€žÃ‚Â± (En az 5 dakika/300.000 ms geÃƒÆ’Ã‚Â§meli)
            open_time = trade.get("open_time", 0)
            if open_time and (current_time_ms - open_time) < 300_000:
                remaining = int((300_000 - (current_time_ms - open_time)) / 1000)
                log.info(
                    "[MANAGE] %s iÃƒâ€¦Ã…Â¸lemi henÃƒÆ’Ã‚Â¼z ÃƒÆ’Ã‚Â§ok taze (kalan sÃƒÆ’Ã‚Â¼re: %dsn) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â Breakeven/Trailing atlandÃƒâ€žÃ‚Â±.",
                    symbol,
                    remaining,
                )
                continue

            try:
                risk_mgr = self._get_risk_manager(symbol)
                # ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂÃ‚Â´ CROSS-SYMBOL FIX: Kendi sembolÃƒÆ’Ã‚Â¼nÃƒÆ’Ã‚Â¼n 5m bar fiyatÃƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± kullan
                symbol_bars = self.hub.get_bars(symbol, "1m")
                symbol_close = symbol_bars[-1].close if symbol_bars else None
                current_price = trade.get("last_price") or symbol_close or trade.get("entry", 0)
                sl_current = trade.get("current_sl", trade["initial_sl"])
                if not trade.get("breakeven_done", False) and risk_mgr.should_move_to_breakeven(trade, current_price):
                    new_sl = risk_mgr.breakeven_sl(trade)
                    trade["current_sl"] = new_sl
                    trade["breakeven_done"] = True
                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Breakeven logging (ADX > 35 korelasyon izleme) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                    if config.BREAKEVEN_LOG_ENABLED:
                        d1_adx = trade.get("d1_adx_at_entry", 0)
                        adx_flag = "ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â ADX>35" if d1_adx >= config.ADX_HIGH_TP_THRESHOLD else "OK"
                        log.info(
                            f"[BE] {symbol} breakeven'a alÃƒâ€žÃ‚Â±ndÃƒâ€žÃ‚Â± | "
                            f"yeni SL={new_sl:.8f} | "
                            f"entry={trade['entry']:.6f} | "
                            f"current_price={current_price:.6f} | "
                            f"d1_adx_at_entry={d1_adx:.1f} ({adx_flag}) | "
                            f"direction={trade['direction']} | "
                            f"fvg_score={trade.get('fvg_score', '?'):.3f}"
                        )
                    else:
                        log.info(f"[BE] {symbol} breakeven'a alÃƒâ€žÃ‚Â±ndÃƒâ€žÃ‚Â±, yeni SL={new_sl:.8f}")
                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Breakeven istatistik takibi ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                    # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Periyodik ÃƒÆ’Ã‚Â¶zet log (her 30 dk) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
                    if config.BREAKEVEN_LOG_ENABLED and current_time_ms - self._last_be_summary > 1_800_000:  # 30 dk
                        self._last_be_summary = current_time_ms
                        total_be = sum(v["count"] for v in self._breakeven_log.values())
                        total_adx35 = sum(v["adx_gt_35"] for v in self._breakeven_log.values())
                        corr_pct = (total_adx35 / total_be * 100) if total_be > 0 else 0.0
                        log.info(
                            f"[BE-SUMMARY] Breakeven ÃƒÆ’Ã¢â‚¬â€œzeti | "
                            f"toplam={total_be} | "
                            f"ADX>35'te BE={total_adx35} ({corr_pct:.1f}%) | "
                            f"sembol sayÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â±={len(self._breakeven_log)}"
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
                        log.info(f"[TRAIL] {symbol} SL gÃƒÆ’Ã‚Â¼ncellendi: {sl_current:.8f} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {new_sl:.8f}")
                        await self._update_sl_order(symbol, trade, new_sl)

            except Exception as e:
                log.error(f"[MANAGE] {symbol} yÃƒÆ’Ã‚Â¶netim hatasÃƒâ€žÃ‚Â±: {e}")

    # ------------------------------------------------------------------
    # SL gÃƒÆ’Ã‚Â¼ncelleme
    # ------------------------------------------------------------------
    async def _update_sl_order(self, symbol: str, trade: dict, new_sl: float):
        """SL gÃƒÆ’Ã‚Â¼ncelle. API'den mevcut SL emrini bulur, cancelReplace yapar."""
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
                log.info("ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â SL UPDATE | %s | yeni SL=%.8f (id=%s)", symbol, new_sl, new_id)
                return

            # Algo order ise cancelReplace KULLANMA (algoId'si vardÃƒâ€žÃ‚Â±r, orderId'si yoktur)
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
                    "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â SL ALGO UPDATE | %s | yeni SL=%.8f (id=%s)",
                    symbol,
                    new_sl,
                    new_id,
                )
                return

            # Standard order ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ cancelReplace dene
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
                "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â SL REPLACED | %s | %.8f ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ %.8f (new_id=%s)",
                symbol,
                float(old_sl.get("stopPrice", 0)),
                new_sl,
                new_id,
            )

        except Exception as e:
            log.critical(
                "[SL_UPDATE] %s cancelReplace baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â±z: %s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â EMERGENCY FALLBACK",
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

                # ADIM 2: Yeni SL emri gÃƒÆ’Ã‚Â¶nder
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
                    "ÃƒÂ°Ã…Â¸Ã¢â‚¬ÂºÃ‚Â¡ÃƒÂ¯Ã‚Â¸Ã‚Â SL FALLBACK OK | %s | yeni SL=%.8f (id=%s)",
                    symbol,
                    new_sl,
                    new_id,
                )
            except Exception as fallback_err:
                log.critical(
                    "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ SL FALLBACK BAÃƒâ€¦Ã…Â¾ARISIZ | %s | EMERGENCY CLOSE tetikleniyor: %s",
                    symbol,
                    fallback_err,
                )
                try:
                    await self.executor.close_position(symbol, reason="emergency_sl_update_fail")
                    log.critical("ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ EMERGENCY CLOSE BAÃƒâ€¦Ã…Â¾ARILI | %s | pozisyon kapatÃƒâ€žÃ‚Â±ldÃƒâ€žÃ‚Â±", symbol)
                except Exception as close_err:
                    log.critical(
                        "ÃƒÂ°Ã…Â¸Ã…Â¡Ã‚Â¨ EMERGENCY CLOSE BAÃƒâ€¦Ã…Â¾ARISIZ | %s | manuel mÃƒÆ’Ã‚Â¼dahale gerekli! hata=%s",
                        symbol,
                        close_err,
                    )

    # ------------------------------------------------------------------
    # 5m bar kapanÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸ handler
    # ------------------------------------------------------------------
    def _is_15m_closed(self, symbol: str, current_bar: Bar) -> bool:
        """15m mumun kapandÃƒâ€žÃ‚Â±Ãƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â±nÃƒâ€žÃ‚Â± timestamp ile tespit et."""
        ts_cache = getattr(self, "_15m_close_cache", {})
        bars_15m = self.hub.get_bars(symbol, "15m")
        if not bars_15m:
            return False
        last_15m_ts = bars_15m[-1].timestamp
        prev = ts_cache.get(symbol)
        if prev is not None and prev == last_15m_ts:
            return False  # aynÃƒâ€žÃ‚Â± 15m, daha ÃƒÆ’Ã‚Â¶nce iÃƒâ€¦Ã…Â¸lendi
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
            # H4 "None" kontrolÃƒÆ’Ã‚Â¼ eklendi
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

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ 15m bar kapanÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸Ãƒâ€žÃ‚Â±nda: sadece snapshot export ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            if self._is_15m_closed(symbol, current_bar):
                export_ohlc_15m(bars_15m[-1], symbol)
                state_logger.write_snapshot(
                    symbol=symbol,
                    state=self.state_machine.get(symbol),
                    killzone_utc=current_bar.timestamp // 3600000 % 24,
                    in_killzone=getattr(self.state_machine.get(symbol), "in_killzone", False),
                )

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Her 1m: state check'ler + emir kapÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
                    log.debug("[CACHE-RESET] %s ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ IDLE, analyzer cache temizlendi", symbol)

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
                            log.warning("[EXECUTE] %s zaten aktif trade var ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â atlandÃƒâ€žÃ‚Â±", symbol)
                        else:
                            risk_mgr = self._get_risk_manager(symbol)
                            trade_params = risk_mgr.build_trade(
                                state=current_state,
                                entry_price=bars_m1[-1].close,
                                h4_swing_level=current_state.h4_swing_level,
                                h1_liquidity_level=current_state.h1_liquidity_level,
                            )
                            if trade_params is None:
                                log.warning("[EXECUTE] %s build_trade reddetti ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ atlanÃƒâ€žÃ‚Â±yor", symbol)
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
                                        "[EXECUTE] %s ÃƒÂ¢Ã…â€œÃ¢â‚¬Â¦ emir gÃƒÆ’Ã‚Â¶nderildi ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â entry=%.5f sl=%.5f tp=%.5f RR=%.2f",
                                        symbol,
                                        trade_params.entry,
                                        trade_params.sl,
                                        trade_params.tp,
                                        trade_params.gross_rr,
                                    )

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ AÃƒÆ’Ã‚Â§Ãƒâ€žÃ‚Â±k pozisyon varsa yeni sinyal alma (analyzer atlanÃƒâ€žÃ‚Â±r) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
            if symbol in self.active_trades:
                existing = self.active_trades[symbol]
                if existing.get("protection_missing"):
                    log.warning("ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ SAFE MODE | %s | yeni sinyal ENGELLENDÃƒâ€žÃ‚Â°", symbol)
                if existing.get("protection_repairing"):
                    log.warning("ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¡ REPAIR MODE | %s | yeni sinyal ENGELLENDÃƒâ€žÃ‚Â°", symbol)
                return

            # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ V3 event-driven flow: analyzer ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ event_router ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ state_machine ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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

                # Boolean deÃƒâ€žÃ…Â¸erleri fmt_bool ile gÃƒÆ’Ã‚Â¶rsel log
                s_sweep = fmt_bool(current_state.sweep_detected)
                s_mss = fmt_bool(current_state.mss_confirmed)
                s_retrace = fmt_bool(current_state.retrace_seen)
                s_ltf = fmt_bool(current_state.ltf_confirmed)

                # TÃƒÆ’Ã‚Â¼m flag'ler emoji formatÃƒâ€žÃ‚Â±nda
                s_sweep = "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â©" if current_state.sweep_detected else "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¥"
                s_mss = "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â©" if current_state.mss_confirmed else "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¥"
                s_retrace = "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â©" if current_state.retrace_seen else "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¥"
                s_ltf = "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â©" if current_state.ltf_confirmed else "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¥"

                # FVG dinamik alan
                if current_state.fvg_upper is None or current_state.fvg_lower is None:
                    fvg_display = "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¥"
                elif current_state.retrace_seen:
                    fvg_display = "fvg_a ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â©"
                elif current_state.fvg_missed:
                    fvg_display = "fvg_c ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â©"
                elif getattr(current_state, "invalidated", False):
                    fvg_display = "ÃƒÂ¢Ã‚Â¬Ã¢â‚¬Âº"
                else:
                    fvg_display = "ÃƒÂ°Ã…Â¸Ã…Â¸Ã‚Â¨"

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
    # API Server ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â dashboard iÃƒÆ’Ã‚Â§in
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
            return web.Response(text="dashboard.html bulunamadÃƒâ€žÃ‚Â±", status=404)

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
        log.info("Dashboard API baÃƒâ€¦Ã…Â¸latÃƒâ€žÃ‚Â±ldÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ http://0.0.0.0:8080 (sadece local)")

    # ------------------------------------------------------------------
    # Ana dÃƒÆ’Ã‚Â¶ngÃƒÆ’Ã‚Â¼
    # ------------------------------------------------------------------
    async def run(self):
        # ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â
        # MEKANÃƒâ€žÃ‚Â°K AKIÃƒâ€¦Ã…Â¾: Cleanup ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Sync ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Safe Mode ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ Run
        # TÃƒÆ’Ã‚Â¼m adÃƒâ€žÃ‚Â±mlar baÃƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â±msÃƒâ€žÃ‚Â±z: biri hata verirse diÃƒâ€žÃ…Â¸eri ÃƒÆ’Ã‚Â§alÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸Ãƒâ€žÃ‚Â±r.
        # ÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚ÂÃƒÂ¢Ã¢â‚¬Â¢Ã‚Â

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 0: Bakiye (hatada varsayÃƒâ€žÃ‚Â±lanla devam) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        try:
            await self._sync_balance()
        except Exception as e:
            log.critical("ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Bakiye alÃƒâ€žÃ‚Â±namadÃƒâ€žÃ‚Â±: %s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â varsayÃƒâ€žÃ‚Â±lan 1000 USDT ile devam", e)
            self._balance = 1000.0
            for rm in self.risk_managers.values():
                rm.balance = self._balance

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 0.5: State dosyasÃƒâ€žÃ‚Â±ndan kaldÃƒâ€žÃ‚Â±Ãƒâ€žÃ…Â¸Ãƒâ€žÃ‚Â± yerden devam ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        try:
            self._load_state()
        except Exception as e:
            log.warning("[STATE] _load_state hatasÃƒâ€žÃ‚Â± ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â temiz baÃƒâ€¦Ã…Â¸langÃƒâ€žÃ‚Â±ÃƒÆ’Ã‚Â§: %s", e)

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 1: PozisyonlarÃƒâ€žÃ‚Â± yÃƒÆ’Ã‚Â¼kle (API'den) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â CLEANUP'TAN ÃƒÆ’Ã¢â‚¬â€œNCE!
        # ÃƒÆ’Ã¢â‚¬â€œNEMLÃƒâ€žÃ‚Â°: ÃƒÆ’Ã¢â‚¬â€œnce pozisyon yÃƒÆ’Ã‚Â¼klenir ki _startup_cleanup, active_trades listesini
        # kullanarak "ORPHAN-GUARD" korumasÃƒâ€žÃ‚Â± yapabilsin.
        # Aksi halde active_trades boÃƒâ€¦Ã…Â¸ olur, API kÃƒâ€žÃ‚Â±smi response dÃƒÆ’Ã‚Â¶ndÃƒÆ’Ã‚Â¼Ãƒâ€žÃ…Â¸ÃƒÆ’Ã‚Â¼nde
        # tÃƒÆ’Ã‚Â¼m SL/TP'ler "orphan" sanÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±p silinir. (Bkz. F11 ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â F13 arasÃƒâ€žÃ‚Â± fix'ler)
        try:
            await self._load_existing_positions()
        except Exception as e:
            log.critical("ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Pozisyon yÃƒÆ’Ã‚Â¼kleme baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â±z: %s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â boÃƒâ€¦Ã…Â¸ envanterle devam", e)

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ State'i diske yaz (startup sonrasÃƒâ€žÃ‚Â±) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        self._flush_state()

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 2: STARTUP CLEANUP (Sorgusuz Ãƒâ€žÃ‚Â°nfaz)
        # Bu noktada active_trades dolu olduÃƒâ€žÃ…Â¸u iÃƒÆ’Ã‚Â§in ORPHAN-GUARD korumasÃƒâ€žÃ‚Â± ÃƒÆ’Ã‚Â§alÃƒâ€žÃ‚Â±Ãƒâ€¦Ã…Â¸Ãƒâ€žÃ‚Â±r:
        # API'de pozisyon gÃƒÆ’Ã‚Â¶rÃƒÆ’Ã‚Â¼nmese bile local state'te trade varsa emirler SÃƒâ€žÃ‚Â°LÃƒâ€žÃ‚Â°NMEZ.
        try:
            await self._startup_cleanup()
        except Exception as e:
            log.critical("ÃƒÂ¢Ã…Â¡Ã‚Â ÃƒÂ¯Ã‚Â¸Ã‚Â Cleanup baÃƒâ€¦Ã…Â¸arÃƒâ€žÃ‚Â±sÃƒâ€žÃ‚Â±z: %s ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â temizlik atlanarak devam", e)

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Cleanup sonrasÃƒâ€žÃ‚Â± state'i gÃƒÆ’Ã‚Â¼ncelle ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        self._flush_state()

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ Startup tamamlandÃƒâ€žÃ‚Â± iÃƒâ€¦Ã…Â¸areti ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        self.executor.mark_startup_complete()

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 2.5: User Data Stream (listenKey) ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
        try:
            listen_key = http_client.new_listen_key()
            if listen_key:
                # WS_BASE_URL'den user data WS base URL'ini tÃƒÆ’Ã‚Â¼ret
                # "wss://stream.binancefuture.com/stream?streams=" ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ "wss://stream.binancefuture.com"
                from urllib.parse import urlparse

                parsed = urlparse(WS_BASE_URL)
                ws_base = f"{parsed.scheme}://{parsed.netloc}"
                self.hub.set_user_data_listen_key(listen_key, ws_base_url=ws_base)
                log.info("[USER_DATA] Listen key oluÃƒâ€¦Ã…Â¸turuldu: %s...", listen_key[:10])

                # ORDER_TRADE_UPDATE callback ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â anlÃƒâ€žÃ‚Â±k emir durumu
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

                # ACCOUNT_UPDATE callback ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â anlÃƒâ€žÃ‚Â±k pozisyon/bakiye gÃƒÆ’Ã‚Â¼ncellemesi
                @self.hub.on_user_data("ACCOUNT_UPDATE")
                async def on_account_update(msg: dict):
                    update_data = msg.get("a", {})
                    reason = update_data.get("m", "")
                    balances = update_data.get("B", [])
                    positions = update_data.get("P", [])

                    # Real-time bakiye gÃƒÆ’Ã‚Â¼ncellemesi (60sn polling'e alternatif)
                    for bal in balances:
                        asset = bal.get("a", "")
                        if asset in ("USDT", "FDUSD", "USDC"):
                            self._wallet_balance = float(bal.get("wb", self._wallet_balance))
                            self._available_balance = float(bal.get("bc", self._available_balance))
                            self._balance = self._available_balance
                    if balances:
                        log.debug(
                            "[USER_DATA] ACCOUNT_UPDATE | reason=%s | %d balance gÃƒÆ’Ã‚Â¼ncellendi", reason, len(balances)
                        )

                    for pos in positions:
                        sym = pos.get("s", "")
                        if sym in self.active_trades:
                            self.active_trades[sym]["pnl"] = float(pos.get("up", 0))
                            self.active_trades[sym]["last_price"] = float(pos.get("ep", 0))
                    if positions:
                        log.debug(
                            "[USER_DATA] ACCOUNT_UPDATE | reason=%s | %d pozisyon gÃƒÆ’Ã‚Â¼ncellendi",
                            reason,
                            len(positions),
                        )
        except Exception as e:
            log.warning("[USER_DATA] Listen key oluÃƒâ€¦Ã…Â¸turulamadÃƒâ€žÃ‚Â± (devam): %s", e)

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 3: Buffer'larÃƒâ€žÃ‚Â± ÃƒÆ’Ã‚Â¶n doldur ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
        log.info("BaÃƒâ€¦Ã…Â¸langÃƒâ€žÃ‚Â±ÃƒÆ’Ã‚Â§ tamamlandÃƒâ€žÃ‚Â±, WebSocket hub baÃƒâ€¦Ã…Â¸latÃƒâ€žÃ‚Â±lÃƒâ€žÃ‚Â±yor...")

        async def _health_loop():
            while True:
                await asyncio.sleep(60)
                try:
                    await self._sync_balance()
                except Exception as e:
                    log.warning("[HEALTH] Bakiye sync hatasÃƒâ€žÃ‚Â± (sonraki denenecek): %s", e)
                try:
                    h = monitor.get_health()
                    log.info(f"[HEALTH] {json.dumps(h)}")
                except Exception:
                    pass

        # ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ ADIM 4: RUN ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â tÃƒÆ’Ã‚Â¼m arka plan task'larÃƒâ€žÃ‚Â± baÃƒâ€¦Ã…Â¸lat ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬ÃƒÂ¢Ã¢â‚¬ÂÃ¢â€šÂ¬
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
        log.info("KullanÃƒâ€žÃ‚Â±cÃƒâ€žÃ‚Â± tarafÃƒâ€žÃ‚Â±ndan durduruldu.")
        bot.hub.stop()

