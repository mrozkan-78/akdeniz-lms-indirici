@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>&1 && (python guncelle.py) || (py -3 guncelle.py)
start "" notepad "%~dp0gizli_ayarlar.json"
echo.
pause
