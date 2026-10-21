# XSYY LangChain Backend

## 快速启动

### 环境变量配置

本项目使用 `.env` 文件管理 API 密钥。首次使用需要：

1. **复制示例文件**：
   ```bash
   cd backend
   copy env.example .env
   ```
2. **编辑** **`.env`** **文件**，填入你的 API 密钥：
   - `DEEPSEEK_API_KEY`：DeepSeek API 密钥（获取地址：<https://platform.deepseek.com/）>
   - `ZENMUX_API_KEY`：ZenMux API 密钥（获取地址：<https://zenmux.ai/）>
3. **可选配置**：
   - `TEST_MODE=1`：启用测试模式（不调用真实 API）
   - `DEEPSEEK_MODEL_NAME`：DeepSeek 模型名称（默认：deepseek-chat）
   - `ZENMUX_IMAGE_MODEL`：图片生成模型名称（默认：google/gemini-3.1-flash-lite-image）
   - `ZENMUX_HTML_MODEL`：HTML 生成模型名称（默认：google/gemini-3.1-flash-lite）
   - `ZENMUX_RESPONSE_MODEL`：AI 助教回答模型名称（默认：google/gemini-3.1-flash-lite）

**注意**：`.env` 文件已添加到 `.gitignore`，不会被提交到版本控制。

### 方式一：生产模式（使用真实 API - 链式调用）

```bash
cd xsyy/backend
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -r requirements.txt

# 确保已配置 .env 文件（见上方"环境变量配置"部分）
# 启动服务
uvicorn app:app --reload
```

**注意**：`.env` 文件已添加到 `.gitignore`，不会被提交到版本控制。

### 方式二：测试模式（使用预设回复，无需 API 密钥）

```bash
cd xsyy/backend
python -m venv .venv && .venv/Scripts/activate  # Windows
pip install -r requirements.txt

# 方式 A：在 .env 文件中设置
# 编辑 .env 文件，添加：TEST_MODE=1

# 方式 B：通过环境变量设置
set TEST_MODE=1

uvicorn app:app --reload
```

或者直接使用测试启动脚本：

```bash
cd xsyy/backend
.\start-test.bat
```

**测试模式说明**：

- ✅ 无需配置 API 密钥
- ✅ 响应速度快（无网络请求）
- ✅ 适合前端功能测试
- ⚠️ 返回的是预设的通用模板，不是针对具体题目的定制化内容
- ⚠️ 不会创建文件夹或保存文件到 storage

## API

- `POST /api/tasks`：上传题目文件（图片/PDF/语音）并创建生成任务。
  - form-data: `file`, 可选 `prompt`
- `GET /api/tasks/{task_id}`：轮询任务状态，返回视频地址、预览图、metadata。
- `POST /api/feedback`：上传学生反馈，便于形成学习闭环。

## LangChain Pipeline（链式调用）

`pipeline.py` 实现了一个**两阶段链式调用**流水线：

### 第一阶段：教学设计师（DeepSeek）

- **模型**：`deepseek-chat`
- **角色**：分析用户的非结构化输入，提取核心数学题，策划教学步骤
- **输入**：用户原始输入（可能包含无关信息）
- **输出**：结构化的教学需求文档（Markdown 格式）
- **Prompt 文件**：
  - `extract_system_prompt.txt`：系统提示词
  - `extract_user_prompt.txt`：用户提示词模板（包含 `__USER_INPUT__` 占位符）

### 第二阶段：程序员（Gemini）

- **模型**：`google/gemini-3.1-flash-lite-image` + `google/gemini-3.1-flash-lite`
- **角色**：根据教学设计师的输出，生成交互式 HTML 教学应用
- **输入**：第一阶段的结构化教学需求文档
- **输出**：完整的单文件 HTML 教学应用
- **Prompt 文件**：
  - `teaching_system_prompt.txt`：系统提示词
  - `teaching_user_prompt.txt`：用户提示词模板（包含 `__PRE_OUT__` 占位符）
  - `teaching_template.html`：HTML 教学应用模板

### 工作流程

1. **题目构造**：优先使用前端上传的 `prompt`，否则使用文件名
2. **教学设计师分析**：DeepSeek 提取题目、定义参数、策划方法、设计演示逻辑
3. **程序员编码**：Gemini 根据设计文档生成 HTML 教学应用
4. **返回结果**：
   - `metadata.question`：提取的题目文本
   - `metadata.plan`：从设计文档中提取的步骤
   - `metadata.teaching_html`：完整的 HTML 教学应用

后续你可以：

- 将 `video_url` / `preview_image` 接到真正的动画渲染服务；
- 或在前端中直接渲染 `teaching_html`，形成每题一个“小教学应用”。

