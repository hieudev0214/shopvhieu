@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Cai dat thu vien cho tool luu anh acc ===
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo Chua co Python. Tai Python tai https://www.python.org/downloads/
  echo Khi cai nho tich o "Add python.exe to PATH", xong chay lai file nay.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
if errorlevel 1 goto loi
python -m playwright install chromium
if errorlevel 1 goto loi
echo.
echo Cai dat xong! Nhap dup chay_web.bat de bat dau.
pause
exit /b 0
:loi
echo.
echo Cai dat bi loi, xem thong bao o tren.
pause
exit /b 1
