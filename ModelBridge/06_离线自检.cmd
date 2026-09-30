@echo off
cd /d "%~dp0"
"runtime\python.exe" -X utf8 test_bridge.py
pause
