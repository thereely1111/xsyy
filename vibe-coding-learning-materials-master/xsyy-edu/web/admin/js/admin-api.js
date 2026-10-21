/**
 * 管理后台 API 调用封装
 */

// 管理后台与当前页面使用同源地址，支持 http://127.0.0.1:8000/admin/index.html
const API_BASE = window.location.protocol === 'file:'
    ? 'http://127.0.0.1:8000'
    : window.location.origin;

// 调试：输出 API_BASE 配置
console.log('管理后台 API_BASE:', API_BASE);
console.log('当前页面地址:', window.location.href);

/**
 * 获取认证 token
 */
function getToken() {
    return localStorage.getItem('auth_token');
}

/**
 * 设置认证 token
 */
function setToken(token) {
    localStorage.setItem('auth_token', token);
}

/**
 * 移除认证 token
 */
function removeToken() {
    localStorage.removeItem('auth_token');
}

/**
 * 通用 API 请求函数
 */
async function apiRequest(url, options = {}) {
    const token = getToken();
    
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };
    
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    
    try {
        const fullUrl = `${API_BASE}${url}`;
        console.log('API请求:', fullUrl, options.method || 'GET');
        
        const response = await fetch(fullUrl, {
            ...options,
            headers
        });
        
        // 检查响应状态
        if (!response.ok) {
            let errorMessage = `HTTP ${response.status}`;
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch (e) {
                // 如果响应不是 JSON，尝试读取文本
                try {
                    const text = await response.text();
                    errorMessage = text || errorMessage;
                } catch (e2) {
                    // 忽略
                }
            }
            throw new Error(errorMessage);
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('API请求失败:', error);
        // 如果是网络错误，提供更友好的提示
        if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
            throw new Error('无法连接到服务器，请检查后端服务是否运行在 http://127.0.0.1:8000');
        }
        throw error;
    }
}

/**
 * 检查是否为管理员
 */
async function checkAdmin() {
    return await apiRequest('/api/admin/check');
}

/**
 * 读取管理员实时日志 SSE 流（旧版实时流，结构化日志请使用 getWebsiteLogs）。
 * 使用 fetch 保留 Bearer token，避免把认证信息放进 URL。
 */
