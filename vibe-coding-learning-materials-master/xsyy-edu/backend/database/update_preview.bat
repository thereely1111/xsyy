@echo off
chcp 65001 >nul
cd /d %~dp0
python update_preview_to_webp_simple.py -y
pause

