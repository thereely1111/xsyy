@echo off
chcp 65001 >nul
REM 删除 storage 目录下所有 preview.png 文件

REM 切换到 backend 目录
cd /d "%~dp0"

REM 激活虚拟环境（如果存在）
if exist "..\.venv\Scripts\activate.bat" (
    call "..\.venv\Scripts\activate.bat"
) else (
    echo [警告] 虚拟环境未找到，尝试直接运行 Python。
)

REM 运行 Python 脚本，跳过确认提示
python delete_preview_png.py -y

echo.
echo 删除 preview.png 文件完成。
echo.
pause