async function streamAdminLogs(onEvent, options = {}) {
    const token = getToken();
    const response = await fetch(`${API_BASE}/api/admin/logs/stream`, {
        headers: {
            'Accept': 'text/event-stream',
            ...(token ? { 'Authorization': `Bearer ${token}` } : {})
        },
        signal: options.signal
    });

    if (!response.ok || !response.body) {
        throw new Error(`日志流连接失败：HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const messages = buffer.split(/\r?\n\r?\n/);
            buffer = messages.pop() || '';

            for (const message of messages) {
                const data = message.split(/\r?\n/)
                    .filter(line => line.startsWith('data:'))
                    .map(line => line.slice(5).trim())
                    .join('\n');
                if (!data) continue;
                try {
                    onEvent(JSON.parse(data));
                } catch (error) {
                    console.warn('日志事件解析失败:', error);
                }
            }
        }
    } finally {
        reader.releaseLock();
    }
}

/**
 * 获取教学内容列表
 */
async function getTeachings(params = {}) {
    const queryParams = new URLSearchParams();
    if (params.page) queryParams.append('page', params.page);
    if (params.page_size) queryParams.append('page_size', params.page_size);
    if (params.search) queryParams.append('search', params.search);
    if (params.user_id) queryParams.append('user_id', params.user_id);
    if (params.main_tag) queryParams.append('main_tag', params.main_tag);
    if (params.version) queryParams.append('version', params.version);
    if (params.grade) queryParams.append('grade', params.grade);
    if (params.sort_by) queryParams.append('sort_by', params.sort_by);
    if (params.sort_order) queryParams.append('sort_order', params.sort_order);

    return await apiRequest(`/api/admin/teachings?${queryParams.toString()}`);
}

/**
 * 获取教学内容详情
 */
async function getTeachingDetail(taskId) {
    return await apiRequest(`/api/admin/teachings/${taskId}`);
}

async function toggleTeachingPin(taskId, pinned) {
    return await apiRequest(`/api/admin/teachings/${taskId}/pin`, {
        method: 'POST',
        body: JSON.stringify({ pinned })
    });
}

async function getTeachingPins() {
    return await apiRequest('/api/admin/teachings/pins');
}

async function getTeachingPinItems() {
    return await apiRequest('/api/admin/teachings/pins');
}

async function updateTeachingPinLimit(limit) {
    return await apiRequest('/api/admin/teachings/pin-limit', {
        method: 'PUT',
        body: JSON.stringify({ limit })
    });
}

/**
 * 删除教学内容
 */
async function deleteTeaching(taskId) {
    return await apiRequest(`/api/admin/teachings/${taskId}`, {
        method: 'DELETE'
    });
}

/**
 * 获取用户列表
 */
async function getUsers(params = {}) {
    const queryParams = new URLSearchParams();
    if (params.page) queryParams.append('page', params.page);
    if (params.page_size) queryParams.append('page_size', params.page_size);
    if (params.search) queryParams.append('search', params.search);
    
    return await apiRequest(`/api/admin/users?${queryParams.toString()}`);
}

/**
 * 获取用户详情
 */
async function getUserDetail(userId) {
    return await apiRequest(`/api/admin/users/${userId}`);
}

/**
 * 更新用户信息
 */
async function updateUser(userId, data) {
    const queryParams = new URLSearchParams();
    if (data.extra_balance !== undefined) {
        queryParams.append('extra_balance', data.extra_balance);
    }
    if (data.add_balance !== undefined) {
        queryParams.append('add_balance', data.add_balance);
    }

    return await apiRequest(`/api/admin/users/${userId}?${queryParams.toString()}`, {
        method: 'PUT'
    });
}

/**
 * 获取用户账号信息
 */
async function getUserAccount(userId) {
    return await apiRequest(`/api/admin/users/${userId}/account`);
}

/**
 * 初始化用户密码
 */
async function resetUserPassword(userId) {
    return await apiRequest(`/api/admin/users/${userId}/reset-password`, {
        method: 'PUT'
    });
}

/**
 * 封禁用户（banUntil: ISO 时间字符串 或 "permanent"；传 null 表示解封）
 */
async function banUser(userId, banUntil) {
    return await apiRequest(`/api/admin/users/${userId}/ban`, {
        method: 'PUT',
        body: JSON.stringify({ ban_until: banUntil })
    });
}

/**
 * 彻底删除用户账号
 */
async function deleteUser(userId) {
    return await apiRequest(`/api/admin/users/${userId}`, {
        method: 'DELETE'
    });
}

/**
 * 获取用户返利数据（汇总 + 明细 + 提现记录）
 */
async function getCommission(userId) {
    return await apiRequest(`/api/admin/commission/${userId}`);
}

/**
 * 编辑用户返利数据（单位：分）
 * 支持 set_total_reward / set_withdrawn_amount / set_pending_amount / add_*
 */
async function updateCommission(userId, data) {
    return await apiRequest(`/api/admin/commission/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

/**
 * 处理返利提现申请
 */
async function processCommissionWithdrawal(requestId, action, admin_note) {
    return await apiRequest(`/api/admin/commission/withdrawals/${requestId}`, {
        method: 'PUT',
        body: JSON.stringify({ action, admin_note })
    });
}

/**
 * 获取统计数据
 */
async function getStatistics() {
    return await apiRequest('/api/admin/statistics');
}

/**
 * 获取充值订单列表
 */
async function getRechargeOrders(params = {}) {
    const queryParams = new URLSearchParams();
    if (params.page) queryParams.append('page', params.page);
    if (params.page_size) queryParams.append('page_size', params.page_size);
    if (params.status) queryParams.append('status', params.status);
    return await apiRequest(`/api/admin/recharge-orders?${queryParams.toString()}`);
}

/**
 * 获取订单管理列表（充值 / 订阅 / 提现）
 */
async function getOrders(params = {}) {
    const queryParams = new URLSearchParams();
    if (params.page) queryParams.append('page', params.page);
    if (params.page_size) queryParams.append('page_size', params.page_size);
    if (params.status) queryParams.append('status', params.status);
    if (params.order_type) queryParams.append('order_type', params.order_type);
    return await apiRequest(`/api/admin/orders?${queryParams.toString()}`);
}

/**
 * 处理充值订单
 */
async function processRechargeOrder(requestId, action, admin_note) {
    return await apiRequest(`/api/admin/recharge-orders/${requestId}`, {
        method: 'PUT',
        body: JSON.stringify({ action, admin_note })
    });
}

/**
 * 获取系统配置
 */
async function getConfig() {
    return await apiRequest('/api/admin/config');
}

/**
 * 更新系统配置（数据库配置实时生效）
 * 支持字段：邀请返利活动总控（invite_activity_enabled / invite_commission_enabled）、
 *          赠送与邀请额度（new_user_gift_quota 等 7 键）、返佣规则（commission_first_fen 等 4 键）、
 *          提现规则（withdraw_min_fen / withdraw_monthly_times）、里程碑（invite_milestones）、套餐价格
 */
async function updateConfig(data) {
    const body = {};
    const allowedKeys = [
        // ⓪ 活动总控
        'invite_activity_enabled',
        'invite_commission_enabled',
        // ① 赠送与邀请额度
        'new_user_gift_quota',
        'new_user_gift_valid_days',
        'invited_extra_quota',
        'invited_extra_valid_days',
        'invite_reward_quota',
        'invite_reward_valid_days',
        'invite_reward_monthly_cap',
        // ② 返佣规则
        'commission_first_fen',
        'commission_renewal_pct',
        'commission_inviter_paid',
        'commission_freeze_days',
        // ③ 提现规则
        'withdraw_min_fen',
        'withdraw_monthly_times',
        // ④ 累计邀请里程碑
        'invite_milestones',
        'invite_manual_review_threshold',
        // 套餐价格
        'plan_monthly',
        'plan_quarterly',
        'plan_halfyear',
        'plan_yearly',
        // 首页多态公告文案配置（4 态）
        'home_announcement_states'
    ];
    allowedKeys.forEach(key => {
        if (data[key] !== undefined) {
            body[key] = data[key];
        }
    });

    return await apiRequest('/api/admin/config', {
        method: 'PUT',
        body: JSON.stringify(body)
    });
}

/**
 * 获取用户反馈（优先从后端获取，失败则回退到 localStorage）
 */
async function getFeedbacks(params = {}) {
    try {
        // 尝试调用后端 API
        const query = new URLSearchParams();
        if (params.page) query.append('page', params.page);
        if (params.page_size) query.append('page_size', params.page_size);
        const data = await apiRequest(`/api/admin/feedbacks?${query.toString()}`);
        return data;
    } catch (err) {
        console.warn('调用后端反馈接口失败，回退到 localStorage:', err.message);
        // 回退：从 localStorage 读取 page-enhancements 存储的反馈
        try {
            const raw = localStorage.getItem('xsyy_feedbacks_v1') || '[]';
            const list = JSON.parse(raw);
            return { feedbacks: Array.isArray(list) ? list : [] };
        } catch (e) {
            return { feedbacks: [] };
        }
    }
}

/**
 * 更新反馈状态（后端）
 */
async function apiUpdateFeedback(feedbackId, data) {
    return await apiRequest(`/api/admin/feedbacks/${feedbackId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

/**
 * 删除反馈（后端）
 */
async function apiDeleteFeedback(feedbackId) {
    return await apiRequest(`/api/admin/feedbacks/${feedbackId}`, {
        method: 'DELETE'
    });
}

/**
 * 获取管理后台左侧导航红点计数：未处理订单 / 未处理反馈 / 新增错误日志
 */
async function getNotificationCounts() {
    return await apiRequest('/api/admin/notifications/counts');
}

/**
 * 管理后台查看网站日志后，清零“新增错误日志”红点计数
 */
async function ackWebsiteLogs() {
    return await apiRequest('/api/admin/website-logs/acknowledge', {
        method: 'POST'
    });
}

/**
 * 管理员发布公告（multipart/form-data，含可选图片）
 * 注意：FormData 不能手动设置 Content-Type，交由浏览器自动填充 boundary。
 */
async function publishAnnouncementApi(formData) {
    const token = getToken();
    const headers = {};
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE}/api/admin/announcements`, {
        method: 'POST',
        headers,
        body: formData
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (e) {
            // 忽略解析错误
        }
        throw new Error(message);
    }
    return await response.json();
}

/**
 * 管理员获取全部公告（管理公告模块：置顶 / 删除列表）
 */
async function getAdminAnnouncements() {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE}/api/admin/announcements/all`, { headers });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (e) { /* ignore */ }
        throw new Error(message);
    }
    return await response.json();
}


/**
 * 管理员编辑公告的标题、正文和通知类型。
 */
async function updateAnnouncementApi(id, data) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/api/admin/announcements/${id}`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify(data)
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try { message = (await response.json()).detail || message; } catch (e) { /* ignore */ }
        throw new Error(message);
    }
    return await response.json();
}

/**
 * 设置或撤下首页顶部公告条。
 */
async function setAnnouncementHomeBannerApi(id, enabled) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}/api/admin/announcements/${id}/home-banner`, {
        method: 'PATCH',
        headers,
        body: JSON.stringify({ enabled: !!enabled })
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try { message = (await response.json()).detail || message; } catch (e) { /* ignore */ }
        throw new Error(message);
    }
    return await response.json();
}
/**
 * 管理员置顶 / 取消置顶公告。isPinned 缺省时切换。
 */
async function pinAnnouncementApi(id, isPinned) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const body = (typeof isPinned === 'boolean') ? JSON.stringify({ is_pinned: isPinned }) : '{}';
    const response = await fetch(`${API_BASE}/api/admin/announcements/${id}/pin`, {
        method: 'PATCH',
        headers,
        body
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (e) { /* ignore */ }
        throw new Error(message);
    }
    return await response.json();
}

/**
 * 管理员删除公告
 */
async function deleteAnnouncementApi(id) {
    const token = getToken();
    const headers = {};
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const response = await fetch(`${API_BASE}/api/admin/announcements/${id}`, {
        method: 'DELETE',
        headers
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (e) { /* ignore */ }
        throw new Error(message);
    }
    return await response.json();
}

/**
 * 管理员更新教学内容的标题与题目内容（绕过所有权校验）
 */
async function adminUpdateTeaching(taskId, data) {
    return await apiRequest(`/api/admin/teachings/${taskId}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    });
}

