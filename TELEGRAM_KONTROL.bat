@echo off
cd /d "%~dp0"
where python >/dev/null 2>&1 && (python telegram_kontrol.py) || (py -3 telegram_kontrol.py)
