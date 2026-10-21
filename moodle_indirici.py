# -*- coding: utf-8 -*-
"""
moodle_indirici.py
==================
Akdeniz Üniversitesi LMS (Moodle 4.5) için arka planda sessiz çalışan
dosya indirme otomasyonu.

Ne yapar?
---------
1. Moodle'a kullanıcı adı / şifre ile giriş yapar (requests + BeautifulSoup,
   tarayıcı açmaz -> tamamen headless).
2. COURSES listesindeki her ders sayfasını belirli aralıklarla (varsayılan
   15 dk) tarar.
3. Sayfadaki tüm dosyaları bulur:
     - "Dosya" etkinlikleri          (mod/resource)
     - "Klasör" etkinlikleri içindeki dosyalar (mod/folder)
     - Etiket / açıklama içine gömülü doğrudan dosya linkleri (pluginfile.php)
     - Ödev (mod/assign) açıklamalarına eklenmiş dosyalar
4. Daha önce indirilmemiş olanları
       Masaüstü/Moodle_Dosyalari/<Ders_Klasoru>/
   altına indirir ve SQLite veritabanına kaydeder (tekrar indirmez).
5. Her indirmeyi log dosyasına + (varsa) konsola yazar, Windows bildirimi
   gösterir.
6. 403 / 404 / zaman aşımı / bağlantı hatalarında 30 sn arayla 3 kez daha
   dener; olmazsa loglayıp devam eder. Ağ kopsa bile betik çökmez.

Kullanım
--------
    pythonw moodle_indirici.py          # sonsuz döngü, sessiz (önerilen)
    python  moodle_indirici.py          # sonsuz döngü, konsolda log görünür
    python  moodle_indirici.py --once   # tek tarama yapıp çıkar (test için)
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import random
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# =============================================================================
# 1) AYARLAR  — sadece bu bölümü düzenlemen yeterli
# =============================================================================

# Giriş bilgileri ve Telegram ayarları artık KODDAN AYRI olarak
# gizli_ayarlar.json dosyasında tutulur (betik güncellense de silinmez):
#   {
#     "moodle_user": "OGRENCI_NO",
#     "moodle_pass": "şifren",
#     "telegram_token": "BotFather'ın verdiği token",
#     "telegram_chat_id": ""      <- boş bırak, bota /start yazınca otomatik dolar
#   }
# Aşağıdaki iki değişken sadece JSON dosyası yoksa yedek olarak kullanılır.
USERNAME = ""
PASSWORD = ""

BASE_URL = "https://lms.akdeniz.edu.tr/moodle"

# Kullanıcı adına "@" yazılmamışsa sonuna bu alan adı eklenir
# (örn. OGRENCI_NO -> OGRENCI_NO@ogr.akdeniz.edu.tr)
EMAIL_DOMAIN = "ogr.akdeniz.edu.tr"

# Takip edilecek dersler: (ders sayfası URL'si, görünen ad, Masaüstündeki alt klasör adı)
COURSES = [
    {
        "url": "https://lms.akdeniz.edu.tr/moodle/course/view.php?id=1728",
        "name": "Natural Science",
        "folder": "Natural_Science",
    },
    {
        "url": "https://lms.akdeniz.edu.tr/moodle/course/view.php?id=1690",
        "name": "Atatürk İlkeleri ve İnkılap Tarihi I",
        "folder": "Ataturk_Ilkeleri_ve_Inkilap_Tarihi_I",
    },
    {
        "url": "https://lms.akdeniz.edu.tr/moodle/course/view.php?id=1675",
        "name": "Veri Yapıları",
        "folder": "Veri_Yapilari",
    },
]

CHECK_INTERVAL_SECONDS = 15 * 60      # dersler kaç saniyede bir kontrol edilsin
REQUEST_DELAY_RANGE = (2.0, 5.0)      # her istek arası rastgele bekleme (sn)
CYCLE_JITTER_SECONDS = (0, 90)        # tur aralığına eklenen rastgele sapma
RETRY_COUNT = 3                       # ilk denemeden SONRA kaç kez daha denensin
RETRY_WAIT_SECONDS = 30               # denemeler arası bekleme
REQUEST_TIMEOUT = (15, 60)            # (bağlanma, okuma) zaman aşımı
ENABLE_TOAST = True                   # Windows bildirimi göster

ROOT_FOLDER_NAME = "Moodle_Dosyalari"
SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "indirilenler.db"
LOG_PATH = SCRIPT_DIR / "moodle_indirici.log"
BROWSER_PROFILE_DIR = SCRIPT_DIR / "tarayici_profili"   # Microsoft oturum çerezleri
SECRETS_PATH = SCRIPT_DIR / "gizli_ayarlar.json"          # giriş + Telegram bilgileri
TELEGRAM_MAX_BYTES = 50 * 1024 * 1024                     # Telegram bot dosya sınırı
TELEGRAM_POLL_SECONDS = 60          # bekleme sırasında Telegram kuyruğu kaç sn'de bir kontrol edilsin

# Tarayıcı gibi görünmek için makul bir User-Agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)

# =============================================================================
# 2) YARDIMCI ARAÇLAR: masaüstü yolu, loglama, bildirim, bekleme
# =============================================================================


def get_desktop_path() -> Path:
    """Windows'ta gerçek Masaüstü yolunu döndürür.

    OneDrive Masaüstünü yönlendirmişse (C:\\Users\\X\\OneDrive\\Desktop gibi)
    ~/Desktop yanlış olur; bu yüzden Windows'un 'Known Folder' API'si kullanılır.
    """
    if os.name == "nt":
        try:
            class GUID(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                            ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

            u = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")  # FOLDERID_Desktop
            guid = GUID(u.fields[0], u.fields[1], u.fields[2],
                        (ctypes.c_ubyte * 8)(*u.bytes[8:]))
            path_ptr = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(
                    ctypes.byref(guid), 0, None, ctypes.byref(path_ptr)) == 0:
                desktop = Path(path_ptr.value)
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                return desktop
        except Exception:
            pass
    return Path.home() / "Desktop"


def setup_logging() -> logging.Logger:
    """Log dosyasına ve (konsol varsa) terminale yazan logger kurar.

    pythonw ile çalışırken sys.stdout None olur; o durumda sadece dosyaya yazılır.
    Mesajların kendisi [TARİH/SAAT] önekini formatter üzerinden alır.
    """
    logger = logging.getLogger("moodle")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%d.%m.%Y %H:%M:%S")

    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # Türkçe karakterler için
        except Exception:
            pass
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


log = setup_logging()


def notify(title: str, message: str) -> None:
    """Sağ altta sessiz Windows bildirimi gösterir. Hata verirse sessizce geçer.

    Not: win10toast yeni Python sürümlerinde (3.12+) sorun çıkardığı için
    bağımlılıksız ve güncel 'winotify' kütüphanesi kullanılıyor.
    """
    if not ENABLE_TOAST or os.name != "nt":
        return
    try:
        from winotify import Notification
        toast = Notification(app_id="Moodle İndirici", title=title, msg=message,
                             duration="short")
        toast.set_audio(None, loop=False)  # sessiz
        toast.show()
    except Exception as exc:  # bildirim asla betiği durdurmamalı
        log.debug("Bildirim gösterilemedi: %s", exc)


def polite_sleep() -> None:
    """Sunucuya yük bindirmemek için istekler arasında rastgele bekler."""
    time.sleep(random.uniform(*REQUEST_DELAY_RANGE))


def safe_filename(name: str) -> str:
    """Windows'ta geçersiz karakterleri temizler."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    return name[:180] or "dosya"


