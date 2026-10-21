@echo off
chcp 65001 >nul
echo 执行数据库迁移：添加每日调用次数相关字段
echo.

cd /d "%~dp0.."
python database\add_daily_calls_fields.py

pause

