@echo off
chcp 936 > nul

:: Disable CMD Quick Edit Mode to prevent program freeze when clicking window
reg add HKCU\Console /v QuickEdit /t REG_DWORD /d 0 /f >nul 2>&1

echo ======================================================
echo   AI Dubbing Server - Streamlit
echo ======================================================
echo.
echo [!] Quick Edit Mode disabled - clicking window will not freeze program
echo.

:: Check Cloudflare Tunnel service status
echo [Check] Cloudflare Tunnel service status...
sc query Cloudflared | findstr "RUNNING" >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Cloudflare Tunnel service is running
    echo     Domain: dubbing.zhangjiangnan.art
) else (
    echo [!] Warning: Cloudflare Tunnel service is not running
    echo     Run as admin: net start cloudflared
    echo.
)
echo.

:: Set Python environment path
set PY=C:\ProgramData\miniconda3\envs\aidubbing\python.exe

:: 0. Clean up old processes on port 8501
echo [1/2] Cleaning up old processes on port 8501...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8501" ^| findstr "LISTENING"') do (
    echo Killing process %%a...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak > nul

:: 1. Start Streamlit
echo [2/2] Starting Streamlit service...
echo ------------------------------------------------------
echo Streamlit starting...
echo Local:  http://localhost:8501
echo Public: https://dubbing.zhangjiangnan.art
echo ------------------------------------------------------
echo.
echo Press Ctrl+C to stop
echo.

"%PY%" -m streamlit run ui/streamlit_app_refactored.py --server.port 8501 --server.address 0.0.0.0

pause
