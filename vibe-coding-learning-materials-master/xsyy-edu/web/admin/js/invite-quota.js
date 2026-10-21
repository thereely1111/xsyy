/**
 * 后台「邀请与额度管理」页面逻辑
 * 结构：顶部共享用户查询 + 全局概览/全部邀请记录 + 两个 Tab 子页（邀请关系管理 / 额度管理）
 * 依赖：admin-api.js（getInviteSummary / getInviteList / getInviteStats / getQuotaGrants
 *       / exportInviteCsv / exportQuotaCsv）、admin-auth.js
 */

const GRANT_LABELS = {
    new_user_gift: '注册赠礼',
    invited_extra: '被邀额外',
    invite_reward: '邀请奖励',
    admin: '管理员补发'
};

const STATUS_LABELS = {
    active: '生效中',
    expired: '已过期',
    exhausted: '已用完'
};

const PAGE_SIZE = 20;
const INVITEE_PAGE_SIZE = 20;

let currentUserId = '';
let currentUsername = '';
let currentSearchKey = '';
let currentTab = 'relation';
let inviteePage = 1;
let grantsPage = 1;
let allListPage = 1;
const ALL_LIST_PAGE_SIZE = 20;

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatDateTime(iso) {
    if (!iso) return '-';
    return String(iso).replace(/Z$/, '');
}

function showSearchError(msg) {
    const el = document.getElementById('searchError');
    el.textContent = msg;
    el.style.display = 'inline';
}

function clearSearchError() {
    const el = document.getElementById('searchError');
    el.textContent = '';
    el.style.display = 'none';
}

/* ---------- Tab 切换 ---------- */
function switchTab(tab) {
    currentTab = tab;
    const relationTab = document.getElementById('tabRelation');
    const quotaTab = document.getElementById('tabQuota');
    const relationPanel = document.getElementById('relationPanel');
    const quotaPanel = document.getElementById('quotaPanel');

    if (tab === 'relation') {
        relationTab.classList.add('active');
        relationTab.setAttribute('aria-selected', 'true');
        quotaTab.classList.remove('active');
        quotaTab.setAttribute('aria-selected', 'false');
        relationPanel.classList.add('active');
        quotaPanel.classList.remove('active');
    } else {
        quotaTab.classList.add('active');
        quotaTab.setAttribute('aria-selected', 'true');
        relationTab.classList.remove('active');
        relationTab.setAttribute('aria-selected', 'false');
        quotaPanel.classList.add('active');
        relationPanel.classList.remove('active');
    }
}

/* ---------- 全局概览 ---------- */
async function loadOverview() {
    try {
        const data = await getInviteSummary();
        document.getElementById('statAllInvited').textContent = data.totalInvited ?? 0;
        document.getElementById('statTotalGranted').innerHTML =
            `${escapeHtml(data.totalQuotaGranted ?? 0)}<span class="unit">次</span>`;
        document.getElementById('statMonthNew').textContent = data.monthNewInvites ?? 0;
    } catch (error) {
        // 概览加载失败不打断页面，保留占位符
        console.error('加载全局概览失败:', error);
    }
}

/* ---------- 全部邀请记录 ---------- */
async function loadAllInvites(page) {
    allListPage = page;
    const loading = document.getElementById('allListLoading');
    const empty = document.getElementById('allListEmpty');
    const table = document.getElementById('allListTable');

    loading.style.display = 'block';
    empty.style.display = 'none';
    table.style.display = 'none';

    try {
        const keyword = document.getElementById('allKeywordInput').value.trim();
        const data = await getInviteList({ keyword, page, size: ALL_LIST_PAGE_SIZE });
        renderAllList(data);
    } catch (error) {
        loading.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = '加载失败：' + (error.message || '未知错误');
    }
}

