"""
用户认证 API 测试
P0 优先级 - 必须通过
"""
import pytest
from fastapi import status


class TestUserRegistration:
    """用户注册测试"""
    
    def test_register_with_password_success(self, test_client, test_user_data):
        """测试用户名密码注册成功"""
        response = test_client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "password": "newpass123",
                "beta_code": "XSYY2025"
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "token" in data
        assert "user" in data
    
    def test_register_duplicate_username(self, test_client, test_user_data):
        """测试重复用户名注册失败"""
        # 第一次注册
        test_client.post(
            "/api/auth/register",
            json={
                "username": "duplicate_user",
                "password": "pass123",
                "beta_code": "XSYY2025"
            }
        )
        
        # 第二次注册相同用户名
        response = test_client.post(
            "/api/auth/register",
            json={
                "username": "duplicate_user",
                "password": "pass123",
                "beta_code": "XSYY2025"
            }
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_register_invalid_beta_code(self, test_client):
        """测试无效内测码注册失败"""
        response = test_client.post(
            "/api/auth/register",
            json={
                "username": "testuser",
                "password": "pass123",
                "beta_code": "INVALID_CODE"
            }
        )
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestUserLogin:
    """用户登录测试"""
    
    def test_login_with_password_success(self, test_client, test_user_data):
        """测试用户名密码登录成功"""
        # 先注册
        test_client.post(
            "/api/auth/register",
            json={
                "username": test_user_data["username"],
                "password": test_user_data["password"],
                "beta_code": "XSYY2025"
            }
        )
        
        # 登录
        response = test_client.post(
            "/api/auth/login",
            json={
                "username": test_user_data["username"],
                "password": test_user_data["password"]
            }
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True
        assert "token" in data
        assert len(data["token"]) > 0
    
    def test_login_invalid_credentials(self, test_client):
        """测试无效凭据登录失败"""
        response = test_client.post(
            "/api/auth/login",
            json={
                "username": "nonexistent",
                "password": "wrongpass"
            }
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_login_wrong_password(self, test_client, test_user_data):
        """测试错误密码登录失败"""
        # 先注册
        test_client.post(
            "/api/auth/register",
            json={
                "username": test_user_data["username"],
                "password": test_user_data["password"],
                "beta_code": "XSYY2025"
            }
        )
        
        # 使用错误密码登录
        response = test_client.post(
            "/api/auth/login",
            json={
                "username": test_user_data["username"],
                "password": "wrongpassword"
            }
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestGetCurrentUser:
    """获取当前用户信息测试"""
    
    def test_get_current_user_success(self, test_client, auth_token):
        """测试获取当前用户信息成功"""
        response = test_client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "user" in data or "username" in data
    
    def test_get_current_user_without_token(self, test_client):
        """测试无 token 获取用户信息失败"""
        response = test_client.get("/api/auth/me")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_get_current_user_invalid_token(self, test_client):
        """测试无效 token 获取用户信息失败"""
        response = test_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token"}
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

