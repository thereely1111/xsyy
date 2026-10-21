"""SQLAlchemy 数据库模型定义"""

from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, BigInteger, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from database.database import Base


class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    user_id = Column(String(36), primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    phone = Column(String(11), unique=True, nullable=True, index=True)
    email = Column(String(100), unique=True, nullable=True, index=True)  # 邮箱
    password_hash = Column(String(64), nullable=False)
    grade = Column(String(10), nullable=True)  # 所在年级
    signature = Column(Text, nullable=True)  # 个性签名
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reset_token = Column(String(255), nullable=True)
    reset_token_expiry = Column(DateTime, nullable=True)
    daily_max_calls = Column(Integer, default=3, nullable=False)  # 每日最大调用次数（可修改）
    daily_calls_count = Column(Integer, default=0, nullable=False)  # 当天已调用次数
    last_call_date = Column(DateTime, nullable=True)  # 最后调用日期（用于重置计数）
    invite_code = Column(String(8), unique=True, nullable=True, index=True)  # 专属邀请码：4位大写字母+4位数字
    first_login_reward_granted = Column(Boolean, default=False, nullable=False)  # 首次登录赠送是否已发放
    paid_once = Column(Boolean, default=False, nullable=False)  # 是否已付费（首次订阅审批通过后置 1，作为「已付费邀请人」佣金资格）
    ip_address = Column(String(64), nullable=True)  # 最近一次登录时记录的客户端 IP（每次登录都会刷新）
    current_session_id = Column(String(128), nullable=True, index=True)  # 普通账号当前唯一有效会话
    
    # 关系
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    teaching_likes = relationship("TeachingLike", back_populates="user", cascade="all, delete-orphan")
    comment_likes = relationship("CommentLike", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    teachings = relationship("Teaching", back_populates="user", cascade="all, delete-orphan", foreign_keys="Teaching.user_id")
    view_history = relationship("UserViewHistory", back_populates="user", cascade="all, delete-orphan")
    topics = relationship("Topic", back_populates="user", cascade="all, delete-orphan")
    ai_teaching_qas = relationship("AITeachingQA", back_populates="user", cascade="all, delete-orphan")
    recharge_requests = relationship("RechargeRequest", back_populates="user", cascade="all, delete-orphan")
    withdrawal_requests = relationship("WithdrawalRequest", back_populates="user", cascade="all, delete-orphan")


class VerificationCode(Base):
    """验证码表（临时数据）"""
    __tablename__ = "verification_codes"
    
    phone = Column(String(11), primary_key=True)
    code = Column(String(6), nullable=False)
    expiry = Column(DateTime, nullable=False, index=True)


class DeviceBinding(Base):
    """设备与账号绑定表：一个设备只能绑定一个账号"""
    __tablename__ = "device_bindings"

    device_id = Column(String(128), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserQuota(Base):
    """用户配额表：登录用户每日免费次数 + 赠送额度聚合（明细见 quota_grants 批次账本）"""
    __tablename__ = "user_quotas"

    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    daily_free_used = Column(Integer, default=0, nullable=False)
    extra_balance = Column(Integer, default=0, nullable=False)  # 赠送额度聚合值（= quota_grants.remaining 之和）
    last_reset_date = Column(String(10), nullable=False, default=lambda: datetime.utcnow().date().isoformat())
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class QuotaGrant(Base):
    """赠送额度批次账本：支持分批到期（有效期）、月上限、溯源；消费按 expire_at 先后（FIFO）扣减。"""
    __tablename__ = "quota_grants"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    grant_type = Column(String(32), nullable=False)          # new_user_gift / invited_extra / invite_reward / admin
    amount = Column(Integer, default=0, nullable=False)      # 发放次数
    remaining = Column(Integer, default=0, nullable=False)   # 剩余可扣次数
    expire_at = Column(DateTime, nullable=True)              # 到期时间；NULL=长期（人工补发）
    source_user_id = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True)  # 邀请场景=被邀请人 user_id
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class RechargeRequest(Base):
    """充值申请记录表"""
    __tablename__ = "recharge_requests"

    request_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    note = Column(Text, nullable=True)
    admin_note = Column(Text, nullable=True)
    processed_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="recharge_requests")


class DeviceQuota(Base):
    """设备配额表：未登录设备每日免费次数"""
    __tablename__ = "device_quotas"

    device_id = Column(String(128), primary_key=True)
    daily_free_used = Column(Integer, default=0, nullable=False)
    last_reset_date = Column(String(10), nullable=False, default=lambda: datetime.utcnow().date().isoformat())
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class InviteProgress(Base):
    """邀请进度表：记录邀请人数和里程碑领取状态"""
    __tablename__ = "invite_progress"

    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    invited_count = Column(Integer, default=0, nullable=False)
    claimed_targets = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class InviteRelation(Base):
    """邀请关系表：防止重复邀请计数"""
    __tablename__ = "invite_relations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inviter_user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    invited_user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    invited_device_id = Column(String(128), nullable=False, index=True)  # 允许同一设备注册多个账号，不做唯一约束
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class OfficialInviteCode(Base):
    """官方邀请码表：由管理员在后台创建/管理，注册时须命中此表（启用中）或用户专属邀请码。

    与用户专属邀请码（users.invite_code，4位大写字母+4位数字）不同，官方码格式自由、
    可重复使用、可随时启停，便于对外统一发放与回收。
    """
    __tablename__ = "official_invite_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(16), unique=True, nullable=False, index=True)  # 官方邀请码（如 XSYY2026）
    is_active = Column(Boolean, default=True, nullable=False, index=True)  # 是否启用
    description = Column(String(255), nullable=True)  # 备注/用途
    created_by = Column(String(50), nullable=True)  # 创建人（管理员用户名）
    used_count = Column(Integer, default=0, nullable=False)  # 累计使用次数
    last_used_at = Column(DateTime, nullable=True)  # 最近使用时间
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CommissionAccount(Base):
    """返利账户表：每个用户累计返利、已提现、提现中金额（单位：分）"""
    __tablename__ = "commission_accounts"

    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    total_reward = Column(Integer, default=0, nullable=False)      # 累计返利总额（分）
    withdrawn_amount = Column(Integer, default=0, nullable=False)  # 已提现金额（分）
    pending_amount = Column(Integer, default=0, nullable=False)    # 提现中金额（分，已申请待审核）
    frozen_amount = Column(Integer, default=0, nullable=False)    # 冻结中金额（分，T+N 解冻前不可提现）
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class CommissionRecord(Base):
    """返利分配记录表：记录每笔返利的来源与分配去向（可溯源）"""
    __tablename__ = "commission_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)   # 触发返利的新注册用户
    recipient_user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True) # 获得返利的用户
    inviter_user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)   # 直接邀请者（记录时冗余保存）
    level = Column(Integer, nullable=False, default=1)          # 层级：固定为 1（单级返佣，仅直接邀请人）
    order_id = Column(String(36), nullable=True, index=True)    # 来源订单 recharge_requests.request_id
    amount = Column(Integer, nullable=False, default=0)         # 返利金额（分）
    plan = Column(String(20), nullable=True)                   # monthly / quarterly / yearly
    order_type = Column(String(16), nullable=True)             # first 首单 / renewal 续费
    status = Column(String(20), nullable=False, default="available")  # frozen / available / withdrawn
    freeze_until = Column(DateTime, nullable=True)             # 解冻时间（status=frozen 时生效）
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class WithdrawalRequest(Base):
    """返利提现申请记录表"""
    __tablename__ = "withdrawal_requests"

    request_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Integer, nullable=False)                     # 提现金额（分）
    status = Column(String(20), nullable=False, default="pending")  # pending / approved / rejected
    note = Column(Text, nullable=True)
    admin_note = Column(Text, nullable=True)
    processed_by = Column(String(50), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="withdrawal_requests")


