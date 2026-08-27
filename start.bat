@echo off
REM Klik dua kali file ini untuk menjalankan Playlist Studio.
cd /d "%~dp0"
python run.py %*
if errorlevel 1 pause
