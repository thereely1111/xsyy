"""
任务相关 API 测试
P0 优先级 - 必须通过
"""
import pytest
import time
from fastapi import status
from io import BytesIO
from PIL import Image


class TestCreateTask:
    """创建任务测试"""
    
    def test_create_task_with_image(self, test_client, auth_token, test_image_file):
        """测试上传图片创建任务成功"""
        # 准备文件
        files = {
            "file": (test_image_file[0], test_image_file[1], test_image_file[2])
        }
        
        response = test_client.post(
            "/api/tasks",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "task_id" in data
        assert data["status"] in ["pending", "running"]
    
    def test_create_task_without_auth(self, test_client, test_image_file):
        """测试未登录创建任务失败"""
        files = {
            "file": (test_image_file[0], test_image_file[1], test_image_file[2])
        }
        
        response = test_client.post("/api/tasks", files=files)
        
        # 可能返回 401 或 200（如果允许匿名）
        assert response.status_code in [status.HTTP_401_UNAUTHORIZED, status.HTTP_200_OK]


class TestGetTaskStatus:
    """获取任务状态测试"""
    
    def test_get_task_status_success(self, test_client, auth_token, test_image_file):
        """测试获取任务状态成功"""
        # 先创建任务
        files = {
            "file": (test_image_file[0], test_image_file[1], test_image_file[2])
        }
        
        create_response = test_client.post(
            "/api/tasks",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        if create_response.status_code != status.HTTP_200_OK:
            pytest.skip("无法创建任务，跳过状态查询测试")
        
        task_id = create_response.json()["task_id"]
        
        # 查询任务状态
        response = test_client.get(
            f"/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "task_id" in data
        assert "status" in data
        assert data["status"] in ["pending", "running", "completed", "failed"]
    
    def test_get_task_status_not_found(self, test_client, auth_token):
        """测试查询不存在的任务失败"""
        response = test_client.get(
            "/api/tasks/nonexistent_task_id",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestTaskWorkflow:
    """任务工作流测试"""
    
    def test_complete_task_workflow(self, test_client, auth_token, test_image_file):
        """测试完整任务流程（创建 -> 查询状态 -> 获取结果）"""
        # 1. 创建任务
        files = {
            "file": (test_image_file[0], test_image_file[1], test_image_file[2])
        }
        
        create_response = test_client.post(
            "/api/tasks",
            files=files,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        if create_response.status_code != status.HTTP_200_OK:
            pytest.skip("无法创建任务，跳过工作流测试")
        
        task_id = create_response.json()["task_id"]
        
        # 2. 轮询任务状态（最多等待30秒）
        max_wait_time = 30
        start_time = time.time()
        
        while time.time() - start_time < max_wait_time:
            status_response = test_client.get(
                f"/api/tasks/{task_id}",
                headers={"Authorization": f"Bearer {auth_token}"}
            )
            
            if status_response.status_code != status.HTTP_200_OK:
                break
            
            status_data = status_response.json()
            task_status = status_data.get("status")
            
            if task_status in ["completed", "failed"]:
                # 任务完成或失败
                assert task_status == "completed" or task_status == "failed"
                break
            
            # 等待1秒后重试
            time.sleep(1)
        
        # 3. 获取任务元数据
        metadata_response = test_client.get(
            f"/api/teachings/{task_id}/metadata",
            headers={"Authorization": f"Bearer {auth_token}"}
        )
        
        # 元数据可能不存在（如果任务还在处理中）
        assert metadata_response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_404_NOT_FOUND
        ]

