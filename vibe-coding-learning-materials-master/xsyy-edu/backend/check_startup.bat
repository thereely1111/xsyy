@echo off
chcp 65001 >nul
echo ========================================
echo XSYY 启动诊断工具
echo ========================================
echo.

REM 检查虚拟环境
echo [1/5] 检查虚拟环境...
if not exist ..\.venv\Scripts\activate.bat (
    echo    ✗ 虚拟环境不存在！
    echo    请先运行: python -m venv .venv
    echo    或运行: .\install.bat
    goto :error
) else (
    echo    ✓ 虚拟环境存在
)

REM 检查 .env 文件
echo [2/5] 检查 .env 文件...
if not exist .env (
    echo    ✗ .env 文件不存在！
    echo    请先创建 .env 文件并配置数据库连接信息
    echo    可以从 env.example 复制: copy env.example .env
    goto :error
) else (
    echo    ✓ .env 文件存在
)

REM 激活虚拟环境并检查依赖
echo [3/5] 检查 Python 依赖...
call ..\.venv\Scripts\activate.bat
python -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
    echo    ✗ 依赖未安装或虚拟环境未激活！
    echo    请运行: pip install -r requirements.txt
    goto :error
) else (
    echo    ✓ Python 依赖正常
)

REM 检查数据库连接
echo [4/5] 检查数据库连接...
python check_db.py
if errorlevel 1 (
    echo    ⚠ 数据库连接失败（服务仍可启动，但部分功能可能不可用）
) else (
    echo    ✓ 数据库连接正常
)

REM 检查端口是否被占用
echo [5/5] 检查端口 8000...
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo    ⚠ 端口 8000 已被占用！
    echo    请关闭占用该端口的程序，或修改启动脚本中的端口号
) else (
    echo    ✓ 端口 8000 可用
)

echo.
echo ========================================
echo 诊断完成！
echo ========================================
echo.
echo 如果所有检查都通过，可以运行: .\start.bat
echo.
pause
exit /b 0

:error
echo.
echo ========================================
echo 诊断失败，请先解决上述问题
echo ========================================
echo.
pause
exit /b 1

