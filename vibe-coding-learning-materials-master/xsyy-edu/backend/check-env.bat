@echo off
chcp 65001 >nul
REM 环境检查脚本：检查虚拟环境、依赖包、配置文件等

echo ========================================
echo    环境检查脚本
echo ========================================
echo.

REM 检查 Python
echo [1/5] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [失败] 未找到 Python！
    echo 请先安装 Python 3.8 或更高版本
    set ERROR_COUNT=1
) else (
    python --version
    echo [成功] Python 环境正常
)
echo.

REM 检查虚拟环境
echo [2/5] 检查虚拟环境...
if not exist .venv\Scripts\activate.bat (
    echo [失败] 虚拟环境不存在！
    echo [建议] 运行: python -m venv .venv
    set ERROR_COUNT=1
) else (
    echo [成功] 虚拟环境存在
    call .venv\Scripts\activate.bat
)
echo.

REM 检查依赖包
echo [3/5] 检查依赖包...
python -m pip list | findstr "fastapi" >nul
if errorlevel 1 (
    echo [警告] 依赖包未安装或版本不匹配
    echo [建议] 运行: pip install -r requirements.txt
    set WARNING_COUNT=1
) else (
    echo [成功] 核心依赖包已安装
    echo [详情] 已安装的包：
    python -m pip list | findstr /i "fastapi uvicorn langchain pydantic"
)
echo.

REM 检查 .env 文件
echo [4/5] 检查配置文件...
if not exist .env (
    echo [警告] .env 文件不存在！
    echo [建议] 复制 env.example 为 .env 并填入 API 密钥
    if exist env.example (
        echo [提示] 运行: copy env.example .env
    )
    set WARNING_COUNT=1
) else (
    echo [成功] .env 文件存在
    REM 检查是否包含占位符
    findstr /c:"your_deepseek_api_key_here" .env >nul
    if not errorlevel 1 (
        echo [警告] .env 文件中包含占位符，请填入真实的 API 密钥
        set WARNING_COUNT=1
    ) else (
        echo [成功] .env 文件已配置
    )
)
echo.

REM 检查 storage 目录
echo [5/5] 检查存储目录...
if not exist ..\storage (
    echo [信息] storage 目录不存在，将在首次使用时自动创建
) else (
    echo [成功] storage 目录存在
)
echo.

REM 总结
echo ========================================
echo    检查完成
echo ========================================
if defined ERROR_COUNT (
    echo [状态] 发现错误，请先解决上述问题
    pause
    exit /b 1
) else if defined WARNING_COUNT (
    echo [状态] 检查完成，但存在警告项（不影响测试模式运行）
    pause
    exit /b 0
) else (
    echo [状态] 所有检查通过，环境配置正常！
    pause
    exit /b 0
)