# =============================================================================
# 3) VERİTABANI: daha önce indirilenleri hatırlamak için SQLite
# =============================================================================


class DownloadDB:
    """İndirilen dosyaları benzersiz bir anahtarla (link) saklar."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS downloads (
                   key        TEXT PRIMARY KEY,   -- benzersiz link/kimlik
                   course     TEXT,
                   filename   TEXT,
                   saved_path TEXT,
                   downloaded_at TEXT
               )"""
        )
        # Eski veritabanlarına "Telegram'a gönderildi mi?" sütununu ekle.
        # Varsayılan 0 olduğu için daha önce inmiş dosyalar da telefona gönderilir.
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(downloads)")]
        if "telegram_sent" not in cols:
            self.conn.execute("ALTER TABLE downloads ADD COLUMN telegram_sent INTEGER DEFAULT 0")
        self.conn.commit()

    def pending_telegram(self) -> list[tuple]:
        """Henüz telefona gönderilmemiş dosyalar (eskiden yeniye)."""
        return self.conn.execute(
            "SELECT key, course, filename, saved_path FROM downloads "
            "WHERE telegram_sent = 0 ORDER BY downloaded_at").fetchall()

    def mark_telegram_sent(self, key: str) -> None:
        self.conn.execute("UPDATE downloads SET telegram_sent = 1 WHERE key = ?", (key,))
        self.conn.commit()

    def has(self, key: str) -> bool:
        return self.conn.execute("SELECT 1 FROM downloads WHERE key=?", (key,)).fetchone() is not None

    def add(self, key: str, course: str, filename: str, saved_path: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO downloads (key, course, filename, saved_path, "
            "downloaded_at, telegram_sent) VALUES (?,?,?,?,?,0)",
            (key, course, filename, saved_path, datetime.now().isoformat(timespec="seconds")),
        )
        self.conn.commit()


# =============================================================================
# 3b) AYAR DOSYASI ve TELEGRAM: dosyaları telefona gönderme
# =============================================================================


def load_secrets() -> dict:
    """gizli_ayarlar.json dosyasını okur (yoksa boş sözlük)."""
    import json
    try:
        return json.loads(SECRETS_PATH.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.info("UYARI: gizli_ayarlar.json okunamadı (%s).", exc)
        return {}


def save_secrets(data: dict) -> None:
    import json
    SECRETS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class TelegramNotifier:
    """Telegram Bot API ile dosya + açıklama gönderir.

    - Token gizli_ayarlar.json'daki "telegram_token" alanından okunur.
    - chat_id boşsa: bota telefondan /start (veya herhangi bir mesaj) yazdığında
      betik bunu yakalar, chat_id'yi kaydeder ve "Bağlandı" mesajı atar.
    - Gönderilemeyen dosyalar veritabanında bekler; internet gelince gönderilir.
    """

    API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, secrets: dict):
        self.secrets = secrets
        self.token = (secrets.get("telegram_token") or "").strip()
        self.chat_id = str(secrets.get("telegram_chat_id") or "").strip()
        self._warned = False
        self._last_alert: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        # "telegram_aktif": false -> bu makine Telegram'a hiç göndermez
        # (bulut sunucusu gönderirken bilgisayardaki kopya çift mesaj atmasın diye)
        return bool(self.token) and self.secrets.get("telegram_aktif", True) is not False

    def alert(self, text: str, key: str, every_seconds: int = 6 * 3600) -> None:
        """Uyarı mesajı gönderir; aynı uyarıyı 6 saatte bir defadan fazla atmaz."""
        self.reload_if_needed()
        if not self.enabled or not self.ensure_chat():
            return
        if time.time() - self._last_alert.get(key, 0) < every_seconds:
            return
        self.send_text(text)
        self._last_alert[key] = time.time()

    def reload_if_needed(self) -> None:
        """Token/chat_id boşsa ayar dosyasını yeniden okur.

        Böylece betik çalışırken gizli_ayarlar.json'a token yazıldığında
        görevi yeniden başlatmaya gerek kalmaz.
        """
        if self.token and self.chat_id:
            return
        fresh = load_secrets()
        if fresh:
            self.secrets.update(fresh)
            self.token = (self.secrets.get("telegram_token") or "").strip()
            self.chat_id = str(self.secrets.get("telegram_chat_id") or "").strip()

    def _call(self, method: str, **kwargs) -> dict:
        url = self.API.format(token=self.token, method=method)
        r = requests.post(url, timeout=(15, 120), **kwargs)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        return data["result"]

    def ensure_chat(self) -> bool:
        """chat_id yoksa bota gelen son mesajdan bulmaya çalışır."""
        if self.chat_id:
            return True
        try:
            updates = self._call("getUpdates", data={"timeout": 0})
        except Exception as exc:
            log.info("UYARI: Telegram'a bağlanılamadı (%s). Token'ı kontrol et.", exc)
            return False
        for upd in reversed(updates):
            msg = upd.get("message") or upd.get("edited_message")
            if msg and msg.get("chat", {}).get("type") == "private":
                self.chat_id = str(msg["chat"]["id"])
                self.secrets["telegram_chat_id"] = self.chat_id
                save_secrets(self.secrets)
                self.send_text("✅ Moodle İndirici bağlandı! Derslere eklenen dosyaları "
                               "buradan göndereceğim.")
                log.info("BİLGİ: Telegram sohbeti bağlandı.")
                return True
        if not self._warned:
            log.info("BİLGİ: Telegram botu hazır; bağlanması için telefondan bota /start yaz.")
            self._warned = True
        return False

    def send_text(self, text: str) -> None:
        self._call("sendMessage", data={"chat_id": self.chat_id, "text": text})

    def send_file(self, path: Path, caption: str) -> None:
        """Dosyayı açıklamasıyla gönderir; 50 MB'tan büyükse sadece mesaj atar."""
        if path.stat().st_size > TELEGRAM_MAX_BYTES:
            self.send_text(caption + "\n\n⚠️ Dosya 50 MB'tan büyük olduğu için "
                                     "gönderilemedi; bilgisayarındaki klasörde duruyor.")
            return
        with open(path, "rb") as fh:
            self._call("sendDocument",
                       data={"chat_id": self.chat_id, "caption": caption[:1024]},
                       files={"document": (path.name, fh)})

    def flush(self, db: "DownloadDB") -> None:
        """Telefona gönderilmemiş tüm dosyaları sırayla gönderir."""
        self.reload_if_needed()
        if not self.enabled or not self.ensure_chat():
            return
        for key, course, filename, saved_path in db.pending_telegram():
            path = Path(saved_path)
            if not path.exists():           # dosya silinmişse tekrar deneme
                db.mark_telegram_sent(key)
                continue
            caption = f"📚 {course} dersinden\n📄 {filename} isimli dosya"
            try:
                self.send_file(path, caption)
                db.mark_telegram_sent(key)
                log.info("TELEGRAM: %s dersinden %s telefona gönderildi.", course, filename)
                time.sleep(1.5)             # Telegram hız sınırına takılmamak için
            except Exception as exc:
                log.info("UYARI: %s Telegram'a gönderilemedi (%s); daha sonra tekrar "
                         "denenecek.", filename, exc)
                return                      # internet yoksa diğerlerini de bekletelim


# =============================================================================
# 4) MOODLE OTURUMU: giriş, sayfa çekme, oturum düşerse yeniden giriş
# =============================================================================


class LoginError(Exception):
    pass


class RetryableHTTPError(Exception):
    """403 / 404 / 5xx gibi yeniden denenebilecek HTTP hataları."""


class MoodleClient:
    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept-Language": "tr-TR,tr;q=0.9"})

    # ---------------- giriş ----------------
    def login(self) -> None:
        """'Akdeniz Üniversitesi Hesabın ile Giriş Yap' (Microsoft) akışıyla giriş yapar.

        Akış:
          1. Arayüzsüz (headless) Edge/Chrome açılır (Playwright).
          2. Moodle'ın OIDC butonu adresine gidilir -> Microsoft giriş sayfası.
          3. E-posta ve şifre girilir, "Oturum açık kalsın mı?" sorusuna Evet denir.
          4. Moodle'a geri dönülünce tarayıcı çerezleri (MoodleSession) requests
             oturumuna kopyalanır; tarama/indirme işleri hızlı requests ile yapılır.
        Tarayıcı profili BROWSER_PROFILE_DIR'de saklanır; böylece sonraki
        girişlerde Microsoft çoğu zaman şifre bile sormadan oturumu açar.
        """
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = self._launch_browser(p)
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(f"{BASE_URL}/auth/oidc/?source=loginpage",
                          wait_until="domcontentloaded", timeout=60_000)
                self._complete_microsoft_login(page)
                cookies = ctx.cookies()
            finally:
                ctx.close()

        # Tarayıcı çerezlerini requests oturumuna aktar
        self.session.cookies.clear()
        for c in cookies:
            self.session.cookies.set(c["name"], c["value"],
                                     domain=c.get("domain"), path=c.get("path", "/"))

        # Gerçekten giriş yapıldı mı? Panoyu açıp kontrol et.
        polite_sleep()
        r = self.session.get(f"{BASE_URL}/my/", timeout=REQUEST_TIMEOUT)
        if self._is_login_page(r):
            raise LoginError("Microsoft girişi tamamlandı ama Moodle oturumu açılamadı.")
        log.info("BİLGİ: Moodle'a giriş yapıldı.")

    @staticmethod
    def _launch_browser(p):
        """Bilgisayarda kurulu Edge'i (yoksa Chrome'u) arayüzsüz başlatır.

        Böylece Playwright'ın ayrıca ~150 MB tarayıcı indirmesine gerek kalmaz.
        """
        BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        last_exc = None
        for channel in ("msedge", "chrome", None):
            try:
                return p.chromium.launch_persistent_context(
                    str(BROWSER_PROFILE_DIR), channel=channel, headless=True,
                    user_agent=USER_AGENT, locale="tr-TR")
            except Exception as exc:
                last_exc = exc
        raise LoginError(f"Tarayıcı başlatılamadı: {last_exc}")

    def _complete_microsoft_login(self, page) -> None:
        """Microsoft giriş sayfalarını adım adım geçer; Moodle'a dönünce biter."""
        email = self.username if "@" in self.username else f"{self.username}@{EMAIL_DOMAIN}"
        email_done = password_done = False
        deadline = time.time() + 120

        def visible(selector):
            loc = page.locator(selector)
            for i in range(loc.count()):
                if loc.nth(i).is_visible():
                    return loc.nth(i)
            return None

        while time.time() < deadline:
            url = page.url
            # Moodle'a geri döndüysek giriş tamam
            if url.startswith(BASE_URL) and "/login/" not in url and "/auth/oidc" not in url:
                return

            # Hata mesajı (yanlış şifre, hesap bulunamadı vb.)
            err = visible("#usernameError, #passwordError, #errorText, #service_exception_message")
            if err and err.inner_text().strip():
                raise LoginError(f"Microsoft girişi reddetti: {err.inner_text().strip()}")

            # İki aşamalı doğrulama (SMS / Authenticator) istenirse headless geçemez
            if visible("input[name=otc], #idDiv_SAOTCAS_Title, #idDiv_SAOTCC_Title, "
                       "#idDiv_SAOTCS_Title, #idRichContext_DisplaySign"):
                raise LoginError("Microsoft iki aşamalı doğrulama (MFA) istiyor; "
                                 "otomatik giriş bu durumda yapılamaz.")

            # "Oturum açık kalsın mı?" -> Evet (sonraki girişler şifresiz olur)
            if "kmsi" in url.lower() or visible("#KmsiDescription, #KmsiCheckboxField"):
                btn = visible("#idSIButton9, input[type=submit], button[type=submit]")
                if btn:
                    btn.click()
                    page.wait_for_timeout(2000)
                    continue

            # Hesap seçme ekranı ("Bir hesap seçin") -> kendi hesabımızı tıkla
            tile = visible(f"div[data-test-id='{email}'], #tilesHolder div[role=button]")
            if tile and not email_done:
                tile.click()
                email_done = True
                page.wait_for_timeout(2000)
                continue

            # 1. adım: e-posta
            field = visible("input[name=loginfmt], input[type=email]")
            if field and not email_done:
                field.fill(email)
                field.press("Enter")
                email_done = True
                page.wait_for_timeout(2500)
                continue

            # 2. adım: şifre
            field = visible("input[name=passwd], input[type=password]")
            if field and not password_done:
                field.fill(self.password)
                field.press("Enter")
                password_done = True
                page.wait_for_timeout(3000)
                continue

            page.wait_for_timeout(1000)

        raise LoginError(f"Microsoft girişi zaman aşımına uğradı (son sayfa: {page.url.split('?')[0]}).")

    @staticmethod
    def _is_login_page(resp: requests.Response) -> bool:
        """Yanıt giriş sayfasına yönlendirildiyse True (oturum düşmüş demektir)."""
        if "/login/index.php" in resp.url:
            return True
        return 'name="logintoken"' in resp.text and 'id="password"' in resp.text

    # ---------------- sayfa çekme ----------------
    def get_page(self, url: str) -> requests.Response:
        """Bir HTML sayfasını çeker; oturum düşmüşse bir kez yeniden giriş yapar."""
        polite_sleep()
        r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        if self._is_login_page(r):
            log.info("BİLGİ: Oturum süresi dolmuş, yeniden giriş yapılıyor.")
            self.login()
            polite_sleep()
            r = self.session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code in (403, 404) or r.status_code >= 500:
            raise RetryableHTTPError(f"HTTP {r.status_code}")
        r.raise_for_status()
        return r


# =============================================================================
# 5) DOSYA BULMA: ders sayfasındaki tüm dosya linklerini çıkarma
# =============================================================================


def _activity_name(a_tag) -> str:
    """Etkinlik linkinden okunur ismi çıkarır ("Dosya", "Klasör" eklerini atar)."""
    name_span = a_tag.find("span", class_="instancename")
    if name_span:
        for hidden in name_span.find_all("span", class_="accesshide"):
            hidden.decompose()
        return name_span.get_text(" ", strip=True)
    return a_tag.get_text(" ", strip=True)


def _clean_pluginfile(url: str) -> str:
    """pluginfile linkini anahtar olarak kullanılabilecek sade hale getirir."""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def find_course_items(client: MoodleClient, course_url: str) -> list[dict]:
    """Ders sayfasını tarayıp indirilecek öğeleri listeler.

    Her öğe: {"key": benzersiz anahtar, "url": indirme/görüntüleme linki,
              "label": loglarda görünecek isim, "folder_sub": klasör içi alt yol}
    """
    resp = client.get_page(course_url)
    soup = BeautifulSoup(resp.text, "html.parser")
    items: dict[str, dict] = {}

    for a in soup.find_all("a", href=True):
        href = urljoin(course_url, a["href"])

        # (a) "Dosya" etkinliği -> view.php?id=X (asıl dosyaya yönlendirir)
        if "/mod/resource/view.php" in href:
            cmid = parse_qs(urlparse(href).query).get("id", [""])[0]
            if cmid:
                items[f"resource:{cmid}"] = {
                    "key": f"resource:{cmid}",
                    "url": f"{BASE_URL}/mod/resource/view.php?id={cmid}&redirect=1",
                    "label": _activity_name(a), "folder_sub": "",
                }

        # (b) "Klasör" etkinliği -> içindeki dosyalar ayrıca taranır
        elif "/mod/folder/view.php" in href:
            cmid = parse_qs(urlparse(href).query).get("id", [""])[0]
            if cmid and f"folder:{cmid}" not in items:
                items[f"folder:{cmid}"] = {"_folder": True, "url": href,
                                           "label": _activity_name(a)}

        # (c) Ödev açıklamalarındaki ekler için ödev sayfası da taranır
        elif "/mod/assign/view.php" in href:
            cmid = parse_qs(urlparse(href).query).get("id", [""])[0]
            if cmid and f"assign:{cmid}" not in items:
                items[f"assign:{cmid}"] = {"_assign": True, "url": href,
                                           "label": _activity_name(a)}

        # (d) Sayfaya doğrudan gömülü dosyalar (etiket, bölüm açıklaması vb.)
        elif "/pluginfile.php/" in href:
            key = _clean_pluginfile(href)
            items[key] = {"key": key, "url": href, "label": "", "folder_sub": ""}

    # Klasör ve ödev sayfalarını aç, içlerindeki pluginfile linklerini topla
    result: list[dict] = []
    for item in items.values():
        if item.get("_folder") or item.get("_assign"):
            try:
                sub = BeautifulSoup(client.get_page(item["url"]).text, "html.parser")
            except Exception as exc:
                log.info("UYARI: '%s' sayfası okunamadı (%s), sonraki turda tekrar denenecek.",
                         item["label"], exc)
                continue
            sub_folder = safe_filename(item["label"]) if item.get("_folder") else ""
            for a in sub.find_all("a", href=True):
                href = urljoin(item["url"], a["href"])
                if "/pluginfile.php/" in href and "/user/icon/" not in href:
                    key = _clean_pluginfile(href)
                    result.append({"key": key, "url": href, "label": "",
                                   "folder_sub": sub_folder})
        else:
            result.append(item)

    # Aynı anahtarı birden fazla kez eklememek için tekilleştir
    unique = {i["key"]: i for i in result}
    return list(unique.values())


# =============================================================================
# 6) İNDİRME: yeniden deneme mekanizmalı, akışlı (stream) indirme
# =============================================================================


def _filename_from_response(resp: requests.Response, fallback: str) -> str:
    """Content-Disposition başlığından veya URL'den dosya adını çıkarır."""
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*\s*=\s*[^']*''([^;]+)", cd, re.I)   # RFC 5987 (UTF-8)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', cd, re.I)
    if m:
        name = m.group(1).strip()
        try:  # Bazı sunucular UTF-8'i latin-1 olarak gönderir; düzelt
            name = name.encode("latin-1").decode("utf-8")
        except Exception:
            pass
        return name
    path_name = unquote(Path(urlparse(resp.url).path).name)
    return path_name or fallback


def _unique_path(path: Path) -> Path:
    """Aynı isimde farklı bir dosya zaten varsa 'ad (2).pdf' şeklinde yeni isim üretir."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _try_download_once(client: MoodleClient, item: dict, target_dir: Path) -> tuple[Path, str]:
    """Tek bir indirme denemesi. Başarılıysa (kaydedilen yol, dosya adı) döner."""
    polite_sleep()
    url = item["url"]
    resp = client.session.get(url, stream=True, timeout=REQUEST_TIMEOUT, allow_redirects=True)

    if client._is_login_page(resp):          # oturum düşmüşse yeniden giriş
        resp.close()
        client.login()
        polite_sleep()
        resp = client.session.get(url, stream=True, timeout=REQUEST_TIMEOUT)

    if resp.status_code in (403, 404) or resp.status_code >= 500:
        resp.close()
        raise RetryableHTTPError(f"HTTP {resp.status_code}")
    resp.raise_for_status()

    # 'Dosya' etkinliği gömülü gösterim ayarındaysa HTML sayfa döner;
    # o sayfanın içindeki asıl pluginfile linkini bulup onu indiriyoruz.
    if "text/html" in resp.headers.get("Content-Type", ""):
        page = BeautifulSoup(resp.text, "html.parser")
        link = None
        for tag in page.select("div.resourceworkaround a[href], object[data], "
                               "iframe[src], embed[src], a[href]"):
            cand = tag.get("href") or tag.get("data") or tag.get("src") or ""
            if "/pluginfile.php/" in cand and "mod_resource" in cand:
                link = urljoin(resp.url, cand)
                break
        resp.close()
        if not link:
            raise RetryableHTTPError("Sayfada indirilebilir dosya bulunamadı")
        polite_sleep()
        resp = client.session.get(link, stream=True, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (403, 404) or resp.status_code >= 500:
            resp.close()
            raise RetryableHTTPError(f"HTTP {resp.status_code}")
        resp.raise_for_status()

    filename = safe_filename(_filename_from_response(resp, item["label"] or "dosya"))
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = _unique_path(target_dir / filename)
    tmp_path = final_path.with_name(final_path.name + ".part")

    # Önce .part dosyasına yaz, bitince yeniden adlandır (yarım dosya kalmasın)
    with open(tmp_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                fh.write(chunk)
    resp.close()
    tmp_path.replace(final_path)
    return final_path, final_path.name


def download_with_retry(client: MoodleClient, item: dict, course: dict,
                        target_dir: Path, db: DownloadDB) -> None:
    """İndirmeyi dener; başarısızsa RETRY_WAIT_SECONDS arayla RETRY_COUNT kez daha dener."""
    display_name = item["label"] or unquote(Path(urlparse(item["url"]).path).name)
    total_attempts = 1 + RETRY_COUNT
    for attempt in range(1, total_attempts + 1):
        try:
            path, fname = _try_download_once(client, item, target_dir)
            db.add(item["key"], course["name"], fname, str(path))
            log.info("BAŞARILI: %s dersinden %s başarıyla indirildi.", course["name"], fname)
            notify("Yeni Moodle dosyası", f"{course['name']}: {fname}")
            return
        except (RetryableHTTPError, requests.Timeout, requests.ConnectionError,
                requests.HTTPError, LoginError, OSError) as exc:
            # Yarım kalan .part dosyalarını temizle
            for part in target_dir.glob("*.part"):
                try:
                    part.unlink()
                except OSError:
                    pass
            if attempt < total_attempts:
                log.info("UYARI: %s dersindeki %s indirilemedi (%s). %d sn sonra tekrar "
                         "denenecek (deneme %d/%d).", course["name"], display_name, exc,
                         RETRY_WAIT_SECONDS, attempt, total_attempts)
                time.sleep(RETRY_WAIT_SECONDS)
    log.info("HATA: %s dersindeki %s dosyasına %d deneme sonucunda erişilemedi.",
             course["name"], display_name, RETRY_COUNT)


# =============================================================================
# 7) ANA DÖNGÜ
# =============================================================================


def check_course(client: MoodleClient, course: dict, db: DownloadDB, root: Path) -> None:
    """Tek bir dersi tarar ve yeni dosyaları indirir."""
    try:
        items = find_course_items(client, course["url"])
    except Exception as exc:
        log.info("UYARI: %s ders sayfası okunamadı (%s). Sonraki turda tekrar denenecek.",
                 course["name"], exc)
        return

    new_items = [i for i in items if not db.has(i["key"])]
    for item in new_items:
        target = root / course["folder"]
        if item.get("folder_sub"):
            target = target / item["folder_sub"]
        download_with_retry(client, item, course, target, db)


def run_cycle(client: MoodleClient, db: DownloadDB, root: Path) -> None:
    """Tüm dersleri sırayla bir kez kontrol eder."""
    for course in COURSES:
        check_course(client, course, db, root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Moodle otomatik dosya indirici")
    parser.add_argument("--once", action="store_true", help="Tek tur çalıştır ve çık")
    args = parser.parse_args()

    secrets = load_secrets()
    username = os.environ.get("MOODLE_USER") or secrets.get("moodle_user") or USERNAME
    password = os.environ.get("MOODLE_PASS") or secrets.get("moodle_pass") or PASSWORD
    if not username or not password:
        log.info("HATA: Kullanıcı adı/şifre girilmemiş. gizli_ayarlar.json dosyasındaki "
                 "moodle_user ve moodle_pass alanlarını doldur.")
        sys.exit(1)

    # İndirme klasörü: MOODLE_ROOT ortam değişkeni (bulut sunucusu) >
    # Windows'ta Masaüstü\Moodle_Dosyalari > Linux'ta ~/Moodle_Dosyalari
    if os.environ.get("MOODLE_ROOT"):
        root = Path(os.environ["MOODLE_ROOT"])
    elif os.name == "nt":
        root = get_desktop_path() / ROOT_FOLDER_NAME
    else:
        root = Path.home() / ROOT_FOLDER_NAME
    root.mkdir(parents=True, exist_ok=True)
    db = DownloadDB(DB_PATH)
    client = MoodleClient(username, password)
    telegram = TelegramNotifier(secrets)
    log.info("BİLGİ: Moodle indirici başlatıldı. Klasör: %s | Telegram: %s", root,
             "açık" if telegram.enabled else "kapalı (token yok)")

    def telegram_flush():
        try:
            telegram.flush(db)
        except Exception as exc:   # Telegram sorunu asla indiriciyi durdurmamalı
            log.info("UYARI: Telegram gönderimi başarısız (%s).", exc)

    while True:
        try:
            client.login()
            run_cycle(client, db, root)
        except LoginError as exc:
            log.info("HATA: %s", exc)
            # Giriş sorunu (şifre değişti, MFA istendi vb.) telefona da bildirilsin
            try:
                telegram.alert(f"⚠️ Moodle'a giriş yapılamadı:\n{exc}", key="login")
            except Exception:
                pass
        except Exception as exc:
            # İnternet kopması, Moodle'ın çökmesi vb. — betik ASLA durmaz
            log.info("UYARI: Tur tamamlanamadı (%s: %s). Bir sonraki turda tekrar denenecek.",
                     type(exc).__name__, exc)

        telegram_flush()   # yeni inenleri (ve bekleyenleri) telefona gönder
        if args.once:
            break

        # Bir sonraki taramaya kadar beklerken Telegram'ı düzenli kontrol et:
        # böylece bota /start yazınca veya internet geri gelince beklemeden gönderilir.
        wake_at = time.time() + CHECK_INTERVAL_SECONDS + random.uniform(*CYCLE_JITTER_SECONDS)
        while time.time() < wake_at:
            time.sleep(min(TELEGRAM_POLL_SECONDS, max(1, wake_at - time.time())))
            telegram.reload_if_needed()
            if telegram.enabled and (not telegram.chat_id or db.pending_telegram()):
                telegram_flush()


if __name__ == "__main__":
    main()
