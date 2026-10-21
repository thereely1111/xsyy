#!/usr/bin/env python3
"""
远程数据库连接诊断工具
用于排查远程数据库连接失败的原因
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://root:password@localhost:3306/xsyy?charset=utf8mb4"
)

print("=" * 60)
print("远程数据库连接诊断工具")
print("=" * 60)
print()

# 1. 检查 DATABASE_URL 配置
print("1. 检查 DATABASE_URL 配置...")
if not DATABASE_URL:
    print("   ✗ DATABASE_URL 未配置")
    print("   请在 .env 文件中设置 DATABASE_URL")
    sys.exit(1)

# 解析连接字符串（不显示密码）
if "://" in DATABASE_URL:
    parts = DATABASE_URL.split("://")
    if len(parts) == 2:
        scheme = parts[0]
        rest = parts[1]
        if "@" in rest:
            auth_part, host_part = rest.split("@", 1)
            if ":" in auth_part:
                user, password = auth_part.split(":", 1)
                print(f"   ✓ 数据库类型: {scheme}")
                print(f"   ✓ 用户名: {user}")
                print(f"   ✓ 密码: {'*' * len(password)}")
                if "/" in host_part:
                    host_port, db_name = host_part.split("/", 1)
                    if "?" in db_name:
                        db_name = db_name.split("?")[0]
                    if ":" in host_port:
                        host, port = host_port.split(":")
                        print(f"   ✓ 主机: {host}")
                        print(f"   ✓ 端口: {port}")
                    else:
                        print(f"   ✓ 主机: {host_part.split('/')[0]}")
                        print(f"   ✓ 端口: 默认")
                    print(f"   ✓ 数据库名: {db_name}")
                else:
                    print(f"   ✓ 主机信息: {host_part}")
            else:
                print(f"   ✓ 连接字符串格式: {scheme}://{rest[:20]}...")
        else:
            print(f"   ✓ 连接字符串格式: {scheme}://{rest[:20]}...")
    else:
        print(f"   ✓ 连接字符串: {DATABASE_URL[:50]}...")
else:
    print(f"   ⚠ 连接字符串格式可能不正确: {DATABASE_URL[:50]}...")

print()

# 2. 检查必要的依赖
print("2. 检查依赖包...")
try:
    import pymysql
    print("   ✓ pymysql 已安装")
except ImportError:
    print("   ✗ pymysql 未安装")
    print("   请运行: pip install pymysql")
    sys.exit(1)

try:
    from sqlalchemy import create_engine, text
    print("   ✓ sqlalchemy 已安装")
except ImportError:
    print("   ✗ sqlalchemy 未安装")
    print("   请运行: pip install sqlalchemy")
    sys.exit(1)

print()

# 3. 尝试解析连接字符串
print("3. 解析连接字符串...")
try:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,  # 10秒超时
        } if "mysql" in DATABASE_URL.lower() else {}
    )
    print("   ✓ 连接字符串解析成功")
except Exception as e:
    print(f"   ✗ 连接字符串解析失败: {e}")
    sys.exit(1)

print()

# 4. 尝试连接数据库
print("4. 尝试连接数据库...")
try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 as test"))
        test_value = result.scalar()
        if test_value == 1:
            print("   ✓ 数据库连接成功！")
            
            # 测试数据库版本
            try:
                version_result = conn.execute(text("SELECT VERSION()"))
                version = version_result.scalar()
                print(f"   ✓ MySQL 版本: {version}")
            except:
                pass
            
            # 测试当前数据库
            try:
                db_result = conn.execute(text("SELECT DATABASE()"))
                current_db = db_result.scalar()
                if current_db:
                    print(f"   ✓ 当前数据库: {current_db}")
            except:
                pass
                
except Exception as e:
    error_msg = str(e)
    print(f"   ✗ 数据库连接失败: {error_msg}")
    print()
    print("   可能的原因和解决方案：")
    print()
    
    # 根据错误信息提供具体建议
    if "Access denied" in error_msg or "1045" in error_msg:
        print("   → 用户名或密码错误")
        print("     请检查 .env 文件中的 DATABASE_URL 用户名和密码")
    elif "Unknown database" in error_msg or "1049" in error_msg:
        print("   → 数据库不存在")
        print("     请先创建数据库，或检查 DATABASE_URL 中的数据库名")
    elif "Can't connect" in error_msg or "2003" in error_msg or "timed out" in error_msg.lower():
        print("   → 无法连接到数据库服务器")
        print("     请检查：")
        print("     1. 数据库服务器是否正在运行")
        print("     2. 主机地址和端口是否正确")
        print("     3. 防火墙是否允许连接（远程数据库需要开放端口）")
        print("     4. 网络连接是否正常")
        if "localhost" in DATABASE_URL or "127.0.0.1" in DATABASE_URL:
            print("     5. 如果是远程数据库，请使用远程服务器IP地址，而不是localhost")
    elif "SSL" in error_msg or "TLS" in error_msg:
        print("   → SSL/TLS 连接问题")
        print("     如果是远程数据库，可能需要添加 SSL 参数：")
        print("     ?charset=utf8mb4&ssl_disabled=true")
        print("     或")
        print("     ?charset=utf8mb4&ssl_verify_cert=false&ssl_verify_identity=false")
    elif "Connection refused" in error_msg or "111" in error_msg:
        print("   → 连接被拒绝")
        print("     请检查：")
        print("     1. 数据库服务是否正在运行")
        print("     2. 端口是否正确（MySQL默认3306）")
        print("     3. 远程数据库是否允许远程连接")
        print("     4. 如果是云数据库，请检查安全组/防火墙规则")
    else:
        print("   → 其他连接错误")
        print("     请检查错误信息并参考上述常见问题")
    
    print()
    print("   远程数据库连接示例：")
    print("   DATABASE_URL=mysql+pymysql://用户名:密码@主机IP:端口/数据库名?charset=utf8mb4")
    print()
    print("   如果是云数据库（如阿里云、腾讯云），可能还需要：")
    print("   - 添加 SSL 参数（如果要求）")
    print("   - 检查白名单设置（允许你的IP访问）")
    print("   - 检查安全组规则（开放3306端口）")
    
    sys.exit(1)

print()
print("=" * 60)
print("✓ 所有检查通过，数据库连接正常！")
print("=" * 60)

