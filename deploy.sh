#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# NEXUS V4 — Sunucu Kurulum Scripti
# Kullanım:  bash deploy.sh
# ──────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SONNET_DIR="$REPO_DIR/sonnet/src"

echo "=== NEXUS V4 Sunucu Kurulumu ==="

# 1) Python versiyonu kontrol
echo ""
echo "[1/6] Python versiyonu kontrol ediliyor..."
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

# 2) pip kontrol
echo ""
echo "[2/6] pip kontrol ediliyor..."
$PYTHON_CMD -m pip --version &>/dev/null || {
    echo "HATA: pip bulunamadi! Kuruluyor..."
    $PYTHON_CMD -m ensurepip --upgrade
}

# 3) Sanal ortam olustur
echo ""
echo "[3/6] Sanal ortam olusturuluyor..."
if [ ! -d "$REPO_DIR/.venv" ]; then
    $PYTHON_CMD -m venv "$REPO_DIR/.env"
    echo "  .venv olusturuldu."
else
    echo "  .venv zaten mevcut, atlanıyor."
fi

# 4) Bağımlılıkları yukle
echo ""
echo "[4/6] pip bağımlılıkları yukleniyor..."
source "$REPO_DIR/.venv/bin/activate"
pip install --upgrade pip
pip install -r "$REPO_DIR/sonnet/requirements.txt"
echo "  Tamamlandı."

# 5) .env kontrol
echo ""
echo "[5/6] .env dosyası kontrol ediliyor..."
if [ ! -f "$REPO_DIR/.env" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo ""
    echo "  ⚠  .env dosyası olusturuldu — LÜTFEN GERÇEK API KEY'LERİ DOLDUR!"
    echo "     nano $REPO_DIR/.env"
    echo ""
else
    echo "  .env mevcut."
fi

# 6) Output klasörlerini olustur
echo ""
echo "[6/6] Output klasörleri olusturuluyor..."
mkdir -p "$SONNET_DIR/output/trading"
mkdir -p "$SONNET_DIR/output/live_ohlc"
mkdir -p "$SONNET_DIR/output/summary"
echo "  Tamamlandı."

echo ""
echo "=== Kurulum Tamamlandı ==="
echo ""
echo "Botu baslatmak icin:"
echo "  cd $SONNET_DIR && source ../../.venv/bin/activate && python bot.py"
echo ""
echo "Arka planda calistirmak icin (screen):"
echo "  screen -S nexus"
echo "  cd $SONNET_DIR && source ../../.venv/bin/activate && python bot.py"
echo "  # Ayrılmak icin: Ctrl+A, D"
echo ""
