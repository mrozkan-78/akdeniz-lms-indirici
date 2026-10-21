#!/usr/bin/env bash
# =============================================================================
# kurulum_bulut.sh — Moodle İndirici'yi Ubuntu bulut sunucusuna kurar.
#
# Bilgisayardaki BULUTA_GONDER.bat bu dosyayı ~/moodle-kurulum/ klasörüne
# kopyalayıp çalıştırır. Elle çalıştırmak için:  bash ~/moodle-kurulum/kurulum_bulut.sh
#
# Yaptıkları:
#   1. Saat dilimini İstanbul yapar, gerekli paketleri kurar
#   2. RAM 2 GB'tan azsa 2 GB swap ekler (Chromium için)
#   3. ~/moodle-indirici altına betiği, ayarları ve veritabanını yerleştirir
#   4. Python sanal ortamı + Playwright Chromium kurar
#   5. Tek tur deneme yapar (giriş çalışıyor mu?)
#   6. systemd servisi olarak 7/24 çalıştırır (çökerse / sunucu yeniden
#      başlarsa otomatik başlar)
# Çıkış kodu: 0 = kurulum + giriş başarılı, 3 = kurulum tamam ama giriş başarısız
# =============================================================================
set -euo pipefail

SRC="$HOME/moodle-kurulum"
APP="$HOME/moodle-indirici"
SERVICE="moodle-indirici"
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/6 Sistem paketleri kuruluyor (birkaç dakika sürebilir)..."
sudo timedatectl set-timezone Europe/Istanbul || true
sudo apt-get update -y -qq
sudo apt-get install -y -qq python3-venv python3-pip sqlite3 >/dev/null

echo "==> 2/6 Bellek kontrolü..."
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 2000 ] && ! swapon --show | grep -q .; then
    echo "    RAM ${MEM_MB} MB; 2 GB swap ekleniyor..."
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null
    sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
else
    echo "    Yeterli (RAM ${MEM_MB} MB)."
fi

echo "==> 3/6 Dosyalar yerleştiriliyor..."
mkdir -p "$APP/Moodle_Dosyalari"
cp "$SRC/moodle_indirici.py" "$APP/"
# Ayar dosyası ve veritabanı sadece ilk kurulumda kopyalanır; yeniden
# gönderimde sunucudaki güncel hâlleri (Telegram bağlantısı, indirme geçmişi) korunur.
[ -f "$APP/gizli_ayarlar.json" ] || cp "$SRC/gizli_ayarlar.json" "$APP/"
if [ ! -f "$APP/indirilenler.db" ] && [ -f "$SRC/indirilenler.db" ]; then
    cp "$SRC/indirilenler.db" "$APP/"
fi
# Bu makine Telegram'a GÖNDERMELİ: bayrağı açık yap
python3 - "$APP/gizli_ayarlar.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8-sig"))
d["telegram_aktif"] = True
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
chmod 600 "$APP/gizli_ayarlar.json"
# Kurulum klasöründeki şifreli kopyayı sil
rm -f "$SRC/gizli_ayarlar.json"

echo "==> 4/6 Python ortamı ve Chromium kuruluyor..."
[ -d "$APP/venv" ] || python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q requests beautifulsoup4 playwright
sudo "$APP/venv/bin/playwright" install-deps chromium >/dev/null
"$APP/venv/bin/playwright" install chromium >/dev/null

echo "==> 5/6 Deneme turu (Moodle girişi test ediliyor, ~1-3 dk)..."
sudo systemctl stop "$SERVICE" 2>/dev/null || true
LOG="$APP/moodle_indirici.log"
BEFORE=$( [ -f "$LOG" ] && wc -l < "$LOG" || echo 0 )
( cd "$APP" && MOODLE_ROOT="$APP/Moodle_Dosyalari" timeout 900 \
    "$APP/venv/bin/python" moodle_indirici.py --once >/dev/null 2>&1 ) || true
NEWLINES=$(tail -n +"$((BEFORE + 1))" "$LOG" 2>/dev/null || true)
echo "$NEWLINES" | sed 's/^/    /'
LOGIN_OK=0
echo "$NEWLINES" | grep -q "Moodle'a giriş yapıldı" && LOGIN_OK=1

echo "==> 6/6 7/24 servis kuruluyor..."
sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=Moodle Indirici (Akdeniz LMS -> Telegram)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP
Environment=MOODLE_ROOT=$APP/Moodle_Dosyalari
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP/venv/bin/python $APP/moodle_indirici.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE" >/dev/null 2>&1
sleep 3
echo "    Servis durumu: $(systemctl is-active $SERVICE)"

echo
if [ "$LOGIN_OK" = 1 ]; then
    echo "KURULUM TAMAM: Sunucu Moodle'a giriş yaptı ve 7/24 çalışıyor."
    exit 0
else
    echo "UYARI: Kurulum tamam ama Moodle girişi BAŞARISIZ (yukarıdaki log'a bak)."
    echo "Servis 15 dakikada bir tekrar deneyecek; sorun Telegram'a da bildirilecek."
    exit 3
fi
