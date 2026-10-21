// @charset "UTF-8";
// 登录弹框相关函数
function showLoginModal() {
    let modal = document.getElementById('loginModal');
    // 弹窗不存在时尝试动态创建，避免点击登录无反应
    if (!modal) {
        if (typeof initAuthModal === 'function') {
            initAuthModal();
            modal = document.getElementById('loginModal');
        } else if (typeof window !== 'undefined' && typeof window.ensureAuthScriptsLoaded === 'function') {
            window.ensureAuthScriptsLoaded((ok) => {
                if (ok && typeof window.showLoginModal === 'function') {
                    window.showLoginModal();
                } else {
                    alert('登录组件尚未加载完成，请稍后重试或刷新页面。');
                }
            });
            return;
        }
    }
    if (modal) {
        modal.classList.add('show');
        modal.style.display = 'flex';
        if (typeof switchTab === 'function') {
            switchTab('login');
        }
    }
}

function hideLoginModal() {
    const modal = document.getElementById('loginModal');
    if (modal) {
        modal.classList.remove('show');
        modal.style.display = 'none';
        const loginForm = document.getElementById('loginForm');
        const registerForm = document.getElementById('registerForm');
        const forgotForm = document.getElementById('forgotForm');
        const resetForm = document.getElementById('resetForm');
        if (loginForm) loginForm.reset();
        if (registerForm) registerForm.reset();
        if (forgotForm) forgotForm.reset();
        if (resetForm) resetForm.reset();
        document.querySelectorAll('.error-message, .success-message').forEach(el => {
            el.classList.remove('show');
            el.textContent = '';
        });
        // 关闭弹窗时清除待绑定的邀请码，避免后续手动打开注册框时残留自动回填
        try { localStorage.removeItem('user_invite_code'); } catch (e) { }
    }
}

function switchTab(tabName) {
    document.querySelectorAll('.modal-tab-content').forEach(el => {
        el.classList.remove('active');
    });
    document.querySelectorAll('.modal-tab').forEach(el => {
        el.classList.remove('active');
    });

    if (tabName === 'login') {
        const loginTab = document.getElementById('loginTab');
        const tabs = document.querySelectorAll('.modal-tab');
        if (loginTab) loginTab.classList.add('active');
        if (tabs[0]) tabs[0].classList.add('active');
    } else if (tabName === 'register') {
        const registerTab = document.getElementById('registerTab');
        const tabs = document.querySelectorAll('.modal-tab');
        if (registerTab) registerTab.classList.add('active');
        if (tabs[1]) tabs[1].classList.add('active');
        try {
            if (typeof fillRegisterBetaCode === 'function') {
                fillRegisterBetaCode();
            }
        } catch (e) {
            console.error('[switchTab] 回填邀请码异常', e);
        }
    } else if (tabName === 'forgot') {
        const forgotTab = document.getElementById('forgotTab');
        if (forgotTab) forgotTab.classList.add('active');
    } else if (tabName === 'reset') {
        const resetTab = document.getElementById('resetTab');
        if (resetTab) resetTab.classList.add('active');
    }
}
if (typeof window !== 'undefined') {
    window.showLoginModal = showLoginModal;
    window.hideLoginModal = hideLoginModal;
    window.switchTab = switchTab;
}
function fillRegisterBetaCode(code) {
    const input = document.getElementById('registerBetaCode');
    if (!input) return;
    // 通过邀请链接进入时，自动回填待绑定的邀请码；无邀请码则保持空白由用户手动填写
    let val = (code || '').trim();
    if (!val && typeof getInviteCodeFromUrl === 'function') {
        val = getInviteCodeFromUrl();
    }
    input.value = val ? val.toUpperCase() : '';
}
if (typeof window !== 'undefined') {
    window.fillRegisterBetaCode = fillRegisterBetaCode;
}

function getInviteCodeFromUrl() {
    try {
        const urlParams = new URLSearchParams(window.location.search);
        const fromUrl = urlParams.get('inviteCode');
        if (fromUrl) return fromUrl.trim();
    } catch (e) { }
    const fromStorage = localStorage.getItem('user_invite_code');
    return (fromStorage && fromStorage !== 'null' && fromStorage !== 'undefined') ? fromStorage.trim() : '';
}
if (typeof window !== 'undefined') {
    window.getInviteCodeFromUrl = getInviteCodeFromUrl;
}