/**
 * 管理员调用生成流水线，基于编辑后的题目内容（可附带纠错信息）原地重新生成动画/解题过程
 */
async function adminRegenerateTeaching(taskId, data) {
    return await apiRequest(`/api/admin/teachings/${taskId}/regenerate`, {
        method: 'POST',
        body: JSON.stringify(data)
    });
}

/**
 * 管理员调用封面生成模型（与首页生成封面同款）重新生成封面 Preview.webp
 */
async function adminRegenerateCover(taskId) {
    return await apiRequest(`/api/admin/teachings/${taskId}/regenerate-cover`, {
        method: 'POST',
        body: JSON.stringify({})
    });
}

/**
 * 管理员调用标签识别模型（与首页流水线同款）重新识别知识点标签。
 * 只返回识别结果，不自动保存，保留手动选择标签能力。
 */
async function adminReidentifyTags(taskId, question, signal) {
    return await apiRequest(`/api/admin/teachings/${taskId}/reidentify-tags`, {
        method: 'POST',
        body: JSON.stringify({ question: question || '' }),
        signal: signal
    });
}

/**
 * 轮询任务生成状态（公开接口，无需鉴权）
 */
async function getTaskStatus(taskId) {
    const fullUrl = `${API_BASE}/api/tasks/${taskId}`;
    const response = await fetch(fullUrl, {
        headers: getToken() ? { 'Authorization': `Bearer ${getToken()}` } : {}
    });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
}

