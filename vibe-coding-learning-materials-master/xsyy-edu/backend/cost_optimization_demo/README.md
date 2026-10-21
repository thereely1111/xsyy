# 降本与回归测试示例

该目录提供一套可直接运行的参考实现，覆盖：

1. Token 成本优化（三层缓存思路）。
2. 基于黄金数据集的回归测试。
3. 基于 Google AI Studio（Gemini API）的低成本模型验证。

## 目录结构

- `config.py`：集中管理缓存、Gemini、推理参数与回归测试配置。
- `cache_service.py`：Redis 优先的教学内容缓存服务（按题目哈希命中）。
- `gemini_client.py`：Gemini API 客户端封装。
- `main_service.py`：核心流程（先查缓存，未命中再调模型，最后回写缓存并渲染模板）。
- `regression_test.py`：10 道黄金题回归测试 + MD5 输出对比。

## 三项任务如何落地

### 任务一：Token 降本

- 第一层（模板复用）：`main_service.py` 默认复用 `backend/prompt/teaching_template.html`。
- 第二层（核心）：`cache_service.py` 按 `problem + difficulty + extra_context` 生成哈希键并缓存教学内容，命中则跳过模型调用。
- 第三层（部署优化参数）：`config.py` 暴露自托管推理建议参数：
  - `ENABLE_KV_CACHE=true`
  - `GPU_MEMORY_UTILIZATION=0.85`
  - `MAX_NUM_BATCHED_TOKENS=4096`

## 安装依赖

在当前目录执行：

```powershell
pip install pytest redis requests google-genai
```

可选：本地启动 Redis

```powershell
docker run -p 6379:6379 redis:7
```

## 环境变量

```powershell
$env:GOOGLE_API_KEY="你的 AI Studio Key"
$env:REGRESSION_API_MODE="local"  # 可选: local 或 http
$env:REGRESSION_BACKEND="mock"    # 可选: mock 或 gemini
$env:CACHE_TTL_SECONDS="86400"
```

如果你要通过 HTTP 接口进行回归（对接现有 FastAPI）：

```powershell
$env:REGRESSION_API_MODE="http"
$env:TEST_API_URL="http://127.0.0.1:8000/api/test/animation-generation"
```

## 运行回归测试

```powershell
pytest -q regression_test.py
```

产物文件：

- `artifacts/latest_hashes.json`：本次测试输出哈希。
- `artifacts/baseline_hashes.json`：人工确认后的基线哈希。
- `artifacts/hash_diff.json`：仅当有差异时生成。

首次运行说明：

- 若不存在 `baseline_hashes.json`，哈希对比用例会被跳过。
- 人工审核 `latest_hashes.json` 后，可复制为 `baseline_hashes.json` 作为基线。

## 说明

- 为保证稳定性，回归脚本默认使用 `mock` 后端。
- 如需真实验证 Gemini 效果，可设置环境变量：`$env:REGRESSION_BACKEND="gemini"`。
