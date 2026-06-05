"""
performance.py — NEXUS V2
─────────────────────────
Per-symbol performance tracker — kalıcı geçmiş + çift CSV destekli.

CSV Mimarisi
────────────
  • output/summary.csv          → Dashboard + Nexus Visualizer için.
                                  Hafif, hızlı. Temel kapanış verisi.
  • output/strategy_analiz.csv  → Derin analiz için. Dashboard okumaz.
                                  Strateji parametrelerinin tamamı.

Restart Davranışı
─────────────────
  • initialize() → bot başlangıcında bir kez çağır
  • summary.csv'den _stats yüklenir, dashboard sıfırdan başlamaz
  • strategy_analiz.csv sadece yazılır, okunmaz

Kurallar
────────
  • Strateji / trading logic içermez
  • Sadece istatistik hesaplar
  • Thread-safe değil — asyncio loop'ta çağırın

Nexus Visualizer Uyumu (v4)
────────────────────────────
  summary.csv kolonları: timestamp, close_time, symbol, side,
                         entry, exit_price, pnl, gross_rr, status
  → direction → side (rename)
  → close_time eklendi (exit_timestamp'ten)
"""

import csv
import logging
import os
import threading
import time
from datetime import UTC, datetime

from config import OUTPUT_DIR

_csv_lock = threading.Lock()

log = logging.getLogger("nexus.performance")

# -------------------------------------------------------------------
# Internal state
# -------------------------------------------------------------------
_stats: dict[str, dict] = {}
_trade_log: list[dict] = []

SUMMARY_CSV = "output/summary.csv"
STRATEGY_CSV = "output/strategy_analiz.csv"

# Dashboard + Nexus Visualizer için — Nexus uyumlu kolon isimleri
SUMMARY_FIELDS = [
    "timestamp",  # Giriş zamanı (UTC)
    "close_time",  # Kapanış zamanı (UTC) — Nexus için zorunlu
    "symbol",  # BTCUSDT
    "side",  # LONG / SHORT — Nexus 'side' bekliyor
    "entry",  # Giriş fiyatı
    "exit_price",  # Çıkış fiyatı
    "pnl",  # Kar/Zarar ($)
    "gross_rr",  # Risk/Reward
    "status",  # TP / SL / MANUAL
]

# Derin analiz için — strateji parametrelerinin tamamı
STRATEGY_FIELDS = [
    # ── Kimlik
    "timestamp",  # Kapanış zamanı (UTC)
    "symbol",  # İşlem sembolü
    "direction",  # LONG / SHORT
    "status",  # TP / SL / MANUAL / LIQUIDATION
    # ── Trend Katmanı (D1)
    "d1_close",  # Günlük kapanış fiyatı
    "d1_ema100",  # EMA100 değeri (trend filtresi)
    "d1_ema_slope",  # EMA eğimi → pozitif=yukarı, negatif=aşağı
    "d1_adx",  # ADX değeri (trend gücü, eşik: 25)
    "trend_direction",  # long / short / none
    # ── CHoCH Katmanı (H1)
    "choch_direction",  # bullish / bearish
    "choch_level",  # Kırılan yapı seviyesi (fiyat)
    "choch_bar_index",  # Kaçıncı H1 barında kırıldı
    # ── FVG Katmanı (15m veya 5m)
    "fvg_timeframe",  # 15m / 5m (hangi TF'de bulundu)
    "fvg_direction",  # bullish / bearish
    "fvg_top",  # FVG üst sınırı
    "fvg_bottom",  # FVG alt sınırı
    "fvg_midpoint",  # FVG orta noktası
    "fvg_size",  # FVG büyüklüğü (top - bottom)
    "fvg_bar_index",  # FVG'nin oluştuğu bar indeksi
    # ── Giriş Anı
    "entry",  # Giriş fiyatı
    "sl_price",  # Stop Loss fiyatı
    "tp_price",  # Take Profit fiyatı
    "rr_ratio",  # Planlanan Risk/Reward oranı
    "lot_size",  # Lot büyüklüğü
    # ── Çıkış
    "exit_price",  # Çıkış fiyatı
    "exit_timestamp",  # Çıkış zamanı (UTC)
    "pnl",  # Gerçekleşen Kar/Zarar ($)
    "gross_rr",  # Gerçekleşen R:R
]


# -------------------------------------------------------------------
# Startup — geçmişi yükle
# -------------------------------------------------------------------


