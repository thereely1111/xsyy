const API_BASE = 'http://localhost:8000/api/v1';

const api = {
    async request(endpoint, options = {}) {
        const url = `${API_BASE}${endpoint}`;
        const token = localStorage.getItem('access_token');
        
        // 提取自定义选项
        const { 
            showLoading = false, 
            loadingText = '加载中...',
            showSuccessToast = false,
            successMessage = '操作成功',
            showErrorToast = true,
            ...fetchOptions 
        } = options;

        const headers = {
            'Content-Type': 'application/json',
            ...fetchOptions.headers
        };

        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        // 显示全屏 loading
        if (showLoading && typeof window.showFullscreenLoading === 'function') {
            window.showFullscreenLoading(loadingText);
        }

        try {
            const response = await fetch(url, {
                ...fetchOptions,
                headers
            });

            const data = response.json ? await response.json() : {};

            if (!response.ok) {
                const errorMessage = data.detail?.message || data.detail || '请求失败';
                throw new Error(errorMessage);
            }

            // 显示成功提示
            if (showSuccessToast && typeof window.showToast === 'function') {
                window.showToast(successMessage, 'success');
            }

            return data;
        } catch (error) {
            console.error('API Error:', error);
            
            // 显示错误提示
            if (showErrorToast && typeof window.showToast === 'function') {
                window.showToast(error.message || '操作失败', 'error');
            }
            
            throw error;
        } finally {
            // 隐藏全屏 loading
            if (showLoading && typeof window.hideFullscreenLoading === 'function') {
                window.hideFullscreenLoading();
            }
        }
    },

    auth: {
        async login(data, options = {}) {
            return api.request('/auth/login', {
                method: 'POST',
                body: JSON.stringify(data),
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '登录成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async register(data, options = {}) {
            return api.request('/auth/register', {
                method: 'POST',
                body: JSON.stringify(data),
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '注册成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async logout(options = {}) {
            return api.request('/auth/logout', {
                method: 'POST',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '已退出登录',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async refresh(token, options = {}) {
            return api.request('/auth/refresh', {
                method: 'POST',
                body: JSON.stringify({ refresh_token: token }),
                ...options
            });
        },

        async me(options = {}) {
            return api.request('/auth/me', options);
        }
    },

    problems: {
        async create(data, options = {}) {
            return api.request('/problems', {
                method: 'POST',
                body: JSON.stringify(data),
                showLoading: options.showLoading !== false,
                loadingText: options.loadingText || '正在创建题目...',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '题目创建成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async list(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/problems${query ? '?' + query : ''}`, options);
        },

        async get(id, options = {}) {
            return api.request(`/problems/${id}`, options);
        },

        async analyze(content, options = {}) {
            return api.request('/problems/analyze', {
                method: 'POST',
                body: JSON.stringify({ content }),
                showLoading: options.showLoading !== false,
                loadingText: options.loadingText || 'AI 正在分析题目...',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '分析完成',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        getTaskStatus(taskId, options = {}) {
            return api.request(`/problems/tasks/${taskId}`, options);
        }
    },

    applications: {
        async generate(data, options = {}) {
            return api.request('/applications/generate', {
                method: 'POST',
                body: JSON.stringify(data),
                showLoading: options.showLoading !== false,
                loadingText: options.loadingText || 'AI 正在生成教学应用...',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '生成成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async list(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/applications${query ? '?' + query : ''}`, options);
        },

        async get(id, options = {}) {
            return api.request(`/applications/${id}`, options);
        },

        getStatus(id, options = {}) {
            return api.request(`/applications/${id}/status`, options);
        },

        async download(id, options = {}) {
            const token = localStorage.getItem('access_token');
            
            if (options.showLoading !== false && typeof window.showFullscreenLoading === 'function') {
                window.showFullscreenLoading(options.loadingText || '正在下载...');
            }

            try {
                const response = await fetch(`${API_BASE}/applications/${id}/download`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.detail?.message || data.detail || '下载失败');
                }

                if (options.showSuccessToast !== false && typeof window.showToast === 'function') {
                    window.showToast(options.successMessage || '下载成功', 'success');
                }

                return response.blob();
            } catch (error) {
                console.error('Download Error:', error);
                
                if (options.showErrorToast !== false && typeof window.showToast === 'function') {
                    window.showToast(error.message || '下载失败', 'error');
                }
                
                throw error;
            } finally {
                if (options.showLoading !== false && typeof window.hideFullscreenLoading === 'function') {
                    window.hideFullscreenLoading();
                }
            }
        }
    },

    comments: {
        async create(data, options = {}) {
            return api.request('/comments', {
                method: 'POST',
                body: JSON.stringify(data),
                showLoading: options.showLoading !== false,
                loadingText: options.loadingText || '正在发表评论...',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '评论发表成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async list(applicationId, params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/comments/application/${applicationId}${query ? '?' + query : ''}`, options);
        },

        async delete(id, options = {}) {
            return api.request(`/comments/${id}`, {
                method: 'DELETE',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '删除成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        }
    },

    users: {
        async profile(options = {}) {
            return api.request('/users/profile', options);
        },

        async updateProfile(data, options = {}) {
            return api.request('/users/profile', {
                method: 'PATCH',
                body: JSON.stringify(data),
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '更新成功',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async favorites(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/users/favorites${query ? '?' + query : ''}`, options);
        },

        async addFavorite(applicationId, options = {}) {
            return api.request(`/users/favorites/${applicationId}`, {
                method: 'POST',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '已添加收藏',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async removeFavorite(applicationId, options = {}) {
            return api.request(`/users/favorites/${applicationId}`, {
                method: 'DELETE',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '已取消收藏',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async addLike(applicationId, options = {}) {
            return api.request(`/users/likes/${applicationId}`, {
                method: 'POST',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '已点赞',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async removeLike(applicationId, options = {}) {
            return api.request(`/users/likes/${applicationId}`, {
                method: 'DELETE',
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || '已取消点赞',
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        },

        async myWorks(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/users/works${query ? '?' + query : ''}`, options);
        }
    },

    recommend: {
        async similar(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/recommend/similar${query ? '?' + query : ''}`, options);
        },

        async popular(limit = 8, options = {}) {
            return api.request(`/recommend/popular?limit=${limit}`, options);
        },

        async latest(limit = 8, options = {}) {
            return api.request(`/recommend/latest?limit=${limit}`, options);
        }
    },

    admin: {
        async dashboard(options = {}) {
            return api.request('/admin/dashboard', options);
        },

        async users(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/admin/users${query ? '?' + query : ''}`, options);
        },

        async pendingApplications(params = {}, options = {}) {
            const query = new URLSearchParams(params).toString();
            return api.request(`/admin/applications/pending${query ? '?' + query : ''}`, options);
        },

        async auditApplication(id, approved, message, options = {}) {
            return api.request(`/admin/applications/${id}/audit`, {
                method: 'POST',
                body: JSON.stringify({ approved, message }),
                showSuccessToast: options.showSuccessToast !== false,
                successMessage: options.successMessage || (approved ? '已通过审核' : '已拒绝'),
                showErrorToast: options.showErrorToast !== false,
                ...options
            });
        }
    },

    tasks: {
        getStatus(taskId, options = {}) {
            return api.request(`/tasks/${taskId}`, options);
        }
    },

    async getCurrentUser(options = {}) {
        return api.auth.me(options);
    }
};

window.api = api;