# 专题分享功能迁移说明

## 概述

本次更新为专题功能添加了分享能力，允许老师将专题分享给家长查看。

## 数据库变更

在 `topics` 表中添加了以下字段：

1. **share_token** (VARCHAR(64), NULL, UNIQUE)
   - 分享令牌，用于生成分享链接
   - 唯一索引，确保每个分享链接唯一

2. **is_shared** (BOOLEAN, DEFAULT FALSE, NOT NULL)
   - 标识专题是否已分享
   - 默认值为 FALSE

3. **share_expires_at** (DATETIME, NULL)
   - 分享过期时间
   - 可选字段，NULL 表示永久有效

## 迁移步骤

### 方法1：使用 Python 脚本（推荐）

```bash
cd backend/database
python add_topic_share_fields.py
```

### 方法2：使用 SQL 脚本

```bash
mysql -u your_username -p your_database < add_topic_share_fields.sql
```

## 验证迁移

迁移完成后，可以执行以下 SQL 验证：

```sql
DESCRIBE topics;
```

应该能看到新增的三个字段：
- `share_token`
- `is_shared`
- `share_expires_at`

## API 接口

### 1. 生成分享链接
```
POST /api/topics/{topic_id}/share
需要认证：是
请求体：{ "expires_days": null }  // null 表示永久有效
返回：{ "share_token": "...", "share_url": "...", "expires_at": null }
```

### 2. 获取分享的专题（公开访问）
```
GET /api/topics/shared/{share_token}
需要认证：否
返回：专题信息和教学内容列表
```

### 3. 取消分享
```
DELETE /api/topics/{topic_id}/share
需要认证：是
返回：{ "message": "分享已取消" }
```

### 4. 获取分享状态
```
GET /api/topics/{topic_id}/share-status
需要认证：是
返回：{ "is_shared": true, "share_url": "...", "expires_at": null }
```

## 前端功能

1. **专题菜单**：在专题卡片右上角菜单中添加了"分享"选项
2. **分享弹窗**：点击分享后显示弹窗，包含：
   - 分享链接（可复制）
   - 二维码（方便手机扫码）
   - 取消分享按钮
3. **分享页面**：`share_topic.html` - 家长查看页面，无需登录

## 使用流程

1. 老师在"我的专题"中点击专题卡片右上角的"···"
2. 选择"分享"选项
3. 系统自动生成分享链接和二维码
4. 老师可以复制链接或让家长扫码
5. 家长打开链接后可以看到专题的所有教学内容
6. 点击教学内容卡片可以查看详细讲解

## 注意事项

1. 分享链接使用安全的随机令牌生成，难以猜测
2. 可以随时取消分享，取消后链接立即失效
3. 支持设置过期时间（可选）
4. 分享页面无需登录，任何人都可以通过链接访问
5. 分享的内容是只读的，家长无法编辑或删除

## 回滚

如果需要回滚，可以执行以下 SQL：

```sql
ALTER TABLE topics
DROP COLUMN share_token,
DROP COLUMN is_shared,
DROP COLUMN share_expires_at;
```

注意：回滚前请确保已取消所有分享，避免数据不一致。
