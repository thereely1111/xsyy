// 管理后台：用户反馈完整管理页
(function () {
  const STORAGE_KEY = 'xsyy_feedbacks_v1';
  const PAGE_SIZE = 20;

  const state = {
    all: [],
    filtered: [],
    search: '',
    status: 'all',
    selectedId: null,
  };

  function parseJson(raw, fallback) {
    try {
      return JSON.parse(raw);
    } catch {
      return fallback;
    }
  }

  // escapeHtml 由 admin-utils.js 提供

  function formatTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('zh-CN', { hour12: false });
  }

  function normalizeFeedback(item) {
    return {
      id: item.id || `${Date.now()}-${Math.random().toString(16).slice(2)}`,
      userId: item.userId || '',
      userName: item.userName || '',
      description: item.description || '',
      images: Array.isArray(item.images) ? item.images : [],
      createdAt: item.createdAt || new Date().toISOString(),
      status: item.status || 'new',
      pageUrl: item.pageUrl || '',
      pageTitle: item.pageTitle || '',
      handledAt: item.handledAt || '',
      handledBy: item.handledBy || '',
      adminNote: item.adminNote || '',
    };
  }

  function loadLocalFeedbacks() {
    const raw = localStorage.getItem(STORAGE_KEY) || '[]';
    return parseJson(raw, []).map(normalizeFeedback);
  }

  function saveLocalFeedbacks(list) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(list.map(normalizeFeedback)));
  }

  async function loadFeedbacks() {
    if (typeof getFeedbacks === 'function') {
      try {
        const result = await getFeedbacks({ page: 1, page_size: 500 });
        const list = (result && result.feedbacks) ? result.feedbacks : (Array.isArray(result) ? result : []);
        if (Array.isArray(list) && list.length) {
          return list.map(normalizeFeedback);
        }
      } catch (err) {
        console.warn('获取反馈列表失败，回退 localStorage：', err.message || err);
      }
    }
    return loadLocalFeedbacks();
  }

  function statusMeta(status) {
    switch (status) {
      case 'in_progress':
        return { label: '处理中', cls: 'tag-warning' };
      case 'resolved':
        return { label: '已解决', cls: 'tag-success' };
      case 'ignored':
        return { label: '已忽略', cls: 'tag-danger' };
      default:
        return { label: '新反馈', cls: 'tag-primary' };
    }
  }

  function summarize(list) {
    const total = list.length;
    const counts = list.reduce((acc, item) => {
      acc[item.status || 'new'] = (acc[item.status || 'new'] || 0) + 1;
      return acc;
    }, { new: 0, in_progress: 0, resolved: 0, ignored: 0 });

    return [
      { title: '总反馈', value: total, cls: 'primary' },
      { title: '新反馈', value: counts.new || 0, cls: 'warning' },
      { title: '处理中', value: counts.in_progress || 0, cls: 'warning' },
      { title: '已解决', value: counts.resolved || 0, cls: 'success' },
      { title: '已忽略', value: counts.ignored || 0, cls: 'danger' },
    ];
  }

  function ensureStyle() {
    if (document.getElementById('admin-feedback-style')) return;
    const style = document.createElement('style');
    style.id = 'admin-feedback-style';
    style.textContent = `
      .feedback-toolbar { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap; margin-bottom:16px; }
      .feedback-toolbar-actions { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
      .feedback-search-bar { flex: 1; min-width: 280px; margin-bottom: 0; }
      .feedback-filter { height: 40px; border: 1px solid var(--border-color); border-radius: 8px; padding: 0 12px; background: white; color: var(--ink-black); }
      .feedback-summary { margin-bottom: 18px; color: var(--ink-grey); font-size: 13px; }
      .feedback-table { width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; }
      .feedback-table th, .feedback-table td { vertical-align: top; }
      .feedback-table td { font-size: 14px; }
      .feedback-desc { max-width: 420px; line-height: 1.6; }
      .feedback-page-link { display:inline-block; max-width: 220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:top; }
      .feedback-status { display:inline-flex; align-items:center; gap:6px; }
      .feedback-actions { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:8px; }
      .feedback-actions .btn { width:100%; padding:8px 12px; font-size:13px; }
      .feedback-image-count { color: var(--ink-grey); }
      .feedback-image-strip { display:grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap:10px; margin-top:12px; }
      .feedback-image-card { border: 1px solid var(--border-color); border-radius: 10px; background: white; padding: 8px; }
      .feedback-image-card img { width: 100%; height: 110px; object-fit: cover; border-radius: 8px; display:block; }
      .feedback-image-card a { display:block; margin-top:6px; font-size:12px; color: var(--primary-blue); word-break: break-all; }
      .feedback-empty { text-align:center; padding: 48px 20px; color: var(--ink-grey); }
      .feedback-empty p { margin-top: 8px; }
      .feedback-detail-grid { display:grid; gap: 12px; }
      .feedback-detail-meta { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:10px; }
      .feedback-detail-box { border: 1px solid var(--border-color); border-radius: 12px; padding: 12px; background: rgba(255,255,255,.78); }
      .feedback-detail-label { font-size:12px; color: var(--ink-grey); margin-bottom: 4px; }
      .feedback-detail-value { font-size:14px; color: var(--ink-black); word-break: break-word; }
      .admin-modal { position: fixed; inset: 0; display:none; align-items:center; justify-content:center; background: rgba(0,0,0,.5); z-index: 10030; padding: 18px; }
      .admin-modal.show { display:flex; }
      .admin-modal-card { width:min(920px, 100%); max-height: 90vh; overflow:auto; border-radius: 16px; background: white; box-shadow: 0 20px 60px rgba(0,0,0,.24); }
      .admin-modal-header { display:flex; justify-content:space-between; align-items:center; gap:12px; padding: 18px 20px; border-bottom:1px solid var(--border-color); }
      .admin-modal-header h3 { margin:0; font-family: var(--font-serif); font-size: 22px; color: var(--ink-black); }
      .admin-modal-close { border:none; background: transparent; font-size: 28px; line-height: 1; color: var(--ink-grey); cursor: pointer; }
      .admin-modal-body { padding: 18px 20px 22px; }
      .feedback-detail-actions { display:flex; gap:8px; flex-wrap:wrap; margin-top: 12px; }
      .feedback-detail-actions .btn { width:auto; }
      .feedback-status-select { height: 36px; border:1px solid var(--border-color); border-radius:8px; padding:0 10px; background:white; }
      @media (max-width: 768px) {
        .feedback-search-bar { min-width: 100%; }
        .feedback-table { display:block; overflow-x:auto; }
      }
    `;
    document.head.appendChild(style);
  }

  function notify(message, type) {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type || 'info');
      return;
    }
    // 兜底：软弹窗（admin-utils.js 提供），避免硬弹窗
    if (typeof adminShowToast === 'function') adminShowToast(message, type || 'info');
    else console.warn('[Toast]', message);
  }

  function applyFilters(list) {
    const search = (state.search || '').trim().toLowerCase();
    return list.filter((item) => {
      if (state.status !== 'all' && (item.status || 'new') !== state.status) return false;
      if (!search) return true;
      const haystack = [
        item.userName,
        item.userId,
        item.description,
        item.pageUrl,
        item.pageTitle,
        item.createdAt,
      ].join(' ').toLowerCase();
      return haystack.includes(search);
    });
  }

  function updateSummary(list) {
    const summary = document.getElementById('feedbackSummary');
    const stats = document.getElementById('feedbackStats');
    const parts = summarize(list);

    if (stats) {
      stats.innerHTML = parts.map((item) => `
        <div class="stat-card ${item.cls}">
          <h3>${item.title}</h3>
          <div class="value">${item.value}</div>
        </div>
      `).join('');
    }

    if (summary) {
      const filteredCount = state.filtered.length;
      summary.innerHTML = `当前显示 ${filteredCount} 条，共 ${list.length} 条反馈`;
    }
  }

  function renderList(list) {
    const container = document.getElementById('feedbackContainer');
    if (!container) return;

    if (!list.length) {
      container.innerHTML = `
        <div class="feedback-empty">
          <div style="font-family:var(--font-serif);font-size:20px;color:var(--ink-black);">暂无反馈</div>
          <p>当前筛选条件下没有反馈记录。</p>
        </div>
      `;
      return;
    }

    const rows = list.slice(0, PAGE_SIZE).map((item) => {
      const status = statusMeta(item.status || 'new');
      const userLabel = item.userName || '匿名用户';
      const desc = item.description || '';

      return `
        <tr data-id="${escapeHtml(item.id)}">
          <td>${escapeHtml(formatTime(item.createdAt))}</td>
          <td>
            <div style="font-weight:600;color:var(--ink-black);">${escapeHtml(userLabel)}</div>
          </td>
          <td class="feedback-desc">${escapeHtml(desc.length > 80 ? `${desc.slice(0, 80)}...` : desc)}</td>
          <td><span class="feedback-image-count">${(item.images || []).length} 张</span></td>
          <td><span class="tag ${status.cls}">${status.label}</span></td>
          <td>
            <div class="feedback-actions">
              <button type="button" class="btn btn-primary" data-action="detail">详情</button>
              <button type="button" class="btn${item.status === 'ignored' ? ' btn-danger' : ''}" data-action="ignored">忽略</button>
              <button type="button" class="btn${item.status === 'resolved' ? ' btn-success' : ''}" data-action="resolved">已解决</button>
              <button type="button" class="btn${item.status === 'in_progress' ? ' btn-warning' : ''}" data-action="in_progress">处理中</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    container.innerHTML = `
      <div class="table-container">
        <table class="feedback-table">
          <thead>
            <tr>
              <th>提交时间</th>
              <th>用户</th>
              <th>反馈内容</th>
              <th>图片</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;

    container.querySelectorAll('tr[data-id]').forEach((row) => {
      const id = row.getAttribute('data-id');
      row.querySelector('[data-action="detail"]').addEventListener('click', () => openDetail(id));
      row.querySelector('[data-action="ignored"]').addEventListener('click', () => updateStatus(id, 'ignored'));
      row.querySelector('[data-action="in_progress"]').addEventListener('click', () => updateStatus(id, 'in_progress'));
      row.querySelector('[data-action="resolved"]').addEventListener('click', () => updateStatus(id, 'resolved'));
    });
  }

  function renderDetail(item) {
    const title = document.getElementById('feedbackDetailTitle');
    const body = document.getElementById('feedbackDetailBody');
    const modal = document.getElementById('feedbackDetailModal');
    if (!title || !body || !modal || !item) return;

    const status = statusMeta(item.status || 'new');
    const images = (item.images || []).map((img, index) => `
      <div class="feedback-image-card">
        <img src="${img}" alt="反馈图片 ${index + 1}">
        <a href="${img}" target="_blank" rel="noreferrer">查看原图</a>
      </div>
    `).join('');

    title.textContent = `反馈详情 · ${item.userName || item.userId || '匿名用户'}`;
    body.innerHTML = `
      <div class="feedback-detail-grid">
        <div class="feedback-detail-meta">
          <div class="feedback-detail-box">
            <div class="feedback-detail-label">提交时间</div>
            <div class="feedback-detail-value">${escapeHtml(formatTime(item.createdAt))}</div>
          </div>
          <div class="feedback-detail-box">
            <div class="feedback-detail-label">用户</div>
            <div class="feedback-detail-value">${escapeHtml(item.userName || item.userId || '匿名')}</div>
          </div>
          <div class="feedback-detail-box">
            <div class="feedback-detail-label">状态</div>
            <div class="feedback-detail-value"><span class="tag ${status.cls}">${status.label}</span></div>
          </div>
        </div>
        <div class="feedback-detail-box">
          <div class="feedback-detail-label">反馈内容</div>
          <div class="feedback-detail-value" style="white-space:pre-wrap;line-height:1.8;">${escapeHtml(item.description)}</div>
        </div>
        <div class="feedback-detail-box">
          <div class="feedback-detail-label">反馈图片</div>
          <div class="feedback-image-strip">${images || '<div style="color:var(--ink-grey);">暂无图片</div>'}</div>
        </div>
        <div class="feedback-detail-box">
          <div class="feedback-detail-label">管理员留言（对用户可见）</div>
          <div class="feedback-detail-value" style="white-space:pre-wrap;line-height:1.7;">${escapeHtml(item.adminNote) || '<span style="color:var(--ink-grey);">暂无留言</span>'}</div>
          <textarea id="feedbackAdminNoteInput" rows="3" placeholder="输入给用户的说明（可选）" style="width:100%;margin-top:8px;padding:8px;border:1px solid var(--border-color);border-radius:8px;font-family:inherit;resize:vertical;">${escapeHtml(item.adminNote)}</textarea>
          <button type="button" class="btn btn-primary" data-detail-note style="width:auto;margin-top:8px;">保存留言</button>
        </div>
        <div class="feedback-detail-actions">
          <button type="button" class="btn" data-detail-status="in_progress">标记处理中</button>
          <button type="button" class="btn btn-primary" data-detail-status="resolved">标记已解决</button>
          <button type="button" class="btn btn-danger" data-detail-status="ignored">标记忽略</button>
        </div>
      </div>
    `;

    modal.classList.add('show');
    modal.setAttribute('aria-hidden', 'false');

    body.querySelectorAll('[data-detail-status]').forEach((btn) => {
      btn.addEventListener('click', () => updateStatus(item.id, btn.getAttribute('data-detail-status')));
    });
    const noteBtn = body.querySelector('[data-detail-note]');
    if (noteBtn) {
      noteBtn.addEventListener('click', async () => {
        const input = document.getElementById('feedbackAdminNoteInput');
        const note = input ? input.value.trim() : '';
        try {
          await apiUpdateFeedback(item.id, { status: item.status || 'new', admin_note: note });
          notify('留言已保存', 'success');
          closeDetail();
          await refreshData();
        } catch (err) {
          notify(`留言保存失败：${err.message || err}`, 'error');
        }
      });
    }
  }

  function closeDetail() {
    const modal = document.getElementById('feedbackDetailModal');
    if (!modal) return;
    modal.classList.remove('show');
    modal.setAttribute('aria-hidden', 'true');
  }

  async function refreshData() {
    const container = document.getElementById('feedbackContainer');
    if (container) container.innerHTML = '加载中...';
    try {
      const list = await loadFeedbacks();
      state.all = list.map(normalizeFeedback).sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
      state.filtered = applyFilters(state.all);
      updateSummary(state.all);
      renderList(state.filtered);
    } catch (err) {
      console.error('加载反馈失败：', err);
      state.all = [];
      state.filtered = [];
      updateSummary(state.all);
      if (container) {
        container.innerHTML = `
          <div class="feedback-empty">
            <div style="font-family:var(--font-serif);font-size:20px;color:var(--ink-black);">加载失败</div>
            <p>反馈数据加载出错，请刷新页面重试。详情见浏览器控制台。</p>
          </div>
        `;
      }
    }
  }

  async function updateStatus(id, status) {
    // 优先更新后端数据库，失败再回退到本地 localStorage
    let serverUpdated = false;
    if (typeof apiUpdateFeedback === 'function') {
      try {
        await apiUpdateFeedback(id, { status });
        serverUpdated = true;
      } catch (err) {
        console.warn('更新反馈状态到服务器失败，回退本地：', err.message || err);
      }
    }
    if (!serverUpdated) {
      const list = loadLocalFeedbacks();
      const item = list.find((entry) => String(entry.id) === String(id));
      if (item) {
        item.status = status;
        item.handledAt = new Date().toISOString();
        item.handledBy = (document.getElementById('userInfo') && document.getElementById('userInfo').textContent) || '管理员';
        saveLocalFeedbacks(list);
      }
    }
    closeDetail();
    await refreshData();
    notify('已更新反馈状态', 'success');
  }

  async function deleteFeedback(id) {
    if (!confirm('确认删除该条反馈？')) return;

    // 优先删除后端数据库记录，失败再回退到本地 localStorage
    let serverDeleted = false;
    if (typeof apiDeleteFeedback === 'function') {
      try {
        await apiDeleteFeedback(id);
        serverDeleted = true;
      } catch (err) {
        console.warn('删除服务器反馈失败，回退本地：', err.message || err);
      }
    }
    if (!serverDeleted) {
      const current = loadLocalFeedbacks();
      saveLocalFeedbacks(current.filter((entry) => String(entry.id) !== String(id)));
    }
    closeDetail();
    await refreshData();
    notify('已删除反馈', 'success');
  }

  function openDetail(id) {
    const key = String(id);
    const item = state.all.find((entry) => String(entry.id) === key) || loadLocalFeedbacks().find((entry) => String(entry.id) === key);
    if (!item) return;
    state.selectedId = key;
    renderDetail(normalizeFeedback(item));
  }

  function bindEvents() {
    const searchInput = document.getElementById('feedbackSearch');
    const searchBtn = document.getElementById('feedbackSearchBtn');
    const statusFilter = document.getElementById('feedbackStatusFilter');
    const refreshBtn = document.getElementById('feedbackRefreshBtn');
    const modal = document.getElementById('feedbackDetailModal');

    const applyAndRender = () => {
      state.search = searchInput ? searchInput.value : '';
      state.status = statusFilter ? statusFilter.value : 'all';
      state.filtered = applyFilters(state.all);
      updateSummary(state.all);
      renderList(state.filtered);
    };

    if (searchInput) {
      searchInput.addEventListener('input', applyAndRender);
      searchInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          applyAndRender();
        }
      });
    }
    if (searchBtn) searchBtn.addEventListener('click', applyAndRender);
    if (statusFilter) statusFilter.addEventListener('change', applyAndRender);
    if (refreshBtn) refreshBtn.addEventListener('click', refreshData);

    if (modal) {
      modal.addEventListener('click', (event) => {
        if (event.target === modal) closeDetail();
      });
    }
    document.querySelectorAll('[data-close-feedback-modal]').forEach((button) => {
      button.addEventListener('click', closeDetail);
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeDetail();
    });
  }

  function ensureToastFallback() {
    if (typeof window.showToast === 'function') return;
    // 软弹窗兜底（admin-utils.js），不再退化为 alert 硬弹窗
    window.showToast = (typeof adminShowToast === 'function')
      ? adminShowToast
      : function (message) { console.warn('[Toast]', message); };
  }

  function initPage() {
    ensureStyle();
    ensureToastFallback();
    bindEvents();
    refreshData();
  }

  window.adminFeedbacks = {
    refreshData,
    openDetail,
    updateStatus,
    deleteFeedback,
  };

  document.addEventListener('DOMContentLoaded', initPage);
})();
