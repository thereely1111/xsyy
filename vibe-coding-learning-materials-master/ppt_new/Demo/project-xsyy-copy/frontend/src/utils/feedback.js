// ====================
// 全局操作反馈系统
// ====================

let loadingLayer = null;
let toastContainer = null;
let toastQueue = [];
let isShowingToast = false;

// ====================
// 全屏 Loading 动画
// ====================

export function showFullscreenLoading(text = '加载中...') {
    if (loadingLayer) return;
    
    loadingLayer = document.createElement('div');
    loadingLayer.className = 'fixed inset-0 bg-black/50 z-50 flex items-center justify-center transition-opacity duration-200';
    loadingLayer.style.opacity = '0';
    
    loadingLayer.innerHTML = `
        <div class="bg-white rounded-3xl p-8 shadow-2xl flex flex-col items-center space-y-4 min-w-[280px]">
            <div class="relative">
                <div class="w-12 h-12 border-4 border-[#a3d9ff] border-t-[#1a365d] rounded-full animate-spin"></div>
                <div class="absolute inset-0 w-12 h-12 border-4 border-transparent border-b-[#1a365d] rounded-full animate-spin" style="animation-direction: reverse; animation-duration: 1.5s;"></div>
            </div>
            <p class="text-[#1a365d] font-medium text-base">${text}</p>
            <div class="w-full h-1 bg-gray-200 rounded-full overflow-hidden">
                <div class="h-full bg-gradient-to-r from-[#a3d9ff] to-[#1a365d] rounded-full animate-pulse"></div>
            </div>
        </div>
    `;
    
    document.body.appendChild(loadingLayer);
    
    requestAnimationFrame(() => {
        loadingLayer.style.opacity = '1';
    });
    
    // 点击蒙层不关闭，只能通过 hideFullscreenLoading() 关闭
    loadingLayer.addEventListener('click', (e) => {
        e.stopPropagation();
    });
}

export function hideFullscreenLoading() {
    if (!loadingLayer) return;
    
    loadingLayer.style.opacity = '0';
    
    setTimeout(() => {
        if (loadingLayer && loadingLayer.parentNode) {
            loadingLayer.parentNode.removeChild(loadingLayer);
            loadingLayer = null;
        }
    }, 200);
}

// ====================
// Toast 提示系统
// ====================

function createToastContainer() {
    if (toastContainer) return;
    
    toastContainer = document.createElement('div');
    toastContainer.className = 'fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex flex-col gap-3';
    document.body.appendChild(toastContainer);
}

function getToastStyles(type) {
    const styles = {
        success: {
            bg: 'bg-gradient-to-r from-green-400 to-green-500',
            icon: '✓',
            textColor: 'text-white'
        },
        error: {
            bg: 'bg-gradient-to-r from-red-400 to-red-500',
            icon: '✕',
            textColor: 'text-white'
        },
        warning: {
            bg: 'bg-gradient-to-r from-yellow-400 to-orange-400',
            icon: '⚠',
            textColor: 'text-gray-800'
        },
        info: {
            bg: 'bg-gradient-to-r from-[#a3d9ff] to-[#1a365d]',
            icon: 'ℹ',
            textColor: 'text-white'
        }
    };
    
    return styles[type] || styles.info;
}

function createToastElement(message, type) {
    const style = getToastStyles(type);
    const toast = document.createElement('div');
    
    toast.className = `${style.bg} ${style.textColor} px-6 py-3 rounded-[32px] shadow-lg flex items-center gap-3 min-w-[200px] max-w-[400px] transition-all duration-300 transform translate-y-full opacity-0`;
    
    toast.innerHTML = `
        <span class="text-lg font-bold">${style.icon}</span>
        <span class="font-medium text-sm">${message}</span>
    `;
    
    return toast;
}

function showNextToast() {
    if (isShowingToast || toastQueue.length === 0) return;
    
    isShowingToast = true;
    const { message, type, duration } = toastQueue.shift();
    
    createToastContainer();
    
    const toast = createToastElement(message, type);
    toastContainer.appendChild(toast);
    
    // 显示动画
    requestAnimationFrame(() => {
        toast.style.transform = 'translateY(0)';
        toast.style.opacity = '1';
    });
    
    // 自动消失
    setTimeout(() => {
        toast.style.transform = 'translateY(20px)';
        toast.style.opacity = '0';
        
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            isShowingToast = false;
            showNextToast();
        }, 300);
    }, duration);
}

export function showToast(message, type = 'success') {
    const durations = {
        success: 2500,
        error: 3500,
        warning: 3000,
        info: 2500
    };
    
    toastQueue.push({
        message,
        type,
        duration: durations[type] || 2500
    });
    
    showNextToast();
}

// ====================
// 按钮状态管理
// ====================

export function disableButton(button, loadingText = '处理中...') {
    if (!button) return;
    
    button.disabled = true;
    button.classList.add('opacity-60', 'cursor-not-allowed');
    
    // 保存原始内容
    button._originalContent = button.innerHTML;
    
    // 显示加载状态
    button.innerHTML = `
        <span class="flex items-center gap-2">
            <span class="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin"></span>
            ${loadingText}
        </span>
    `;
}

export function enableButton(button) {
    if (!button) return;
    
    button.disabled = false;
    button.classList.remove('opacity-60', 'cursor-not-allowed');
    
    // 恢复原始内容
    if (button._originalContent !== undefined) {
        button.innerHTML = button._originalContent;
        delete button._originalContent;
    }
}

// ====================
// 表单状态管理
// ====================

export function disableForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    const inputs = form.querySelectorAll('input, textarea, select, button');
    inputs.forEach(element => {
        if (element.tagName === 'BUTTON') {
            disableButton(element);
        } else {
            element.readOnly = true;
            element.classList.add('opacity-60', 'cursor-not-allowed');
        }
    });
}

export function enableForm(formId) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    const inputs = form.querySelectorAll('input, textarea, select, button');
    inputs.forEach(element => {
        if (element.tagName === 'BUTTON') {
            enableButton(element);
        } else {
            element.readOnly = false;
            element.classList.remove('opacity-60', 'cursor-not-allowed');
        }
    });
}

// ====================
// 页面过渡效果
// ====================

export function fadeOutPage(callback) {
    const body = document.body;
    body.style.opacity = '1';
    body.style.transition = 'opacity 0.3s ease';
    
    setTimeout(() => {
        body.style.opacity = '0';
        
        setTimeout(() => {
            if (callback) callback();
        }, 300);
    }, 100);
}

export function fadeInPage() {
    const body = document.body;
    body.style.opacity = '0';
    body.style.transition = 'opacity 0.3s ease';
    
    requestAnimationFrame(() => {
        body.style.opacity = '1';
    });
}

// ====================
// 批量导出到全局
// ====================

window.showFullscreenLoading = showFullscreenLoading;
window.hideFullscreenLoading = hideFullscreenLoading;
window.showToast = showToast;
window.disableButton = disableButton;
window.enableButton = enableButton;
window.disableForm = disableForm;
window.enableForm = enableForm;
window.fadeOutPage = fadeOutPage;
window.fadeInPage = fadeInPage;