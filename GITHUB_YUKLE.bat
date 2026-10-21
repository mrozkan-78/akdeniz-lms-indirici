@echo off
chcp 65001 >nul
REM Moodle Indirici - GitHub'a guvenli yukleme
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0github_yukle.ps1"
echo.
pause
