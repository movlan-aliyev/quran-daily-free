@echo off
cd /d "%~dp0"
python send_daily_quran.py
if errorlevel 1 pause