class SystemConfig(Base):
    """系统配置表（键值对）：返利份数、赠送额度等，支持后台实时修改生效"""
    __tablename__ = "system_configs"

    config_key = Column(String(64), primary_key=True)
    config_value = Column(Text, nullable=False)  # 存 JSON（如 user_subscriptions 会随订阅用户增长，需用 TEXT）
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConfigChangeLog(Base):
    """系统配置修改日志表：记录每次配置变更，便于追溯"""
    __tablename__ = "config_change_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(64), nullable=False, index=True)
    # 配置值可能是较长 JSON（首页公告 4 态、订阅价格、返佣规则、里程碑等），
    # 必须用 TEXT，否则写入超 255 字的值会触发 MySQL Data too long -> HTTP 500。
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=False)
    operator = Column(String(50), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class Teaching(Base):
    """教学内容表"""
    __tablename__ = "teachings"
    
    task_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    prompt = Column(Text, nullable=True)
    title = Column(String(100), nullable=True)
    is_math_problem = Column(Boolean, default=True, nullable=False)
    has_pic = Column(Boolean, default=False, nullable=False)  # 是否包含图片输入
    main_tag = Column(String(50), nullable=True, index=True)
    sub_tags = Column(JSON, nullable=True)  # MySQL 5.7+ 支持 JSON 类型
    reasoning = Column(String(200), nullable=True)
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    input_file = Column(String(500), nullable=True)
    teaching_html_file = Column(String(100), nullable=False, default="teaching.html")
    preview_image = Column(String(100), nullable=True)
    view_count = Column(Integer, default=0, nullable=False)  # 观看次数
    is_pinned = Column(Boolean, default=False, nullable=False, index=True)
    topic_id = Column(String(36), ForeignKey("topics.topic_id", ondelete="SET NULL"), nullable=True, index=True)
    # 知识点标签（新标签体系：version, grade, main_tag, sub_tags）
    knowledge_tags = Column(JSON, nullable=True)
    # 第二标签组（多知识点题目，与主标签组知识域不同；结构同 knowledge_tags，可空）
    second_tag = Column(JSON, nullable=True)
    # 注意：embedding 向量存储在 Chroma 向量数据库中，不再存储在 MySQL
    
    # 关系
    comments = relationship("Comment", back_populates="teaching", cascade="all, delete-orphan")
    teaching_likes = relationship("TeachingLike", back_populates="teaching", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="teaching", cascade="all, delete-orphan")
    view_history = relationship("UserViewHistory", back_populates="teaching", cascade="all, delete-orphan")
    user = relationship("User", back_populates="teachings", foreign_keys=[user_id])
    topic = relationship("Topic", back_populates="teachings")


class Comment(Base):
    """评论表"""
    __tablename__ = "comments"
    
    comment_id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("teachings.task_id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    username = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    likes = Column(Integer, default=0, nullable=False)
    parent_id = Column(String(36), ForeignKey("comments.comment_id", ondelete="CASCADE"), nullable=True, index=True)
    
    # 关系
    teaching = relationship("Teaching", back_populates="comments")
    user = relationship("User", back_populates="comments")
    parent = relationship("Comment", remote_side=[comment_id], back_populates="replies")
    replies = relationship("Comment", back_populates="parent", cascade="all, delete-orphan")
    comment_likes = relationship("CommentLike", back_populates="comment", cascade="all, delete-orphan")


class CommentLike(Base):
    """评论点赞关系表"""
    __tablename__ = "comment_likes"
    
    comment_id = Column(String(36), ForeignKey("comments.comment_id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True, index=True)
    
    # 关系
    comment = relationship("Comment", back_populates="comment_likes")
    user = relationship("User", back_populates="comment_likes")


class TeachingLike(Base):
    """教学内容点赞关系表"""
    __tablename__ = "teaching_likes"
    
    task_id = Column(String(36), ForeignKey("teachings.task_id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True, index=True)
    
    # 关系
    teaching = relationship("Teaching", back_populates="teaching_likes")
    user = relationship("User", back_populates="teaching_likes")


class Favorite(Base):
    """用户收藏表"""
    __tablename__ = "favorites"
    
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True, index=True)
    task_id = Column(String(36), ForeignKey("teachings.task_id", ondelete="CASCADE"), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # 关系
    user = relationship("User", back_populates="favorites")
    teaching = relationship("Teaching", back_populates="favorites")


class UserViewHistory(Base):
    """用户浏览记录表"""
    __tablename__ = "user_view_history"
    
    view_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("teachings.task_id", ondelete="CASCADE"), nullable=False, index=True)
    viewed_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    view_count = Column(Integer, default=1, nullable=False)  # 同一用户对同一内容的浏览次数
    
    # 关系
    user = relationship("User", back_populates="view_history")
    teaching = relationship("Teaching", back_populates="view_history")


class Topic(Base):
    """用户专题表"""
    __tablename__ = "topics"
    
    topic_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)  # 专题名称
    description = Column(Text, nullable=True)  # 专题描述（可选）
    is_default = Column(Boolean, default=False, nullable=False)  # 是否为默认专题
    share_token = Column(String(64), nullable=True, unique=True, index=True)  # 分享令牌
    is_shared = Column(Boolean, default=False, nullable=False)  # 是否已分享
    share_expires_at = Column(DateTime, nullable=True)  # 分享过期时间
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    user = relationship("User", back_populates="topics")
    teachings = relationship("Teaching", back_populates="topic", cascade="all, delete-orphan")


class AITeachingSession(Base):
    """AI 教学会话摘要缓存表"""
    __tablename__ = "ai_teaching_session"

    session_hash = Column(String(64), primary_key=True)
    page_id = Column(String(128), nullable=False, index=True)
    content_full_hash = Column(String(64), nullable=False, index=True)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    qas = relationship("AITeachingQA", back_populates="session", cascade="all, delete-orphan")


class AITeachingQA(Base):
    """AI 教学问答缓存表"""
    __tablename__ = "ai_teaching_qa"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_hash = Column(String(64), ForeignKey("ai_teaching_session.session_hash", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False, index=True)
    question_hash = Column(String(64), nullable=False, index=True)
    question_text = Column(Text, nullable=False)
    answer_summary = Column(Text, nullable=False)
    full_qa_data = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    session = relationship("AITeachingSession", back_populates="qas")
    user = relationship("User", back_populates="ai_teaching_qas")


class KnowledgeTagFramework(Base):
    """知识点标签框架表（知识域→年级→章/单元→知识点标签，附强特征关键词）"""
    __tablename__ = "knowledge_tag_framework"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version = Column(String(50), nullable=False, index=True)  # 知识域（数与式/方程与不等式/函数/图形与几何/统计与概率）
    grade = Column(String(10), nullable=False, index=True)    # 年级
    main_tag = Column(String(100), nullable=False, index=True)  # 章/单元
    sub_tag = Column(String(100), nullable=False, index=True)  # 知识点标签（模块级）
    keyword = Column(String(500), nullable=True)  # 强特征关键词（仅作大模型判断依据，不作为题目属性）
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class UserFeedback(Base):
    """用户问题反馈表"""
    __tablename__ = "user_feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)
    user_name = Column(String(50), nullable=False, default="")
    description = Column(Text, nullable=False)
    images = Column(JSON, nullable=False, default=list)  # base64 图片列表（后续建议改存文件/对象存储）
    page_url = Column(String(500), nullable=False, default="")
    page_title = Column(String(255), nullable=False, default="")
    status = Column(String(20), nullable=False, default="new", index=True)  # new/in_progress/resolved/ignored
    handled_by = Column(String(50), nullable=False, default="")
    admin_note = Column(Text, nullable=True)  # 管理员留言（向用户说明处理情况）
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    handled_at = Column(DateTime, nullable=True)


class WebsiteLog(Base):
    """网站日志表：集中记录网站运行过程中产生的所有报错与异常信息。

    覆盖场景：
    - 动画生成失败的具体原因（category=animation_generation, level=ERROR）
    - 动画生成过程中的轻微异常 / 小问题（category=animation_generation, level=WARN）
    - 服务端未捕获的 5xx 错误（category=server_error）
    - 前端页面运行期报错（category=client_page，由 /api/logs/client 上报）
    字段设计以"便于排查与追溯"为目标，完整保留触发用户与上下文。
    """
    __tablename__ = "website_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)  # 发生时间
    level = Column(String(20), nullable=False, default="ERROR", index=True)  # ERROR / WARN / INFO
    category = Column(String(50), nullable=False, default="system", index=True)  # animation_generation / server_error / client_page / system / api
    message = Column(Text, nullable=False)  # 报错具体原因 / 描述
    # 触发问题的用户标识
    user_id = Column(String(36), nullable=True, index=True)
    username = Column(String(50), nullable=False, default="")
    # 关联对象
    task_id = Column(String(36), nullable=True, index=True)  # 关联的动画生成任务
    trace_id = Column(String(36), nullable=True, index=True)  # 统一链路 ID：与 task_id 1:1（前端/后端/流水线全程透传）
    # 结构化事件字段（事件字典，见 website_log.py 的 EVENT_* / STAGE_* / ERROR_TYPE_* 常量）
    event = Column(String(50), nullable=False, default="", index=True)  # 事件名，如 task_created / preview_generation_failed
    stage = Column(String(50), nullable=False, default="")  # 阶段名，如 home_submit / pipeline / video_page_polling
    error_type = Column(String(50), nullable=False, default="")  # 错误大类，如 third_party_http_error / resource_load_error
    # 上下文：页面 / 设备 / 请求
    page_url = Column(String(500), nullable=False, default="")  # 触发页面 URL（含 referer）
    page_title = Column(String(255), nullable=False, default="")
    device = Column(String(255), nullable=False, default="")  # 设备 / 浏览器 UA
    request_method = Column(String(10), nullable=False, default="")
    request_path = Column(String(500), nullable=False, default="")
    request_params = Column(JSON, nullable=True)  # 请求参数（如 prompt 摘要）
    error_code = Column(String(50), nullable=False, default="")
    stack_trace = Column(Text, nullable=True)  # 异常堆栈
    context = Column(JSON, nullable=True)  # 其他相关上下文详情


class Announcement(Base):
    """管理员发布的公告（对接前端系统消息模块）"""
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False, default="")  # 公告标题（可选）
    content = Column(Text, nullable=False)  # 公告正文
    image_url = Column(String(512), nullable=True)  # 公告配图（相对 /web 的路径）
    is_published = Column(Boolean, nullable=False, default=True)
    is_pinned = Column(Boolean, nullable=False, default=False, index=True)  # 是否置顶
    # 首页公告条展示开关；同一时间只允许一条已发布的系统公告开启。
    is_home_banner = Column(Boolean, nullable=False, default=False, index=True)
    published_by = Column(String(50), nullable=False, default="")  # 发布人用户名
    category = Column(String(20), nullable=False, default="system", index=True)  # 公告分类：system=系统公告 / activity=活动公告
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

class Notification(Base):
    """用户通知（互动通知 / 活动通知 / 系统通知）。

    - interaction：自己生成的案例或评论被点赞、评论、回复时通知本人
    - activity：管理员发布的活动公告（广播给所有用户）
    - system：系统类通知，如账号被封禁
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), nullable=False, index=True)  # 接收通知的用户
    category = Column(String(20), nullable=False, default="system", index=True)  # interaction / activity / system
    title = Column(String(255), nullable=False, default="")  # 通知标题
    content = Column(Text, nullable=False, default="")  # 通知正文
    target_url = Column(String(512), nullable=True)  # 点击跳转的详情地址（如 video.html?task_id=...）
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    extra = Column(JSON, nullable=True)  # 其他上下文：{actor_id, actor_name, task_id, comment_id}
    source_type = Column(String(50), nullable=False, default="system")  # 通知来源类型（interaction / activity / system）
    source_id = Column(String(64), nullable=False, default="")  # 通知来源 ID（如 task_id、comment_id）


class TaskStatus(Base):
    """生成任务状态表：任务状态跨进程持久化。

    背景：公网部署 uvicorn --workers N（多进程）时，任务状态字典 tasks 只存在于
    创建任务的 worker 进程内存中，其他 worker 轮询 /api/tasks/{task_id} 会返回
    not_found，导致前端误报"任务不存在或已过期"。此表把任务状态落库，
    供任意 worker 跨进程读取，任务完成/失败后由 Teaching 表接管。
    """
    __tablename__ = "task_status"

    task_id = Column(String(64), primary_key=True)
    status = Column(String(32), nullable=False, default="pending", index=True)
    progress = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    video_url = Column(String(512), nullable=True)
    preview_image = Column(String(512), nullable=True)
    metadata_json = Column(JSON, nullable=True)  # 任务元数据（剔除 teaching_html，避免超大字段）
    user_id = Column(String(64), nullable=True, index=True)
    topic_id = Column(String(64), nullable=True)
    prompt = Column(Text, nullable=True)
    input_file = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