// 生成「环境感知」的邀请链接：始终指向当前环境的首页根路径，并携带 ?inviteCode=
// 本地(localhost/file) → http://127.0.0.1:8000；其他(生产/测试域名) → 当前 origin
function buildInviteShareUrl(code) {
    const host = window.location.hostname;
    const isLocal = host === 'localhost' || host === '127.0.0.1' || window.location.protocol === 'file:';
    const base = isLocal ? 'http://127.0.0.1:8000' : (window.location.origin || '');
    const clean = (code || '').trim();
    return `${base}/?inviteCode=${encodeURIComponent(clean)}`;
}
if (typeof window !== 'undefined') {
    window.buildInviteShareUrl = buildInviteShareUrl;
}

// 打开邀请链接时：持久化邀请码；已登录则仅记录（不注销、不踢其他标签页），未登录才弹注册框并回填
// 说明：邀请链接是给「未登录好友」注册的。所有标签页共享同一份 localStorage 会话令牌，
// 且后端为单会话模型（current_session_id），若在此处强行清掉 token，会误把「原已登录的标签页」判定为
// 「在别处登录」而弹窗踢下线，新标签注册后又会因共享 token 被覆盖再次触发 401 弹窗。
// 因此已登录时只静默记录邀请码，留给用户本机退出登录后的注册流程使用。
function handleInviteLinkOnLoad() {
    if (window.__inviteBootstrapDone) return;
    window.__inviteBootstrapDone = true;
    let code = '';
    try {
        const params = new URLSearchParams(window.location.search);
        code = (params.get('inviteCode') || params.get('ref') || '').trim();
    } catch (e) { }
    if (!code) return; // 仅当通过邀请链接（带 inviteCode/ref）进入时才触发
    // 持久化到 localStorage，供注册表单回填（即使稍后清理 URL 参数也不丢失）
    try { localStorage.setItem('user_invite_code', code); } catch (e) { }
    // 清理 URL 中的邀请参数，避免刷新页面重复触发
    try {
        const url = new URL(window.location.href);
        url.searchParams.delete('inviteCode');
        url.searchParams.delete('ref');
        history.replaceState(null, '', url.pathname + url.search + url.hash);
    } catch (e) { }

    const alreadyLoggedIn = (typeof getToken === 'function') && !!getToken();
    if (alreadyLoggedIn) {
        // 已登录：不注销、不弹注册框、不踢原账号。仅记录邀请码并轻提示，避免破坏当前会话。
        try {
            const msg = '你已登录，邀请码已记录；退出登录后再打开注册将自动绑定。';
            if (typeof window.showToast === 'function') window.showToast(msg, 'info', 2800);
        } catch (e) { }
        return;
    }

    // 未登录：打开注册弹窗并自动切换到注册 Tab（switchTab 内部会回填邀请码）
    try {
        if (typeof showLoginModal === 'function') showLoginModal();
        if (typeof switchTab === 'function') switchTab('register');
    } catch (e) { console.error('[邀请] 打开注册弹窗失败', e); }
}
if (typeof window !== 'undefined') {
    window.handleInviteLinkOnLoad = handleInviteLinkOnLoad;
    // auth.js 在 load 之后注入执行，此时 DOM 已就绪；个别异步加载场景兜底等 DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', handleInviteLinkOnLoad, { once: true });
    } else {
        handleInviteLinkOnLoad();
    }
}

function switchRegisterMethod(method) {
    document.querySelectorAll('.register-method-tab').forEach((tab, index) => {
        tab.classList.remove('active');
        if ((method === 'password' && index === 0) || (method === 'phone' && index === 1)) {
            tab.classList.add('active');
        }
    });

    const passwordForm = document.getElementById('registerPasswordForm');
    const phoneForm = document.getElementById('registerPhoneForm');
    if (passwordForm) passwordForm.classList.toggle('active', method === 'password');
    if (phoneForm) phoneForm.classList.toggle('active', method === 'phone');
}

function saveToken(token, sessionId) {
    localStorage.setItem('auth_token', token);
    if (sessionId) {
        localStorage.setItem('auth_session_id', sessionId);
    } else {
        localStorage.removeItem('auth_session_id');
    }
}

function getToken() {
    return localStorage.getItem('auth_token');
}

function removeToken() {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_session_id');
}

