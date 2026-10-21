"""
pytest 配置文件和共享 fixtures
"""
import os
import pytest
import sys
from pathlib import Path
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# 添加项目根目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 设置测试环境变量
os.environ["TEST_MODE"] = "1"
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-only"

# 导入应用
from app import app
from database.database import Base, get_db

# 测试数据库配置（使用内存数据库或独立的测试数据库）
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "mysql+pymysql://root:password@localhost/xsyy_test?charset=utf8mb4"
)

# 创建测试数据库引擎
test_engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
    echo=False
)

# 创建测试会话工厂
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine
)


@pytest.fixture(scope="function")
def db_session() -> Generator[Session, None, None]:
    """
    创建测试数据库会话
    每个测试函数都会创建一个新的会话，测试结束后回滚
    """
    # 创建表
    Base.metadata.create_all(bind=test_engine)
    
    # 创建会话
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def test_client(db_session: Session) -> Generator[TestClient, None, None]:
    """
    创建测试客户端
    """
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    # 覆盖依赖
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as client:
        yield client
    
    # 清理
    app.dependency_overrides.clear()


@pytest.fixture
def test_user_data():
    """测试用户数据"""
    return {
        "username": "testuser",
        "password": "testpass123",
        "phone": "13800138000",
        "email": "test@example.com"
    }


@pytest.fixture
def test_admin_data():
    """测试管理员数据"""
    return {
        "username": "admin",
        "password": "admin123",
        "phone": "13900139000",
        "email": "admin@example.com"
    }


@pytest.fixture
def auth_token(test_client: TestClient, test_user_data: dict) -> str:
    """
    创建已登录用户的 token
    """
    # 先注册用户
    response = test_client.post(
        "/api/auth/register",
        json={
            "username": test_user_data["username"],
            "password": test_user_data["password"],
            "beta_code": os.getenv("BETA_CODE", "XSYY2025")
        }
    )
    
    # 登录获取 token
    response = test_client.post(
        "/api/auth/login",
        json={
            "username": test_user_data["username"],
            "password": test_user_data["password"]
        }
    )
    
    if response.status_code == 200:
        return response.json()["token"]
    else:
        pytest.fail(f"无法创建测试用户 token: {response.text}")


@pytest.fixture
def admin_token(test_client: TestClient, test_admin_data: dict) -> str:
    """
    创建管理员 token
    """
    # 先注册管理员用户
    response = test_client.post(
        "/api/auth/register",
        json={
            "username": test_admin_data["username"],
            "password": test_admin_data["password"],
            "beta_code": os.getenv("BETA_CODE", "XSYY2025")
        }
    )
    
    # 登录获取 token
    response = test_client.post(
        "/api/auth/login",
        json={
            "username": test_admin_data["username"],
            "password": test_admin_data["password"]
        }
    )
    
    if response.status_code == 200:
        return response.json()["token"]
    else:
        pytest.fail(f"无法创建管理员 token: {response.text}")


@pytest.fixture
def test_image_file():
    """创建测试图片文件"""
    from io import BytesIO
    from PIL import Image
    
    # 创建一个简单的测试图片
    img = Image.new('RGB', (100, 100), color='red')
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return ("test_image.png", img_bytes, "image/png")

