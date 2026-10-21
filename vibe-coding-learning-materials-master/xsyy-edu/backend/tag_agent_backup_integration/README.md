# 标签智能体使用说明

> 适用范围：象数演易 xsyy 项目的标签智能体体系
> 代码位置：`backend/tag_agent/`（xsyy 侧接入模块）+ `E:\象数演易\agent-platform\`（AgentScope 智能体平台）
> 更新日期：2026-08-28（阶段一~四完成）

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

## 二、架构概览

```
xsyy 后端（8000）                         agent-platform（9000）
┌──────────────────────┐                 ┌──────────────────────────┐
│ backend/tag_agent/   │   HTTP 转发      │ app/tag_agent/           │
│  ├ client.py 识别客户端│ ───────────────▶│  ├ orchestrator 编排器    │
│  ├ compat.py 结果映射  │                 │  ├ agents/ 7 个智能体      │
│  ├ proxy.py 审核代理   │ ◀───────────────│  │  (域年级/匹配/关键词/   │
│  ├ question_queue.py  │                 │  │   新标签/查重/纠错/去重) │
│  └ config.py 配置读取  │                 │  ├ tag_library 远程标签库   │
└──────────────────────┘                 │  ├ service 审核/落库       │
管理后台 tag_review.html                  │  └ router /tag-agent/*    │
（预修改+题目标签审核）                      └──────────────────────────┘
```

---

## 三、启动与配置

### 1. 启动 agent-platform（先启动，供识别与审核使用）
```bash
cd E:\象数演易\agent-platform\backend
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 9000
```
验证：`curl http://127.0.0.1:9000/health` → 200

### 2. 启动 xsyy 后端
```bash
cd E:\象数演易\1\xsyy\...\xsyy-edu\backend
python run.py --reload    # 用 hermes venv 运行（backend venv 缺 chromadb）
```

### 3. 环境变量（两端 .env，均为追加项）
| 文件 | 键 | 说明 |
|---|---|---|
| agent-platform `.env` | `GPTSAPI_KEY` | 中转 API 密钥（与 xsyy KIMI_API_KEY 同值） |
| | `GPTSAPI_BASE` | `https://kuaipao.pro/v1` |
| | `GPTSAPI_CHAT_MODEL` | `gpt-5.5` |
| | `TAG_AGENT_REMOTE_DB_URL` | 远程标签库连接串（MySQL） |
| xsyy `.env` | `AGENT_PLATFORM_URL` | agent-platform 地址（默认 `http://127.0.0.1:9000`） |
| | `AGENT_PLATFORM_X_USER_ID` | 代理转发用户标识（dev 模式默认 admin） |
| | `AGENT_PLATFORM_TIMEOUT` | 转发超时（默认 180s） |
| | `TAG_RECOGNITION_ENGINE` | `agent` / `legacy` / `dual`（默认 dual） |

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

## 五、API 一览（agent-platform /tag-agent/*）

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

xsyy 管理后台同路径前缀 `/api/admin/tag-agent/*` 代理转发。

---

## 六、验证与排查

### 冒烟验证（一条命令全链路）
```bash
# 1) agent-platform 健康 + 远程标签库
curl -H "X-User-ID: admin" http://127.0.0.1:9000/tag-agent/framework   # source=database

# 2) 真实识别（约 15-20s，gpt-5.5）
curl -X POST -H "X-User-ID: admin" -H "Content-Type: application/json" \
  -d '{"question":"袋中有红球3个、黄球2个，求摸到黄球的概率"}' \
  http://127.0.0.1:9000/tag-agent/recognize

# 3) 查看待审核提案
curl -H "X-User-ID: admin" "http://127.0.0.1:9000/tag-agent/pending?status=pending"
```

### 常见问题
| 现象 | 排查 |
|---|---|
| 识别返回"缺少 GPTsAPI_KEY" | agent-platform .env 未配置 `GPTSAPI_KEY` |
| `/framework` 显示 `source=json` | `TAG_AGENT_REMOTE_DB_URL` 未生效/连不上（看启动日志） |
| 审核页提示"无法连接智能体平台" | agent-platform（9000）未启动 |
| 识别慢（16s+/题） | 中转模型延迟，属正常；成本走阶段六监控 |
| 识别质量偏差（如年级判错） | 属持续优化范畴：调整 prompt/同义词/混淆规则，审核结果反哺 |

---

## 七、目录说明

```
backend/tag_agent/            # xsyy 侧智能体接入（独立模块，不与业务代码混放）
├── __init__.py
├── config.py                 # 读取 .env 配置（URL/用户/超时/引擎开关）
├── client.py                 # 识别客户端（调 /recognize，失败降级 legacy）
├── compat.py                 # agent 结果 → xsyy knowledge_tags 结构映射
├── proxy.py                  # 管理后台审核页代理转发
└── question_queue.py         # 题目审核结果应用（写 teachings）

E:\象数演易\agent-platform\backend\app\tag_agent\   # 智能体本体
├── orchestrator.py           # 三场景编排 + 纠错/去重入口
├── agents/                   # 7 个智能体（base/域年级/匹配/关键词/新标签/查重/纠错/去重）
├── tag_library.py            # 远程标签库加载（MySQL knowledge_tag_framework）
├── service.py                # 审核应用（增/改/删/合并）+ 批量 + 题目队列 + 去重落库
├── models.py                 # pending 队列 / 题目队列 / 学习记录 / 识别日志 表
└── router.py                 # /tag-agent/* API
```

> 历史说明：xsyy 旧体系的「识别日志/评测/纠错台」功能已按需求删除（数据备份于 `E:\象数演易\备份_识别日志纠错表_2026-08-28\`），新体系由上述审核队列与学习记录替代。
