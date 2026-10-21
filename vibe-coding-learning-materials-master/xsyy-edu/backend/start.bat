@echo off
chcp 65001 >nul
REM 生产模式启动脚本
REM 使用 .env 文件加载 API 密钥
REM 请确保 backend/.env 文件存在并包含正确的 API 密钥

REM 检查虚拟环境
if not exist ..\.venv\Scripts\activate.bat (
    echo [错误] 虚拟环境不存在！
    echo 请先运行: python -m venv .venv
    echo 或运行: .\install.bat
    pause
    exit /b 1
)

REM 激活虚拟环境
call ..\.venv\Scripts\activate.bat

REM 检查 .env 文件
if not exist .env (
    echo [警告] .env 文件不存在！
    echo 请先创建 .env 文件并配置数据库连接信息
    echo 可以从 env.example 复制: copy env.example .env
    echo.
    pause
)

REM 检查数据库连接（可选，如果失败只提示不中断）
echo [检查] 正在检查数据库连接...
python check_db.py
if errorlevel 1 (
    echo.
    echo [提示] 数据库连接失败，但将继续启动服务
    echo 如果启动后出现数据库错误，请先运行: python setup_local_db.py
    echo.
    timeout /t 2 /nobreak >nul
)

REM 在后台延迟打开浏览器（等待服务启动）
REM 使用 HTTP 协议打开页面（推荐，但需要配置静态文件服务）
REM 或者直接打开文件（file:// 协议，已支持）
echo [提示] 服务启动后将自动打开浏览器...
start "" cmd /c "timeout /t 3 /nobreak >nul && cd /d %~dp0.. && start web\index.html"

echo.
echo ========================================
echo 正在启动后端服务...
echo 前端页面将在 3 秒后自动打开
echo API 地址: http://127.0.0.1:8000
echo ========================================
echo.

REM 启动服务（前台运行，可以看到日志）
uvicorn app:app --reload --host 127.0.0.1 --port 8000

