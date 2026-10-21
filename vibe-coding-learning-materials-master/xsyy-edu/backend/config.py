"""
系统配置文件
管理管理员列表、系统配置等
"""

import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# 加载 .env 文件
backend_dir = Path(__file__).resolve().parent
env_path = backend_dir / ".env"
load_dotenv(dotenv_path=env_path)


def get_admin_usernames() -> List[str]:
    """
    获取管理员用户名列表
    从环境变量 ADMIN_USERNAMES 读取，格式为逗号分隔的字符串
    例如：ADMIN_USERNAMES=admin,administrator,superuser
    """
    admin_usernames_str = os.getenv("ADMIN_USERNAMES", "")
    if not admin_usernames_str:
        # 如果没有配置，返回空列表（需要手动配置管理员）
        return []
    
    # 分割并去除空白
    usernames = [name.strip() for name in admin_usernames_str.split(",") if name.strip()]
    return usernames


def is_admin(username: str) -> bool:
    """
    检查用户名是否为管理员
    
    Args:
        username: 用户名
        
    Returns:
        是否为管理员
    """
    admin_usernames = get_admin_usernames()
    return username.lower() in [name.lower() for name in admin_usernames]


# 系统配置默认值
DEFAULT_BETA_CODE = os.getenv("BETA_CODE", "XSYY2025")
DEFAULT_DAILY_MAX_CALLS = int(os.getenv("DEFAULT_DAILY_MAX_CALLS", "3"))
ANONYMOUS_DAILY_MAX_CALLS = int(os.getenv("ANONYMOUS_DAILY_MAX_CALLS", "0"))

