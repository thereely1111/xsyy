#!/usr/bin/env python3
"""
数据库初始化脚本
用于创建数据库表结构
"""

import sys
from pathlib import Path

# 确保可以导入 backend 模块
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from database import init_db

if __name__ == "__main__":
    print("正在初始化数据库...")
    try:
        init_db()
        print("✓ 数据库初始化成功！")
    except Exception as e:
        print(f"✗ 数据库初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

