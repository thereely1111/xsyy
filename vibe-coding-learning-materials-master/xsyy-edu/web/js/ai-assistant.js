let assistantStorageUserId = null;

function getUserId(user) {
    if (!user) return '';
    return String(user.user_id || user.userId || user.id || '').trim();
}

function getStorageKey() {
    const taskId = getPageId();
    if (!assistantStorageUserId) return '';
    return `xsyy_ai_assistant_state_v3_${encodeURIComponent(assistantStorageUserId)}_${encodeURIComponent(taskId)}`;
}
const AI_MAX_TURNS = 5;

function createStore(initialState) {
    let state = { ...initialState };
    const listeners = [];
    return {
        getState() {
            return state;
        },
        setState(partial) {
            state = { ...state, ...partial };
            listeners.forEach((listener) => listener(state));
        },
        subscribe(listener) {
            listeners.push(listener);
            return () => {
                const idx = listeners.indexOf(listener);
                if (idx >= 0) listeners.splice(idx, 1);
            };
        },
    };
}

const aiStore = createStore({
    isLoggedIn: false,
    user: null,
    panelOpen: false,
    loading: false,
    sessions: [],
    currentSessionId: null,
});

function safeJsonParse(text, fallback) {
    try {
        return JSON.parse(text);
    } catch (_) {
        return fallback;
    }
}

function getApiBase() {
    return window.API_BASE || '';
}

function getAuthToken() {
    return localStorage.getItem('auth_token') || '';
}

function clearAuth() {
    localStorage.removeItem('auth_token');
    resetAssistantState();
}