function clearUserSession() {
    removeToken();
    localStorage.removeItem('xsyy_user_v2');
    if (typeof window.clearAiAssistantState === 'function') {
        window.clearAiAssistantState();
    }
    window.dispatchEvent(new Event('xsyy:authChanged'));
}

function ensureSessionKickedModal() {
    let overlay = document.getElementById('sessionKickedModal');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'sessionKickedModal';
    overlay.style.display = 'none';
    Object.assign(overlay.style, {
        position: 'fixed',
        inset: '0',
        zIndex: '30010',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px',
        background: 'rgba(18, 22, 31, 0.42)',
        backdropFilter: 'blur(6px)'
    });

    const panel = document.createElement('div');
    Object.assign(panel.style, {
        width: 'min(420px, calc(100vw - 32px))',
        borderRadius: '18px',
        padding: '28px 24px 22px',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.98), rgba(245,242,235,0.98))',
        border: '1px solid rgba(140, 102, 58, 0.16)',
        boxShadow: '0 24px 60px rgba(28, 20, 10, 0.24)',
        textAlign: 'center'
    });

    const title = document.createElement('div');
    title.textContent = '你的账号已在别处登录';
    Object.assign(title.style, {
        fontSize: '22px',
        lineHeight: '1.35',
        color: '#3d2a1d',
        fontWeight: '700',
        marginBottom: '12px'
    });

    const message = document.createElement('div');
    message.textContent = '当前登录已失效，请重新登录。';
    Object.assign(message.style, {
        fontSize: '14px',
        lineHeight: '1.7',
        color: '#745741',
        marginBottom: '22px'
    });

    const actions = document.createElement('div');
    Object.assign(actions.style, {
        display: 'flex',
        justifyContent: 'center'
    });

    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.textContent = '确定';
    Object.assign(confirmBtn.style, {
        minWidth: '132px',
        height: '44px',
        border: 'none',
        borderRadius: '999px',
        cursor: 'pointer',
        background: '#9a2a2a',
        color: '#fff',
        fontSize: '15px',
        fontWeight: '600',
        boxShadow: '0 10px 24px rgba(154, 42, 42, 0.22)'
    });

    confirmBtn.addEventListener('click', () => {
        overlay.style.display = 'none';
        clearUserSession();
        if (typeof window.updateUIForLoggedOut === 'function') {
            window.updateUIForLoggedOut();
        }
        if (typeof hideLoginModal === 'function') {
            hideLoginModal();
        }
        window.__xsyySessionKickedShown = false;
    });

    actions.appendChild(confirmBtn);
    panel.appendChild(title);
    panel.appendChild(message);
    panel.appendChild(actions);
    overlay.appendChild(panel);
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) {
            confirmBtn.click();
        }
    });
    document.body.appendChild(overlay);
    return overlay;
}

function showSessionKickedModal() {
    if (window.__xsyySessionKickedShown) return;
    window.__xsyySessionKickedShown = true;
    const modal = ensureSessionKickedModal();
    modal.style.display = 'flex';
}

if (typeof window !== 'undefined') {
    window.showSessionKickedModal = showSessionKickedModal;
    if (window.__xsyySessionKickedPending) {
        window.setTimeout(() => {
            window.__xsyySessionKickedPending = false;
            showSessionKickedModal();
        }, 0);
    }
}
var ss11;

function showLoginSuccessToast(message) {
    if (typeof window.showToast === 'function') {
        window.showToast(message, 'success', 1500);
        return;
    }
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        Object.assign(container.style, {
            position: 'fixed',
            top: '16px',
            right: '16px',
            zIndex: '99999',
            pointerEvents: 'none'
        });
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast success';
    toast.textContent = message;
    Object.assign(toast.style, {
        padding: '10px 18px',
        marginBottom: '8px',
        borderRadius: '6px',
        minWidth: '140px',
        maxWidth: '320px',
        opacity: '1',
        transform: 'translateY(0)',
        transition: 'all 0.25s ease',
        pointerEvents: 'auto',
        background: '#27ae60',
        color: '#fff'
    });
    container.appendChild(toast);
    window.setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        window.setTimeout(() => toast.remove(), 250);
    }, 1500);
}

