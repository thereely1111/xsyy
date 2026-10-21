#!/usr/bin/env python3
"""
快速测试脚本 - 上线前必须通过
运行所有 P0 优先级的核心功能测试
"""
import sys
import subprocess
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

def run_tests():
    """运行快速测试"""
    print("=" * 60)
    print("XSYY 项目快速测试")
    print("=" * 60)
    print()
    
    # 测试列表（P0 优先级）
    test_modules = [
        "tests/integration/test_api_health.py",
        "tests/integration/test_api_auth.py",
        "tests/integration/test_api_tasks.py",
    ]
    
    failed_tests = []
    passed_tests = []
    
    for test_module in test_modules:
        print(f"\n运行测试: {test_module}")
        print("-" * 60)
        
        try:
            # 运行 pytest
            result = subprocess.run(
                ["pytest", test_module, "-v", "--tb=short"],
                cwd=backend_dir,
                capture_output=True,
                text=True
            )
            
            print(result.stdout)
            if result.stderr:
                print("错误输出:", result.stderr)
            
            if result.returncode == 0:
                passed_tests.append(test_module)
                print(f"✓ {test_module} 通过")
            else:
                failed_tests.append(test_module)
                print(f"✗ {test_module} 失败")
        
        except Exception as e:
            print(f"✗ 运行 {test_module} 时出错: {e}")
            failed_tests.append(test_module)
    
    # 输出总结
    print()
    print("=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"通过: {len(passed_tests)}/{len(test_modules)}")
    print(f"失败: {len(failed_tests)}/{len(test_modules)}")
    
    if passed_tests:
        print("\n通过的测试:")
        for test in passed_tests:
            print(f"  ✓ {test}")
    
    if failed_tests:
        print("\n失败的测试:")
        for test in failed_tests:
            print(f"  ✗ {test}")
        print("\n请修复失败的测试后再上线！")
        return 1
    
    print("\n✓ 所有快速测试通过！可以上线。")
    return 0


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)

