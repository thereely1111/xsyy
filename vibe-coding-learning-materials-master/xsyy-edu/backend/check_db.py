#!/usr/bin/env python3
"""
快速检查数据库连接
用于启动脚本中的数据库检查
"""

import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

try:
    from database import engine
    from sqlalchemy import text
    
    # 尝试连接数据库
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        result.scalar()
    print("✓ 数据库连接正常")
    sys.exit(0)
except Exception as e:
    print(f"✗ 数据库连接失败: {e}")
    print("\n请检查:")
    print("  1. MySQL 服务是否正在运行")
    print("  2. .env 文件中的 DATABASE_URL 配置是否正确")
    print("  3. 数据库是否已创建（运行 python setup_local_db.py）")
    sys.exit(1)

