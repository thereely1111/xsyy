"""
健康检查 API 测试
P0 优先级 - 必须通过
"""
import pytest
from fastapi import status


class TestHealthCheck:
    """健康检查端点测试"""
    
    def test_health_check_success(self, test_client):
        """测试健康检查端点正常响应"""
        response = test_client.get("/api/health")
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        
        assert data["status"] == "ok"
        assert "message" in data
        assert "timestamp" in data
    
    def test_health_check_response_time(self, test_client):
        """测试健康检查响应时间"""
        import time
        
        start_time = time.time()
        response = test_client.get("/api/health")
        elapsed_time = time.time() - start_time
        
        assert response.status_code == status.HTTP_200_OK
        assert elapsed_time < 1.0  # 应该在1秒内响应

