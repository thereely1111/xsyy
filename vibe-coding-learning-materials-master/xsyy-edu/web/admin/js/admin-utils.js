/**
 * 管理后台共享工具函数
 */

/**
 * 标准化 HTML 转义函数
 * 用于安全地将用户生成的内容插入 HTML。
 * 转义: & < > " '
 */
function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * 分 → 元（金额展示）
 */
function fenToYuan(fen) {
    return ((fen || 0) / 100).toFixed(2);
}

/**
 * 计算「返回首页」应跳转的地址。
 *
 * 管理后台通常由后端独立托管（可能是非标准端口，如 :808），
 * 而网站首页位于站点标准 https 入口（如 https://xsyy.top/ 或 https://wxyfb.tipdm.net/）。
 * 若直接用相对路径 ../index.html，会被解析到后端根路径而非首页。
 * 因此：
 *   - 非本地环境：跳转到「同主机名的 https 标准入口」，兼容各公网部署；
 *   - 本地开发（localhost/127.0.0.1）：后端已挂载 web 根，沿用相对路径。
 */
function xsyyHomeUrl() {
    var host = window.location.hostname;
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1') {
        return '../index.html?v=3';
    }
    return 'https://' + host + '/';
}

/** 程序化跳转到首页 */
function xsyyGoHome() {
    window.location.href = xsyyHomeUrl();
}

// 统一接管「返回首页」链接（.btn-home / .login-home-link），避免跳到后端根路径
(function fixHomeLinks() {
    function bind() {
        document.querySelectorAll('a.btn-home, a.login-home-link').forEach(function (a) {
            if (a.getAttribute('data-home-bound')) return;
            a.setAttribute('data-home-bound', '1');
            a.href = xsyyHomeUrl();
            a.addEventListener('click', function (e) {
                e.preventDefault();
                xsyyGoHome();
            });
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }
})();

// ══════════ 软弹窗（Toast）：自动消失，无需强制点击 ══════════
// 与首页「动画生成任务创建成功」提示一致：右上角滑入、自动关闭。
// 挂载为 window.showToast，admin 各页面（含 admin-feedbacks.js 的反馈模块）统一使用。
if (!window._adminToastContainer) {
    window._adminToastContainer = null;
}

function adminToastInit() {
    if (window._adminToastContainer) return;
    window._adminToastContainer = document.getElementById('toast-container');
    if (!window._adminToastContainer) {
        window._adminToastContainer = document.createElement('div');
        window._adminToastContainer.id = 'toast-container';
        Object.assign(window._adminToastContainer.style, {
            position: 'fixed',
            top: '16px',
            right: '16px',
            zIndex: '99999',
            pointerEvents: 'none'
        });
        document.body.appendChild(window._adminToastContainer);
    }
}

/**
 * 软弹窗提示
 * @param {string} message 提示内容
 * @param {'success'|'error'|'warn'|'info'} [type=info] 类型
 * @param {number} [timeout=4500] 自动关闭毫秒数（下限 4.5s）
 */
function adminShowToast(message, type = 'info', timeout = 4500) {
    adminToastInit();
    if (!window._adminToastContainer) return;
    // 延长显示时长：至少 4.5s（覆盖调用处传的较短时长），但始终不拦截点击，确保不遮挡其他功能
    timeout = Math.max(Number(timeout) || 4500, 4500);

    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
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
        pointerEvents: 'none',
        boxShadow: '0 2px 8px rgba(0,0,0,0.18)'
    });

    switch (type) {
        case 'success':
            toast.style.background = '#27ae60';
            break;
        case 'error':
            toast.style.background = '#e74c3c';
            break;
        case 'warn':
            toast.style.background = '#f39c12';
            break;
        default:
            toast.style.background = '#2c3e50';
    }
    toast.style.color = '#fff';

    window._adminToastContainer.appendChild(toast);
    window.setTimeout(function () {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        window.setTimeout(function () { toast.remove(); }, 250);
    }, timeout);
}

if (!window.showToast) {
    window.showToast = adminShowToast;
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', adminToastInit);
} else {
    adminToastInit();
}
