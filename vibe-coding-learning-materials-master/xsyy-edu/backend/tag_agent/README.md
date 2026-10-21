# 标签智能体使用说明

> 适用范围：象数演易 xsyy 项目的标签智能体体系
> 代码位置：`backend/tag_agent/`（智能体本体 + 接入，一体化运行，2026-08-31 重新部署回 xsyy 进程）
> 更新日期：2026-08-31（一体化回归）

---

## 一、智能体功能清单（当前已实现）

### 1. 标签识别（核心）
| 能力 | 说明 |
|---|---|
| 知识域 + 年级判定 | 5 大知识域 / 18 年级（一上~九下） |
| 章/单元、知识点标签匹配 | 候选锁定，禁止自创正式标签 |
| 关键词提取与提案 | 场景一：补关键词（进审核队列，不直写） |
| 新标签生成（场景二） | 已有章下生成新知识点标签提案 |
| 新标签链路生成（场景三） | 章/单元+标签整条链路提案（更严审核） |
| 查重校验 | 新标签生成前与正式库/pending 池双重查重 |

### 2. 自动纠错标签
- 对已有标签提出**修改提案**：关键词缺失 / 年级归属错误 / 知识域错误 / 章归属错误 / 命名不规范（五类字段）
- 仅提案，由管理员审核后生效

### 3. 删除重复标签
- 全库扫描重复标签（字符相似度 + LLM 边界确认），产出**合并/删除提案**
- 「一键转合并提案」：扫描结果直接进入审核队列

### 4. 预修改审核流程（库级）
- 智能体对正式标签库的**增 / 改 / 删 / 合并**四类操作**全部进审核队列**
- 管理员审核动作：通过 / 修改后通过 / 合并 / 驳回；删除需**二次确认**（硬删除）
- 支持**批量审核**（勾选多条一次通过/驳回）
- 审核结果全部回写学习记录（learning_records）

### 5. 题目标签审核（题目级）
- 题目级标签**全部人工审核**：识别结果先入队，管理员确认后才写题目 `knowledge_tags`
- 审核通过后**自动应用**到 teachings 表并同步 metadata

### 6. 系统集成
- 识别引擎开关：`agent`（智能体）/ `legacy`（原提示词）/ `dual`（默认，agent 优先失败降级）
- 智能体故障自动降级 legacy，不影响用户

### 7. 底层引擎
- 模型：`gpt-5.5`（经 kuaipao.pro OpenAI 兼容中转）
- 标签库：**远程 MySQL `knowledge_tag_framework` 表**（5 域 / 18 年级 / 924 知识点标签，加载失败自动降级本地种子）

---

## 二、架构概览（一体化，2026-08-31 重新部署）

```
xsyy 后端（8000）— 单进程自包含
┌─────────────────────────────────────────┐
│ backend/tag_agent/                      │
│  ├ orchestrator.py   三场景编排          │
│  ├ agents/           8 个智能体          │
│  │   (域年级/匹配/关键词/新标签/查重/    │
│  │    纠错/去重/校验)                    │
│  ├ tag_library.py    远程标签库          │
│  ├ service.py        审核/落库           │
│  ├ models.py/db.py   四张智能体表        │
│  ├ router.py         /tag-agent/* API    │
│  ├ client.py         进程内直调编排器    │
│  └ compat.py         结果映射            │
└─────────────────────────────────────────┘
管理后台 tag_review.html（预修改+题目标签审核）
```

- **智能体本体随 xsyy 进程运行**，不依赖独立 agent-platform 服务（公网单进程部署）；
- 识别：`client.py` 进程内直调 `orchestrator`（失败降级 legacy 提示词模型）；
- 审核：管理后台 `tag_review.html` → xsyy `router.py` → 本地 `service`（进程内）；
- 题目审核通过后，`question_queue.py` 将标签写入本库 `teachings`；
- 四张智能体表（pending / question-proposals / learning_records / recognition_logs）在**远程 MySQL 业务库**（`TAG_AGENT_REMOTE_DB_URL`），与业务表同库；
- agent-platform 项目（`E:\象数演易\agent-platform`）保留相同本体代码，可独立部署（平台 Agent 化场景），xsyy 已不依赖它。