function genSessionId() {
    return `sess_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function getPageId() {
    const params = new URLSearchParams(window.location.search);
    return params.get('task_id') || params.get('id') || window.location.pathname || 'video-page';
}

function normalizeExtractedText(text) {
    return (text || '')
        .replace(/\r/g, '\n')
        .replace(/\t/g, ' ')
        .replace(/[ \u00A0]+/g, ' ')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
}

function buildStepOutline(text) {
    const normalized = normalizeExtractedText(text);
    if (!normalized) return '';

    const stepRegex = /(第\s*[零一二两三四五六七八九十\d]+\s*步[：:]?|步骤\s*[零一二两三四五六七八九十\d]+[：:]?|Step\s*\d+[：:]?)/gi;
    const matches = [...normalized.matchAll(stepRegex)];
    if (!matches.length) return '';

    const blocks = [];
    for (let i = 0; i < matches.length; i += 1) {
        const start = matches[i].index || 0;
        const end = i + 1 < matches.length ? (matches[i + 1].index || normalized.length) : normalized.length;
        const segment = normalized.slice(start, end).trim();
        if (!segment) continue;
        blocks.push(segment.slice(0, 260));
        if (blocks.length >= 10) break;
    }

    if (!blocks.length) return '';
    return ['【解题步骤索引】', ...blocks.map((line) => `- ${line}`)].join('\n');
}

function extractPageContent() {
    const preferredSelectors = [
        '#teaching-html-container',
        '.teaching-content',
        '#mainTeachingContainer',
    ];

    for (const selector of preferredSelectors) {
        const node = document.querySelector(selector);
        if (node && node.innerText && node.innerText.trim().length > 50) {
            const content = normalizeExtractedText(node.innerText);
            const stepOutline = buildStepOutline(content);
            const merged = stepOutline ? `${stepOutline}\n\n【教学正文】\n${content}` : content;
            return merged.slice(0, 8000);
        }
    }

    const fallback = normalizeExtractedText(document.body.innerText || '');
    const stepOutline = buildStepOutline(fallback);
    const merged = stepOutline ? `${stepOutline}\n\n【教学正文】\n${fallback}` : fallback;
    return merged.slice(0, 8000);
}

function persistState() {
    const storageKey = getStorageKey();
    if (!storageKey) return;
    const state = aiStore.getState();
    const payload = {
        sessions: state.sessions,
        currentSessionId: state.currentSessionId,
        panelOpen: state.panelOpen,
    };
    localStorage.setItem(storageKey, JSON.stringify(payload));
}

function restoreState() {
    const storageKey = getStorageKey();
    if (!storageKey) return;
    const raw = localStorage.getItem(storageKey);
    if (!raw) return;
    const parsed = safeJsonParse(raw, null);
    if (!parsed || !Array.isArray(parsed.sessions)) return;
    aiStore.setState({
        sessions: parsed.sessions,
        currentSessionId: parsed.currentSessionId || (parsed.sessions[0] && parsed.sessions[0].id) || null,
        panelOpen: !!parsed.panelOpen,
    });
}

function resetAssistantState() {
    aiStore.setState({
        sessions: [],
        currentSessionId: null,
        panelOpen: false,
        loading: false,
    });
}

function applyAuthResult(authResult) {
    const nextUserId = getUserId(authResult.user);
    const accountChanged = assistantStorageUserId !== nextUserId;
    assistantStorageUserId = nextUserId || null;

    if (accountChanged) {
        resetAssistantState();
        if (assistantStorageUserId) restoreState();
    }

    aiStore.setState({
        isLoggedIn: authResult.isLoggedIn,
        user: authResult.user,
    });
}

function clearAssistantPersistence() {
    const storageKey = getStorageKey();
    if (storageKey) localStorage.removeItem(storageKey);
}

function getCurrentSession() {
    const state = aiStore.getState();
    return state.sessions.find((session) => session.id === state.currentSessionId) || null;
}

function upsertSession(updatedSession) {
    const state = aiStore.getState();
    const sessions = state.sessions.map((session) => (session.id === updatedSession.id ? updatedSession : session));
    aiStore.setState({ sessions });
    persistState();
}

function createNewSession(initialMessage) {
    const state = aiStore.getState();
    const nextIndex = state.sessions.length + 1;
    const session = {
        id: genSessionId(),
        title: `会话${nextIndex}`,
        sessionHash: '',
        coreSummary: '',
        turnCount: 0,
        messages: initialMessage ? [{ role: 'ai', content: initialMessage }] : [],
        createdAt: Date.now(),
        updatedAt: Date.now(),
    };
    aiStore.setState({
        sessions: [session, ...state.sessions].slice(0, 8),
        currentSessionId: session.id,
    });
    persistState();
    return session;
}

function replaceMessages(session, messages) {
    upsertSession({
        ...session,
        messages,
        updatedAt: Date.now(),
    });
}

function appendMessage(session, role, content) {
    const nextMessages = [...session.messages, { role, content }];
    replaceMessages(session, nextMessages);
}

function setTurnCount(session, turnCount) {
    upsertSession({
        ...session,
        turnCount,
        updatedAt: Date.now(),
    });
}

async function checkAuth() {
    const token = getAuthToken();
    if (!token) return { isLoggedIn: false, user: null };

    try {
        const response = await fetch(`${getApiBase()}/api/auth/me`, {
            headers: {
                Authorization: `Bearer ${token}`,
            },
        });
        // Token-first policy for UI gating:
        // backend endpoints still do hard auth checks, but the assistant button
        // should not be blocked by occasional /api/auth/me misclassification.
        if (response.ok) {
            const user = await response.json();
            return { isLoggedIn: true, user };
        }
        return { isLoggedIn: true, user: null };
    } catch (_) {
        return { isLoggedIn: !!getAuthToken(), user: null };
    }
}

async function apiFetchWithAuth(path, options = {}) {
    const token = getAuthToken();
    const headers = {
        ...(options.headers || {}),
        Authorization: `Bearer ${token}`,
    };

    const response = await fetch(`${getApiBase()}${path}`, {
        ...options,
        headers,
    });

    if (response.status === 401) {
        clearAuth();
        aiStore.setState({ isLoggedIn: false, loading: false });
        if (typeof window.showLoginModal === 'function') {
            window.showLoginModal();
        }
        throw new Error('401_UNAUTHORIZED');
    }

    return response;
}

async function apiJson(path, payload) {
    const options = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    if (payload && Object.keys(payload).length > 0) {
        options.method = 'POST';
        options.body = JSON.stringify(payload);
    } else {
        options.method = 'GET';
    }
    
    const response = await apiFetchWithAuth(path, options);

    if (!response.ok) {
        const detail = safeJsonParse(await response.text(), {}).detail || `请求失败(${response.status})`;
        throw new Error(detail);
    }

    return response.json();
}

function buildRecentHistory(messages) {
    return messages
        .filter((message) => message.role === 'user' || message.role === 'assistant')
        .slice(-4)
        .map((message) => ({ role: message.role, content: message.content }));
}

async function streamChat(payload, onChunk) {
    const response = await apiFetchWithAuth('/api/ai-teacher/chat', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body) {
        const detail = safeJsonParse(await response.text(), {}).detail || `请求失败(${response.status})`;
        throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    const result = { model: '', provider: '' };

    while (true) {
        const { value, done } = await reader.read();
        if (value) {
            buffer += decoder.decode(value, { stream: true });
        }
        
        // 处理buffer中的数据
        while (buffer.includes('\n\n')) {
            const splitIndex = buffer.indexOf('\n\n');
            const eventBlock = buffer.slice(0, splitIndex);
            buffer = buffer.slice(splitIndex + 2);

            const dataLine = eventBlock
                .split('\n')
                .find((line) => line.startsWith('data:'));
            if (!dataLine) continue;

            const rawPayload = dataLine.slice(5).trim();
            const parsed = safeJsonParse(rawPayload, null);
            if (!parsed) continue;

            if (parsed.type === 'chunk' && parsed.content) {
                onChunk(parsed.content);
            }
            if (parsed.type === 'error') {
                throw new Error(parsed.message || 'AI 服务异常');
            }
            if (parsed.type === 'done') {
                result.model = parsed.model || '';
                result.provider = parsed.provider || '';
                return result;
            }
        }
        
        if (done) break;
    }
    
    // 处理剩余的buffer数据
    if (buffer) {
        const dataLine = buffer
            .split('\n')
            .find((line) => line.startsWith('data:'));
        if (dataLine) {
            const rawPayload = dataLine.slice(5).trim();
            const parsed = safeJsonParse(rawPayload, null);
            if (parsed && parsed.type === 'chunk' && parsed.content) {
                onChunk(parsed.content);
            }
        }
    }
}

const aiChat = {
    
    async toggleHistory() {
        const overlay = document.getElementById('aiHistoryOverlay');
        if (!overlay) return;
        if (overlay.classList.contains('active')) {
            overlay.classList.remove('active');
            return;
        }
        overlay.classList.add('active');
        const contentDiv = document.getElementById('aiHistoryContent');
        contentDiv.innerHTML = '<div style="text-align:center;color:#999;padding:20px;">加载中...</div>';
        
        try {
            const taskId = getPageId();
            console.log('Loading history for taskId:', taskId);
            // 确保用户状态已同步
            await this.syncAuthStatus();
            const currentUser = aiStore.getState().user;
            console.log('Current user:', currentUser);
            
            const data = await apiJson(`/api/ai-teacher/history?pageId=${taskId}`, {});
            console.log('History data:', data);
            
            if (!data.history || data.history.length === 0) {
                contentDiv.innerHTML = '<div style="text-align:center;color:#999;margin-top:20px;">暂无其他历史记录</div>';
            } else {
                let html = '';
                data.history.forEach(item => {
                    let ans = item.answer;
                    if (window.marked) ans = window.marked.parse(ans);
                    // 简化判断，只要用户已登录就显示删除按钮
                    const isCurrentUser = currentUser;
                    console.log('History item:', item);
                    console.log('Is current user:', isCurrentUser);
                    
                    html += `<div class="ai-history-item">
                        <div class="ai-history-q">Q: ${item.question}</div>
                        <div class="ai-history-a">A: ${ans}</div>
                        <div class="ai-history-actions" style="display: flex; gap: 10px; margin-top: 10px; font-size: 12px;">
                            ${isCurrentUser ? `<button onclick="aiChat.deleteHistoryItem(${item.id})" style="background: transparent; border: 1px solid var(--primary-red); color: var(--primary-red); padding: 4px 8px; border-radius: 4px; cursor: pointer; transition: all 0.2s;">删除</button>` : ''}
                            <button onclick="aiChat.likeHistoryItem(${item.id})" style="background: transparent; border: 1px solid var(--primary-blue); color: var(--primary-blue); padding: 4px 8px; border-radius: 4px; cursor: pointer; transition: all 0.2s;">点赞 (${item.likes || 0})</button>
                        </div>
                    </div>`;
                });
                contentDiv.innerHTML = html;
                if (window.MathJax && window.MathJax.typesetPromise) {
                    setTimeout(() => window.MathJax.typesetPromise([contentDiv]), 50);
                }
            }
        } catch (e) {
            console.error('Failed to load history:', e);
            // 处理API不存在的情况，显示友好提示
            if (e.message.includes('Not Found') || e.message.includes('404')) {
                contentDiv.innerHTML = '<div style="text-align:center;color:#999;margin-top:20px;">暂无历史对话记录</div>';
            } else {
                contentDiv.innerHTML = `<div style="color:red;text-align:center;margin-top:20px;">加载失败: ${e.message || '未知错误'}</div>`;
            }
        }
    },

    async init() {
        const authResult = await checkAuth();
        applyAuthResult(authResult);

        if (aiStore.getState().panelOpen && aiStore.getState().sessions.length === 0) {
            aiStore.setState({ panelOpen: false });
        }

        this.render();
        aiStore.subscribe(() => this.render());
    },

    async syncAuthStatus() {
        const authResult = await checkAuth();
        applyAuthResult(authResult);
    },

    async handleAiAssistClick() {
        await this.syncAuthStatus();
        const state = aiStore.getState();

        if (!state.isLoggedIn) {
            if (typeof window.showLoginModal === 'function') {
                window.showLoginModal();
                return;
            }
            alert('请先登录后使用 AI 助教');
            return;
        }

        aiStore.setState({ panelOpen: true });
        let session = getCurrentSession();
        if (!session || state.sessions.length === 0) {
            session = createNewSession('正在初始化教学上下文，请稍候...');
            await this.ensureSummary(session);
        } else {
            // 确保会话与当前任务ID匹配，不匹配则重置
            await this.ensureSummary(session);
        }
        persistState();
    },

    closePanel() {
        aiStore.setState({
            panelOpen: false,
            loading: false,
        });
        persistState();
    },

    async resetSession() {
        const state = aiStore.getState();
        if (!state.isLoggedIn) return;
        const session = createNewSession('正在初始化教学上下文，请稍候...');
        await this.ensureSummary(session);
    },

    switchSession(sessionId) {
        const state = aiStore.getState();
        if (!state.sessions.find((session) => session.id === sessionId)) return;
        aiStore.setState({ currentSessionId: sessionId });
        persistState();
    },

    async ensureSummary(session) {
        if (!session || session.sessionHash) return;
        try {
            const data = await apiJson('/api/ai-teacher/init-summary', {
                pageId: getPageId(),
                content: extractPageContent(),
            });

            upsertSession({
                ...session,
                sessionHash: data.sessionHash || '',
                coreSummary: data.summary || '',
                messages: [
                    { role: 'system', content: data.summary || '暂无摘要' },
                    { role: 'ai', content: '我已经阅读完毕并准备好了，你对当前教学内容有什么疑问吗？' }
                ],
                updatedAt: Date.now(),
            });
        } catch (error) {
            replaceMessages(session, [{ role: 'ai', content: `初始化失败：${error.message || '请稍后重试'}` }]);
        }
    },

    async sendMessage() {
        const state = aiStore.getState();
        if (state.loading) return;

        const input = document.getElementById('aiInput');
        if (!input) return;
        const question = (input.value || '').trim();
        if (!question) return;

        let session = getCurrentSession();
        if (!session) {
            session = createNewSession('正在初始化教学上下文，请稍候...');
            await this.ensureSummary(session);
            session = getCurrentSession();
        }
        if (!session) return;

        if (session.turnCount >= AI_MAX_TURNS) {
            return;
        }

        if (!session.sessionHash) {
            await this.ensureSummary(session);
            session = getCurrentSession();
            if (!session || !session.sessionHash) {
                return;
            }
        }

        const recentHistory = buildRecentHistory(session.messages);
        const nextTurnCount = session.turnCount + 1;

        const nextMessages = [
            ...session.messages,
            { role: 'user', content: question },
            { role: 'assistant', content: '' },
        ];

        upsertSession({
            ...session,
            messages: nextMessages,
            turnCount: nextTurnCount,
            updatedAt: Date.now(),
        });

        aiStore.setState({ loading: true });
        input.value = '';

        let streamedText = '';
        let answerMeta = { model: '', provider: '' };
        try {
            answerMeta = (await streamChat(
                {
                    sessionHash: session.sessionHash,
                    question,
                    recentHistory,
                },
                (chunk) => {
                    streamedText += chunk;
                    const current = getCurrentSession();
                    if (!current) return;
                    const updatedMessages = [...current.messages];
                    const lastIndex = updatedMessages.length - 1;
                    if (lastIndex >= 0 && updatedMessages[lastIndex].role === 'assistant') {
                        updatedMessages[lastIndex] = {
                            role: 'assistant',
                            content: streamedText,
                        };
                        replaceMessages(current, updatedMessages);
                    }
                }
            )) || answerMeta;
            // 流式传输完成后，确保MathJax渲染所有公式，并记录实际回答的模型
            const _cur = getCurrentSession();
            if (_cur) {
                const _msgs = [..._cur.messages];
                const _last = _msgs.length - 1;
                if (_last >= 0 && _msgs[_last].role === 'assistant') {
                    _msgs[_last] = { ..._msgs[_last], model: answerMeta.model, provider: answerMeta.provider };
                    replaceMessages(_cur, _msgs);
                }
            }
            setTimeout(() => {
                const chatHistory = document.getElementById('aiChatHistory');
                if (chatHistory && window.MathJax && window.MathJax.typesetPromise) {
                    window.MathJax.typesetPromise([chatHistory]);
                }
            }, 100);
        } catch (error) {
            const current = getCurrentSession();
            if (current) {
                const updatedMessages = [...current.messages];
                const lastIndex = updatedMessages.length - 1;
                if (lastIndex >= 0 && updatedMessages[lastIndex].role === 'assistant') {
                    updatedMessages[lastIndex] = {
                        role: 'assistant',
                        content: `抱歉，当前请求失败：${error.message || '请稍后重试'}`,
                    };
                    replaceMessages(current, updatedMessages);
                }
                if (current.turnCount > 0) {
                    setTurnCount(current, current.turnCount - 1);
                }
            }
        } finally {
            aiStore.setState({ loading: false });
        }
    },

    async deleteHistoryItem(itemId) {
        console.log('Delete history item:', itemId);
        if (!confirm('确定要删除这条历史记录吗？')) return;
        try {
            console.log('Calling delete API with itemId:', itemId);
            const response = await apiJson('/api/ai-teacher/history/delete', { itemId });
            console.log('Delete response:', response);
            // 重新加载历史记录
            this.toggleHistory();
            this.toggleHistory();
        } catch (error) {
            console.error('Delete error:', error);
            alert('删除失败：' + error.message);
        }
    },

    async likeHistoryItem(itemId) {
        console.log('Like history item:', itemId);
        try {
            console.log('Calling like API with itemId:', itemId);
            const response = await apiJson('/api/ai-teacher/history/like', { itemId });
            console.log('Like response:', response);
            // 重新加载历史记录
            this.toggleHistory();
            this.toggleHistory();
        } catch (error) {
            console.error('Like error:', error);
            alert('点赞失败：' + error.message);
        }
    },

    render() {
        const state = aiStore.getState();
        const panel = document.getElementById('aiAssistantPanel');
        const button = document.getElementById('triggerAiBtn');
        const buttonText = button ? button.querySelector('.btn-text') : null;
        const chatHistory = document.getElementById('aiChatHistory');
        const tabs = document.getElementById('aiSessionTabs');
        const loading = document.getElementById('aiLoading');
        const turnHint = document.getElementById('aiTurnHint');
        const input = document.getElementById('aiInput');
        const sendBtn = document.getElementById('aiSendBtn');

        if (button && buttonText) {
            buttonText.textContent = state.isLoggedIn ? '点击询问AI助教' : '登录后使用AI助教';
            button.classList.toggle('disabled', !state.isLoggedIn);
            button.setAttribute('aria-disabled', state.isLoggedIn ? 'false' : 'true');
        }

        if (panel) {
            panel.classList.toggle('active', state.panelOpen && state.isLoggedIn);
        }

        if (tabs) {
            tabs.innerHTML = '';
            state.sessions
                .slice()
                .sort((a, b) => b.updatedAt - a.updatedAt)
                .forEach((session) => {
                    const tab = document.createElement('button');
                    tab.type = 'button';
                    tab.className = `ai-session-tab ${session.id === state.currentSessionId ? 'active' : ''}`;
                    tab.textContent = session.title;
                    tab.onclick = () => this.switchSession(session.id);
                    tabs.appendChild(tab);
                });
        }

        const session = getCurrentSession();

        if (chatHistory) {
            chatHistory.innerHTML = '';
            if (session && session.messages.length > 0) {
                session.messages.forEach((message) => {
                    const node = document.createElement('div');
                    let roleClass = 'ai';
                    if (message.role === 'user') roleClass = 'user';
                    if (message.role === 'system') roleClass = 'system';
                    
                    node.className = `chat-msg ${roleClass}`;
                    
                    let htmlContent = message.content || (message.role === 'assistant' && state.loading ? '...' : '');
                    
                    if ((message.role === 'assistant' || message.role === 'ai') && window.marked && htmlContent && message.content.length > 0) {
                        // 确保Markdown解析正确
                        try {
                            htmlContent = window.marked.parse(htmlContent);
                            node.innerHTML = htmlContent;
                        } catch (e) {
                            node.textContent = htmlContent;
                        }
                    } else if (message.role === 'system') {
                        node.innerHTML = `<strong>本节摘要：</strong><br/>${htmlContent}`;
                    } else {
                        node.textContent = htmlContent;
                    }
                    
                    // 确保MathJax渲染所有公式
                    if (window.MathJax && window.MathJax.typesetPromise) {
                        setTimeout(() => window.MathJax.typesetPromise([node]), 100);
                    }

                    // 显示实际回答的模型（来自主模型或国内备用模型 fallback 链）
                    if ((message.role === 'assistant' || message.role === 'ai') && message.model) {
                        const tag = document.createElement('div');
                        tag.className = 'ai-model-tag';
                        const label = message.provider
                            ? `${message.provider} · ${message.model}`
                            : message.model;
                        tag.textContent = `由 ${label} 回答`;
                        node.appendChild(tag);
                    }

                    chatHistory.appendChild(node);
                });
                chatHistory.scrollTop = chatHistory.scrollHeight;
                
                if (window.MathJax && window.MathJax.typesetPromise) {
                    setTimeout(() => window.MathJax.typesetPromise([chatHistory]), 50);
                }
            }
        }

        const turnCount = session ? session.turnCount : 0;
        const remaining = Math.max(0, AI_MAX_TURNS - turnCount);
        const reachedLimit = turnCount >= AI_MAX_TURNS;

        if (input) {
            input.disabled = !state.isLoggedIn || reachedLimit || state.loading;
        }

        if (sendBtn) {
            sendBtn.disabled = !state.isLoggedIn || reachedLimit || state.loading;
        }

        if (loading) {
            loading.style.display = state.loading ? 'block' : 'none';
        }

        if (turnHint) {
            turnHint.classList.remove('warning', 'limit');
            if (!state.isLoggedIn) {
                turnHint.textContent = '登录后可使用 AI 助教';
                return;
            }
            if (reachedLimit) {
                turnHint.textContent = '本次对话已达上限，请重新开启新会话';
                turnHint.classList.add('limit');
                return;
            }
            if (remaining === 1) {
                turnHint.textContent = '还剩最后一轮提问机会';
                turnHint.classList.add('warning');
                return;
            }
            turnHint.textContent = `剩余问答轮数: ${remaining} 轮`;
        }
    },
};

// 立即绑定aiChat对象到window，确保在页面加载过程中也能访问
window.aiChat = aiChat;
window.handleAiAssistClick = () => aiChat.handleAiAssistClick();
window.syncAiAssistantAuth = () => aiChat.syncAuthStatus();
window.clearAiAssistantState = () => resetAssistantState();

// 确保toggleHistory函数存在，防止在初始化完成前调用
window.aiChat.toggleHistory = aiChat.toggleHistory || function() {
    console.warn('AI助教尚未完全初始化，请稍后再试');
};

// 动态加载兼容：脚本晚于 DOMContentLoaded 加载时也能初始化（video.html 等改为链式加载后需要）
const initAiAssistant = async () => {
    await aiChat.init();
    window.addEventListener('storage', (event) => {
        if (event.key === 'auth_token' || event.key === 'xsyy_user_v2') {
            aiChat.syncAuthStatus();
        }
    });
    window.addEventListener('xsyy:authChanged', () => {
        aiChat.syncAuthStatus();
    });
};
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAiAssistant, { once: true });
} else {
    void initAiAssistant();
}