function ensureLogoutModal() {
    let overlay = document.getElementById('logoutConfirmModal');
    if (overlay) return overlay;

    overlay = document.createElement('div');
    overlay.id = 'logoutConfirmModal';
    overlay.style.display = 'none';
    Object.assign(overlay.style, {
        position: 'fixed',
        inset: '0',
        background: 'rgba(20, 24, 32, 0.38)',
        backdropFilter: 'blur(6px)',
        zIndex: '30000',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px'
    });

    const panel = document.createElement('div');
    Object.assign(panel.style, {
        width: 'min(420px, calc(100vw - 32px))',
        borderRadius: '20px',
        padding: '28px 24px 22px',
        background: 'linear-gradient(180deg, rgba(249,245,236,0.98), rgba(244,236,222,0.98))',
        border: '1px solid rgba(154, 42, 42, 0.18)',
        boxShadow: '0 24px 60px rgba(54, 33, 18, 0.22), inset 0 1px 0 rgba(255,255,255,0.72)',
        position: 'relative',
        overflow: 'hidden'
    });

    const ornament = document.createElement('div');
    Object.assign(ornament.style, {
        position: 'absolute',
        inset: '0',
        pointerEvents: 'none',
        background: 'radial-gradient(circle at top left, rgba(171, 52, 40, 0.12), transparent 38%), radial-gradient(circle at bottom right, rgba(43, 78, 109, 0.10), transparent 32%)'
    });

    const title = document.createElement('div');
    title.textContent = '确认退出登录';
    Object.assign(title.style, {
        fontSize: '24px',
        lineHeight: '1.25',
        color: '#3a2718',
        fontWeight: '700',
        textAlign: 'center',
        marginBottom: '10px'
    });

    const subtitle = document.createElement('div');
    subtitle.textContent = '退出后将回到未登录状态';
    Object.assign(subtitle.style, {
        fontSize: '14px',
        lineHeight: '1.7',
        color: '#7b5a42',
        textAlign: 'center',
        marginBottom: '22px'
    });

    const actions = document.createElement('div');
    Object.assign(actions.style, {
        display: 'flex',
        justifyContent: 'center'
    });

    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.textContent = '退出登录';
    Object.assign(confirmBtn.style, {
        minWidth: '176px',
        height: '46px',
        border: 'none',
        borderRadius: '999px',
        cursor: 'pointer',
        fontSize: '15px',
        fontWeight: '700',
        letterSpacing: '0',
        color: '#f6df9f',
        background: 'linear-gradient(135deg, #a52f2b, #7f1f1d)',
        boxShadow: '0 10px 24px rgba(127, 31, 29, 0.28)'
    });

    confirmBtn.addEventListener('click', () => {
        hideLogoutConfirmModal();
        performLogout();
    });

    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) {
            hideLogoutConfirmModal();
        }
    });

    actions.appendChild(confirmBtn);
    panel.appendChild(ornament);
    panel.appendChild(title);
    panel.appendChild(subtitle);
    panel.appendChild(actions);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    return overlay;
}

function showLogoutConfirmModal() {
    const overlay = ensureLogoutModal();
    overlay.style.display = 'flex';
}

function hideLogoutConfirmModal() {
    const overlay = document.getElementById('logoutConfirmModal');
    if (overlay) {
        overlay.style.display = 'none';
    }
}

function performLogout() {
    clearUserSession();
    if (typeof window.updateUIForLoggedOut === 'function') {
        window.updateUIForLoggedOut();
    }
    // 退出登录：清除首页多态公告「本次会话已关闭」记忆（按身份存于 sessionStorage）。
    // reload() 不会清空 sessionStorage，不清会导致同一账号重新登录后公告条不再出现的回归。
    if (window.__clearAnnouncementClose) window.__clearAnnouncementClose();
    showLoginSuccessToast('已退出登录');
    window.setTimeout(() => {
        window.location.reload();
    }, 700);
}

function logout() {
    showLogoutConfirmModal();
}

if (typeof window !== 'undefined') {
    window.logout = logout;
}

