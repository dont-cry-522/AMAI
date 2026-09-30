@echo off
chcp 65001 >nul
cd /d "%~dp0"
"runtime\python.exe" -X utf8 bridge.py diagnose
pause
