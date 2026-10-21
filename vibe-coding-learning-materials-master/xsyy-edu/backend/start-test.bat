@echo off
chcp 65001 >nul
REM 测试模式启动脚本：使用预设回复，不调用真实 API
REM 适合快速测试前端功能，无需配置 API 密钥

REM 开启测试模式
set TEST_MODE=1

REM 检查虚拟环境
if not exist ..\.venv\Scripts\activate.bat (
    echo [错误] 虚拟环境不存在！
    echo 请先运行: python -m venv .venv
    echo 或运行: .\install.bat
    pause
    exit /b 1
)

REM 激活虚拟环境并启动服务
call ..\.venv\Scripts\activate.bat

REM 在后台延迟打开浏览器（等待服务启动）
REM 使用相对路径打开 index.html
start "" cmd /c "timeout /t 3 /nobreak >nul && cd /d %~dp0.. && start web\index.html"

REM 启动服务（前台运行，可以看到日志）
echo [启动服务] 测试模式已启用
uvicorn app:app --reload

