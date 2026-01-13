@echo off
chcp 65001 > nul

echo ======================================================
echo   AI Dubbing Server - Custom Domain Mode
echo ======================================================
echo.

:: 设置 Python 环境路径
set PY="C:\ProgramData\miniconda3\envs\aidubbing\python.exe"

:: 1. 启动 Streamlit
echo [1/2] Starting Streamlit service...
start "AI-Dubbing" /min cmd /c "%PY% -m streamlit run ui/streamlit_app_refactored.py --server.port 8501 --server.address 0.0.0.0"

:: 2. 启动 Cloudflare Tunnel
echo [2/2] Starting Cloudflare Tunnel...
echo ------------------------------------------------------
echo 配置说明:
echo 1. 如果使用命名隧道，请先运行:
echo    .\cloudflared.exe tunnel login
echo    .\cloudflared.exe tunnel create aidubbing
echo    .\cloudflared.exe tunnel route dns aidubbing dubbing.zhangjiangnan.art
echo.
echo 2. 如果使用快速隧道（临时URL），将使用 --url 模式
echo ------------------------------------------------------
timeout /t 3 /nobreak > nul

:: 检查是否使用命名隧道（检查证书文件是否存在）
if exist "%USERPROFILE%\.cloudflared\a248363e-2c23-4648-b6d6-8791b4f28212.json" (
    echo 检测到命名隧道配置，使用命名隧道模式...
    echo 域名: dubbing.zhangjiangnan.art
    echo 使用配置文件: cloudflared-config.yml
    .\cloudflared.exe tunnel --config cloudflared-config.yml run aidubbing
) else (
    echo 未检测到命名隧道配置，使用快速隧道模式...
    echo 注意：快速隧道会生成临时URL，每次运行都不同
    .\cloudflared.exe tunnel --url http://localhost:8501
)

pause