/**
 * 获取网站日志列表（管理员）。
 * 支持筛选：level / category / user_id / search / start_date / end_date，分页 page / page_size。
 */
async function getWebsiteLogs(params = {}) {
    const queryParams = new URLSearchParams();
    ['page', 'page_size', 'level', 'category', 'user_id', 'search', 'start_date', 'end_date'].forEach(key => {
        if (params[key] !== undefined && params[key] !== '' && params[key] !== null) {
            queryParams.append(key, params[key]);
        }
    });
    return await apiRequest(`/api/admin/website-logs?${queryParams.toString()}`);
}

/**
 * 获取单条任务的日志时间线（管理员）。
 * 按 task_id / trace_id 聚合该任务从创建到完成/失败的全部日志，按时间正序。
 */
async function getWebsiteLogTimeline(taskId) {
    if (!taskId) return { logs: [], total: 0 };
    const params = new URLSearchParams({ task_id: taskId });
    return await apiRequest(`/api/admin/website-logs/timeline?${params.toString()}`);
}

/**
 * 删除单条网站日志（管理员）。
 */
async function deleteWebsiteLog(id) {
    return await apiRequest(`/api/admin/website-logs/${id}`, {
        method: 'DELETE'
    });
}

/**
 * 清空全部网站日志（管理员）。需二次确认后调用。
 */
