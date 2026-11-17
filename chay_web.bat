@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Luu anh acc - Web
python web.py
pause