---

## 三、启动与配置

### 1. 安装依赖（公网部署关键）
```bash
pip install -r requirements.txt
# 智能体必需包（已加入 requirements.txt）：agentscope、pydantic-settings、aiomysql
# 若旧服务器未装，单独补装：
pip install "agentscope>=2.0.0" "pydantic-settings>=2.0.0" "aiomysql>=0.2.0"
```

### 2. 启动（一体化：只启 xsyy，智能体随进程）
```bash
# 启动 xsyy 后端（8000，用 hermes venv 运行）
cd E:\象数演易\1\xsyy\...\xsyy-edu\backend
python -m uvicorn app:app --reload    # backend venv 缺 chromadb，须用 hermes venv
```
启动日志应出现：`标签识别智能体数据表就绪` + `标签识别智能体已预热`；
验证：`curl http://127.0.0.1:8000/tag-agent/health` → 401（未带管理员 token，路由已注册）

### 3. 公网部署注意（Nginx，两重转发都要改）
- ⚠️ **公网 nginx 是两重转发**：主配置（www.xsyy.top，80/443）+ `xsyy-frontend.conf`（前端兜底层，SPA fallback 到 index.html）；
- `location /tag-agent/ { proxy_pass http://127.0.0.1:8000; }` **必须同时存在于两重配置**，漏任一层 → `/tag-agent/*` 被 SPA 兜底返回 HTML → 前端报 `Unexpected token '<'`（2026-09-02 公网事故即漏改 xsyy-frontend.conf）；
- 改后 `sudo nginx -t && sudo systemctl reload nginx`，复测 `curl https://www.xsyy.top/tag-agent/health` 返回 JSON 而非 HTML；
- 完整排查/修复流程见同目录《智能体部署更新问题排查指南.md》。

### 4. 环境变量（xsyy `.env`）
| 键 | 说明 |
|---|---|
| `GPTSAPI_KEY` / `GPTSAPI_BASE` / `GPTSAPI_CHAT_MODEL` | 模型配置（kuaipao.pro 中转 gpt-5.5；`GPTsAPI_*` 写法同样生效，pydantic 大小写不敏感） |
| `TAG_AGENT_REMOTE_DB_URL` | 智能体数据表连接串（四张表与业务库同库 MySQL） |
| `TAG_RECOGNITION_ENGINE` | `agent` / `legacy` / `dual`（默认 dual） |
| `AGENT_PLATFORM_URL` 等 | 已废弃（HTTP 分离遗留），保留不影响运行 |

> 注意：`config.py` 的字段经 pydantic-settings 映射，**只认 `GPTSAPI_KEY`（无 TAG_AGENT_ 前缀）**；`TAG_AGENT_REMOTE_DB_URL` 已加别名支持。

---

## 四、使用流程

### 1. 日常识别（自动，无需人工）
教学内容创建时自动识别标签（`dual` 模式 agent 优先，失败降级 legacy）。

### 2. 审核智能体提案（管理后台「标签智能体审核」页）
入口：管理后台侧边栏 → `标签智能体审核`（tag_review.html）

| Tab | 内容 | 操作 |
|---|---|---|
| 📚 库级预修改审核 | 增/改/删/合并四类提案 | 通过 / 修改后通过 / 合并 / 驳回；删除二次确认；批量操作 |
| 📝 题目标签审核 | 题目级标签建议 | 通过 / 修改后通过 / 驳回；通过后自动写题目标签 |
| 🔍 全库去重扫描 | 重复标签检测结果 | 一键转为合并提案进审核队列 |

审核原则：**智能体永不直接写正式库 / 题目标签**，全部经管理员确认。

### 3. 灰度切换（识别引擎）
- 默认 `dual`：agent 优先，失败自动降级 legacy（安全）
- 观察识别质量达标后，改 `.env`：`TAG_RECOGNITION_ENGINE=agent`，重启生效

---

