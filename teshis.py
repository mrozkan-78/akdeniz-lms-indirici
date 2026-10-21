# -*- coding: utf-8 -*-
"""Teşhis: ders sayfalarındaki etkinlik türlerini listeler (giriş bilgisi yazmaz)."""
import os, re
from collections import Counter
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import moodle_indirici as m

out = []
user = os.environ.get("MOODLE_USER") or m.USERNAME
pw = os.environ.get("MOODLE_PASS") or m.PASSWORD
c = m.MoodleClient(user, pw)
try:
    c.login()
    for course in m.COURSES:
        out.append(f"===== {course['name']} ({course['url']})")
        r = c.get_page(course["url"])
        soup = BeautifulSoup(r.text, "html.parser")
        out.append(f"Başlık: {soup.title.get_text(strip=True) if soup.title else '-'}  | URL: {r.url}")
        kinds = Counter()
        for a in soup.find_all("a", href=True):
            href = urljoin(r.url, a["href"])
            mm = re.search(r"/mod/(\w+)/view\.php", href)
            if mm:
                kinds[mm.group(1)] += 1
                out.append(f"  [{mm.group(1)}] {m._activity_name(a)[:80]} -> {href.split('?')[1] if '?' in href else ''}")
            elif "/pluginfile.php/" in href:
                kinds["pluginfile"] += 1
                out.append(f"  [pluginfile] {href.split('/')[-1][:80]}")
            elif "/course/section.php" in href or ("section=" in href and "/course/view.php" in href):
                kinds["section"] += 1
                out.append(f"  [section] {a.get_text(' ', strip=True)[:60]} -> {href.split('moodle')[-1]}")
        out.append(f"Özet: {dict(kinds)}")
        # iframe / video gömüleri
        out.append(f"iframe sayısı: {len(soup.find_all('iframe'))}, video: {len(soup.find_all('video'))}")
except Exception as exc:
    out.append(f"HATA: {type(exc).__name__}: {exc}")

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "teshis_sonuc.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
