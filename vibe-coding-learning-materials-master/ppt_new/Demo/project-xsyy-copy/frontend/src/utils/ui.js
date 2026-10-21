function showToast(message, type = 'info') {
    const toast = document.getElementById('messageToast');
    if (!toast) return;

    const colors = {
        success: 'bg-green-500 text-white',
        error: 'bg-red-500 text-white',
        warning: 'bg-yellow-500 text-white',
        info: 'bg-xsyy-blue text-white'
    };

    toast.className = `fixed bottom-8 right-8 px-6 py-4 rounded-xl shadow-lg transition-all duration-300 z-50 ${colors[type] || colors.info}`;
    toast.textContent = message;

    toast.classList.remove('translate-y-full', 'opacity-0');
    toast.classList.add('translate-y-0', 'opacity-100');

    setTimeout(() => {
        toast.classList.add('translate-y-full', 'opacity-0');
        toast.classList.remove('translate-y-0', 'opacity-100');
    }, 3000);
}

function showLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.innerHTML = '<div class="flex items-center justify-center py-8"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-xsyy-blue"></div></div>';
    }
}

function hideLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        const loadingElement = element.querySelector('.animate-spin');
        if (loadingElement) {
            element.innerHTML = '';
        }
    }
}

function showProgressBar(containerId, progress = 0) {
    let container = document.getElementById(containerId);
    if (!container) {
        container = document.createElement('div');
        container.id = containerId;
        container.className = 'w-full bg-gray-200 rounded-full h-4 overflow-hidden';
        document.body.appendChild(container);
    }

    container.innerHTML = `
        <div class="bg-xsyy-gold h-4 rounded-full transition-all duration-300" style="width: ${progress}%"></div>
        <div class="text-center mt-1 text-sm text-gray-600">${progress}%</div>
    `;

    return container;
}

function updateProgress(containerId, progress) {
    const container = document.getElementById(containerId);
    if (container) {
        const bar = container.querySelector('.bg-xsyy-gold');
        const text = container.querySelector('.text-center');
        if (bar) bar.style.width = `${progress}%`;
        if (text) text.textContent = `${progress}%`;
    }
}

function hideProgress(containerId) {
    const container = document.getElementById(containerId);
    if (container) {
        container.remove();
    }
}

async function pollTaskStatus(taskId, callback, interval = 2000) {
    const poll = async () => {
        try {
            const response = await api.tasks.getStatus(taskId);
            const data = response.data;

            callback(data);

            if (data.status === 'pending' || data.status === 'processing') {
                setTimeout(poll, interval);
            }
        } catch (error) {
            console.error('Polling error:', error);
            callback({ status: 'error', error_message: error.message });
        }
    };

    await poll();
}

function renderMarkdown(text) {
    if (!text) return '';

    return text
        .replace(/^### (.*$)/gim, '<h3 class="text-lg font-bold text-xsyy-blue mt-4 mb-2">$1</h3>')
        .replace(/^## (.*$)/gim, '<h2 class="text-xl font-bold text-xsyy-blue mt-6 mb-3">$1</h2>')
        .replace(/^# (.*$)/gim, '<h1 class="text-2xl font-bold text-xsyy-blue mt-8 mb-4">$1</h1>')
        .replace(/\*\*(.*)\*\*/gim, '<strong class="font-bold">$1</strong>')
        .replace(/\*(.*)\*/gim, '<em class="italic">$1</em>')
        .replace(/\n/gim, '<br>');
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

function formatDateTime(dateString) {
    const date = new Date(dateString);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('已复制到剪贴板', 'success');
        }).catch(err => {
            console.error('Failed to copy:', err);
            showToast('复制失败', 'error');
        });
    } else {
        const textarea = document.createElement('textarea');
        textarea.value = text;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        showToast('已复制到剪贴板', 'success');
    }
}

function downloadBlob(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}

window.showToast = showToast;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.showProgressBar = showProgressBar;
window.updateProgress = updateProgress;
window.hideProgress = hideProgress;
window.pollTaskStatus = pollTaskStatus;
window.renderMarkdown = renderMarkdown;
window.formatDate = formatDate;
window.formatDateTime = formatDateTime;
window.debounce = debounce;
window.throttle = throttle;
window.copyToClipboard = copyToClipboard;
window.downloadBlob = downloadBlob;
