@echo off
chcp 65001 >nul
REM Moodle Indirici - cift tiklayarak kurulum
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kurulum.ps1"
echo.
pause
