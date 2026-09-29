@echo off
rem Training simulator DDS-112: install and start (Windows). Details: README.md
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\start.ps1"
echo.
pause
