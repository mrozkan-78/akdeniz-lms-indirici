# Akdeniz LMS İndirici

Akdeniz Üniversitesi LMS'ine (Moodle 4.5) eklenen ders dosyalarını otomatik olarak bulan, indiren ve **Telegram üzerinden telefona gönderen** Python otomasyonu. Kişisel bilgisayarda arka planda ya da **Oracle Cloud** sunucusunda 7/24 servis olarak çalışır.

> **EN:** A Python automation that monitors Moodle course pages, downloads newly added files, and pushes them to your phone via a Telegram bot. Runs silently on Windows or 24/7 as a systemd service on an Oracle Cloud (Always Free) Ubuntu server.

## Özellikler

- **Microsoft SSO girişi:** Playwright ile üniversitenin Microsoft oturum açma akışını otomatik tamamlar, oturumu kalıcı tarayıcı profilinde saklar.
- **Kapsamlı dosya tespiti:** Dosya etkinlikleri, klasörler, ödev ekleri ve açıklamalara gömülü bağlantılar (`pluginfile.php`).
- **Tekrarsız indirme:** İndirilen her dosya SQLite veritabanına kaydedilir.
- **Telegram botu:** Yeni dosyalar telefona gönderilir; `chat_id` bota ilk mesajda otomatik bağlanır. Giriş hataları da bildirilir.
- **Dayanıklılık:** 403/404/zaman aşımında yeniden deneme, istekler arasında rastgele bekleme, ağ kesintisinde çökmeme.
- **Windows entegrasyonu:** Görev Zamanlayıcı ile oturum açılışında sessiz başlatma, Windows bildirimleri.
- **Bulut dağıtımı:** Tek tıkla Oracle Cloud sunucusuna SSH/SCP ile kurulum, swap ayarı, sanal ortam ve `systemd` servisi.

## Mimari

```
            ┌──────────────────────────┐
            │  Oracle Cloud (Ubuntu)   │   7/24 systemd servisi
 Moodle ◄───┤  moodle_indirici.py      ├──► Telegram Bot ──► Telefon
 (LMS)      └──────────────────────────┘
            ┌──────────────────────────┐
            │  Windows PC (isteğe bağlı)│──► Masaüstü/Moodle_Dosyalari
            └──────────────────────────┘
```

## Teknolojiler

Python · requests · BeautifulSoup · Playwright · SQLite · Telegram Bot API · PowerShell · Bash · systemd · Oracle Cloud

## Kurulum (Windows)

1. Depoyu klonla.
2. `gizli_ayarlar.example.json` dosyasını `gizli_ayarlar.json` adıyla kopyala ve kendi bilgilerini yaz.
3. `moodle_indirici.py` içindeki `COURSES` listesine takip edilecek dersleri ekle.
4. `KURULUM.bat` dosyasına çift tıkla (Python kütüphanelerini kurar ve görevi oluşturur).

Test için: `python moodle_indirici.py --once`

## Bulut kurulumu (Oracle Cloud)

1. `bulut/BULUTA_GONDER.bat` dosyasını çalıştır; sunucu IP'si ve SSH anahtarı sorulur.
2. Betik dosyaları sunucuya kopyalar ve `kurulum_bulut.sh` ile servisi kurar.
3. Durum için `bulut/DURUM.bat`, loglar için `bulut/BULUT_LOG.bat`.

## Güvenlik

Giriş bilgileri, Telegram token'ı ve sunucu bağlantı bilgileri koddan ayrı JSON dosyalarında tutulur ve `.gitignore` ile depodan hariç tutulur. Teşhis betikleri şifre veya token yazdırmaz.

## Not

Bu proje kişisel kullanım ve öğrenme amaçlıdır. Sunucuyu yormamak için istekler arasında bekleme yapılır. İndirilen ders materyalleri depoya dahil edilmez.
