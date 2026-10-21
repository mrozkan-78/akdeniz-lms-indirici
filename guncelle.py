# -*- coding: utf-8 -*-
"""
guncelle.py — Telegram sürümüne güvenli geçiş.

1. Çalışan "Moodle Indirici" görevini durdurur.
2. Eski moodle_indirici.py içindeki USERNAME / PASSWORD değerlerini okuyup
   gizli_ayarlar.json dosyasına taşır (şifre ekrana YAZDIRILMAZ).
3. moodle_indirici_yeni.py dosyasını moodle_indirici.py'nin yerine koyar.
4. Görevi yeniden başlatır.
"""
import ast
import json
import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = HERE / "moodle_indirici.py"
NEW = HERE / "moodle_indirici_yeni.py"
SECRETS = HERE / "gizli_ayarlar.json"
TASK = "Moodle Indirici"


def read_old_credentials(path: Path) -> dict:
    """Eski betikteki USERNAME/PASSWORD sabitlerini güvenli şekilde (ast ile) okur."""
    creds = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return creds
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("USERNAME", "PASSWORD"):
                    creds[target.id] = str(node.value.value)
    return creds


def main():
    print("1) Görev durduruluyor...")
    subprocess.run(["schtasks", "/End", "/TN", TASK], capture_output=True)

    secrets = {}
    if SECRETS.exists():
        secrets = json.loads(SECRETS.read_text(encoding="utf-8-sig"))

    print("2) Giriş bilgileri ayar dosyasına taşınıyor...")
    creds = read_old_credentials(OLD)
    if creds.get("USERNAME") and not secrets.get("moodle_user"):
        secrets["moodle_user"] = creds["USERNAME"]
    if creds.get("PASSWORD") and not secrets.get("moodle_pass"):
        secrets["moodle_pass"] = creds["PASSWORD"]
    secrets.setdefault("moodle_user", "")
    secrets.setdefault("moodle_pass", "")
    secrets.setdefault("telegram_token", "")
    secrets.setdefault("telegram_chat_id", "")
    SECRETS.write_text(json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   Kullanıcı adı:", "TAŞINDI" if secrets["moodle_user"] else "BOŞ!")
    print("   Şifre        :", "TAŞINDI" if secrets["moodle_pass"] else "BOŞ!")

    if NEW.exists():
        print("3) Yeni betik yerine konuyor...")
        os.replace(NEW, OLD)
    else:
        print("3) Yeni betik zaten yerinde.")

    print("4) Görev yeniden başlatılıyor...")
    subprocess.run(["schtasks", "/Run", "/TN", TASK], capture_output=True)
    print("\nTAMAM. Şimdi açılacak Not Defteri'nde telegram_token alanını doldurup kaydet.")


if __name__ == "__main__":
    main()