async function handleLogin(event) {
    event.preventDefault();
    const btn = document.getElementById('loginBtn');
    const errorEl = document.getElementById('loginError');
    const usernameEl = document.getElementById('loginUsername');
    const passwordEl = document.getElementById('loginPassword');
    const agreementEl = document.getElementById('loginAgreementCheckbox');

    if (!btn || !errorEl || !usernameEl || !passwordEl || !agreementEl) return;
    if (!agreementEl.checked) {
        errorEl.textContent = '请先勾选用户协议和隐私政策';
        errorEl.classList.add('show');
        return;
    }

    const username = usernameEl.value;
    const password = passwordEl.value;

    btn.disabled = true;
    btn.textContent = '登录中...';
    errorEl.classList.remove('show');

    try {
        let API_BASE = '';
        if (typeof window !== 'undefined' && window.API_BASE) {
            API_BASE = window.API_BASE;
        } else {
            const isLocalDev = window.location.hostname === 'localhost' ||
                window.location.hostname === '127.0.0.1' ||
                window.location.protocol === 'file:';
            API_BASE = isLocalDev ? "http://127.0.0.1:8000" : "";
        }

        const res = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });

        let data;
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            data = await res.json();
            localStorage.setItem('xsyy_user_v2', decodeURIComponent(JSON.stringify(data.user)));
        } else {
            const text = await res.text();
            throw new Error(`服务器返回了非 JSON 响应 (${res.status}): ${text.substring(0, 100)}`);
        }

        if (res.ok) {
            const decodedToken = (() => {
                try {
                    const parts = String(data.token || '').split('.');
                    if (parts.length !== 3) return null;
                    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
                    return payload;
                } catch (e) {
                    return null;
                }
            })();
            saveToken(data.token, decodedToken && decodedToken.sid ? decodedToken.sid : null);
            const registerLink = document.getElementById('registerLink');
            if (registerLink) registerLink.style.display = 'none';
            if (typeof ensureAdminLink === 'function') ensureAdminLink();
            if (typeof updateUIForLoggedIn === 'function') {
                updateUIForLoggedIn(data.user);
            }
            // 登录成功：清除首页多态公告「本次会话已关闭」记忆并按新身份重新展示
            // （index.html 的 setAuthStateFromV2 已做同样处理；此处覆盖直接走 handleLogin 的生产入口）。
            if (window.__clearAnnouncementClose) {
                window.__clearAnnouncementClose();
                if (window.__reloadHomeAnnouncement) window.__reloadHomeAnnouncement();
            }
            hideLoginModal();
            window.dispatchEvent(new Event('xsyy:authChanged'));
            showLoginSuccessToast('登录成功！');
            if (typeof window.onLoginSuccess === 'function') {
                window.onLoginSuccess(data.user);
            } else {
                setTimeout(function () { window.location.reload(); }, 700);
            }
        } else {
            errorEl.textContent = data.detail || '登录失败';
            errorEl.classList.add('show');
        }
    } catch (err) {
        console.error('登录错误详情:', {
            name: err.name,
            message: err.message,
            stack: err.stack,
            err: err
        });

        let errorMessage = '网络错误，请稍后重试';
        if (err.name === 'TypeError' && (
            err.message.includes('fetch') ||
            err.message.includes('Failed to fetch') ||
            err.message.includes('NetworkError') ||
            err.message.includes('Network request failed')
        )) {
            errorMessage = '无法连接到服务器，请检查网络连接或联系管理员';
        }
        else if (err.name === 'SyntaxError' ||
            err.message.includes('JSON') ||
            err.message.includes('Unexpected token') ||
            err.message.includes('parse')) {
            errorMessage = '服务器响应格式错误，请稍后重试或联系管理员';
        }
        else if (err.message && err.message.includes('服务器返回了非 JSON')) {
            errorMessage = '服务器错误，请稍后重试或联系管理员';
        }
        else if (err.message) {
            errorMessage = `错误: ${err.message}`;
        }
        else if (err.toString && err.toString() !== '[object Object]') {
            errorMessage = `错误: ${err.toString()}`;
        }

        errorEl.textContent = errorMessage;
        errorEl.classList.add('show');
    } finally {
        btn.disabled = false;
        btn.textContent = '登录';
    }
}

function ensureAdminLink() {
    var token = localStorage.getItem('auth_token');
    if (!token) return;
    var API_BASE = (typeof window !== 'undefined' && window.API_BASE) ? window.API_BASE
        : (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' || window.location.protocol === 'file:'
            ? 'http://127.0.0.1:8000' : '');
    fetch(API_BASE + '/api/admin/check', { headers: { 'Authorization': 'Bearer ' + token } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (result) {
            if (!result || !result.is_admin) return;
            var adminLink = document.getElementById('adminLink');
            if (adminLink) { adminLink.style.display = 'block'; return; }
            var userDropdown = document.getElementById('userDropdown');
            if (!userDropdown) return;
            var firstItem = userDropdown.querySelector('a.dropdown-item');
            adminLink = document.createElement('a');
            adminLink.href = 'admin/dashboard.html';
            adminLink.className = 'dropdown-item';
            adminLink.id = 'adminLink';
            adminLink.textContent = '管理后台';
            if (firstItem) {
                userDropdown.insertBefore(adminLink, firstItem.nextSibling);
            } else {
                userDropdown.appendChild(adminLink);
            }
        })
        .catch(function () { });
}
if (typeof window !== 'undefined') {
    window.ensureAdminLink = ensureAdminLink;
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', ensureAdminLink);
    } else {
        ensureAdminLink();
    }
}