async function clearWebsiteLogs() {
    return await apiRequest('/api/admin/website-logs?confirm=yes', {
        method: 'DELETE'
    });
}

/**
 * 用户登录
 */
async function login(username, password) {
    try {
        const fullUrl = `${API_BASE}/api/auth/login`;
        console.log('登录请求:', fullUrl);
        
        const response = await fetch(fullUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });
        
        // 检查响应状态
        if (!response.ok) {
            let errorMessage = '登录失败';
            try {
                const errorData = await response.json();
                errorMessage = errorData.detail || errorMessage;
            } catch (e) {
                errorMessage = `HTTP ${response.status}: ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }
        
        const data = await response.json();
        
        if (data.token) {
            setToken(data.token);
        }
        
        return data;
    } catch (error) {
        console.error('登录失败:', error);
        // 如果是网络错误，提供更友好的提示
        if (error.message === 'Failed to fetch' || error.name === 'TypeError') {
            throw new Error('无法连接到服务器，请检查后端服务是否运行在 http://127.0.0.1:8000');
        }
        throw error;
    }
}

/**
 * 后台「邀请与额度管理」只读接口封装
 */

/**
 * 单个用户的邀请与额度概览：邀请数 / 累计获得额度 / 本月邀请所得 / 里程碑进度。
 * @param {object} params { user_id }
 */
async function getInviteStats(params = {}) {
    const query = new URLSearchParams();
    if (params.user_id) query.append('user_id', params.user_id);
    return await apiRequest(`/api/admin/invite/stats?${query.toString()}`);
}

/**
 * 全局概览：总邀请人数 / 总发放额度 / 本月新增邀请。
 */
async function getInviteSummary() {
    return await apiRequest('/api/admin/invite/summary');
}

/**
 * 全量邀请关系分页列表（可按用户名 / user_id / 邀请码关键字过滤）。
 * @param {object} params { keyword, page, size }
 */
async function getInviteList(params = {}) {
    const query = new URLSearchParams();
    if (params.keyword) query.append('keyword', params.keyword);
    if (params.page) query.append('page', params.page);
    if (params.size) query.append('size', params.size);
    return await apiRequest(`/api/admin/invite/list?${query.toString()}`);
}

/**
 * 某用户的额度发放明细（按 grant_type 筛选 + 分页）。
 * @param {object} params { user_id, grant_type, page, size }
 */
async function getQuotaGrants(params = {}) {
    const query = new URLSearchParams();
    if (params.user_id) query.append('user_id', params.user_id);
    if (params.grant_type) query.append('grant_type', params.grant_type);
    if (params.page) query.append('page', params.page);
    if (params.size) query.append('size', params.size);
    return await apiRequest(`/api/admin/quota/grants?${query.toString()}`);
}

/**
 * 导出邀请关系 + 额度汇总 CSV（流式下载）。
 * 不能走 apiRequest（响应为二进制流，非 JSON），单独 fetch + blob 处理。
 * @param {object} params { user_id } 传入则只导出该用户的下游邀请关系
 * @returns {Promise<{blob: Blob, filename: string}>}
 */
async function exportInviteCsv(params = {}) {
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const query = new URLSearchParams();
    if (params.user_id) query.append('user_id', params.user_id);

    const response = await fetch(`${API_BASE}/api/admin/invite/export?${query.toString()}`, {
        method: 'GET',
        headers
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (e) { /* ignore */ }
        throw new Error(message);
    }

    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename=([^;]+)/);
    const filename = match ? match[1].trim() : 'invite_quota_export.csv';

    return { blob: await response.blob(), filename };
}

/**
 * 导出某用户的额度发放明细 CSV（流式下载）。
 * @param {object} params { user_id }
 * @returns {Promise<{blob: Blob, filename: string}>}
 */
async function exportQuotaCsv(params = {}) {
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const query = new URLSearchParams();
    if (params.user_id) query.append('user_id', params.user_id);

    const response = await fetch(`${API_BASE}/api/admin/quota/export?${query.toString()}`, {
        method: 'GET',
        headers
    });
    if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
            const data = await response.json();
            message = data.detail || message;
        } catch (e) { /* ignore */ }
        throw new Error(message);
    }

    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename=([^;]+)/);
    const filename = match ? match[1].trim() : 'quota_export.csv';

    return { blob: await response.blob(), filename };
}

