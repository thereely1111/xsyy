let auth = {
    isAuthenticated() {
        const token = localStorage.getItem('access_token');
        if (!token) return false;

        const expiry = localStorage.getItem('token_expiry');
        if (expiry && Date.now() > parseInt(expiry)) {
            this.logout();
            return false;
        }

        return true;
    },

    getToken() {
        return localStorage.getItem('access_token');
    },

    getRefreshToken() {
        return localStorage.getItem('refresh_token');
    },

    setTokens(accessToken, refreshToken, expiresIn) {
        localStorage.setItem('access_token', accessToken);
        localStorage.setItem('refresh_token', refreshToken);
        localStorage.setItem('token_expiry', Date.now() + expiresIn * 1000);
    },

    logout() {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('token_expiry');
        localStorage.removeItem('username');
    },

    async refreshAccessToken() {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) {
            this.logout();
            return false;
        }

        try {
            const response = await api.auth.refresh(refreshToken);
            if (response.data.access_token) {
                this.setTokens(
                    response.data.access_token,
                    response.data.refresh_token,
                    response.data.expires_in
                );
                return true;
            }
        } catch (error) {
            console.error('Token refresh failed:', error);
            this.logout();
        }
        return false;
    },

    getCurrentUser() {
        return new Promise((resolve, reject) => {
            const token = this.getToken();
            if (!token) {
                reject(new Error('No token'));
                return;
            }

            api.auth.me()
                .then(response => resolve(response.data))
                .catch(error => {
                    if (error.message.includes('401')) {
                        this.refreshAccessToken()
                            .then(success => {
                                if (success) {
                                    api.auth.me()
                                        .then(response => resolve(response.data))
                                        .catch(reject);
                                } else {
                                    reject(new Error('Authentication failed'));
                                }
                            })
                            .catch(reject);
                    } else {
                        reject(error);
                    }
                });
        });
    }
};

function initAuth() {
    const token = auth.getToken();
    if (token) {
        updateAuthUIForLoggedInUser();
    } else {
        updateAuthUIForGuest();
    }

    setupAuthInterceptor();
}

function updateAuthUIForLoggedInUser() {
    const authButtons = document.getElementById('authButtons');
    const userMenu = document.getElementById('userMenu');
    const usernameDisplay = document.getElementById('usernameDisplay');

    if (authButtons && userMenu) {
        authButtons.classList.add('hidden');
        authButtons.classList.remove('flex');
        userMenu.classList.remove('hidden');
        userMenu.classList.add('flex');

        const username = localStorage.getItem('username');
        if (usernameDisplay) {
            usernameDisplay.textContent = username || '';
        }
    }
}

function updateAuthUIForGuest() {
    const authButtons = document.getElementById('authButtons');
    const userMenu = document.getElementById('userMenu');

    if (authButtons && userMenu) {
        authButtons.classList.remove('hidden');
        authButtons.classList.add('flex');
        userMenu.classList.add('hidden');
        userMenu.classList.remove('flex');
    }
}

function setupAuthInterceptor() {
    const originalFetch = window.fetch;
    window.fetch = async function(url, options = {}) {
        const token = auth.getToken();

        if (token && !url.includes('/auth/')) {
            options.headers = {
                ...options.headers,
                'Authorization': `Bearer ${token}`
            };
        }

        const response = await originalFetch(url, options);

        if (response.status === 401 && !url.includes('/auth/')) {
            const refreshed = await auth.refreshAccessToken();
            if (refreshed) {
                const newToken = auth.getToken();
                options.headers = {
                    ...options.headers,
                    'Authorization': `Bearer ${newToken}`
                };
                return originalFetch(url, options);
            } else {
                window.location.href = '/?login_required=true';
            }
        }

        return response;
    };
}

function requireAuth() {
    if (!auth.isAuthenticated()) {
        window.location.href = '/?login_required=true';
        return false;
    }
    return true;
}

function requireRole(...roles) {
    if (!requireAuth()) return false;

    const userRole = localStorage.getItem('user_role');
    if (!roles.includes(userRole)) {
        window.location.href = '/';
        return false;
    }
    return true;
}

window.auth = auth;
window.initAuth = initAuth;
window.requireAuth = requireAuth;
window.requireRole = requireRole;
