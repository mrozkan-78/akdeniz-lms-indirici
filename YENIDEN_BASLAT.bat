@echo off
schtasks /End /TN "Moodle Indirici"
timeout /t 3 /nobreak >nul
schtasks /Run /TN "Moodle Indirici"
