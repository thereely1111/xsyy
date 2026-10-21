/**
 * 管理后台认证模块
 */

/**
 * 检查管理员权限并重定向
 */
async function checkAdminAuth() {
    const token = getToken();
    if (!token) {
        // 未登录，重定向到登录页
        if (!window.location.pathname.endsWith('/admin/index.html') &&
            !window.location.pathname.endsWith('/admin/')) {
            window.location.href = 'index.html';
        }
        return false;
    }
    
    try {
        const result = await checkAdmin();
        if (!result.is_admin) {
            // 不是管理员，重定向到登录页
            if (typeof window.showToast === 'function') {
                window.showToast('您没有管理员权限', 'warn', 2600);
            } else {
                alert('您没有管理员权限');
            }
            removeToken();
            window.location.href = 'index.html';
            return false;
        }
        return true;
    } catch (error) {
        console.error('检查管理员权限失败:', error);
        // 可能是token过期，清除token并重定向
        removeToken();
        if (!window.location.pathname.endsWith('/admin/index.html') &&
            !window.location.pathname.endsWith('/admin/')) {
            window.location.href = 'index.html';
        }
        return false;
    }
}

/**
 * 退出登录
 */
function logout() {
    if (confirm('确定要退出登录吗？')) {
        removeToken();
        window.location.href = 'index.html';
    }
}

/**
 * 初始化认证检查（在需要管理员权限的页面调用）
 */
async function initAdminAuth() {
    // 如果是登录页，不需要检查
    if (window.location.pathname.includes('index.html') || 
        window.location.pathname.endsWith('/admin/')) {
        return;
    }
    
    // 检查管理员权限
    const isAdmin = await checkAdminAuth();
    if (!isAdmin) {
        return;
    }
    
    // 更新用户信息显示
    try {
        const adminInfo = await checkAdmin();
        const userInfoElement = document.getElementById('userInfo');
        if (userInfoElement) {
            userInfoElement.textContent = adminInfo.username;
        }
    } catch (error) {
        console.error('获取管理员信息失败:', error);
    }
}

