#!/bin/bash
# Bash 脚本：运行测试
# 使用方法: bash run_tests.sh [quick|all|integration|unit]

case "$1" in
    quick)
        echo "运行快速测试..."
        python test_quick.py
        ;;
    all)
        echo "运行所有测试..."
        python test_all.py
        ;;
    integration)
        echo "运行集成测试..."
        pytest tests/integration/ -v
        ;;
    unit)
        echo "运行单元测试..."
        pytest tests/unit/ -v
        ;;
    *)
        echo "使用方法: bash run_tests.sh [quick|all|integration|unit]"
        echo ""
        echo "  quick        - 运行快速测试（上线前必须通过）"
        echo "  all          - 运行所有测试"
        echo "  integration  - 运行集成测试"
        echo "  unit         - 运行单元测试"
        ;;
esac

