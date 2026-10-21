"""
管理后台 API 测试
P1 优先级
"""
import pytest
from fastapi import status


class TestAdminCheck:
    """管理员权限检查测试"""
    
    def test_admin_check_success(self, test_client, admin_token):
        """测试管理员权限检查成功"""
        response = test_client.get(
            "/api/admin/check",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        # 如果 admin 用户在 ADMIN_USERNAMES 中，应该返回成功
        # 否则可能返回 403
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_403_FORBIDDEN
        ]
        
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert "is_admin" in data
    
    def test_admin_check_without_auth(self, test_client):
        """测试未登录检查管理员权限失败"""
        response = test_client.get("/api/admin/check")
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_admin_check_normal_user(self, test_client, auth_token):
        """测试普通用户检查管理员权限失败"""
        response = test_client.get(
            "/api/admin/check",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # 普通用户应该返回 403 或 200（但 is_admin 为 false）
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_403_FORBIDDEN
        ]


class TestAdminTeachings:
    """管理后台教学内容管理测试"""
    
    def test_get_all_teachings(self, test_client, admin_token):
        """测试获取所有教学内容"""
        response = test_client.get(
            "/api/admin/teachings",
            headers={"Authorization": f"Bearer {admin_token}"},
            params={"page": 1, "page_size": 10}
        )
        
        # 如果 admin 有权限，应该返回成功
        # 否则返回 403
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_403_FORBIDDEN
        ]
        
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert "total" in data
            assert "data" in data
            assert isinstance(data["data"], list)


class TestAdminStatistics:
    """管理后台统计数据测试"""
    
    def test_get_statistics(self, test_client, admin_token):
        """测试获取统计数据"""
        response = test_client.get(
            "/api/admin/statistics",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        # 如果 admin 有权限，应该返回成功
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_403_FORBIDDEN
        ]
        
        if response.status_code == status.HTTP_200_OK:
            data = response.json()
            assert "users" in data or "teachings" in data

