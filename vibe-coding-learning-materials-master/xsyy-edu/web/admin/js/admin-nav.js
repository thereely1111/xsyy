/**
 * 管理后台左侧导航增强脚本
 *  - 注入“发布公告”按钮：弹窗编辑内容 + 上传图片 + 确认发布
 *  - 为"订单管理 / 用户反馈 / 网站日志"注入红点徽标，轮询未处理数量
 * 依赖：admin-api.js（getNotificationCounts / ackWebsiteLogs / publishAnnouncementApi）
 *       admin-utils.js（escapeHtml）
 */

(function () {
    'use strict';

    // href -> 红点计数分组
    var SECTION_BY_HREF = {
        'recharge_requests.html': 'orders',
        'feedbacks.html': 'feedbacks',
        'logs.html': 'logs'
    };

    var MAX_IMAGE_BYTES = 5 * 1024 * 1024;
    var ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];

    function getEl(id) { return document.getElementById(id); }

    /* ----------------------- 红点计数 ----------------------- */
    function setBadge(section, count) {
        var badge = document.querySelector('.nav-badge[data-badge="' + section + '"]');
        if (!badge) return;
        count = Number(count) || 0;
        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : String(count);
            badge.style.display = 'inline-flex';
        } else {
            badge.style.display = 'none';
        }
    }

    async function refreshCounts() {
        try {
            var data = await getNotificationCounts();
            setBadge('orders', data.new_orders);
            setBadge('feedbacks', data.new_feedbacks);
            setBadge('logs', data.new_error_logs);
        } catch (e) {
            // 静默失败，不阻塞导航使用
        }
    }

    /* ----------------------- 发布与管理公告 ----------------------- */
    var selectedImage = null;
    var editingAnnouncement = null;
    var managedAnnouncements = [];
    // 首页多态公告：当前从后台拉取到的配置（{enabled, states:{guest,logged_in_quota,member,quota_exhausted}}）
    var homeAnnouncementStates = null;

    function ensureAnnounceModal() {
        if (getEl('announceModal')) return;

        var overlay = document.createElement('div');
        overlay.id = 'announceModal';
        overlay.className = 'announce-modal-overlay';
        overlay.innerHTML = [
            '<div class="announce-modal" role="dialog" aria-modal="true">',
            '  <div class="announce-modal-header">',
            '    <h3 id="announceModalHeading">发布公告</h3>',
            '    <button type="button" class="announce-modal-close" id="announceCloseBtn" aria-label="关闭">&times;</button>',
            '  </div>',
            '  <div class="announce-modal-body">',
            '    <label class="announce-field-label">公告标题（可选）</label>',
            '    <input id="announceTitle" class="announce-select" maxlength="255" placeholder="例如：平台公告" />',
            '    <label class="announce-field-label announce-mt">公告内容 <span class="announce-required">*</span></label>',
            '    <textarea id="announceContent" class="announce-textarea" maxlength="1000" placeholder="请输入公告内容（最多 1000 字）..."></textarea>',
            '    <div class="announce-char-count"><span id="announceCharCount">0</span>/1000</div>',
            '    <label class="announce-field-label announce-mt">通知类型</label>',
            '    <select id="announceCategory" class="announce-select">',
            '      <option value="system">系统通知（默认）</option>',
            '      <option value="activity">活动通知</option>',
            '    </select>',
            '    <div id="announceImageGroup">',
            '      <label class="announce-field-label announce-mt">上传图片（可选，单张，JPG/PNG/WEBP/GIF，&le;5MB）</label>',
            '      <input type="file" id="announceImage" class="announce-file" accept="image/png,image/jpeg,image/webp,image/gif" />',
            '      <div id="announcePreview" class="announce-preview"></div>',
            '    </div>',
            '    <p id="announceEditHint" style="display:none; margin:10px 0 0; color:var(--ink-grey); font-size:12px;">编辑公告仅修改标题、正文和通知类型；原配图会保留。</p>',
            '    <p id="announceError" class="announce-error"></p>',
            '  </div>',
            '  <div class="announce-modal-footer">',
            '    <button type="button" class="announce-btn announce-btn-ghost" id="announceCancelBtn">取消</button>',
            '    <button type="button" class="announce-btn announce-btn-primary" id="announcePublishBtn">发布</button>',
            '  </div>',
            '</div>'
        ].join('');
        document.body.appendChild(overlay);

        getEl('announceContent').addEventListener('input', function () {
            getEl('announceCharCount').textContent = String(this.value.length);
        });
        getEl('announceCloseBtn').addEventListener('click', closeAnnounceModal);
        getEl('announceCancelBtn').addEventListener('click', closeAnnounceModal);
        overlay.addEventListener('click', function (e) {
            if (e.target === overlay) closeAnnounceModal();
        });
        getEl('announcePublishBtn').addEventListener('click', saveAnnouncement);
        getEl('announceImage').addEventListener('change', onImageSelected);
    }

    function setAnnouncementEditor(item) {
        editingAnnouncement = item || null;
        selectedImage = null;
        getEl('announceModalHeading').textContent = item ? '编辑公告' : '发布公告';
        getEl('announceTitle').value = item ? (item.title || '') : '';
        getEl('announceContent').value = item ? (item.content || '') : '';
        getEl('announceCharCount').textContent = String(getEl('announceContent').value.length);
        getEl('announceCategory').value = item && item.category === 'activity' ? 'activity' : 'system';
        getEl('announcePreview').innerHTML = '';
        getEl('announceImage').value = '';
        getEl('announceImageGroup').style.display = item ? 'none' : '';
        getEl('announceEditHint').style.display = item ? '' : 'none';
        getEl('announcePublishBtn').textContent = item ? '保存修改' : '发布';
        getEl('announceError').textContent = '';
    }

    function openAnnounceModal() {
        ensureAnnounceModal();
        setAnnouncementEditor(null);
        getEl('announceModal').style.display = 'flex';
    }

    function openEditAnnouncement(id) {
        var item = managedAnnouncements.filter(function (a) { return Number(a.id) === Number(id); })[0];
        if (!item) {
            showToast('未找到该公告，请刷新列表后重试。', 'warn');
            return;
        }
        ensureAnnounceModal();
        setAnnouncementEditor(item);
        getEl('announceModal').style.display = 'flex';
    }

    function closeAnnounceModal() {
        var modal = getEl('announceModal');
        if (modal) modal.style.display = 'none';
    }

    function onImageSelected(e) {
        var file = e.target.files && e.target.files[0];
        var preview = getEl('announcePreview');
        var err = getEl('announceError');
        if (err) err.textContent = '';
        selectedImage = null;
        if (preview) preview.innerHTML = '';
        if (!file) return;
        if (ALLOWED_IMAGE_TYPES.indexOf(file.type) < 0) {
            if (err) err.textContent = '仅支持 JPG/PNG/WEBP/GIF 图片';
            e.target.value = '';
            return;
        }
        if (file.size > MAX_IMAGE_BYTES) {
            if (err) err.textContent = '图片大小不能超过 5MB';
            e.target.value = '';
            return;
        }
        selectedImage = file;
        var reader = new FileReader();
        reader.onload = function (ev) {
            if (!preview) return;
            var img = document.createElement('img');
            img.src = ev.target.result;
            img.alt = file.name;
            preview.appendChild(img);
        };
        reader.readAsDataURL(file);
    }

    async function saveAnnouncement() {
        var content = getEl('announceContent');
        var err = getEl('announceError');
        var body = (content.value || '').trim();
        if (!body) {
            if (err) err.textContent = '请输入公告内容';
            return;
        }
        var category = getEl('announceCategory').value === 'activity' ? 'activity' : 'system';
        var title = (getEl('announceTitle').value || '').trim();
        var btn = getEl('announcePublishBtn');
        btn.disabled = true;
        btn.textContent = editingAnnouncement ? '保存中...' : '发布中...';
        if (err) err.textContent = '';
        try {
            if (editingAnnouncement) {
                await updateAnnouncementApi(editingAnnouncement.id, { title: title, content: body, category: category });
                showToast('公告已修改', 'success');
                await loadManageAnnounceList();
            } else {
                var fd = new FormData();
                fd.append('title', title);
                fd.append('content', body);
                fd.append('category', category);
                if (selectedImage) fd.append('image', selectedImage);
                await publishAnnouncementApi(fd);
                showToast('公告发布成功，已推送至前端系统消息模块', 'success');
            }
            closeAnnounceModal();
        } catch (e) {
            if (err) err.textContent = (editingAnnouncement ? '保存失败：' : '发布失败：') + (e.message || '未知错误');
        } finally {
            btn.disabled = false;
            btn.textContent = editingAnnouncement ? '保存修改' : '发布';
        }
    }

    /* ----------------------- 首页多态公告管理（4 态分别编辑） ----------------------- */
    // 4 个用户态：key 与后端 home_announcement_states.states 一一对应
    var HA_STATES = [
        { key: 'guest',           label: '未登录用户',     cond: '未登录（游客）访问首页时展示' },
        { key: 'logged_in_quota', label: '已登录 · 有额度', cond: '已登录、非会员、剩余次数 > 0' },
        { key: 'member',          label: '会员',           cond: '会员有效期内（无限次生成）' },
        { key: 'quota_exhausted', label: '额度用尽',       cond: '已登录、非会员、剩余次数 = 0' },
    ];

    function ensureHomeAnnouncementModal() {
        if (getEl('homeAnnouncementModal')) return;
        var stateCards = HA_STATES.map(function (s) {
            return [
                '<div class="ha-state-card" data-ha-state="' + s.key + '">',
                '  <div class="ha-state-head">',
                '    <div class="ha-state-title">' + s.label + '</div>',
                '    <label class="ha-switch"><input type="checkbox" id="ha_enabled_' + s.key + '" /><span class="ha-switch-track"></span></label>',
                '  </div>',
                '  <div class="ha-state-cond">' + s.cond + '</div>',
                '  <label class="announce-field-label announce-mt">公告文案</label>',
                '  <textarea id="ha_text_' + s.key + '" class="announce-textarea ha-textarea" maxlength="1000" placeholder="该态展示的文案（最多 1000 字）"></textarea>',
                '  <label class="announce-field-label announce-mt">CTA 按钮文字</label>',
                '  <input id="ha_cta_' + s.key + '" class="announce-select" maxlength="50" placeholder="如 立即注册、去邀请（个人中心）" />',
                '  <label class="announce-field-label announce-mt">跳转链接</label>',
                '  <input id="ha_link_' + s.key + '" class="announce-select" list="haLinkPresets" placeholder="从下拉选常用入口，或填页面地址 / action:open-login" />',
                '</div>'
            ].join('');
        }).join('');

        var overlay = document.createElement('div');
        overlay.id = 'homeAnnouncementModal';
        overlay.className = 'announce-modal-overlay';
        overlay.innerHTML = [
            '<div class="announce-modal ha-modal" role="dialog" aria-modal="true">',
            '  <div class="announce-modal-header">',
            '    <h3>首页多态公告管理</h3>',
            '    <button type="button" class="announce-modal-close" id="homeAnnouncementCloseBtn" aria-label="关闭">&times;</button>',
            '  </div>',
            '  <div class="announce-modal-body">',
            '    <div class="ha-global">',
            '      <label class="ha-switch"><input type="checkbox" id="haEnabled" /><span class="ha-switch-track"></span></label>',
            '      <span class="ha-global-label">启用首页公告条（总开关）</span>',
            '    </div>',
            '    <p class="ha-hint">按用户状态分别编辑文案、CTA 按钮文字与跳转链接；首页会自动展示对应用户态的内容。跳转链接可从下方下拉选择常用入口（登录窗口 / 注册窗口 / 邀请有礼 / 额度管理 等），也可手填页面地址；填 <code>action:open-login</code> / <code>action:open-register</code> 表示点击打开对应弹窗。「未登录用户」态默认打开登录窗口。</p>',
            '    <datalist id="haLinkPresets">',
            '      <option value="action:open-login">登录窗口（打开登录弹窗）</option>',
            '      <option value="action:open-register">注册窗口（打开注册弹窗）</option>',
            '      <option value="user_interface.html#invite">邀请有礼（个人中心）</option>',
            '      <option value="user_interface.html#recharge">额度管理 / 充值（个人中心）</option>',
            '      <option value="user_interface.html#activity">我的权益（个人中心）</option>',
            '      <option value="user_interface.html#commission">我的返现（个人中心）</option>',
            '      <option value="user_interface.html">个人中心首页</option>',
            '    </datalist>',
            stateCards,
            '    <p id="homeAnnouncementError" class="announce-error"></p>',
            '  </div>',
            '  <div class="announce-modal-footer">',
            '    <button type="button" class="announce-btn announce-btn-ghost" id="homeAnnouncementCancelBtn">取消</button>',
            '    <button type="button" class="announce-btn announce-btn-primary" id="saveHomeAnnouncementBtn">保存全部</button>',
            '  </div>',
            '</div>'
        ].join('');
        document.body.appendChild(overlay);
        getEl('homeAnnouncementCloseBtn').addEventListener('click', closeHomeAnnouncementModal);
        getEl('homeAnnouncementCancelBtn').addEventListener('click', closeHomeAnnouncementModal);
        getEl('saveHomeAnnouncementBtn').addEventListener('click', saveHomeAnnouncement);
        overlay.addEventListener('click', function (e) { if (e.target === overlay) closeHomeAnnouncementModal(); });
    }

    async function loadHomeAnnouncementEditor() {
        try {
            var data = await getConfig();
            var raw = (data && data.home_announcement_states) || '{"enabled":true,"states":{}}';
            var cfg;
            try { cfg = JSON.parse(raw); } catch (e) { cfg = { enabled: true, states: {} }; }
            homeAnnouncementStates = cfg;
            getEl('haEnabled').checked = cfg.enabled !== false;
            HA_STATES.forEach(function (s) {
                var st = (cfg.states && cfg.states[s.key]) || {};
                getEl('ha_enabled_' + s.key).checked = st.enabled !== false;
                getEl('ha_text_' + s.key).value = st.text || '';
                getEl('ha_cta_' + s.key).value = st.cta_text || '';
                // 未登录用户态：超链接默认指向登录窗口（首页点击会打开登录弹窗）；仍可手动改为其它地址后保存
                var link = (s.key === 'guest') ? 'action:open-login' : (st.link || '');
                getEl('ha_link_' + s.key).value = link;
            });
            getEl('homeAnnouncementError').textContent = '';
        } catch (e) {
            getEl('homeAnnouncementError').textContent = '加载失败：' + (e.message || '未知错误');
        }
    }

    function openHomeAnnouncementModal() {
        ensureHomeAnnouncementModal();
        getEl('homeAnnouncementModal').style.display = 'flex';
        loadHomeAnnouncementEditor();
    }

    function closeHomeAnnouncementModal() {
        var modal = getEl('homeAnnouncementModal');
        if (modal) modal.style.display = 'none';
    }

    async function saveHomeAnnouncement() {
        var error = getEl('homeAnnouncementError');
        error.textContent = '';
        var states = {};
        for (var i = 0; i < HA_STATES.length; i++) {
            var s = HA_STATES[i];
            var enabled = getEl('ha_enabled_' + s.key).checked;
            var text = (getEl('ha_text_' + s.key).value || '').trim();
            var ctaText = (getEl('ha_cta_' + s.key).value || '').trim();
            var link = (getEl('ha_link_' + s.key).value || '').trim();
            // 仅启用态需要校验文案非空（未启用可留空，不展示）
            if (enabled && !text) {
                error.textContent = '「' + s.label + '」已启用，请填写公告文案';
                return;
            }
            states[s.key] = { enabled: enabled, text: text, cta_text: ctaText, link: link };
        }
        var payload = { enabled: getEl('haEnabled').checked, states: states };
        var btn = getEl('saveHomeAnnouncementBtn');
        btn.disabled = true;
        btn.textContent = '保存中...';
        try {
            await updateConfig({ home_announcement_states: JSON.stringify(payload) });
            showToast('首页多态公告已保存', 'success');
            closeHomeAnnouncementModal();
        } catch (e) {
            error.textContent = '保存失败：' + (e.message || '未知错误');
        } finally {
            btn.disabled = false;
            btn.textContent = '保存全部';
        }
    }
    function ensureManageAnnounceModal() {
        if (getEl('manageAnnounceModal')) return;
        var overlay = document.createElement('div');
        overlay.id = 'manageAnnounceModal';
        overlay.className = 'announce-modal-overlay';
        overlay.innerHTML = [
            '<div class="announce-modal" role="dialog" aria-modal="true" style="max-width:720px;">',
            '  <div class="announce-modal-header">',
            '    <h3>管理普通公告</h3>',
            '    <button type="button" class="announce-modal-close" id="manageAnnounceCloseBtn" aria-label="关闭">&times;</button>',
            '  </div>',
            '  <div class="announce-modal-body">',
            '    <p style="margin:0 0 12px; color:var(--ink-grey); font-size:12px; line-height:1.6;">普通公告单独维护；首页顶部公告请通过“首页公告管理”单独发布、修改或撤下。</p>',
            '    <div id="manageAnnounceList" style="max-height:460px; overflow-y:auto;"><div style="text-align:center; padding:30px; color:var(--ink-grey);">加载中...</div></div>',
            '  </div>',
            '  <div class="announce-modal-footer"><button type="button" class="announce-btn announce-btn-ghost" id="manageAnnounceCancelBtn">关闭</button></div>',
            '</div>'
        ].join('');
        document.body.appendChild(overlay);
        getEl('manageAnnounceCloseBtn').addEventListener('click', closeManageAnnounceModal);
        getEl('manageAnnounceCancelBtn').addEventListener('click', closeManageAnnounceModal);
        overlay.addEventListener('click', function (e) { if (e.target === overlay) closeManageAnnounceModal(); });
    }

    function openManageAnnounceModal() {
        ensureManageAnnounceModal();
        getEl('manageAnnounceModal').style.display = 'flex';
        loadManageAnnounceList();
    }

    function closeManageAnnounceModal() {
        var modal = getEl('manageAnnounceModal');
        if (modal) modal.style.display = 'none';
    }

    function renderManageAnnounceItem(a) {
        var pinned = !!a.isPinned;
        var isSystem = (a.category || 'system') === 'system';
        var time = a.createdAt ? new Date(a.createdAt).toLocaleString('zh-CN', { hour12: false }) : '';
        var contentEsc = escapeHtml(a.content || '');
        var titleEsc = escapeHtml(a.title || '');
        var pubBy = escapeHtml(a.publishedBy || '');
        var img = a.imageUrl ? '<div style="margin-top:8px;"><img src="' + escapeHtml(a.imageUrl) + '" alt="" style="max-width:140px; max-height:100px; border-radius:6px; border:1px solid #eee;"></div>' : '';
        var tags = [
            pinned ? '<span style="background:#faad14; color:#fff; font-size:12px; padding:2px 8px; border-radius:10px;">已置顶</span>' : '',
            '<span style="background:#f3f0e8; color:var(--ink-grey); font-size:12px; padding:2px 8px; border-radius:10px;">' + (isSystem ? '系统通知' : '活动通知') + '</span>'
        ].join('');
        return [
            '<div style="border:1px solid ' + (pinned ? '#ffe58f' : 'var(--border-color)') + '; border-radius:8px; padding:12px 14px; margin-bottom:10px; background:' + (pinned ? '#fffbe6' : '#fff') + ';">',
            '  <div style="display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:8px; flex-wrap:wrap;">',
            '    <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;"><span style="font-weight:600; color:var(--ink-black);">#' + a.id + '</span>' + tags + '<span style="color:var(--ink-grey); font-size:12px;">' + pubBy + ' · ' + time + '</span></div>',
            '    <div style="display:flex; gap:6px; flex-shrink:0; flex-wrap:wrap;">',
            '      <button type="button" class="announce-btn announce-btn-ghost" data-act="edit" data-id="' + a.id + '" style="padding:4px 10px; font-size:12px;">编辑</button>',
            '      <button type="button" class="announce-btn announce-btn-ghost" data-act="pin" data-id="' + a.id + '" style="padding:4px 10px; font-size:12px;">' + (pinned ? '取消置顶' : '置顶') + '</button>',
            '      <button type="button" class="announce-btn" data-act="del" data-id="' + a.id + '" style="padding:4px 10px; font-size:12px; background:#ff4d4f; color:#fff; border-color:#ff4d4f;">删除</button>',
            '    </div>',
            '  </div>',
            titleEsc ? '  <div style="font-weight:600; color:var(--ink-black); margin-bottom:5px;">' + titleEsc + '</div>' : '',
            '  <div style="color:var(--ink-black); white-space:pre-wrap; word-break:break-word; font-size:13px;">' + contentEsc + '</div>',
            img,
            '</div>'
        ].join('');
    }

    async function loadManageAnnounceList() {
        var list = getEl('manageAnnounceList');
        if (!list) return;
        list.innerHTML = '<div style="text-align:center; padding:30px; color:var(--ink-grey);">加载中...</div>';
        try {
            var data = await getAdminAnnouncements();
            // 首页公告在“首页公告管理”中单独维护，普通公告列表不混入当前首页公告。
            managedAnnouncements = ((data && data.announcements) || []).filter(function (item) {
                return !item.isHomeBanner;
            });
            if (!managedAnnouncements.length) {
                list.innerHTML = '<div style="text-align:center; padding:30px; color:var(--ink-grey);">暂无普通公告</div>';
                return;
            }
            list.innerHTML = managedAnnouncements.map(renderManageAnnounceItem).join('');
            list.querySelectorAll('button[data-act]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var id = Number(btn.getAttribute('data-id'));
                    var act = btn.getAttribute('data-act');
                    if (act === 'edit') openEditAnnouncement(id);
                    else if (act === 'pin') onPinAnnouncement(id);
                    else if (act === 'del') onDeleteAnnouncement(id);
                });
            });
        } catch (e) {
            list.innerHTML = '<div style="color:#ff4d4f; text-align:center; padding:20px;">加载失败：' + escapeHtml(e.message || '未知错误') + '</div>';
        }
    }


    async function onPinAnnouncement(id) {
        try {
            await pinAnnouncementApi(Number(id));
            await loadManageAnnounceList();
        } catch (e) {
            showToast('操作失败：' + (e.message || '未知错误'), 'error');
        }
    }

    async function onDeleteAnnouncement(id) {
        if (!confirm('确定要删除该公告吗？此操作不可恢复。')) return;
        try {
            await deleteAnnouncementApi(Number(id));
            await loadManageAnnounceList();
        } catch (e) {
            showToast('删除失败：' + (e.message || '未知错误'), 'error');
        }
    }

    // 暴露给系统配置页（以及任何页面）调用
    window.openAnnounceModal = openAnnounceModal;
    window.openManageAnnounceModal = openManageAnnounceModal;
    window.openHomeAnnouncementModal = openHomeAnnouncementModal;

    /* ----------------------- 初始化 ----------------------- */
    function initAdminNav() {
        // 1) 为三个目标导航项注入红点徽标（侧边栏）
        var navUl = document.querySelector('.sidebar-nav');
        if (navUl) {
            navUl.querySelectorAll('a[href]').forEach(function (a) {
                var key = SECTION_BY_HREF[a.getAttribute('href')];
                if (!key) return;
                if (a.querySelector('.nav-badge')) return;
                var badge = document.createElement('span');
                badge.className = 'nav-badge';
                badge.setAttribute('data-badge', key);
                a.appendChild(badge);
            });
        }

        // 2) 原"发布公告"按钮已从顶部全局注入移除，改由系统配置页的"管理公告"模块触发
        //    （按钮 openAnnounceModal / openManageAnnounceModal 通过 window 暴露给页面调用）

        // 3) 构建弹窗
        ensureAnnounceModal();

        // 4) 立即拉取一次，并定时轮询（20s）
        refreshCounts();
        if (!window.__adminCountsTimer) {
            window.__adminCountsTimer = setInterval(refreshCounts, 20000);
        }
    }

    // 供网站日志页加载时清零“新增错误日志”红点
    window.markWebsiteLogsSeen = function () {
        ackWebsiteLogs()
            .then(refreshCounts)
            .catch(function () { /* 忽略 */ });
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAdminNav);
    } else {
        initAdminNav();
    }
})();