def initialize() -> None:
    """
    Bot başlarken bir kez çağır.
    summary.csv varsa tüm geçmişi _stats'a yükler.
    Restart sonrası dashboard doğru veri gösterir.
    """
    _load_history()
    log.info(
        f"[PERF] initialize tamamlandı — "
        f"{len(_stats)} sembol, "
        f"{sum(s['total'] for s in _stats.values())} işlem yüklendi."
    )


def _load_history() -> None:
    """summary.csv'den geçmiş işlemleri okuyup _stats'a yükler."""
    if not os.path.exists(SUMMARY_CSV):
        log.info("[PERF] Geçmiş CSV bulunamadı, temiz başlangıç.")
        return

    loaded = 0
    skipped = 0
    try:
        with open(SUMMARY_CSV, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    symbol = row.get("symbol", "").strip()
                    if not symbol:
                        skipped += 1
                        continue

                    pnl = float(row.get("pnl") or 0)
                    rr = float(row.get("gross_rr") or 0)

                    s = _get_or_create(symbol)
                    s["total"] += 1
                    s["total_pnl"] += pnl
                    s["total_rr"] += rr

                    if pnl > 0:
                        s["wins"] += 1
                    else:
                        s["losses"] += 1

                    if s["best_pnl"] is None or pnl > s["best_pnl"]:
                        s["best_pnl"] = pnl
                        # 'side' yeni isim, eski kayıtlarda 'direction' olabilir
                        s["best_trade"] = row.get("side") or row.get("direction", "")

                    if s["worst_pnl"] is None or pnl < s["worst_pnl"]:
                        s["worst_pnl"] = pnl
                        s["worst_trade"] = row.get("side") or row.get("direction", "")

                    # _trade_log (sidebar + /api/trades için)
                    _trade_log.append(
                        {
                            "ts": row.get("timestamp", ""),
                            "symbol": symbol,
                            "direction": row.get("side") or row.get("direction", ""),
                            "entry": _safe_float(row.get("entry")),
                            "exit": _safe_float(row.get("exit_price")),
                            "pnl": round(pnl, 4),
                            "rr": round(rr, 4),
                            "status": row.get("status", ""),
                        }
                    )

                    loaded += 1

                except Exception as row_err:
                    log.warning(f"[PERF] Satır atlandı: {row_err}")
                    skipped += 1

        log.info(f"[PERF] CSV yüklendi: {loaded} işlem, {skipped} atlandı.")

    except Exception as e:
        log.error(f"[PERF] Geçmiş yükleme hatası: {e}")


def _safe_float(v) -> float | None:
    try:
        return float(v) if v not in (None, "", "None") else None
    except Exception:
        return None


# -------------------------------------------------------------------
# Internal state factory
# -------------------------------------------------------------------


def _get_or_create(symbol: str) -> dict:
    if symbol not in _stats:
        _stats[symbol] = {
            "symbol": symbol,
            "total": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_rr": 0.0,
            "best_pnl": None,
            "worst_pnl": None,
            "best_trade": None,
            "worst_trade": None,
            "adx_sum": 0.0,
            "adx_count": 0,
            "last_trade_ts": None,
        }
    return _stats[symbol]


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------


def record_trade(trade: dict) -> None:
    """
    Kapanan bir işlemi kaydet.

    Zorunlu alanlar:
        symbol, direction, entry, exit_price, pnl, status

    Opsiyonel — summary.csv için:
        gross_rr, exit_timestamp

    Opsiyonel — strategy_analiz.csv için (analyzer.py'den gelir):
        adx_at_entry, d1_close, d1_ema100, d1_ema_slope, trend_direction,
        choch_direction, choch_level, choch_bar_index,
        fvg_timeframe, fvg_direction, fvg_top, fvg_bottom,
        fvg_midpoint, fvg_size, fvg_bar_index,
        sl_price, tp_price, rr_ratio, lot_size, exit_timestamp

    Kullanım örneği (işlem kapandığında):
        trade = {
            # Zorunlu
            "symbol":     "BTCUSDT",
            "direction":  "LONG",
            "entry":      64200.0,
            "exit_price": 65100.0,
            "pnl":        48.2,
            "status":     "TP",

            # Strateji parametreleri (analyzer.py'den doldur)
            "exit_timestamp":  "2024-01-15 10:30:00",
            "d1_close":        64500.0,
            "d1_ema100":       63800.0,
            "d1_ema_slope":    0.0012,
            "adx_at_entry":    31.4,
            "trend_direction": "long",
            ...
        }
        performance.record_trade(trade)
    """
    try:
        symbol = trade.get("symbol")
        if not symbol:
            return

        pnl = float(trade.get("pnl") or 0)
        rr = float(trade.get("gross_rr") or 0)
        adx = float(trade.get("adx_at_entry") or trade.get("adx_val") or 0)

        s = _get_or_create(symbol)
        s["total"] += 1
        s["total_pnl"] += pnl
        s["total_rr"] += rr
        s["last_trade_ts"] = time.time()

        if pnl > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1

        if s["best_pnl"] is None or pnl > s["best_pnl"]:
            s["best_pnl"] = pnl
            s["best_trade"] = trade.get("direction", "")

        if s["worst_pnl"] is None or pnl < s["worst_pnl"]:
            s["worst_pnl"] = pnl
            s["worst_trade"] = trade.get("direction", "")

        if adx > 0:
            s["adx_sum"] += adx
            s["adx_count"] += 1

        # Trade log (sidebar + /api/trades için)
        _trade_log.append(
            {
                "ts": datetime.now(UTC).isoformat(),
                "symbol": symbol,
                "direction": trade.get("direction", ""),
                "entry": trade.get("entry"),
                "exit": trade.get("exit_price"),
                "pnl": round(pnl, 4),
                "rr": round(rr, 4),
                "adx": round(adx, 2),
                "status": trade.get("status", ""),
            }
        )

        # ── İki CSV'ye ayrı yaz ──
        _write_summary_csv(trade)
        _write_strategy_csv(trade)

        log.info(f"[PERF] {symbol} kaydedildi | pnl={pnl:.2f} win_rate={get_win_rate(symbol):.1f}%")

    except Exception as e:
        log.error(f"[PERF] record_trade hatası: {e}")


def get_stats(symbol: str | None = None) -> dict:
    """
    İstatistikleri döndürür.
    symbol=None → tüm semboller
    symbol=X    → tek sembol
    """
    if symbol:
        return _build_stat(symbol)
    return {sym: _build_stat(sym) for sym in sorted(_stats.keys())}


def get_win_rate(symbol: str) -> float:
    s = _stats.get(symbol)
    if not s or s["total"] == 0:
        return 0.0
    return round(s["wins"] / s["total"] * 100, 1)


def get_leaderboard() -> list[dict]:
    """PnL'e göre sıralı sembol listesi döndürür."""
    return sorted(
        [_build_stat(sym) for sym in _stats],
        key=lambda x: x["total_pnl"],
        reverse=True,
    )


def get_trade_log() -> list[dict]:
    """Tüm kapanan işlemleri döndürür (en yeni önce)."""
    return list(reversed(_trade_log))


# -------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------


def _build_stat(symbol: str) -> dict:
    s = _get_or_create(symbol)
    total = s["total"]
    return {
        "symbol": symbol,
        "total": total,
        "wins": s["wins"],
        "losses": s["losses"],
        "win_rate": round(s["wins"] / total * 100, 1) if total > 0 else 0.0,
        "total_pnl": round(s["total_pnl"], 2),
        "avg_pnl": round(s["total_pnl"] / total, 2) if total > 0 else 0.0,
        "avg_rr": round(s["total_rr"] / total, 2) if total > 0 else 0.0,
        "best_pnl": round(s["best_pnl"], 2) if s["best_pnl"] is not None else 0.0,
        "worst_pnl": round(s["worst_pnl"], 2) if s["worst_pnl"] is not None else 0.0,
        "avg_adx": (round(s["adx_sum"] / s["adx_count"], 1) if s["adx_count"] > 0 else 0.0),
        "last_trade": s["last_trade_ts"],
    }


def _fmt(v) -> str:
    return "" if v is None else str(v)


def _write_summary_csv(trade: dict) -> None:
    """
    Dashboard + Nexus Visualizer için hafif kayıt.
    Nexus uyumlu kolonlar: timestamp, close_time, symbol, side,
                           entry, exit_price, pnl, gross_rr, status
    """
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        write_header = not os.path.exists(SUMMARY_CSV)

        now_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

        # ── ZAMAN DÜZELTMESİ ──
        # entry_time: İşleme giriş anı (timestamp kolonu)
        entry_raw = trade.get("entry_timestamp") or trade.get("open_time") or now_utc
        if isinstance(entry_raw, int | float) and entry_raw > 1_000_000_000:
            entry_time = datetime.fromtimestamp(entry_raw / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        else:
            entry_time = str(entry_raw) if entry_raw else now_utc

        # close_time: İşlemden çıkış anı (close_time kolonu)
        exit_raw = trade.get("exit_timestamp") or trade.get("close_time") or now_utc
        if isinstance(exit_raw, int | float) and exit_raw > 1_000_000_000:
            close_time = datetime.fromtimestamp(exit_raw / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
        else:
            close_time = str(exit_raw) if exit_raw else now_utc

        with _csv_lock, open(SUMMARY_CSV, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(SUMMARY_FIELDS)
            writer.writerow(
                [
                    entry_time,  # 1. Kolon: Giriş Zamanı
                    close_time,  # 2. Kolon: Kapanış Zamanı
                    _fmt(trade.get("symbol")),
                    _fmt(
                        trade.get("side") or trade.get("direction", "")
                    ).upper(),  # 4. Kolon: side (Nexus 'side' bekliyor)
                    _fmt(trade.get("entry")),
                    _fmt(trade.get("exit_price")),
                    _fmt(round(float(trade.get("pnl") or 0), 4)),
                    _fmt(trade.get("gross_rr")),
                    _fmt(trade.get("status")),
                ]
            )

    except Exception as e:
        log.error(f"[PERF] summary.csv yazma hatası: {e}")


def _write_strategy_csv(trade: dict) -> None:
    """
    Derin analiz için tam kayıt.
    Dashboard bu dosyayı okumaz — sadece yazılır.
    Alanlar analyzer.py'den gelen AnalysisResult ile doldurulur.
    Eksik alanlar boş bırakılır, hata vermez.
    """
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        write_header = not os.path.exists(STRATEGY_CSV)

        # FVG büyüklüğü hesapla (eğer trade'de yoksa)
        fvg_top = _safe_float(trade.get("fvg_top"))
        fvg_bottom = _safe_float(trade.get("fvg_bottom"))
        fvg_size = round(fvg_top - fvg_bottom, 6) if (fvg_top and fvg_bottom) else ""

        # FVG midpoint (eğer trade'de yoksa hesapla)
        fvg_mid = trade.get("fvg_midpoint")
        if fvg_mid is None and fvg_top and fvg_bottom:
            fvg_mid = round((fvg_top + fvg_bottom) / 2, 6)

        with _csv_lock, open(STRATEGY_CSV, "a", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(STRATEGY_FIELDS)
            writer.writerow(
                [
                    # ── Kimlik
                    datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    _fmt(trade.get("symbol")),
                    _fmt(trade.get("direction", "")).upper(),
                    _fmt(trade.get("status")),
                    # ── Trend Katmanı (D1)
                    _fmt(trade.get("d1_close")),
                    _fmt(trade.get("d1_ema100")),
                    _fmt(trade.get("d1_ema_slope")),
                    _fmt(trade.get("adx_at_entry") or trade.get("adx_val")),
                    _fmt(trade.get("trend_direction")),
                    # ── CHoCH Katmanı (H1)
                    _fmt(trade.get("choch_direction")),
                    _fmt(trade.get("choch_level")),
                    _fmt(trade.get("choch_bar_index")),
                    # ── FVG Katmanı
                    _fmt(trade.get("fvg_timeframe")),
                    _fmt(trade.get("fvg_direction")),
                    _fmt(fvg_top),
                    _fmt(fvg_bottom),
                    _fmt(fvg_mid),
                    _fmt(fvg_size),
                    _fmt(trade.get("fvg_bar_index")),
                    # ── Giriş
                    _fmt(trade.get("entry")),
                    _fmt(trade.get("sl_price")),
                    _fmt(trade.get("tp_price")),
                    _fmt(trade.get("rr_ratio")),
                    _fmt(trade.get("lot_size")),
                    # ── Çıkış
                    _fmt(trade.get("exit_price")),
                    _fmt(trade.get("exit_timestamp") or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")),
                    _fmt(round(float(trade.get("pnl") or 0), 4)),
                    _fmt(trade.get("gross_rr")),
                ]
            )

    except Exception as e:
        log.error(f"[PERF] strategy_analiz.csv yazma hatası: {e}")
