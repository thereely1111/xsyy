# XSYY 项目测试文档

## 测试结构

```
tests/
├── unit/              # 单元测试
├── integration/       # 集成测试
├── e2e/              # 端到端测试
├── performance/      # 性能测试
├── fixtures/         # 测试数据
└── utils/            # 测试工具
```

## 运行测试

### 快速测试（上线前必须通过）

```bash
cd backend
python test_quick.py
```

### 运行所有测试

```bash
cd backend
python test_all.py
```

### 运行特定测试模块

```bash
# 运行健康检查测试
pytest tests/integration/test_api_health.py -v

# 运行认证测试
pytest tests/integration/test_api_auth.py -v

# 运行任务测试
pytest tests/integration/test_api_tasks.py -v

# 运行管理后台测试
pytest tests/integration/test_api_admin.py -v
```

### 运行测试并生成覆盖率报告

```bash
pytest tests/ --cov=. --cov-report=html
```

覆盖率报告会生成在 `htmlcov/index.html`

## 测试优先级

### P0 - 核心功能（必须通过）
- ✅ 健康检查
- ✅ 用户认证（注册、登录）
- ✅ 任务创建和状态查询

### P1 - 重要功能（建议通过）
- ⚠️ 教学内容管理
- ⚠️ 管理后台功能

### P2 - 辅助功能（可选）
- 📝 性能测试
- 📝 边界情况测试

## 测试配置

### 环境变量

测试使用独立的测试数据库，通过环境变量配置：

```bash
export TEST_DATABASE_URL="mysql+pymysql://root:password@localhost/xsyy_test?charset=utf8mb4"
export TEST_MODE=1
```

### 测试数据库

测试会自动创建和清理测试数据库，确保测试隔离。

## 注意事项

1. **测试模式**: 测试时自动启用 `TEST_MODE=1`，不会调用真实的 LLM API
2. **数据隔离**: 每个测试使用独立的数据库会话，测试结束后自动回滚
3. **Token 管理**: 测试会自动创建测试用户和管理员，并生成有效的 token

## 添加新测试

1. 在对应的测试目录创建测试文件
2. 使用 `test_client` fixture 进行 API 测试
3. 使用 `auth_token` 或 `admin_token` fixture 进行认证测试
4. 遵循 pytest 命名规范：测试函数以 `test_` 开头

## 故障排查

### 测试数据库连接失败

检查 `TEST_DATABASE_URL` 环境变量是否正确配置。

### 测试失败但功能正常

可能是测试数据问题，检查 fixtures 和测试数据。

### 测试运行缓慢

检查是否启用了 `TEST_MODE=1`，避免调用真实 API。