function renderAllList(data) {
    const loading = document.getElementById('allListLoading');
    const empty = document.getElementById('allListEmpty');
    const table = document.getElementById('allListTable');
    const tbody = document.getElementById('allListBody');
    const pagination = document.getElementById('allListPagination');

    loading.style.display = 'none';

    const items = data.items || [];
    if (!items.length) {
        empty.style.display = 'block';
        table.style.display = 'none';
        pagination.innerHTML = '';
        return;
    }

    empty.style.display = 'none';
    tbody.innerHTML = items.map((item) => `
        <tr>
            <td>
                <div style="font-weight:500;">${escapeHtml(item.inviterUsername)}</div>
                <div style="font-size:12px;color:var(--ink-grey);">${escapeHtml(item.inviterUserId)}</div>
            </td>
            <td>
                <div style="font-weight:500;">${escapeHtml(item.invitedUsername)}</div>
                <div style="font-size:12px;color:var(--ink-grey);">${escapeHtml(item.invitedUserId)}</div>
            </td>
            <td>${escapeHtml(formatDateTime(item.createdAt))}</td>
        </tr>`).join('');

    table.style.display = 'table';
    const totalPages = Math.ceil((data.total || 0) / (data.size || ALL_LIST_PAGE_SIZE)) || 1;
    renderAllListPagination(totalPages, data.page || 1, data.total || 0);
}

function renderAllListPagination(totalPages, current, total) {
    const pagination = document.getElementById('allListPagination');
    if (!totalPages || totalPages <= 1) {
        pagination.innerHTML = total ? `<span>共 ${escapeHtml(total)} 条</span>` : '';
        return;
    }

    let html = `<span>共 ${escapeHtml(total)} 条</span>`;
    html += `<button onclick="loadAllInvites(${current - 1})" ${current === 1 ? 'disabled' : ''}>上一页</button>`;
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= current - 2 && i <= current + 2)) {
            html += `<button onclick="loadAllInvites(${i})" class="${i === current ? 'active' : ''}">${i}</button>`;
        } else if (i === current - 3 || i === current + 3) {
            html += '<span>...</span>';
        }
    }
    html += `<button onclick="loadAllInvites(${current + 1})" ${current === totalPages ? 'disabled' : ''}>下一页</button>`;
    pagination.innerHTML = html;
}

