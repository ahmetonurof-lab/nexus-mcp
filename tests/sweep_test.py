import os

import pandas as pd

# --- AYARLAR ---
SUMMARY_FILE = "sonnet/src/output/summary/summary_2026-06-12.csv"
DATA_DIR = "data"  # Ham veri dosyalarının (örn: LINKUSDT_1h.csv) bulunduğu klasör
ATR_PERIOD = 14
PENETRATION_MULT = 0.10  # ATR'in %10'u kadar fitil olması gerekir


def calculate_atr(df, period=ATR_PERIOD):
    high = df["high"]
    low = df["low"]
    close = df["close"].shift(1)

    tr1 = high - low
    tr2 = abs(high - close)
    tr3 = abs(low - close)

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr


def check_sweep_rules(row, df_1h):
    """
    Yeni Sweep Kuralları:
    1. Wick (Fitil) Seviyeyi Kırmalı
    2. Kapanış Seviyenin İçinde Kalmalı (False Breakout)
    3. Minimum Penetrasyon (ATR x 0.10)
    """
    if not row["sweep"]:
        return None  # Zaten sweep yoksa kontrol etmeye gerek yok (veya missed arıyorsan bu kısmı değiştirebiliriz)

    sweep_level = row["sweep_level"]
    sweep_side = row["sweep_side"]
    sweep_bar_index = row["sweep_bar_index"]

    # İlgili barı ve bir önceki barı bul
    # Not: summary'deki bar_index, ham verideki index ile eşleşmeli.
    # Eğer saat bazlı ise timestamp eşleştirmesi daha sağlıklıdır.
    # Burada basitlik için index kullanıyoruz, hata payı varsa timestamp'e çevrilmeli.

    try:
        # Güvenlik: Index sınırlarını kontrol et
        if sweep_bar_index >= len(df_1h) or sweep_bar_index < 1:
            return {"status": "ERROR", "reason": "Index out of bounds"}

        current_bar = df_1h.iloc[sweep_bar_index]

        # ATR Hesabı (O anki değer)
        # Not: ATR'i tüm df için önceden hesaplayıp buraya getirmek daha performanslı olur
        # ama basitlik için burada hesaplıyoruz (veya dışarıdan geçebiliriz)
        atr_val = calculate_atr(df_1h).iloc[sweep_bar_index]
        if pd.isna(atr_val):
            return {"status": "SKIP", "reason": "ATR NaN (veri yetersiz)"}

        min_penetration = atr_val * PENETRATION_MULT

        is_valid = False
        reason = ""

        if sweep_side == "HIGH":
            # Kural 1: Fitil seviyeyi kırdı mı?
            wick_break = current_bar["high"] > sweep_level

            # Kural 2: Kapanış içeride mi? (Seviyenin altında)
            close_inside = current_bar["close"] < sweep_level

            # Kural 3: Minimum penetrasyon sağlandı mı?
            penetration = current_bar["high"] - sweep_level
            valid_penetration = penetration >= min_penetration

            if wick_break and close_inside and valid_penetration:
                is_valid = True
                reason = f"Wick:{current_bar['high']:.4f} > Level:{sweep_level:.4f}, Close:{current_bar['close']:.4f} < Level. Pen:{penetration:.4f} (> {min_penetration:.4f})"
            else:
                reason = (
                    f"Fail: WickBreak={wick_break}, CloseIn={close_inside}, Pen={penetration:.4f}/{min_penetration:.4f}"
                )

        elif sweep_side == "LOW":
            # Kural 1: Fitil seviyeyi kırdı mı?
            wick_break = current_bar["low"] < sweep_level

            # Kural 2: Kapanış içeride mi? (Seviyenin üstünde)
            close_inside = current_bar["close"] > sweep_level

            # Kural 3: Minimum penetrasyon sağlandı mı?
            penetration = sweep_level - current_bar["low"]
            valid_penetration = penetration >= min_penetration

            if wick_break and close_inside and valid_penetration:
                is_valid = True
                reason = f"Wick:{current_bar['low']:.4f} < Level:{sweep_level:.4f}, Close:{current_bar['close']:.4f} > Level. Pen:{penetration:.4f} (> {min_penetration:.4f})"
            else:
                reason = (
                    f"Fail: WickBreak={wick_break}, CloseIn={close_inside}, Pen={penetration:.4f}/{min_penetration:.4f}"
                )
        else:
            return {"status": "ERROR", "reason": f"Unknown sweep side: {sweep_side}"}

        return {
            "status": "VALID" if is_valid else "INVALID",
            "reason": reason,
            "details": {
                "open": current_bar["open"],
                "high": current_bar["high"],
                "low": current_bar["low"],
                "close": current_bar["close"],
                "atr": atr_val,
            },
        }

    except Exception as e:
        return {"status": "ERROR", "reason": str(e)}


