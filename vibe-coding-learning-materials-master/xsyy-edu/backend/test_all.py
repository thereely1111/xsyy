#!/usr/bin/env python3
"""
运行所有测试
包括单元测试、集成测试、端到端测试
"""
import sys
import subprocess
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("XSYY 项目完整测试套件")
    print("=" * 60)
    print()
    
    # 运行所有测试
    result = subprocess.run(
        [
            "pytest",
            "tests/",
            "-v",
            "--tb=short",
            "--cov=.",
            "--cov-report=html",
            "--cov-report=term"
        ],
        cwd=backend_dir
    )
    
    return result.returncode


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)