## 五、API 一览（xsyy 8000 `/tag-agent/*`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/recognize` | 识别题目（三场景编排） |
| GET | `/framework` | 正式标签库概览（source=json/database） |
| GET | `/pending` | 预修改提案列表（可按 operation/status 过滤） |
| POST | `/pending/{id}/review` | 审核单条（增/改/删/合并） |
| POST | `/pending/batch-review` | 批量审核 |
| GET | `/question-proposals` | 题目标签审核队列 |
| POST | `/question-proposals/{id}/review` | 审核题目标签建议 |
| POST | `/duplicates/scan` | 全库去重扫描（仅提案） |
| POST | `/duplicates/persist` | 去重提案转合并提案入队列 |
| GET | `/recognition-logs` | 识别日志 |
| GET | `/learning-records` | 学习闭环记录 |

xsyy 管理后台同路径前缀 `/tag-agent/*` 直接调用（require_admin 鉴权）。

---

## 六、验证与排查

### 冒烟验证（管理员登录后）
```bash
# 1) 健康 + 远程标签库（需管理员 token）
curl -H "Authorization: Bearer <admin_token>" http://127.0.0.1:8000/tag-agent/health    # status=ok，标签数=924
curl -H "Authorization: Bearer <admin_token>" http://127.0.0.1:8000/tag-agent/framework  # source=database

# 2) 查看待审核提案
curl -H "Authorization: Bearer <admin_token>" "http://127.0.0.1:8000/tag-agent/pending?status=pending"
```

### 常见问题
| 现象 | 排查 |
|---|---|
| 识别返回"缺少 GPTsAPI_KEY" | xsyy .env 未配置 `GPTSAPI_KEY`（与 KIMI_API_KEY 同值） |
| `/framework` 显示 `source=json` | `TAG_AGENT_REMOTE_DB_URL` 未生效/连不上（看启动日志） |
| 审核页无数据 | 检查管理后台登录态；识别是否入队（stats 看 pending_queue） |
| 识别慢（16s+/题） | 中转模型延迟，属正常；成本走阶段六监控 |
| 识别质量偏差（如年级判错） | 属持续优化范畴：调整 prompt/同义词/混淆规则，审核结果反哺 |

---

## 七、目录说明

```
backend/tag_agent/            # 智能体本体 + 接入（一体化，2026-08-31 起）
├── __init__.py
├── config.py                 # 读取 .env 配置（模型/远程库/引擎开关）
├── client.py                 # 识别客户端（进程内直调编排器，失败降级 legacy）
├── compat.py                 # agent 结果 → xsyy knowledge_tags 结构映射
├── router.py                 # /tag-agent/* API（require_admin 鉴权，题目审核写 teachings）
├── question_queue.py         # 题目审核结果应用（写 teachings）
├── orchestrator.py           # 三场景编排 + 纠错/去重入口
├── agents/                   # 8 个智能体（base/域年级/匹配/关键词/新标签/查重/纠错/去重）
├── tag_library.py            # 远程标签库加载（MySQL knowledge_tag_framework）
├── service.py                # 审核应用（增/改/删/合并）+ 批量 + 题目队列 + 去重落库
├── models.py / db.py         # 四张智能体表（独立 TagBase 异步引擎连远程 MySQL）
├── schemas.py                # API 请求/响应模型
├── llm.py                    # AgentScope 模型构建（gpt-5.5 @ kuaipao.pro）
└── seed_data/                # 标签库种子（远程库连通前兜底）

E:\象数演易\agent-platform\backend\app\tag_agent\   # 相同本体（平台独立部署场景，xsyy 不依赖）
```

历史说明：HTTP 分离版（xsyy 转发 agent-platform 9000）已废弃；一体化版（智能体搬入 xsyy 进程）备份于 `tag_agent/*.inprocess.bak` 与 `tag_agent_backup_integration/`，本次已恢复并升级为一体化架构。

> 历史说明：xsyy 旧体系的「识别日志/评测/纠错台」功能已按需求删除（数据备份于 `E:\象数演易\备份_识别日志纠错表_2026-08-28\`），新体系由上述审核队列与学习记录替代。
