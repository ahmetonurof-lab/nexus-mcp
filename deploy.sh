#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# NEXUS — Sunucu Kurulum Scripti (sniper + sonnet)
# Kullanım:  bash deploy.sh [--sniper|--sonnet|--all]
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SNIPER_DIR="$REPO_DIR/sniper/src"
SONNET_DIR="$REPO_DIR/sonnet/src"
TARGET="${1:---all}"

echo "=== NEXUS Sunucu Kurulumu ($TARGET) ==="

# ── 1) Python versiyonu kontrol ──────────────────────────────
echo ""
echo "[1/7] Python versiyonu kontrol ediliyor..."
PYTHON_CMD=""
if command -v python3 &>/dev/null; then
    PYTHON_CMD="python3"
elif command -v python &>/dev/null; then
    PYTHON_CMD="python"
else
    echo "HATA: Python bulunamadi! Python 3.12+ gerekli."
    echo "  Ubuntu/Debian:  sudo apt install python3.12 python3.12-venv"
    echo "  CentOS/RHEL:    sudo dnf install python3.12"
    exit 1
fi
PY_VER=$($PYTHON_CMD --version 2>&1 | grep -oP '\d+\.\d+')
echo "  Bulunan: Python $PY_VER"

# ── 2) pip kontrol ──────────────────────────────────────────
echo ""
echo "[2/7] pip kontrol ediliyor..."
$PYTHON_CMD -m pip --version &>/dev/null || {
    echo "  pip bulunamadi, kuruluyor..."
    $PYTHON_CMD -m ensurepip --upgrade
}

# ── 3) Sanal ortam olustur ──────────────────────────────────
echo ""
echo "[3/7] Sanal ortam olusturuluyor..."
if [ ! -d "$REPO_DIR/.venv" ]; then
    $PYTHON_CMD -m venv "$REPO_DIR/.venv"
    echo "  .venv olusturuldu."
else
    echo "  .venv zaten mevcut, atlandi."
fi
source "$REPO_DIR/.venv/bin/activate"
pip install --upgrade pip -q

# ── 4) Bağımlılıkları yukle ─────────────────────────────────
echo ""
echo "[4/7] pip bağımlılıkları yukleniyor..."
if [ "$TARGET" = "--sniper" ] || [ "$TARGET" = "--all" ]; then
    echo "  → sniper/requirements.txt"
    pip install -r "$REPO_DIR/sniper/requirements.txt" -q
fi
if [ "$TARGET" = "--sonnet" ] || [ "$TARGET" = "--all" ]; then
    echo "  → sonnet/requirements.txt"
    pip install -r "$REPO_DIR/sonnet/requirements.txt" -q
fi
echo "  Tamamlandi."

# ── 5) .env kontrol ─────────────────────────────────────────
echo ""
echo "[5/7] .env dosyasi kontrol ediliyor..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  !! .env olusturuldu — LUTFEN GERCEK API KEY'LERI DOLDUR!"
    echo "     nano $REPO_DIR/.env"
    echo ""
else
    echo "  .env mevcut."
fi

# ── 6) Output klasorleri ────────────────────────────────────
echo ""
echo "[6/7] Output klasorleri olusturuluyor..."
if [ "$TARGET" = "--sniper" ] || [ "$TARGET" = "--all" ]; then
    mkdir -p "$SNIPER_DIR/output/trading"
    mkdir -p "$SNIPER_DIR/output/live_ohlc"
fi
if [ "$TARGET" = "--sonnet" ] || [ "$TARGET" = "--all" ]; then
    mkdir -p "$SONNET_DIR/output/trading"
    mkdir -p "$SONNET_DIR/output/live_ohlc"
    mkdir -p "$SONNET_DIR/output/summary"
fi
echo "  Tamamlandi."

# ── 7) Ozet ─────────────────────────────────────────────────
echo ""
echo "[7/7] Kurulum tamamlandi."
echo ""
echo "=== Bot Baslatma Komutlari ==="
echo ""
if [ "$TARGET" = "--sniper" ] || [ "$TARGET" = "--all" ]; then
    echo "  SNIPER:"
    echo "    cd $SNIPER_DIR && source ../../.venv/bin/activate && python bot.py"
    echo ""
fi
if [ "$TARGET" = "--sonnet" ] || [ "$TARGET" = "--all" ]; then
    echo "  SONNET:"
    echo "    cd $SONNET_DIR && source ../../.venv/bin/activate && python bot.py"
    echo ""
fi
echo "  Arka plan (screen):"
echo "    screen -S nexus"
echo "    <yukaridaki baslatma komutu>"
echo "    # Ayrilmak icin: Ctrl+A, D"
echo ""
