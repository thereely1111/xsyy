# Vibe Coding 学习资料库

本仓库收录 **Vibe Coding（氛围编程）** 相关的学习资料、教学演示与实践项目，主要包含：

- **教学演示 PPT（HTML）**：用于课堂/Workshop 的可交互教学页面与 Demo
- **象数演易教育平台（XSYY）**：一个基于 AI 的智能教学平台（后端 FastAPI + LangChain 流水线 + 前端静态网页）

> 仓库描述：上进双创工作室 vibe coding 产品开发学习资源

## 📁 目录结构

```text
vibe-coding-learning-materials/
├── xsyy-edu/                        # 象数演易教育平台（XSYY）
    ├── backend/                     # 后端服务（FastAPI / LangChain）
    │   ├── chroma_db/
    │   ├── cost_optimization_demo/  # 降本与回归测试
    │   ├── database/                # 数据库模型和迁移脚本
    │   ├── prompt/                  # AI 提示词模板
    │   ├── tests/                   # 测试套件
    │   ├── users/
    │   └── utils/                   # 工具函数
    ├── deploy/                      # 部署脚本和配置
    ├── storage/                     # 教学资源存储（生成结果、预览图、metadata 等）
    └── web/                         # 前端网页（静态资源）
        ├── admin/                   # 管理后台
        ├── css/                     # 样式文件
        ├── dist/
        ├── src/
        ├── js/                      # JavaScript 文件
        └── images/                  # 图片资源
```

## 🎯 项目介绍
### 象数演易教育平台（`xsyy-edu/`）

一个基于 AI 的智能教学平台，主要能力包括：

- **智能教案生成**：将题目/素材转化为结构化教学设计与讲解步骤
- **教学应用生成**：根据教学设计生成单文件 HTML 交互式教学应用
- **用户与反馈闭环**：支持提交学生反馈，便于持续优化
- **资源与存储**：生成结果与预览资源落盘到 `storage/`
- **部署与运维**：提供部署文档，便于上云部署与服务管理

#### 后端技术栈（以仓库现状为准）

- **Web 框架**：FastAPI
- **运行**：Uvicorn
- **LLM / 编排**：LangChain
- **模型接入**：DeepSeek、Gemini（以及 LangChain OpenAI 适配器等）
- **数据库**：SQLAlchemy + MySQL/SQLite（按配置切换）

#### LangChain Pipeline（两阶段链式调用）

后端实现了两阶段流水线（详见 `xsyy-edu/backend/README.md`）：

1. **教学设计师（DeepSeek）**：从非结构化输入中提取题目与关键参数，输出结构化教学需求文档（Markdown）
2. **程序员（Gemini）**：基于结构化需求文档生成完整的单文件 HTML 教学应用

## 🚀 快速开始（XSYY 后端）

> 更完整步骤请阅读：`xsyy-edu/backend/快速开始.md`

### 1) 进入目录

```bash
cd xsyy-edu/backend
```

### 2) 创建虚拟环境并安装依赖

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

### 3) 配置环境变量

```bash
cp env.example .env
# 编辑 .env 文件：配置 DATABASE_URL、DEEPSEEK_API_KEY、ZENMUX_API_KEY 等
```

### 4)（推荐）初始化本地数据库并验证配置

```bash
python setup_local_db.py
python database/migrate.py
python verify_db_config.py
```

### 5) 启动服务

```bash
python -m uvicorn app:app --reload
```

启动后默认地址：`http://localhost:8000`

### 6) 简单健康检查

```bash
curl http://localhost:8000/api/health
```

## 📚 文档

- XSYY 项目介绍：`xsyy-edu/项目介绍.md`
- [部署指南](xsyy-edu/deploy/DEPLOYMENT.md)
- 后端说明与 Pipeline：`xsyy-edu/backend/README.md`
- 后端配置指南：`xsyy-edu/backend/配置指南.md`
- 后端快速开始：`xsyy-edu/backend/快速开始.md`

## 🔗 相关链接

- GitHub 仓库：https://github.com/followmh0418-stack/vibe-coding-learning-materials

## 📝 说明

本仓库用于学习和实践 Vibe Coding 理念，包含教学材料与完整项目代码。欢迎通过 Issue / PR 补充资料与改进文档。
