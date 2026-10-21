@echo off
chcp 65001 >nul
REM 一键安装脚本：创建虚拟环境并安装所有依赖

echo ========================================
echo    XSYY 项目环境配置脚本
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python！
    echo 请先安装 Python 3.8 或更高版本
    pause
    exit /b 1
)

echo [1/3] 检查 Python 版本...
python --version
echo.

REM 创建虚拟环境（如果不存在）
if not exist .venv (
    echo [2/3] 创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败！
        pause
        exit /b 1
    )
    echo [成功] 虚拟环境已创建
) else (
    echo [2/3] 虚拟环境已存在，跳过创建
)
echo.

REM 激活虚拟环境并安装依赖
echo [3/3] 安装项目依赖...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip

REM 尝试直接安装
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [警告] 直接安装失败，尝试分步安装...
    echo [步骤1] 安装核心依赖...
    python -m pip install fastapi==0.114.0 uvicorn[standard]==0.30.3 pydantic==2.9.1 python-multipart==0.0.9 python-dotenv==1.0.0
    echo [步骤2] 安装 LangChain 核心...
    python -m pip install "langchain>=0.3.0"
    echo [步骤3] 安装 LangChain 扩展...
    python -m pip install langchain-google-genai langchain-openai
    if errorlevel 1 (
        echo [错误] 依赖安装失败！
        echo [建议] 请检查网络连接或尝试手动安装
        pause
        exit /b 1
    )
)

echo.
echo ========================================
echo    安装完成！
echo ========================================
echo.
echo 下一步：
echo 1. 复制 env.example 为 .env
echo    copy env.example .env
echo.
echo 2. 编辑 .env 文件，填入你的 API 密钥
echo.
echo 3. （可选）运行环境检查：
echo    .\check-env.bat
echo.
echo 4. 启动项目：
echo    生产模式: .\start.bat
echo    测试模式: .\start-test.bat
echo.
pause