/* ---------- 全量导出 ---------- */
async function doExportAll() {
    const btn = document.getElementById('allExportBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.classList.add('is-loading');
    btn.textContent = '导出中…';

    try {
        const { blob, filename } = await exportInviteCsv({});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        showSearchError('导出失败：' + (error.message || '未知错误'));
    } finally {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.textContent = originalText;
    }
}

/* ---------- 查询：两个 Tab 一起加载 ---------- */
async function doSearch() {
    const key = document.getElementById('searchInput').value.trim();
    if (!key) {
        showSearchError('请输入用户名 / user_id / 邀请码');
        return;
    }
    clearSearchError();
    currentSearchKey = key;

    const resultArea = document.getElementById('resultArea');
    const hintCard = document.getElementById('hintCard');
    const globalArea = document.getElementById('globalArea');
    resultArea.style.display = 'none';
    hintCard.style.display = 'none';

    try {
        const [stats, grants] = await Promise.all([
            getInviteStats({ user_id: key, page: 1, size: INVITEE_PAGE_SIZE }),
            getQuotaGrants({ user_id: key, page: 1, size: PAGE_SIZE })
        ]);

        currentUserId = stats.userId;
        currentUsername = stats.username || currentUserId;
        inviteePage = 1;
        grantsPage = 1;

        renderRelationPanel(stats);
        renderQuotaPanel(grants);
        resultArea.style.display = 'block';
        // 查询成功后收起全局概览/全部记录，聚焦该用户结果
        globalArea.style.display = 'none';
    } catch (error) {
        showSearchError(error.message || '查询失败');
        hintCard.style.display = 'block';
        globalArea.style.display = 'block';
    }
}

/* ---------- 邀请关系管理 ---------- */
function renderRelationPanel(stats) {
    const invitedCount = stats.invitedCount ?? 0;
    const invitees = stats.invitees || [];
    const inviteRewardTotal = invitees.reduce((sum, item) => sum + (Number(item.rewardAmount) || 0), 0);

    document.getElementById('statInvited').textContent = invitedCount;
    document.getElementById('statInviteRewardTotal').innerHTML =
        `${escapeHtml(inviteRewardTotal)}<span class="unit">次</span>`;

    renderMilestones(stats);
    renderInvitees(
        invitees,
        stats.inviteeTotal || 0,
        stats.inviteePage || 1,
        stats.inviteeSize || INVITEE_PAGE_SIZE
    );

    const summaryEl = document.getElementById('relationSummary');
    if (invitedCount > 0) {
        summaryEl.innerHTML =
            `全部邀请人·有效邀请关系 <span class="num">${escapeHtml(invitedCount)}</span> 条`;
    } else {
        summaryEl.textContent = '暂无有效邀请关系';
    }
}

function renderMilestones(stats) {
    const list = document.getElementById('milestoneList');
    const card = document.getElementById('milestoneCard');
    const milestones = stats.milestones || [];
    const invitedCount = Number(stats.invitedCount || 0);

    if (!milestones.length) {
        card.style.display = 'none';
        return;
    }
    card.style.display = 'block';

    list.innerHTML = milestones.map((m) => {
        const target = Number(m.invited || 0);
        const done = invitedCount >= target;
        const pct = target > 0 ? Math.min(invitedCount / target, 1) * 100 : (done ? 100 : 0);
        const stateClass = done ? 'done' : 'todo';
        const stateText = done ? '已达' : '未达';
        return `
            <div class="milestone-row">
                <div class="milestone-meta">${escapeHtml(m.label || ('累计邀请' + target + '人'))}（${invitedCount}/${target}）</div>
                <div class="milestone-state ${stateClass}">${stateText}</div>
                <div class="progress-track">
                    <div class="progress-fill ${done ? 'done' : ''}" style="width:0%" data-pct="${pct.toFixed(1)}"></div>
                </div>
            </div>`;
    }).join('');

    const fills = list.querySelectorAll('.progress-fill');
    requestAnimationFrame(() => {
        fills.forEach((f) => { f.style.width = (f.dataset.pct || '0') + '%'; });
    });
}

function renderInvitees(invitees, total, page, size) {
    const loading = document.getElementById('inviteesLoading');
    const empty = document.getElementById('inviteesEmpty');
    const table = document.getElementById('inviteesTable');
    const tbody = document.getElementById('inviteesBody');

    loading.style.display = 'none';

    if (!invitees.length) {
        empty.style.display = 'block';
        table.style.display = 'none';
        document.getElementById('inviteesPagination').innerHTML = '';
        return;
    }

    empty.style.display = 'none';
    tbody.innerHTML = invitees.map((item) => {
        const rewardText = item.rewardAmount
            ? `双方各+${escapeHtml(item.rewardAmount)}次 ${formatDateTime(item.rewardGrantedAt)} 已发放`
            : '-';
        const monthlyText = `${escapeHtml(currentUsername)}：${Number(item.inviterMonthlyCount || 0)}/30`;
        return `
            <tr>
                <td>
                    <div style="font-weight:500;">${escapeHtml(item.username)}</div>
                    <div style="font-size:12px;color:var(--ink-grey);">${escapeHtml(item.phone || '-')}</div>
                </td>
                <td>${formatDateTime(item.registeredAt)}</td>
                <td>${escapeHtml(item.inviteCode || '-')}</td>
                <td><span class="relation-badge">${escapeHtml(item.relationStatus || '已绑定·生效')}</span></td>
                <td>${escapeHtml(rewardText)}</td>
                <td>${escapeHtml(monthlyText)}</td>
            </tr>`;
    }).join('');

    table.style.display = 'table';
    const totalPages = Math.ceil((total || 0) / size) || 1;
    renderInviteePagination(totalPages, page);
}

function renderInviteePagination(totalPages, current) {
    const pagination = document.getElementById('inviteesPagination');
    if (!totalPages || totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';
    html += `<button onclick="loadInvitees(${current - 1})" ${current === 1 ? 'disabled' : ''}>上一页</button>`;
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= current - 2 && i <= current + 2)) {
            html += `<button onclick="loadInvitees(${i})" class="${i === current ? 'active' : ''}">${i}</button>`;
        } else if (i === current - 3 || i === current + 3) {
            html += '<span>...</span>';
        }
    }
    html += `<button onclick="loadInvitees(${current + 1})" ${current === totalPages ? 'disabled' : ''}>下一页</button>`;
    pagination.innerHTML = html;
}

