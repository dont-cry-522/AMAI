@echo off
chcp 65001 >nul
cd /d "%~dp0"
"runtime\python.exe" -X utf8 test_bridge.py
if errorlevel 1 goto done
"runtime\python.exe" -X utf8 test_launcher.py
if errorlevel 1 goto done
"runtime\python.exe" -X utf8 test_voice.py
:done
pause
