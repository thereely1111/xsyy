#!/usr/bin/env python3
"""
本地开发环境数据库设置脚本
自动创建数据库并初始化表结构
"""

import sys
from pathlib import Path
import pymysql
from sqlalchemy import create_engine, text

# 确保可以导入 backend 模块
backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from database.database import DATABASE_URL, engine
from dotenv import load_dotenv
import os

# 加载 .env 文件
env_path = backend_dir / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    print("⚠️  警告: .env 文件不存在，请先创建 .env 文件")
    print("   可以从 env.example 复制: cp env.example .env")
    sys.exit(1)

def parse_database_url(url):
    """解析数据库连接字符串"""
    # 使用 urllib.parse 来正确解析 URL（处理特殊字符）
    from urllib.parse import urlparse, unquote
    
    # 移除 mysql+pymysql:// 前缀
    if url.startswith("mysql+pymysql://"):
        url = url.replace("mysql+pymysql://", "mysql://", 1)
    
    try:
        parsed = urlparse(url)
        
        # 解析用户名和密码
        user = unquote(parsed.username) if parsed.username else "root"
        password = unquote(parsed.password) if parsed.password else ""
        
        # 解析主机和端口
        host = parsed.hostname or "localhost"
        port = parsed.port or 3306
        
        # 解析数据库名（移除前导斜杠）
        database = parsed.path.lstrip("/") if parsed.path else ""
        
        return {
            "user": user,
            "password": password,
            "host": host,
            "port": port,
            "database": database
        }
    except Exception as e:
        # 如果解析失败，尝试简单解析
        print(f"⚠️  URL 解析警告: {e}，使用简单解析")
        url = url.replace("mysql+pymysql://", "").replace("mysql://", "")
        if "?" in url:
            url = url.split("?")[0]
        
        if "@" in url:
            auth, rest = url.split("@", 1)
            if ":" in auth:
                user, password = auth.split(":", 1)
            else:
                user, password = auth, ""
            
            if "/" in rest:
                host_port, database = rest.split("/", 1)
            else:
                host_port, database = rest, ""
            
            if ":" in host_port:
                host, port = host_port.split(":", 1)
                port = int(port)
            else:
                host, port = host_port, 3306
        else:
            user, password, host, port, database = "root", "", "localhost", 3306, ""
        
        return {
            "user": user,
            "password": password,
            "host": host,
            "port": port,
            "database": database
        }

def create_database():
    """创建数据库"""
    print("=" * 60)
    print("本地开发环境数据库设置")
    print("=" * 60)
    
    # 解析数据库连接信息
    db_config = parse_database_url(DATABASE_URL)
    
    if not db_config["database"]:
        print("✗ 错误: DATABASE_URL 中未指定数据库名")
        sys.exit(1)
    
    db_name = db_config["database"]
    
    print(f"\n1. 正在创建数据库: {db_name}")
    
    try:
        # 连接到 MySQL（不指定数据库）
        conn = pymysql.connect(
            host=db_config["host"],
            port=db_config["port"],
            user=db_config["user"],
            password=db_config["password"],
            charset='utf8mb4'
        )
        
        with conn.cursor() as cursor:
            # 创建数据库
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            conn.commit()
            print(f"   ✓ 数据库 {db_name} 创建成功")
        
        conn.close()
        
    except pymysql.Error as e:
        print(f"   ✗ 创建数据库失败: {e}")
        print("\n请检查:")
        print("  1. MySQL 服务是否正在运行")
        print("  2. .env 文件中的 DATABASE_URL 配置是否正确")
        print("  3. MySQL 用户名和密码是否正确")
        sys.exit(1)
    
    print(f"\n2. 正在初始化数据库表结构...")
    
    try:
        from database import init_db
        init_db()
        print("   ✓ 数据库表结构初始化成功")
    except Exception as e:
        print(f"   ✗ 初始化表结构失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print(f"\n3. 验证数据库连接...")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT DATABASE()"))
            current_db = result.scalar()
            if current_db == db_name:
                print(f"   ✓ 数据库连接成功，当前数据库: {current_db}")
            else:
                print(f"   ⚠️  警告: 当前数据库为 {current_db}，期望为 {db_name}")
    except Exception as e:
        print(f"   ✗ 数据库连接验证失败: {e}")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✓ 数据库设置完成！")
    print("=" * 60)
    print("\n下一步:")
    print("  运行数据迁移脚本: python database/migrate.py")
    print("  或查看配置指南: 本地开发环境配置指南.md")

if __name__ == "__main__":
    create_database()