async function loadInvitees(page) {
    if (!currentUserId) return;
    inviteePage = page;

    const loading = document.getElementById('inviteesLoading');
    const empty = document.getElementById('inviteesEmpty');
    const table = document.getElementById('inviteesTable');

    loading.style.display = 'block';
    empty.style.display = 'none';
    table.style.display = 'none';

    try {
        const stats = await getInviteStats({
            user_id: currentUserId,
            page: page,
            size: INVITEE_PAGE_SIZE
        });
        renderInvitees(
            stats.invitees || [],
            stats.inviteeTotal || 0,
            stats.inviteePage || page,
            stats.inviteeSize || INVITEE_PAGE_SIZE
        );
    } catch (error) {
        loading.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = '加载失败：' + (error.message || '未知错误');
    }
}

/* ---------- 额度管理 ---------- */
function renderQuotaPanel(data) {
    const summary = data.summary || {};
    const summaryEl = document.getElementById('quotaSummary');
    const total = data.total || 0;
    const active = summary.activeCount || 0;
    const expired = summary.expiredCount || 0;
    if (total > 0) {
        summaryEl.innerHTML =
            `共 <span class="num">${escapeHtml(total)}</span> 条：生效中 <span class="num">${escapeHtml(active)}</span> 条，已过期/已回收 <span class="num">${escapeHtml(expired)}</span> 条`;
    } else {
        summaryEl.textContent = '暂无额度发放记录';
    }

    renderGrants(data);
}

async function loadGrants(page) {
    if (!currentUserId) return;
    grantsPage = page;

    const loading = document.getElementById('grantsLoading');
    const empty = document.getElementById('grantsEmpty');
    const table = document.getElementById('grantsTable');

    loading.style.display = 'block';
    empty.style.display = 'none';
    table.style.display = 'none';

    try {
        const grantType = document.getElementById('grantTypeFilter').value;
        const status = document.getElementById('statusFilter').value;
        const data = await getQuotaGrants({
            user_id: currentUserId,
            grant_type: grantType,
            status: status,
            page: page,
            size: PAGE_SIZE
        });
        renderQuotaPanel(data);
    } catch (error) {
        loading.style.display = 'none';
        empty.style.display = 'block';
        empty.textContent = '加载失败：' + (error.message || '未知错误');
    }
}

