@echo off
REM Windows 批处理脚本：运行测试
REM 使用方法: run_tests.bat [quick|all|integration|unit]

setlocal

if "%1"=="quick" (
    echo 运行快速测试...
    python test_quick.py
) else if "%1"=="all" (
    echo 运行所有测试...
    python test_all.py
) else if "%1"=="integration" (
    echo 运行集成测试...
    pytest tests/integration/ -v
) else if "%1"=="unit" (
    echo 运行单元测试...
    pytest tests/unit/ -v
) else (
    echo 使用方法: run_tests.bat [quick^|all^|integration^|unit]
    echo.
    echo   quick        - 运行快速测试（上线前必须通过）
    echo   all          - 运行所有测试
    echo   integration  - 运行集成测试
    echo   unit         - 运行单元测试
)

endlocal

