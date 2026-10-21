(function () {
  const AGREEMENT_VERSION = 'v1.0.0';
  const AGREEMENT_LAST_UPDATED = '2026-05-01';
  const STORAGE_KEYS = {
    agreementRecords: 'xsyy_user_agreements_v1',
    systemMessages: 'xsyy_system_messages_v1',
    feedbacks: 'xsyy_feedbacks_v1',
    generatedContents: 'xsyy_generated_contents_v1',
    lastLoginDate: 'xsyy_last_login_date_v1',
  };

  const USER_AGREEMENT_TEXT = `《象数演易用户协议》
版本号：${AGREEMENT_VERSION}
最后更新：${AGREEMENT_LAST_UPDATED}

欢迎使用“象数演易”服务。请您在注册、登录及使用服务前仔细阅读并理解本协议。

一、账号管理
1. 用户应妥善保管账号信息与登录凭证，并对账号下的一切操作承担责任。
2. 用户不得利用平台实施违法违规行为，不得发布侵犯他人合法权益的内容。
3. 用户有权申请注销账号。账号注销后，平台将按规则删除或匿名化您的个人数据，且该操作不可撤销。

二、使用规范
1. 用户应遵守中华人民共和国现行法律法规及公序良俗。
2. 用户不得通过技术手段干扰平台正常运行，不得恶意刷量、批量爬取或攻击系统。

三、内容与版权
1. 用户在平台生成或发布的内容，知识产权归用户所有。
2. 为实现产品运营与展示功能，用户授予平台在服务范围内的非独占展示与传播权。
3. 用户应确保其发布内容不侵犯第三方权益，如产生纠纷由用户自行承担责任。

四、免责声明
1. 平台将尽力保障服务稳定，但不承诺服务绝对不中断、无错误或完全满足特定需求。
2. 因不可抗力、网络故障、第三方服务异常等原因导致的损失，平台在法律允许范围内不承担间接损失责任。

五、协议变更与适用法律
1. 平台可根据业务发展对本协议进行更新，并通过适当方式提示。
2. 本协议的订立、执行与争议解决均适用中华人民共和国法律。`;

  const PRIVACY_POLICY_TEXT = `《象数演易隐私政策》
版本号：${AGREEMENT_VERSION}
最后更新：${AGREEMENT_LAST_UPDATED}

本政策用于说明平台如何收集、使用、存储与保护您的个人信息。

一、我们收集的信息
1. 账号信息：用户名、手机号（如您提供）等。
2. 设备信息：设备标识、登录环境等，用于账号安全与设备绑定管理。
3. 使用记录：题目输入、生成记录、邀请记录、反馈信息、系统交互记录。

二、信息使用目的
1. 用于提供核心功能，包括登录认证、题目生成、次数管理、消息通知与问题反馈处理。
2. 用于产品优化与服务改进，包括故障排查、统计分析和体验优化。
3. 用于安全风控，防止欺诈、滥用和非法访问。

三、信息存储与保护
1. 我们采取合理措施保护您的信息安全，防止未经授权访问、泄露或篡改。
2. 在达到处理目的或您申请注销后，我们将依法删除或匿名化相关个人信息。

四、对外提供
1. 除法律法规要求或为提供服务所必需外，我们不会向无关第三方出售您的个人信息。
2. 在涉及第三方服务时，我们将要求其履行相应的信息保护义务。

五、您的权利
1. 您有权访问、更正、删除您的个人信息。
2. 您有权注销账号并要求删除相关个人数据（法律法规另有规定的除外）。

六、未成年人说明
若您为未成年人，请在监护人同意和指导下使用本服务。

七、法律适用
本政策受中华人民共和国法律管辖。`;

  const STATE = {
    currentUser: null,
    announcementPopupShownThisSession: false,
    currentAnnouncementId: null,
  };

  function getApiBase() {
    return window.API_BASE || '';
  }

  function getCurrentUser() {
    try {
      const userRaw = localStorage.getItem('xsyy_user_v2');
      return userRaw ? JSON.parse(decodeURIComponent(userRaw)) : null;
    } catch {
      return null;
    }
  }

  function parseJson(raw, fallback) {
    try {
      return JSON.parse(raw);
    } catch {
      return fallback;
    }
  }

  function loadMap(key) {
    return parseJson(localStorage.getItem(key) || '{}', {});
  }

  function saveMap(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  function loadArray(key) {
    return parseJson(localStorage.getItem(key) || '[]', []);
  }

  function saveArray(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
  }

  function escapeHtml(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function showToast(message, type) {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type || 'info');
      return;
    }
    alert(message);
  }

  function ensureStyle() {
    if (document.getElementById('xsyy-enhancement-style')) return;
    const style = document.createElement('style');
    style.id = 'xsyy-enhancement-style';
    style.textContent = `
      .xsyy-footer-bar { border-top: 1px solid rgba(62,92,118,.14); background: rgba(242,238,228,.8); padding: 24px 16px; }
      .xsyy-footer-wrap { max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 1.3fr 1.7fr; gap: 20px; }
      .xsyy-footer-card { border: 1px solid rgba(62,92,118,.14); background: rgba(255,255,255,.52); backdrop-filter: blur(8px); border-radius: 18px; padding: 16px; }
      .xsyy-qr-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
      .xsyy-qr { display: flex; flex-direction: column; align-items: center; gap: 6px; }
      .xsyy-qr-box { width: 80px; height: 80px; border: 1px solid rgba(62,92,118,.22); border-radius: 12px; background: rgba(255,255,255,.76); display:block; object-fit: cover; }
      .xsyy-modal { position: fixed; inset: 0; background: rgba(0,0,0,.52); z-index: 10020; display: none; align-items: center; justify-content: center; padding: 16px; }
      .xsyy-modal.show { display: flex; }
      .xsyy-modal-card { width: min(960px, 100%);  overflow: auto; background: rgba(248,242,231,.98); border: 1px solid rgba(62,92,118,.2); border-radius: 18px; box-shadow: 0 20px 60px rgba(0,0,0,.28); padding: 20px; }
      .xsyy-modal-card.small { width: min(640px, 100%); }
      .xsyy-modal-head { display:flex; justify-content: space-between; align-items:center; gap:12px; margin-bottom: 14px; }
      .xsyy-modal-title { font-family: var(--font-serif); font-size: 24px; font-weight: 700; color: #2e4151; }
      .xsyy-modal-close { border: 1px solid rgba(62,92,118,.25); background: white; border-radius: 10px; padding: 6px 12px; cursor: pointer; }
      .xsyy-modal-body { background: rgba(255,255,255,.72);max-height: 70vh;overflow-y: auto; border: 1px solid rgba(62,92,118,.12); border-radius: 14px; padding: 12px; line-height: 1.6; white-space: normal; }
      #xsyy-agreement-content { white-space: pre-wrap; line-height: 1.8; }
      /* System messages: tighter list items */
      #xsyy-system-messages-modal .xsyy-modal-body { padding: 8px; }
      #xsyy-system-messages-modal .xsyy-list-item { padding: 6px 8px; margin: 0; min-height: 0; height: auto; display: block; }
      #xsyy-system-messages-modal .xsyy-list { gap: 4px; }
      #xsyy-system-messages-modal .xsyy-list-meta { margin-top: 4px; }
      /* Feedback modal: tighter spacing and smaller textarea */
      #xsyy-feedback-modal .xsyy-modal-body { padding: 10px; }
      #xsyy-feedback-modal form { gap: 6px; }
      #xsyy-feedback-modal textarea { height: 96px; padding: 8px; border-radius: 10px; }
      #xsyy-feedback-modal .xsyy-modal-actions { margin-top: 8px; }
      .xsyy-modal-actions { display:flex; justify-content: flex-end; gap:10px; margin-top: 14px; }
      .xsyy-btn-primary { background: #2e4151; color: white; border: none; border-radius: 10px; padding: 10px 16px; cursor: pointer; }
      .xsyy-btn-danger { background: #a13f2b; color: white; border: none; border-radius: 10px; padding: 10px 16px; cursor: pointer; }
      .xsyy-list { display:flex; flex-direction:column; gap:10px; }
      .xsyy-list-item { padding: 12px 14px; border: 1px solid rgba(62,92,118,.12); border-radius: 12px; background: rgba(255,255,255,.76); }
      .xsyy-list-meta { display:flex; justify-content: space-between; align-items:center; gap:10px; margin-top: 6px; font-size: 12px; color: #8a5a44; }
      .xsyy-feedback-images { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px; margin-top: 10px; }
      .xsyy-feedback-thumb { border: 1px solid rgba(62,92,118,.12); border-radius: 12px; padding: 8px; background: rgba(255,255,255,.8); }
      .xsyy-feedback-thumb img { width: 100%; height: 96px; object-fit: cover; border-radius: 8px; }
      .xsyy-consent-row { display:flex; align-items:flex-start; gap:10px; font-size: 12px; color:#8a5a44; line-height: 1.5; }
      .xsyy-consent-row input { margin-top: 3px; }
      .xsyy-consent-link { border: none; background: transparent; color: #2e4151; text-decoration: underline; text-underline-offset: 2px; cursor: pointer; padding: 0; }
      .xsyy-dropdown-item { display:block; }
      /* 通知中心：三分类标签页 + 红点 */
      .xsyy-notif-tabs { display:flex; gap:8px; margin-bottom:10px; }
      .xsyy-notif-tab { position:relative; flex:1; border:1px solid rgba(62,92,118,.2); background:rgba(255,255,255,.6); color:#2e4151; border-radius:10px; padding:8px 6px; cursor:pointer; font-size:14px; font-weight:600; transition:all .15s ease; }
      .xsyy-notif-tab.active { background:#2e4151; color:#fff; border-color:#2e4151; }
      .xsyy-notif-dot { position:absolute; top:4px; right:6px; min-width:16px; height:16px; padding:0 4px; box-sizing:border-box; border-radius:999px; background:#e23b3b; color:#fff; font-size:11px; line-height:16px; text-align:center; }
      .xsyy-notif-list { max-height:56vh; overflow-y:auto; }
      .xsyy-notif-item.unread { border-color:rgba(161,63,43,.32); background:rgba(255,246,239,.96); }
      .xsyy-notif-title { font-weight:600; color:#2e4151; }
      .xsyy-notif-empty { padding:18px; text-align:center; color:#8a5a44; }
      .xsyy-nav-dot { display:inline-block; margin-left:6px; min-width:8px; height:8px; border-radius:50%; background:#e23b3b; vertical-align:middle; }
      .xsyy-nav-dot[hidden] { display:none; }
      .xsyy-btn-ghost { border:1px solid rgba(62,92,118,.3); background:rgba(255,255,255,.7); border-radius:10px; padding:8px 14px; cursor:pointer; color:#2e4151; }
      @media (max-width: 900px) {
        .xsyy-footer-wrap { grid-template-columns: 1fr; }
        .xsyy-qr-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
        .xsyy-qr { gap: 4px; }
        .xsyy-qr-box { width: 60px; height: 60px; }
      }
    `;
    document.head.appendChild(style);
  }

  function ensureFooter() {
    const existingFooter = document.getElementById('xsyy-footer-bar');
    if (window.location.pathname.endsWith('/user_interface.html')) {
      if (existingFooter) existingFooter.remove();
      return;
    }
    if (existingFooter) existingFooter.remove(); // 防御：重复执行时先移除旧实例，保证用最新代码内容渲染
    const footer = document.createElement('footer');
    footer.id = 'xsyy-footer-bar';
    footer.className = 'xsyy-footer-bar';
    footer.innerHTML = `
      <div class="xsyy-footer-wrap">
        <div class="xsyy-footer-card">
          <div class="xsyy-qr-grid">
            <div class="xsyy-qr"><img class="xsyy-qr-box" src="/images/illustrations/官方公众号.webp"><div style="font-size:14px;color:#8a5a44;">官方公众号</div></div>
            <div class="xsyy-qr"><img class="xsyy-qr-box" src="/images/illustrations/企业微信.webp"><div style="font-size:14px;color:#8a5a44;">象数演易交流群</div></div>
          </div>
        </div>
        <div class="xsyy-footer-card">
          <div style="font-family:var(--font-serif);font-size:18px;font-weight:700;color:#2e4151;margin-bottom:10px;">平台信息</div>
          <div style="display:grid;gap:10px;grid-template-columns:repeat(2,minmax(0,1fr));font-size:14px;line-height:1.8;">
            <div>协议：<button type="button" class="xsyy-consent-link" data-open-agreement="user">用户协议</button> / <button type="button" class="xsyy-consent-link" data-open-agreement="privacy">隐私政策</button></div>
            <div>联系电话：40068-40020</div>
            <div>邮箱：liumingjun@tipdm.com</div>
          </div>
        </div>
      </div>
    `;
    // 直接 appendChild，保证永远放在 body 的最后，页面最底部
    document.body.appendChild(footer);

    footer.querySelectorAll('[data-open-agreement]').forEach((button) => {
      button.addEventListener('click', () => openAgreementModal(button.getAttribute('data-open-agreement')));
    });
  }

  function modalTemplate(id, title, content, options = {}) {
    return `
      <div id="${id}" class="xsyy-modal" role="dialog" aria-modal="true">
        <div class="xsyy-modal-card ${options.small ? 'small' : ''}">
          <div class="xsyy-modal-head">
            <div class="xsyy-modal-title">${title}</div>
            <button type="button" class="xsyy-modal-close" data-close="${id}">关闭</button>
          </div>
          <div class="xsyy-modal-body" id="${id}-body">${content}</div>
          ${options.footer || ''}
        </div>
      </div>
    `;
  }

  function ensureModals() {
    if (!document.getElementById('xsyy-agreement-modal')) {
      // Agreement modal: do not include bottom-right close button (keep header close only)
      document.body.insertAdjacentHTML('beforeend', modalTemplate('xsyy-agreement-modal', '用户协议', `<div id="xsyy-agreement-content"></div>`, {}));
    }
    if (!document.getElementById('xsyy-system-messages-modal')) {
      // 通知中心：互动通知 / 活动通知 / 系统通知 三分类
      const notifBody = `
        <div class="xsyy-notif-tabs">
          <button type="button" class="xsyy-notif-tab active" data-tab="interaction">互动通知<span class="xsyy-notif-dot" id="notifDotInteraction" hidden></span></button>
          <button type="button" class="xsyy-notif-tab" data-tab="activity">活动通知<span class="xsyy-notif-dot" id="notifDotActivity" hidden></span></button>
          <button type="button" class="xsyy-notif-tab" data-tab="system">系统通知<span class="xsyy-notif-dot" id="notifDotSystem" hidden></span></button>
        </div>
        <div id="xsyy-system-messages-list" class="xsyy-list xsyy-notif-list"></div>
      `;
      document.body.insertAdjacentHTML('beforeend', modalTemplate('xsyy-system-messages-modal', '通知中心', notifBody, {
        small: true,
        footer: '<div class="xsyy-modal-actions"><button type="button" class="xsyy-btn-ghost" id="xsyy-clear-messages">全部标为已读</button></div>',
      }));
      const clearBtn = document.getElementById('xsyy-clear-messages');
      if (clearBtn) clearBtn.addEventListener('click', handleClearNotifications);
      document.querySelectorAll('.xsyy-notif-tab').forEach((tabBtn) => {
        tabBtn.addEventListener('click', () => {
          STATE.activeNotifTab = tabBtn.dataset.tab;
          renderNotifications();
        });
      });
    }
    if (!document.getElementById('xsyy-feedback-modal')) {
      // Feedback modal: reduce vertical spacing and textarea size
      document.body.insertAdjacentHTML('beforeend', modalTemplate('xsyy-feedback-modal', '问题反馈', `
        <form id="xsyy-feedback-form" style="display:grid;gap:8px;">
          <div>
            <label style="display:block;margin-bottom:4px;font-weight:600;color:#2e4151;">问题描述</label>
            <textarea id="xsyy-feedback-description" maxlength="500" required placeholder="请描述您遇到的问题或建议（最多500字）" style="width:100%;height:96px;border:1px solid rgba(62,92,118,.15);border-radius:10px;padding:8px;background:rgba(255,255,255,.85);outline:none;"></textarea>
            <div style="text-align:right;font-size:12px;color:#8a5a44;">最多500字</div>
          </div>
          <div>
            <label style="display:block;margin-bottom:4px;font-weight:600;color:#2e4151;">上传图片（最多1张，JPG/PNG，2MB 内）</label>
            <input type="file" id="xsyy-feedback-images" accept="image/png,image/jpeg" multiple style="width:100%;">
            <div id="xsyy-feedback-preview" class="xsyy-feedback-images"></div>
          </div>
          <div class="xsyy-modal-actions"><button type="submit" class="xsyy-btn-primary">提交反馈</button></div>
        </form>
      `, { small: true }));
    }
    if (!document.getElementById('xsyy-account-modal')) {
      document.body.insertAdjacentHTML('beforeend', modalTemplate('xsyy-account-modal', '个人中心', `
        <div style="display:grid;gap:14px;">
          <section class="xsyy-list-item">
            <div style="font-family:var(--font-serif);font-size:18px;font-weight:700;color:#2e4151;">账号安全</div>
            <div style="margin-top:8px;color:#8a5a44;font-size:14px;">修改密码</div>
            <div style="margin-top:6px;font-size:12px;color:#8a5a44;">如需修改密码，请在账号安全页完成。</div>
          </section>
          <section class="xsyy-list-item" style="border-color: rgba(161,63,43,.35); background: rgba(255,244,241,.9);">
            <div style="font-family:var(--font-serif);font-size:18px;font-weight:700;color:#a13f2b;">注销账号</div>
            <div style="margin-top:8px;color:#8a5a44;font-size:14px;">注销后所有个人数据将被永久删除，无法恢复。</div>
            <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;">
              <button type="button" class="xsyy-btn-danger" id="xsyy-open-delete-confirm">注销账号</button>
            </div>
          </section>
          <div id="xsyy-delete-confirm-box" class="xsyy-list-item" style="display:none;border-color:rgba(161,63,43,.3);">
            <div>确定要注销账号吗？此操作将清除您的次数余额、邀请记录等。操作不可逆。</div>
            <div style="display:flex;gap:10px;margin-top:12px;">
              <button type="button" class="xsyy-btn-danger" id="xsyy-confirm-delete-account">确认注销</button>
              <button type="button" class="xsyy-modal-close" id="xsyy-cancel-delete-account">取消</button>
            </div>
          </div>
        </div>
        <div class="xsyy-modal-actions"><button type="button" class="xsyy-btn-primary" data-close="xsyy-account-modal">关闭</button></div>
      `, { small: true }));
    }

    document.querySelectorAll('[data-close]').forEach((button) => {
      button.addEventListener('click', () => closeModal(button.getAttribute('data-close')));
    });
  }

  function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
      modal.classList.remove('show');
    }
  }

  function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
      modal.classList.add('show');
    }
  }

  function openAgreementModal(type) {
    ensureModals();
    const body = document.getElementById('xsyy-agreement-content');
    if (body) {
      body.textContent = type === 'privacy' ? PRIVACY_POLICY_TEXT : USER_AGREEMENT_TEXT;
    }
    openModal('xsyy-agreement-modal');
  }

  function ensureSystemMessages(userId) {
    const loginDateKey = STORAGE_KEYS.lastLoginDate;
    const today = new Date().toISOString().slice(0, 10);
    const loginMap = loadMap(loginDateKey);
    if (loginMap[userId] === today) return;

    loginMap[userId] = today;
    saveMap(loginDateKey, loginMap);

    const messageMap = loadMap(STORAGE_KEYS.systemMessages);
    const current = Array.isArray(messageMap[userId]) ? messageMap[userId] : [];
    messageMap[userId] = [
      {
        id: `${Date.now()}-${Math.floor(Math.random() * 1000)}`,
        content: '今日免费生成次数已刷新',
        createdAt: new Date().toISOString(),
        read: false,
      },
      ...current,
    ].slice(0, 200);
    saveMap(STORAGE_KEYS.systemMessages, messageMap);
  }

  function withApiBase(url) {
    if (!url) return '';
    if (/^https?:\/\//i.test(url)) return url;
    return (getApiBase() || '') + url;
  }

  function formatDateTime(value) {
    if (!value) return '';
    const d = new Date(value);
    if (isNaN(d.getTime())) return String(value);
    return d.toLocaleString();
  }

  function fetchAnnouncements() {
    const token = localStorage.getItem('auth_token');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(`${getApiBase()}/api/announcements`, { headers })
      .then((r) => (r.ok ? r.json() : { announcements: [] }))
      .then((d) => (Array.isArray(d.announcements) ? d.announcements : []))
      .catch(() => []);
  }

  async function fetchNotifications() {
    const token = localStorage.getItem('auth_token');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      const r = await fetch(`${getApiBase()}/api/notifications`, { headers });
      if (!r.ok) return { interaction: [], system: [], unread: { interaction: 0, system: 0, total: 0 } };
      const d = await r.json();
      return {
        interaction: Array.isArray(d.interaction) ? d.interaction : [],
        system: Array.isArray(d.system) ? d.system : [],
        unread: d.unread || { interaction: 0, system: 0, total: 0 },
      };
    } catch {
      return { interaction: [], system: [], unread: { interaction: 0, system: 0, total: 0 } };
    }
  }

  async function fetchAnnouncementsByCategory(category) {
    const token = localStorage.getItem('auth_token');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      const r = await fetch(`${getApiBase()}/api/announcements?category=${encodeURIComponent(category)}`, { headers });
      if (!r.ok) return [];
      const d = await r.json();
      return Array.isArray(d.announcements) ? d.announcements : [];
    } catch {
      return [];
    }
  }

  function loadLocalSystemMessages(userId) {
    const map = loadMap(STORAGE_KEYS.systemMessages);
    return Array.isArray(map[userId]) ? map[userId] : [];
  }

  async function markNotificationRead(id) {
    const token = localStorage.getItem('auth_token');
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      await fetch(`${getApiBase()}/api/notifications/${id}/read`, { method: 'POST', headers });
    } catch { /* 忽略：保持 UI 可用 */ }
    renderNotifications();
  }

  function setNotifDot(id, n) {
    const el = document.getElementById(id);
    if (!el) return;
    if (n > 0) {
      el.hidden = false;
      el.textContent = n > 99 ? '99+' : String(n);
    } else {
      el.hidden = true;
      el.textContent = '';
    }
  }

  async function updateNotifBadges() {
    const user = getCurrentUser();
    if (!user) return;
    const data = await fetchNotifications();
    const acked = getAckedAnnouncements();
    const activityAnns = await fetchAnnouncementsByCategory('activity');
    const unreadActivity = activityAnns.filter((a) => !acked.includes(String(a.id))).length;
    const localUnread = loadLocalSystemMessages(user.userId).filter((m) => !m.read).length;
    const systemUnread = (data.unread.system || 0) + localUnread;
    setNotifDot('notifDotInteraction', data.unread.interaction || 0);
    setNotifDot('notifDotActivity', unreadActivity);
    setNotifDot('notifDotSystem', systemUnread);
    const total = (data.unread.total || 0) + unreadActivity + localUnread;
    const navDot = document.getElementById('navNotifDot');
    if (navDot) navDot.hidden = total <= 0;
  }

  async function handleClearNotifications() {
    const token = localStorage.getItem('auth_token');
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    try {
      await fetch(`${getApiBase()}/api/notifications/read-all`, { method: 'POST', headers });
    } catch { /* 忽略 */ }
    const user = getCurrentUser();
    if (user) {
      const map = loadMap(STORAGE_KEYS.systemMessages);
      map[user.userId] = [];
      saveMap(STORAGE_KEYS.systemMessages, map);
    }
    renderNotifications();
  }

  function renderInteractionTab(list, items) {
    if (!items.length) {
      list.innerHTML = '<div class="xsyy-notif-empty">暂无互动通知</div>';
      return;
    }
    list.innerHTML = items.map((it) => `
      <div class="xsyy-list-item xsyy-notif-item ${it.isRead ? '' : 'unread'}" data-notif-id="${it.id}" data-target="${escapeHtml(it.targetUrl || '')}" style="cursor:pointer;">
        <div class="xsyy-notif-title">${escapeHtml(it.title || '互动通知')}</div>
        <div class="xsyy-list-meta"><span>${formatDateTime(it.createdAt)}</span><span>${it.isRead ? '已读' : '未读'}</span></div>
      </div>
    `).join('');
    list.querySelectorAll('.xsyy-notif-item').forEach((node) => {
      node.addEventListener('click', () => {
        const id = node.getAttribute('data-notif-id');
        const target = node.getAttribute('data-target');
        if (id) markNotificationRead(id);
        if (target) window.location.href = target;
        else renderNotifications();
      });
    });
  }

  function renderActivityTab(list, anns) {
    if (!anns.length) {
      list.innerHTML = '<div class="xsyy-notif-empty">暂无活动通知</div>';
      return;
    }
    list.innerHTML = anns.map((a) => {
      const img = a.imageUrl
        ? `<div style="margin-top:8px;"><img src="${escapeHtml(withApiBase(a.imageUrl))}" alt="配图" style="max-width:100%;border-radius:8px;"></div>`
        : '';
      return `
        <div class="xsyy-list-item" data-ann-id="${a.id}" style="border-color:rgba(161,63,43,.18);background:rgba(255,250,245,.96);cursor:pointer;">
          <div style="font-weight:600;color:#2e4151;">${a.isPinned ? '📌 ' : ''}${escapeHtml(a.title || '活动公告')}</div>
          <div style="margin-top:4px;white-space:pre-wrap;line-height:1.7;color:#3a4a5a;font-size:14px;">${escapeHtml(a.content)}</div>
          ${img}
          <div class="xsyy-list-meta"><span>${formatDateTime(a.createdAt)}</span>${a.publishedBy ? `<span>发布人：${escapeHtml(a.publishedBy)}</span>` : ''}</div>
        </div>`;
    }).join('');
    list.querySelectorAll('.xsyy-list-item[data-ann-id]').forEach((node) => {
      node.addEventListener('click', () => {
        markAckedAnnouncement(node.getAttribute('data-ann-id'));
        updateNotifBadges();
      });
    });
  }

  function renderSystemTab(list, sysNotifs, local, sysAnns) {
    const parts = [];
    local.forEach((m) => {
      parts.push(`
        <div class="xsyy-list-item xsyy-notif-item ${m.read ? '' : 'unread'}" data-local-id="${escapeHtml(m.id)}" style="cursor:pointer;">
          <div>${escapeHtml(m.content)}</div>
          <div class="xsyy-list-meta"><span>${new Date(m.createdAt).toLocaleString()}</span><span>${m.read ? '已读' : '未读'}</span></div>
        </div>`);
    });
    sysNotifs.forEach((n) => {
      parts.push(`
        <div class="xsyy-list-item xsyy-notif-item ${n.isRead ? '' : 'unread'}" data-notif-id="${n.id}" style="cursor:pointer;">
          <div style="font-weight:600;color:#2e4151;">${escapeHtml(n.title || '系统通知')}</div>
          <div style="margin-top:4px;color:#3a4a5a;font-size:14px;">${escapeHtml(n.content)}</div>
          <div class="xsyy-list-meta"><span>${formatDateTime(n.createdAt)}</span><span>${n.isRead ? '已读' : '未读'}</span></div>
        </div>`);
    });
    sysAnns.forEach((a) => {
      const img = a.imageUrl
        ? `<div style="margin-top:8px;"><img src="${escapeHtml(withApiBase(a.imageUrl))}" alt="配图" style="max-width:100%;border-radius:8px;"></div>`
        : '';
      parts.push(`
        <div class="xsyy-list-item" style="border-color:rgba(161,63,43,.18);background:rgba(255,250,245,.96);">
          <div style="font-weight:600;color:#2e4151;">${a.isPinned ? '📌 ' : ''}${escapeHtml(a.title || '系统公告')}</div>
          <div style="margin-top:4px;white-space:pre-wrap;line-height:1.7;color:#3a4a5a;font-size:14px;">${escapeHtml(a.content)}</div>
          ${img}
          <div class="xsyy-list-meta"><span>${formatDateTime(a.createdAt)}</span>${a.publishedBy ? `<span>发布人：${escapeHtml(a.publishedBy)}</span>` : ''}</div>
        </div>`);
    });
    if (!parts.length) {
      list.innerHTML = '<div class="xsyy-notif-empty">暂无系统通知</div>';
    } else {
      list.innerHTML = parts.join('');
    }
    list.querySelectorAll('[data-local-id]').forEach((node) => {
      node.addEventListener('click', () => {
        const id = node.getAttribute('data-local-id');
        const user = getCurrentUser();
        if (user) {
          const map = loadMap(STORAGE_KEYS.systemMessages);
          map[user.userId] = (Array.isArray(map[user.userId]) ? map[user.userId] : [])
            .map((m) => (m.id === id ? { ...m, read: true } : m));
          saveMap(STORAGE_KEYS.systemMessages, map);
        }
        renderNotifications();
      });
    });
    list.querySelectorAll('[data-notif-id]').forEach((node) => {
      node.addEventListener('click', () => markNotificationRead(node.getAttribute('data-notif-id')));
    });
  }

  async function renderNotifications() {
    const user = getCurrentUser();
    const list = document.getElementById('xsyy-system-messages-list');
    if (!user || !list) return;
    const tab = STATE.activeNotifTab || 'interaction';
    document.querySelectorAll('.xsyy-notif-tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    if (tab === 'interaction') {
      const data = await fetchNotifications();
      renderInteractionTab(list, data.interaction);
    } else if (tab === 'activity') {
      const anns = await fetchAnnouncementsByCategory('activity');
      renderActivityTab(list, anns);
    } else {
      const data = await fetchNotifications();
      const local = loadLocalSystemMessages(user.userId);
      const sysAnns = await fetchAnnouncementsByCategory('system');
      renderSystemTab(list, data.system, local, sysAnns);
    }
    updateNotifBadges();
  }

  // 原 renderSystemMessages 已由 renderNotifications（三分类通知中心）取代。

  function getAckedAnnouncements() {
    return loadArray('xsyy_acked_announcements_v1');
  }

  function markAckedAnnouncement(id) {
    const acked = getAckedAnnouncements();
    const key = String(id);
    if (!acked.includes(key)) {
      acked.push(key);
      saveArray('xsyy_acked_announcements_v1', acked);
    }
  }

  function ensureAnnouncementPopupModal() {
    if (document.getElementById('xsyy-announcement-popup-modal')) return;
    document.body.insertAdjacentHTML('beforeend', modalTemplate(
      'xsyy-announcement-popup-modal',
      '📢 平台公告',
      '<div id="xsyy-announcement-popup-body"></div>',
      {
        footer: '<div class="xsyy-modal-actions"><button type="button" class="xsyy-btn-primary" id="xsyy-announcement-popup-ok">我知道了</button></div>',
      }
    ));
    const modal = document.getElementById('xsyy-announcement-popup-modal');
    if (modal) {
      const closeBtn = modal.querySelector('[data-close]');
      if (closeBtn) closeBtn.addEventListener('click', () => closeModal('xsyy-announcement-popup-modal'));
    }
    const ok = document.getElementById('xsyy-announcement-popup-ok');
    if (ok) ok.addEventListener('click', () => {
      if (STATE.currentAnnouncementId != null) markAckedAnnouncement(STATE.currentAnnouncementId);
      closeModal('xsyy-announcement-popup-modal');
    });
  }

  function showAnnouncementPopup(announcement) {
    ensureAnnouncementPopupModal();
    STATE.currentAnnouncementId = announcement.id;
    const body = document.getElementById('xsyy-announcement-popup-body');
    if (body) {
      const img = announcement.imageUrl
        ? `<div style="margin:10px 0;"><img src="${escapeHtml(withApiBase(announcement.imageUrl))}" alt="公告配图" style="max-width:100%;border-radius:10px;"></div>`
        : '';
      body.innerHTML = `
        ${announcement.title ? `<div style="font-family:var(--font-serif);font-size:18px;font-weight:700;color:#2e4151;margin-bottom:8px;">${escapeHtml(announcement.title)}</div>` : ''}
        ${img}
        <div style="white-space:pre-wrap;line-height:1.8;color:#3a4a5a;font-size:15px;">${escapeHtml(announcement.content)}</div>
        ${announcement.publishedBy ? `<div style="margin-top:10px;font-size:12px;color:#8a5a44;">发布人：${escapeHtml(announcement.publishedBy)}</div>` : ''}
      `;
    }
    openModal('xsyy-announcement-popup-modal');
  }

  async function maybeShowAnnouncementPopup() {
    if (STATE.announcementPopupShownThisSession) return;
    const user = getCurrentUser();
    const token = localStorage.getItem('auth_token');
    if (!user || !token) return;
    let announcements = [];
    try {
      announcements = await fetchAnnouncements();
    } catch {
      return;
    }
    const pinned = announcements.find((a) => a.is_pinned);
    if (!pinned) return;
    const acked = getAckedAnnouncements();
    if (acked.includes(String(pinned.id))) return;
    STATE.announcementPopupShownThisSession = true;
    showAnnouncementPopup(pinned);
  }

  function openSystemMessages() {
    ensureModals();
    renderNotifications();
    openModal('xsyy-system-messages-modal');
  }

  function openFeedbackModal() {
    ensureModals();
    const user = getCurrentUser();
    if (!user) {
      showToast('请先登录', 'error');
      return;
    }
    const form = document.getElementById('xsyy-feedback-form');
    const desc = document.getElementById('xsyy-feedback-description');
    const imageInput = document.getElementById('xsyy-feedback-images');
    const preview = document.getElementById('xsyy-feedback-preview');
    if (form && desc && imageInput && preview) {
      form.reset();
      preview.innerHTML = '';
      const cloneInput = imageInput.cloneNode(true);
      imageInput.parentElement.replaceChild(cloneInput, imageInput);
      cloneInput.addEventListener('change', handleFeedbackImagesChange);
      form.onsubmit = handleFeedbackSubmit;
    }
    openModal('xsyy-feedback-modal');
  }

  async function handleFeedbackImagesChange(event) {
    const input = event.target;
    const files = Array.from(input.files || []);
    const preview = document.getElementById('xsyy-feedback-preview');
    if (!preview) return;

    if (files.length > 3) {
      showToast('最多上传 1 张图片', 'error');
      input.value = '';
      return;
    }

    const previews = [];
    for (const file of files) {
      if (!['image/jpeg', 'image/png'].includes(file.type)) {
        showToast('仅支持 JPG/PNG 图片', 'error');
        continue;
      }
      if (file.size > 2 * 1024 * 1024) {
        showToast(`图片 ${file.name} 超过 2MB`, 'error');
        continue;
      }
      const dataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || ''));
        reader.onerror = () => reject(new Error('读取失败'));
        reader.readAsDataURL(file);
      }).catch(() => '');
      if (dataUrl) {
        previews.push({ name: file.name, dataUrl });
      }
    }

    preview.innerHTML = previews.map((item) => `
      <div class="xsyy-feedback-thumb"><img src="${item.dataUrl}" alt="${item.name}"><div style="font-size:12px;color:#8a5a44;margin-top:6px;word-break:break-all;">${item.name}</div></div>
    `).join('');
    input.dataset.base64Images = JSON.stringify(previews.map((item) => item.dataUrl));
  }

  async function handleFeedbackSubmit(event) {
    event.preventDefault();
    const user = getCurrentUser();
    const descEl = document.getElementById('xsyy-feedback-description');
    const imageInput = document.getElementById('xsyy-feedback-images');
    if (!user || !descEl || !imageInput) return false;

    const description = (descEl.value || '').trim();
    if (!description) {
      showToast('请填写问题描述', 'error');
      return false;
    }
    if (description.length > 500) {
      showToast('问题描述不能超过 500 字', 'error');
      return false;
    }

    const images = parseJson(imageInput.dataset.base64Images || '[]', []);
    const userName = user.username || user.nickname || '';
    const feedbackMap = loadArray(STORAGE_KEYS.feedbacks);
    const item = {
      id: `${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      userId: user.userId,
      userName,
      description,
      images,
      createdAt: new Date().toISOString(),
      status: 'new',
      pageUrl: window.location.href,
      pageTitle: document.title || '',
    };
    feedbackMap.unshift(item);

    // 同步到后端数据库（失败时保留本地记录，管理后台可从服务端读取）
    try {
      const token = localStorage.getItem('auth_token');
      const response = await fetch(`${getApiBase()}/api/feedback/submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          description,
          images,
          pageUrl: item.pageUrl,
          pageTitle: item.pageTitle,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
      if (data && data.id) {
        item.id = String(data.id);
        item.serverId = String(data.id);
      }
    } catch (err) {
      console.warn('反馈提交到服务器失败，已保存到本地：', err.message || err);
    }

    saveArray(STORAGE_KEYS.feedbacks, feedbackMap.slice(0, 500));
    showToast('反馈已提交，感谢您的建议！', 'success');
    closeModal('xsyy-feedback-modal');
    return false;
  }

  function recordAgreementAccepted(userId) {
    if (!userId) return;
    const records = loadMap(STORAGE_KEYS.agreementRecords);
    records[userId] = {
      userId,
      agreedAt: new Date().toISOString(),
      agreementVersion: AGREEMENT_VERSION,
    };
    saveMap(STORAGE_KEYS.agreementRecords, records);
  }

  function recordGeneratedContent(taskId, question) {
    if (!taskId) return;
    const list = loadArray(STORAGE_KEYS.generatedContents);
    const next = [{ taskId, question: question || '', createdAt: new Date().toISOString() }, ...list.filter((item) => item.taskId !== taskId)];
    saveArray(STORAGE_KEYS.generatedContents, next.slice(0, 500));
  }

  async function deleteAccount() {
    const user = getCurrentUser();
    const token = localStorage.getItem('auth_token');
    if (!user || !token) {
      showToast('请先登录', 'error');
      return;
    }

    try {
      const response = await fetch(`${getApiBase()}/api/v2/account`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.message || '注销失败');
      }

      const agreementRecords = loadMap(STORAGE_KEYS.agreementRecords);
      delete agreementRecords[user.userId];
      saveMap(STORAGE_KEYS.agreementRecords, agreementRecords);

      const messageRecords = loadMap(STORAGE_KEYS.systemMessages);
      delete messageRecords[user.userId];
      saveMap(STORAGE_KEYS.systemMessages, messageRecords);

      const loginDates = loadMap(STORAGE_KEYS.lastLoginDate);
      delete loginDates[user.userId];
      saveMap(STORAGE_KEYS.lastLoginDate, loginDates);

      const feedbacks = loadArray(STORAGE_KEYS.feedbacks).filter((item) => item.userId !== user.userId);
      saveArray(STORAGE_KEYS.feedbacks, feedbacks);

      localStorage.removeItem('auth_token');
      localStorage.removeItem('xsyy_user_v2');
      showToast('账号已注销，相关数据已清除', 'success');
      if (typeof window.updateUIForLoggedOut === 'function') {
        window.updateUIForLoggedOut();
      }
      closeModal('xsyy-account-modal');
      // ?v=2 绕开故障时期被浏览器缓存的旧 301 重定向（2026-08-20 事故）
      window.location.href = 'index.html?v=3';
    } catch (err) {
      showToast(err.message || '注销失败，请稍后重试', 'error');
    }
  }

  function openAccountCenter() {
    ensureModals();
    openModal('xsyy-account-modal');
    const openDeleteBtn = document.getElementById('xsyy-open-delete-confirm');
    const confirmBox = document.getElementById('xsyy-delete-confirm-box');
    const confirmBtn = document.getElementById('xsyy-confirm-delete-account');
    const cancelBtn = document.getElementById('xsyy-cancel-delete-account');
    if (openDeleteBtn && confirmBox) {
      openDeleteBtn.onclick = () => { confirmBox.style.display = 'block'; };
    }
    if (confirmBtn) {
      confirmBtn.onclick = () => { void deleteAccount(); };
    }
    if (cancelBtn && confirmBox) {
      cancelBtn.onclick = () => { confirmBox.style.display = 'none'; };
    }
  }

  function ensureUserDropdownItems() {
    const dropdown = document.getElementById('userDropdown');
    if (!dropdown || dropdown.querySelector('[data-enhanced="true"]')) return;

    const personalCenter = dropdown.querySelector('a[href="user_interface.html"]');
    const divider = dropdown.querySelector('.dropdown-divider');
    const insertBeforeNode = divider || null;
    const createItem = (label, handler, danger = false) => {
      const item = document.createElement('a');
      item.href = '#';
      item.className = 'dropdown-item';
      item.dataset.enhanced = 'true';
      if (danger) item.style.color = 'var(--primary-red)';
      item.textContent = label;
      item.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        handler();
      });
      return item;
    };

    const systemMsgItem = createItem('通知', () => openSystemMessages());
    const navDot = document.createElement('span');
    navDot.id = 'navNotifDot';
    navDot.className = 'xsyy-nav-dot';
    navDot.hidden = true;
    systemMsgItem.appendChild(navDot);
    const feedbackItem = createItem('问题反馈', () => openFeedbackModal());

    if (personalCenter && personalCenter.parentElement === dropdown) {
      personalCenter.insertAdjacentElement('afterend', systemMsgItem);
      systemMsgItem.insertAdjacentElement('afterend', feedbackItem);
    } else if (insertBeforeNode) {
      dropdown.insertBefore(systemMsgItem, insertBeforeNode);
      dropdown.insertBefore(feedbackItem, insertBeforeNode);
    } else {
      dropdown.appendChild(systemMsgItem);
      dropdown.appendChild(feedbackItem);
    }
  }

  function onLogin(user) {
    STATE.currentUser = user || getCurrentUser();
    const currentUser = STATE.currentUser;
    if (!currentUser || !currentUser.userId) return;
    ensureSystemMessages(currentUser.userId);
    const messageMap = loadMap(STORAGE_KEYS.systemMessages);
    if (messageMap[currentUser.userId]) {
      // no-op; messages are rendered on demand
    }
    if (typeof window.updateInviteRedDot === 'function' && typeof window.loadInviteInfo === 'function') {
      setTimeout(() => {
        try {
          window.loadInviteInfo();
        } catch {
          // ignore
        }
      }, 0);
    }
    maybeShowAnnouncementPopup();
    // 刷新通知红点，并定时轮询未读数
    updateNotifBadges();
    if (!STATE.notifBadgeTimer) {
      STATE.notifBadgeTimer = setInterval(() => {
        if (getCurrentUser()) updateNotifBadges();
      }, 60000);
    }
  }

  function onLogout() {
    STATE.currentUser = null;
    closeModal('xsyy-system-messages-modal');
    closeModal('xsyy-feedback-modal');
    closeModal('xsyy-account-modal');
  }

  function attachModalCloseHandlers() {
    document.querySelectorAll('.xsyy-modal').forEach((modal) => {
      modal.addEventListener('click', (event) => {
        if (event.target === modal) {
          modal.classList.remove('show');
        }
      });
    });
  }

  function run() {
    ensureStyle();
    ensureFooter();
    ensureModals();
    ensureUserDropdownItems();
    attachModalCloseHandlers();
    STATE.currentUser = getCurrentUser();
    if (STATE.currentUser && STATE.currentUser.userId) {
      ensureSystemMessages(STATE.currentUser.userId);
      maybeShowAnnouncementPopup();
    }
    document.addEventListener('click', (event) => {
      const dropdown = document.getElementById('userDropdown');
      const avatarContainer = document.getElementById('userAvatarContainer');
      if (dropdown && avatarContainer && !avatarContainer.contains(event.target)) {
        dropdown.classList.remove('show');
        dropdown.style.removeProperty('display');
      }
    });
  }

  window.xsyyEnhancer = {
    onLogin,
    onLogout,
    openAgreementModal,
    openSystemMessages,
    openFeedbackModal,
    openAccountCenter,
    recordAgreementAccepted,
    recordGeneratedContent,
  };

  window.openAgreementModal = openAgreementModal;
  window.openSystemMessages = openSystemMessages;
  window.openFeedbackModal = openFeedbackModal;
  window.openAccountCenter = openAccountCenter;
  window.recordAgreementAccepted = recordAgreementAccepted;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run, { once: true });
  } else {
    run();
  }
})();