function renderGrants(data) {
    const loading = document.getElementById('grantsLoading');
    const empty = document.getElementById('grantsEmpty');
    const table = document.getElementById('grantsTable');
    const tbody = document.getElementById('grantsBody');
    const pagination = document.getElementById('pagination');

    loading.style.display = 'none';

    const items = data.items || [];
    if (!items.length) {
        empty.style.display = 'block';
        table.style.display = 'none';
        pagination.innerHTML = '';
        return;
    }

    empty.style.display = 'none';
    tbody.innerHTML = items.map((g) => {
        const typeLabel = GRANT_LABELS[g.grantType] || g.grantType;
        const statusLabel = STATUS_LABELS[g.status] || g.status;
        return `
            <tr>
                <td style="font-weight:500;">${escapeHtml(currentUsername)}</td>
                <td><span class="grant-badge grant-${escapeHtml(g.grantType)}">${escapeHtml(typeLabel)}</span></td>
                <td style="text-align:right;font-variant-numeric:tabular-nums;">${escapeHtml(g.amount)}</td>
                <td>${escapeHtml(formatDateTime(g.grantedAt))}</td>
                <td>${escapeHtml(formatDateTime(g.expireAt))}</td>
                <td><span class="status-badge status-${escapeHtml(g.status)}">${escapeHtml(statusLabel)}</span></td>
                <td style="font-size:13px;color:var(--ink-grey);max-width:260px;white-space:normal;">${escapeHtml(g.rule || '-')}</td>
            </tr>`;
    }).join('');

    table.style.display = 'table';
    const totalPages = Math.ceil((data.total || 0) / PAGE_SIZE) || 1;
    renderPagination(totalPages, data.page || 1);
}

function renderPagination(totalPages, current) {
    const pagination = document.getElementById('pagination');
    if (!totalPages || totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';
    html += `<button onclick="loadGrants(${current - 1})" ${current === 1 ? 'disabled' : ''}>上一页</button>`;
    for (let i = 1; i <= totalPages; i++) {
        if (i === 1 || i === totalPages || (i >= current - 2 && i <= current + 2)) {
            html += `<button onclick="loadGrants(${i})" class="${i === current ? 'active' : ''}">${i}</button>`;
        } else if (i === current - 3 || i === current + 3) {
            html += '<span>...</span>';
        }
    }
    html += `<button onclick="loadGrants(${current + 1})" ${current === totalPages ? 'disabled' : ''}>下一页</button>`;
    pagination.innerHTML = html;
}

/* ---------- 导出 ---------- */
async function doExportRelation() {
    if (!currentUserId) {
        showSearchError('请先查询用户后再导出');
        return;
    }
    const btn = document.getElementById('relationExportBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.classList.add('is-loading');
    btn.textContent = '导出中…';

    try {
        const { blob, filename } = await exportInviteCsv({ user_id: currentUserId });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        showSearchError('导出失败：' + (error.message || '未知错误'));
    } finally {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.textContent = originalText;
    }
}

async function doExportQuota() {
    if (!currentUserId) {
        showSearchError('请先查询用户后再导出');
        return;
    }
    const btn = document.getElementById('quotaExportBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.classList.add('is-loading');
    btn.textContent = '导出中…';

    try {
        const { blob, filename } = await exportQuotaCsv({ user_id: currentUserId });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        showSearchError('导出失败：' + (error.message || '未知错误'));
    } finally {
        btn.disabled = false;
        btn.classList.remove('is-loading');
        btn.textContent = originalText;
    }
}

/* ---------- 事件绑定 ---------- */
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('searchBtn').addEventListener('click', doSearch);
    document.getElementById('searchInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') doSearch();
    });

    document.getElementById('tabRelation').addEventListener('click', () => switchTab('relation'));
    document.getElementById('tabQuota').addEventListener('click', () => switchTab('quota'));

    document.getElementById('relationResetBtn').addEventListener('click', () => {
        document.getElementById('relationFilter').value = '';
        if (currentUserId) loadInvitees(1);
    });
    document.getElementById('relationExportBtn').addEventListener('click', doExportRelation);

    document.getElementById('grantTypeFilter').addEventListener('change', () => loadGrants(1));
    document.getElementById('statusFilter').addEventListener('change', () => loadGrants(1));
    document.getElementById('quotaExportBtn').addEventListener('click', doExportQuota);

    document.getElementById('allListBtn').addEventListener('click', () => loadAllInvites(1));
    document.getElementById('allKeywordInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadAllInvites(1);
    });
    document.getElementById('allExportBtn').addEventListener('click', doExportAll);

    // 打开页面即加载全局概览与全部邀请记录
    loadOverview();
    loadAllInvites(1);
});
