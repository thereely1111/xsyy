"""
测试配置
"""
import os
from pathlib import Path

# 测试基础配置
TEST_API_BASE = os.getenv("TEST_API_BASE", "http://localhost:8000")
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "mysql+pymysql://root:password@localhost/xsyy_test?charset=utf8mb4"
)

# 测试超时设置
TEST_TIMEOUT = int(os.getenv("TEST_TIMEOUT", "30"))  # 秒

# 测试数据目录
TEST_DATA_DIR = Path(__file__).resolve().parent / "fixtures"

# 测试图片目录
TEST_IMAGES_DIR = TEST_DATA_DIR / "test_images"

