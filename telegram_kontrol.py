# -*- coding: utf-8 -*-
"""Telegram kurulumunu kontrol eder. Token'ı veya şifreyi YAZDIRMAZ."""
import json, re, subprocess
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
out = []
try:
    raw = (HERE / "gizli_ayarlar.json").read_text(encoding="utf-8-sig")
    try:
        s = json.loads(raw)
        out.append("JSON biçimi: GEÇERLİ")
    except Exception as exc:
        s = {}
        out.append(f"JSON biçimi: BOZUK -> {exc}")
    out.append(f"Alanlar: {sorted(s.keys())}")
    tok = (s.get("telegram_token") or "").strip()
    cid = str(s.get("telegram_chat_id") or "").strip()
    out.append(f"telegram_token uzunluğu: {len(tok)} | biçim doğru mu: "
               f"{bool(re.fullmatch(r'\d{6,12}:[A-Za-z0-9_-]{30,}', tok))}")
    out.append(f"telegram_chat_id dolu mu: {bool(cid)} | chat_id alanında token var mı: "
               f"{':' in cid}")
    if tok:
        try:
            me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=20).json()
            out.append(f"getMe: ok={me.get('ok')} bot=@{me.get('result', {}).get('username')} "
                       f"hata={me.get('description')}")
            up = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=20).json()
            msgs = [u for u in up.get("result", []) if u.get("message")]
            out.append(f"getUpdates: ok={up.get('ok')} gelen mesaj sayısı={len(msgs)} "
                       f"hata={up.get('description')}")
        except Exception as exc:
            out.append(f"Telegram'a erişilemedi: {type(exc).__name__}: {exc}")
except Exception as exc:
    out.append(f"HATA: {exc}")

r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe"], capture_output=True,
                   text=True, errors="ignore")
out.append("pythonw çalışıyor mu: " + ("EVET" if "pythonw.exe" in r.stdout else "HAYIR"))
r = subprocess.run(["schtasks", "/Query", "/TN", "Moodle Indirici", "/FO", "LIST"],
                   capture_output=True, text=True, errors="ignore")
out.append("Görev durumu:\n" + "\n".join(l for l in r.stdout.splitlines()
                                         if any(k in l for k in ("Durum", "Status")))
           )
(HERE / "telegram_kontrol_sonuc.txt").write_text("\n".join(out), encoding="utf-8")