// ========== 注册处理（跨页面公共） ==========
// 抽出自 index.html 的 v2 注册逻辑，保证所有加载 auth-modal.js 的页面（video.html /
// user_interface.html / share_topic.html 等）都能正常注册。否则这些页面的注册表单
// onsubmit 调用 handleRegisterPassword 会因函数未定义而抛错，preventDefault 未执行，
// 表单以 GET 方式重新提交到当前页（教学详情页即重加载成空白页）。
// 协助 UI 钩子（showToast / updateUIForLoggedIn / updateInviteRedDot / xsyyEnhancer）
// 均按 typeof 判断存在才调用，缺失也不影响注册主流程。
(function () {
    function getApiBase() {
        if (typeof window.API_BASE !== 'undefined') return window.API_BASE;
        const host = window.location.hostname;
        if (['localhost', '127.0.0.1'].includes(host) || window.location.protocol === 'file:') {
            return 'http://127.0.0.1:8000';
        }
        return '';
    }

    function getOrCreateDeviceId() {
        let did = localStorage.getItem('device_id');
        if (!did) {
            did = 'web_' + Math.random().toString(36).slice(2) + '_' + Date.now().toString(36);
            localStorage.setItem('device_id', did);
        }
        return did;
    }

    function getDeviceIdForAuth() {
        return getOrCreateDeviceId();
    }

    async function readApiResponse(res) {
        const text = await res.text();
        try {
            return JSON.parse(text);
        } catch {
            return text;
        }
    }

    async function setAuthStateFromV2(result, showGift = false) {
        localStorage.setItem('auth_token', result.token);
        let authenticatedUser = result.user || {};
        if (result.user) {
            // v2 登录响应只返回基础用户字段，不含实时额度/订阅。
            // 优先用 /api/auth/me 补全；若其偶发失败，则用登录响应自带的 quota.remainingTotal 兜底，
            // 避免首页公告把仍有额度的用户误判为“额度已用完”（与个人中心 /api/auth/me 同源一致）。
            let meUser = null;
            try {
                const meResponse = await fetch(`${getApiBase()}/api/auth/me`, {
                    headers: { 'Authorization': `Bearer ${result.token}` },
                    cache: 'no-store'
                });
                if (meResponse.ok) {
                    const meData = await meResponse.json();
                    if (meData && meData.user) {
                        meUser = meData.user;
                    }
                }
            } catch (error) {
                console.warn('登录后获取完整用户状态失败，回退使用登录响应 quota:', error);
            }
            const quota = (result && result.quota) || {};
            const fallbackRemaining = (quota.remainingTotal != null) ? Number(quota.remainingTotal)
                : (quota.freeBalance != null) ? Number(quota.freeBalance)
                : (quota.extraBalance != null) ? Number(quota.extraBalance) : 0;
            authenticatedUser = {
                ...result.user,
                ...meUser,
                remaining_total: (meUser && meUser.remaining_total != null) ? meUser.remaining_total : fallbackRemaining,
                remaining_calls: (meUser && meUser.remaining_calls != null) ? meUser.remaining_calls : fallbackRemaining,
            };
            localStorage.setItem('xsyy_user_v2', encodeURIComponent(JSON.stringify(authenticatedUser)));
            if (typeof updateInviteRedDot === 'function') updateInviteRedDot(authenticatedUser);
            if (typeof updateUIForLoggedIn === 'function') void updateUIForLoggedIn(authenticatedUser);
            if (window.__clearAnnouncementClose) window.__clearAnnouncementClose();
            if (window.__reloadHomeAnnouncement) window.__reloadHomeAnnouncement();
            window.dispatchEvent(new Event('xsyy:authChanged'));
            if (window.xsyyEnhancer && typeof window.xsyyEnhancer.onLogin === 'function') {
                window.xsyyEnhancer.onLogin(authenticatedUser);
            }
            if (showGift && window.xsyyEnhancer && typeof window.xsyyEnhancer.recordAgreementAccepted === 'function' && authenticatedUser.userId) {
                window.xsyyEnhancer.recordAgreementAccepted(authenticatedUser.userId);
            }
        }
        if (showGift && typeof showToast === 'function') {
            // 展示后端实际发放的注册赠送额度（与后台系统配置 new_user_gift_quota 同步）
            const giftQuota = Number(result?.firstLoginReward ?? 0);
            if (giftQuota > 0) {
                showToast(`新用户首次登录免费赠送${giftQuota}次生成次数`, 'success', 2200);
            }
        }
        if (typeof hideLoginModal === 'function') hideLoginModal();
        return authenticatedUser;
    }

    window.handleRegisterPassword = async function (event) {
        if (event) event.preventDefault();
        const usernameEl = document.getElementById('registerUsername');
        const passwordEl = document.getElementById('registerPassword');
        const confirmEl = document.getElementById('registerPasswordConfirm');
        const inviteEl = document.getElementById('registerBetaCode');
        const gradeEl = document.getElementById('registerGrade');
        const agreementEl = document.getElementById('registerAgreementCheckbox');
        const errorEl = document.getElementById('registerError');
        const successEl = document.getElementById('registerSuccess');
        const btn = document.getElementById('registerBtn');

        const username = (usernameEl?.value || '').trim();
        const password = passwordEl?.value || '';
        const confirm = confirmEl?.value || '';
        const grade = (gradeEl?.value || '').trim();
        // 邀请码优先级：手动输入 > 分享链接URL参数 > 本地缓存（仅来自真实邀请链接）
        let inviteCode = (inviteEl?.value || new URLSearchParams(window.location.search).get('inviteCode') || localStorage.getItem('user_invite_code') || '').trim().toUpperCase();
        // 清理早期残留的无效临时码（INV 开头），避免注册被误拒
        if (/^INV/i.test(inviteCode)) {
            inviteCode = (inviteEl?.value || '').trim().toUpperCase() || '';
            localStorage.removeItem('user_invite_code');
        }
        if (!username || !password || !confirm || !inviteCode) {
            if (errorEl) { errorEl.textContent = '请完整填写用户名、密码、确认密码和邀请码'; errorEl.classList.add('show'); }
            return false;
        }
        if (password !== confirm) {
            if (errorEl) { errorEl.textContent = '两次输入的密码不一致'; errorEl.classList.add('show'); }
            return false;
        }
        if (agreementEl && !agreementEl.checked) {
            if (errorEl) { errorEl.textContent = '请先同意用户协议与隐私政策'; errorEl.classList.add('show'); }
            return false;
        }

        errorEl?.classList.remove('show');
        successEl?.classList.remove('show');
        if (btn) { btn.disabled = true; btn.textContent = '注册中...'; }

        try {
            const API_BASE = getApiBase();
            const deviceId = getDeviceIdForAuth();

            const bindingRes = await fetch(`${API_BASE}/api/v2/device/check-binding`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ deviceId })
            });
            const bindingData = await readApiResponse(bindingRes);
            if (!bindingRes.ok) throw new Error(bindingData?.detail || '设备校验失败');

            const inviteRes = await fetch(`${API_BASE}/api/v2/invite/validate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ inviteCode })
            });
            const inviteData = await readApiResponse(inviteRes);
            if (!inviteRes.ok || !inviteData?.isValid) {
                throw new Error(inviteData?.detail || '邀请码不存在或格式不正确');
            }

            const res = await fetch(`${API_BASE}/api/v2/auth/register`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, passwordConfirm: confirm, inviteCode, deviceId, grade: grade || undefined })
            });
            const data = await readApiResponse(res);
            if (!res.ok) throw new Error(data?.detail || data?.message || '注册失败');

            await setAuthStateFromV2(data, true);
            if (window.xsyyEnhancer?.recordAgreementAccepted && data.user?.userId) {
                window.xsyyEnhancer.recordAgreementAccepted(data.user.userId);
            }
            if (successEl) { successEl.textContent = '注册成功，已自动登录'; successEl.classList.add('show'); }

            return false;
        } catch (err) {
            if (errorEl) { errorEl.textContent = err.message; errorEl.classList.add('show'); }
            return false;
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '注册'; }
        }
    };
})();
