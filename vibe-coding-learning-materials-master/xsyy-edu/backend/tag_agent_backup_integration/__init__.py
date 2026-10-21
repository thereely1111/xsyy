# -*- coding: utf-8 -*-
"""xsyy 侧智能体接入模块（独立文件夹，不与其他代码混放，便于定位与修复）.

约定（方案 §3.2）：
- client.py    — HTTP 客户端（阶段三接入识别时使用）
- config.py    — 读取 .env 的 TAG_AGENT_* / AGENT_PLATFORM_* 配置
- proxy.py     — 管理后台审核页代理：/api/admin/tag-agent/* → agent-platform /tag-agent/*
- compat.py    — 结果结构兼容层（阶段三）
- question_queue.py — 题目标签审核队列应用（阶段三）
"""
