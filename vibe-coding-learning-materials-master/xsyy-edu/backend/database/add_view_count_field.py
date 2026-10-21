"""
添加 view_count 字段到 teachings 表的迁移脚本
"""
import sys
from pathlib import Path

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, engine
from sqlalchemy import text

def add_view_count_field():
    """添加 view_count 字段到 teachings 表"""
    print("=" * 60)
    print("开始添加 view_count 字段...")
    print("=" * 60)
    
    try:
        # 检查字段是否已存在
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT COUNT(*) as count 
                FROM information_schema.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                AND TABLE_NAME = 'teachings' 
                AND COLUMN_NAME = 'view_count'
            """))
            exists = result.fetchone()[0] > 0
            
            if exists:
                print("✓ view_count 字段已存在，跳过添加")
                return True
            
            # 添加字段
            print("正在添加 view_count 字段...")
            conn.execute(text("""
                ALTER TABLE teachings 
                ADD COLUMN view_count INT NOT NULL DEFAULT 0 
                AFTER preview_image
            """))
            conn.commit()
            print("✓ view_count 字段添加成功！")
            
            # 验证
            result = conn.execute(text("DESCRIBE teachings"))
            columns = [row[0] for row in result]
            if 'view_count' in columns:
                print("✓ 验证成功：view_count 字段已存在于 teachings 表中")
                return True
            else:
                print("✗ 验证失败：view_count 字段未找到")
                return False
                
    except Exception as e:
        print(f"✗ 添加字段失败: {e}")
        print("\n提示：")
        print("  1. 请确认 MySQL 服务正在运行")
        print("  2. 请确认 .env 文件中的 DATABASE_URL 配置正确")
        print("  3. 请确认数据库用户有 ALTER TABLE 权限")
        return False

if __name__ == "__main__":
    success = add_view_count_field()
    sys.exit(0 if success else 1)

