# PowerShell 脚本：测试后端 API
# 使用方法: .\test_api.ps1

Write-Host "测试后端 API 健康检查端点..." -ForegroundColor Cyan

try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -Method GET
    Write-Host "✓ API 响应成功" -ForegroundColor Green
    Write-Host "状态码: $($response.StatusCode)" -ForegroundColor Green
    Write-Host "响应内容:" -ForegroundColor Yellow
    $response.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
} catch {
    Write-Host "✗ API 请求失败" -ForegroundColor Red
    Write-Host "错误信息: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host "请确保:" -ForegroundColor Yellow
    Write-Host "  1. 后端服务正在运行 (python -m uvicorn app:app --reload)" -ForegroundColor Yellow
    Write-Host "  2. 服务运行在 http://localhost:8000" -ForegroundColor Yellow
}