def main():
    print(f"📂 Özet dosyası okunuyor: {SUMMARY_FILE}")

    if not os.path.exists(SUMMARY_FILE):
        print(f"❌ HATA: Dosya bulunamadı! Yol yanlış olabilir: {SUMMARY_FILE}")
        return

    df_summary = pd.read_csv(SUMMARY_FILE)

    # Sadece sweep olanları filtrele
    sweeps = df_summary[df_summary["sweep"]].copy()

    if sweeps.empty:
        print("✅ Özet dosyasında işaretlenmiş hiç SWEEP bulunamadı.")
        return

    print(f"🔍 {len(sweeps)} adet sweep kaydı bulundu. Detaylı kontrol başlatılıyor...\n")

    results = []

    for index, row in sweeps.iterrows():
        symbol = row["symbol"]
        # Veri dosyası adı formatı: LINKUSDT_1h.csv (Varsayım)
        # Proje yapısına göre zaman dilimi değişebilir (genelde sweep 1H veya 15m'de bakılır)
        # Analyzer.py'de hangi timeframe'de sweep arandığını biliyorsan burayı güncelle.
        # Şimdilik 1H varsayalım, yoksa 15m deneyelim.

        data_file_1h = os.path.join(DATA_DIR, f"{symbol}_1h.csv")
        data_file_15m = os.path.join(DATA_DIR, f"{symbol}_15m.csv")

        df_1h = None

        if os.path.exists(data_file_1h):
            df_1h = pd.read_csv(data_file_1h)
        elif os.path.exists(data_file_15m):
            df_1h = pd.read_csv(data_file_15m)  # Değişken adı aynı kalabilir, mantık aynı
        else:
            print(f"⚠️  Veri dosyası bulunamadı: {symbol} (Ne _1h ne _15m)")
            results.append(
                {
                    "timestamp": row["timestamp"],
                    "symbol": symbol,
                    "side": row["sweep_side"],
                    "level": row["sweep_level"],
                    "status": "NO_DATA",
                    "reason": "Ham veri dosyası eksik",
                }
            )
            continue

        # Bar index'in doğru olduğundan emin ol (Timestamp eşleştirmesi daha güvenli olabilir ama şimdilik index)
        # Eğer summary'deki index, ham verinin satır numarası ise bu çalışır.
        # Değilse, row['timestamp'] ile df içinde eşleştirme yapılmalı.
        # Basitlik için index kullanıyoruz, hata alırsan timestamp moduna geçeriz.

        res = check_sweep_rules(row, df_1h)

        if res:
            results.append(
                {
                    "timestamp": row["timestamp"],
                    "symbol": symbol,
                    "side": row["sweep_side"],
                    "level": row["sweep_level"],
                    "status": res["status"],
                    "reason": res["reason"],
                }
            )

            # Konsola yazdır
            icon = "✅" if res["status"] == "VALID" else "❌"
            if res["status"] == "ERROR":
                icon = "⚠️"
            print(f"{icon} [{symbol}] {row['timestamp']} - {res['status']}: {res['reason']}")

    # Sonuçları kaydet
    output_file = "sweep_test_results.csv"
    df_results = pd.DataFrame(results)
    df_results.to_csv(output_file, index=False)
    print(f"\n📊 Detaylı sonuçlar '{output_file}' dosyasına kaydedildi.")

    # Özet istatistik
    if not df_results.empty:
        valid_count = len(df_results[df_results["status"] == "VALID"])
        invalid_count = len(df_results[df_results["status"] == "INVALID"])
        print("\n--- ÖZET ---")
        print(f"Toplam Kontrol: {len(df_results)}")
        print(f"Geçerli Sweep (Kurallara Uyan): {valid_count}")
        print(f"Geçersiz Sweep (Kural Dışı): {invalid_count}")


if __name__ == "__main__":
    main()
