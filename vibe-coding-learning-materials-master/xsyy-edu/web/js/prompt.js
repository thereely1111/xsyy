// 不再使用顶层let，挂载到window全局对象，防止重复let报错
if (!window._toastContainer) {
    window._toastContainer = null;
}

function initToastContainer() {
    if (window._toastContainer) return;

    window._toastContainer = document.getElementById('toast-container');
    if (!window._toastContainer) {
        window._toastContainer = document.createElement('div');
        window._toastContainer.id = 'toast-container';
        Object.assign(window._toastContainer.style, {
            position: 'fixed',
            top: '16px',
            right: '16px',
            zIndex: '99999',
            pointerEvents: 'none'
        });
        document.body.appendChild(window._toastContainer);
    }
}

function showToast(message, type = 'info', timeout = 4500) {
    initToastContainer();
    if (!window._toastContainer) return;
    // 延长显示时长：至少 4.5s（覆盖调用处传的较短时长），但始终不拦截点击，确保不遮挡其他功能
    timeout = Math.max(Number(timeout) || 4500, 4500);

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;

    const baseStyle = {
        padding: '10px 18px',
        marginBottom: '8px',
        borderRadius: '6px',
        minWidth: '140px',
        maxWidth: '320px',
        opacity: '1',
        transform: 'translateY(0)',
        transition: 'all 0.25s ease',
        pointerEvents: 'none'
    };
    Object.assign(toast.style, baseStyle);

    switch (type) {
        case 'success':
            toast.style.background = '#27ae60';
            toast.style.color = '#fff';
            break;
        case 'error':
            toast.style.background = '#e74c3c';
            toast.style.color = '#fff';
            break;
        case 'warn':
            toast.style.background = '#f39c12';
            toast.style.color = '#fff';
            break;
        default:
            toast.style.background = '#2c3e50';
            toast.style.color = '#fff';
    }

    window._toastContainer.appendChild(toast);

    window.setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        window.setTimeout(() => toast.remove(), 250);
    }, timeout);
}

// 防止重复挂载函数
if (!window.showToast) {
    window.showToast = showToast;
}

// 全局拦截原生 alert → 软提示 toast：不再弹出需点击『确定』的黑底硬弹窗。
// 拦截后无论哪处调用 alert() 都显示为 toast，避免遗漏切换。
if (window.alert && !window._xsAlertPatched) {
    window._xsAlertPatched = true;
    window.alert = function (msg) {
        if (typeof window.showToast === 'function') {
            window.showToast(String(msg), 'warn', 3200);
        } else {
            console.log(String(msg));
        }
    };
}

// DOM就绪初始化
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initToastContainer);
} else {
    initToastContainer();
}