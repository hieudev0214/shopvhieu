@echo off
chcp 65001 >nul
cd /d "%~dp0"
set /p LINK=Dan link bai viet Facebook (Enter de dung links.txt):
if "%LINK%"=="" (python fb_save.py) else (python fb_save.py "%LINK%")
pause
