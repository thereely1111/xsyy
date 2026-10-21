/*
 * error-reporter.js
 * 全局前端错误采集 + 业务埋点上报：
 *  - window.onerror / unhandledrejection / 资源加载失败 / fetch 非 2xx
 *  - 业务埋点：window.reportWebsiteLog(level, category, message, extra)
 *  - 结构化事件字典：event / stage / error_type（与后端 website_log.py 常量对齐）
 *  - 链路透传：自动从 URL / localStorage 提取 task_id 作为 trace_id，一次任务一条链
 * 通过 POST /api/logs/client 写入"网站日志"，纯 best-effort：任何异常都不影响页面运行。
 */
(function () {
  'use strict';

  var ENDPOINT = '/api/logs/client';
  var DEDUP_MS = 5000;
  var reported = {};

  // ---------- 事件字典（与后端 website_log.py 常量保持一致） ----------
  var EVENTS = {
    TASK_CREATED: 'task_created',
    TASK_STARTED: 'task_started',
    TASK_COMPLETED: 'task_completed',
    TASK_FAILED: 'task_failed',
    TASK_REDIRECT_STARTED: 'task_redirect_started',
    POLL_STARTED: 'task_poll_started',
    POLL_FAILED: 'task_poll_failed',
    PREVIEW_GENERATION_STARTED: 'preview_generation_started',
    PREVIEW_GENERATION_FAILED: 'preview_generation_failed',
    PREVIEW_GENERATION_COMPLETED: 'preview_generation_completed',
    FRONTEND_RESOURCE_ERROR: 'frontend_resource_load_failed',
    FRONTEND_RUNTIME_ERROR: 'frontend_runtime_error',
    FRONTEND_API_ERROR: 'frontend_api_request_failed'
  };
  var STAGES = {
    HOME_SUBMIT: 'home_submit',
    UPLOAD_PARSE: 'upload_parse',
    PIPELINE: 'pipeline',
    PREVIEW_GENERATION: 'preview_generation',
    VIDEO_PAGE_POLLING: 'video_page_polling',
    FRONTEND_RENDER: 'frontend_render'
  };
  var ERROR_TYPES = {
    THIRD_PARTY_HTTP: 'third_party_http_error',
    TIMEOUT: 'timeout',
    RESOURCE_LOAD: 'resource_load_error',
    DB_WRITE: 'db_write_error',
    LOCAL_FILE_MISSING: 'local_file_missing',
    PROMPT_TOO_LONG: 'prompt_too_long',
    UNKNOWN: 'unknown'
  };

  // ---------- 链路透传 ----------
  // task_id 优先级：显式传入 > URL ?task_id= > 页面历史中的最近任务
  function getTaskId() {
    try {
      var m = (window.location.search || '').match(/[?&]task_id=([^&]+)/);
      if (m && m[1]) return decodeURIComponent(m[1]);
      return localStorage.getItem('xsyy_last_task_id') || '';
    } catch (e) {
      return '';
    }
  }

  function setTaskId(taskId) {
    try {
      if (taskId) localStorage.setItem('xsyy_last_task_id', String(taskId));
    } catch (e) { /* ignore */ }
  }

  function getToken() {
    try {
      var t = localStorage.getItem('auth_token');
      return t ? String(t) : '';
    } catch (e) {
      return '';
    }
  }

  function send(payload) {
    try {
      var token = getToken();
      var headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = 'Bearer ' + token;

      // 统一补链路 ID：未显式携带时从 URL / 最近任务自动对齐
      if (!payload.task_id && !payload.trace_id) {
        var tid = getTaskId();
        if (tid) {
          payload.task_id = tid;
          payload.trace_id = tid;
        }
      }
      if (payload.task_id && !payload.trace_id) payload.trace_id = payload.task_id;

      // 优先使用 sendBeacon，可在页面卸载时可靠送达
      if (navigator.sendBeacon) {
        try {
          var blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
          if (navigator.sendBeacon(ENDPOINT, blob)) return;
        } catch (e) { /* 回退到 fetch */ }
      }

      fetch(ENDPOINT, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify(payload),
        keepalive: true
      }).catch(function () { /* 忽略网络错误 */ });
    } catch (e) { /* 绝不影响页面 */ }
  }

  function buildContext(extra) {
    var ctx = {
      userAgent: navigator.userAgent,
      location: location.href,
      referrer: document.referrer || '',
      viewport: (window.innerWidth || 0) + 'x' + (window.innerHeight || 0)
    };
    try {
      if (window.performance && typeof performance.now === 'function') {
        ctx.timingMs = Math.round(performance.now());
      }
    } catch (e) { /* ignore */ }
    if (extra) {
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) ctx[k] = extra[k];
      }
    }
    return ctx;
  }

  function report(category, message, stack, extra) {
    try {
      if (!message) return;
      var key = (category || '') + '|' + message + '|' + (stack || '').slice(0, 200);
      var now = Date.now();
      if (reported[key] && (now - reported[key] < DEDUP_MS)) return;
      reported[key] = now;

      var payload = {
        level: 'ERROR',
        category: category || 'client_page',
        message: String(message).slice(0, 4000),
        page_url: location.href,
        page_title: document.title || '',
        device: navigator.userAgent,
        stack_trace: stack || '',
        context: buildContext(extra)
      };
      if (extra) {
        if (extra.event) payload.event = extra.event;
        if (extra.stage) payload.stage = extra.stage;
        if (extra.error_type) payload.errorType = extra.error_type;
        if (extra.task_id) payload.task_id = extra.task_id;
      }
      send(payload);
    } catch (e) { /* 忽略 */ }
  }

  // 脚本运行期错误（同步异常）
  window.onerror = function (message, source, lineno, colno, error) {
    var stack = (error && error.stack) ? error.stack : '';
    report('client_page', message, stack, {
      event: EVENTS.FRONTEND_RUNTIME_ERROR,
      stage: STAGES.FRONTEND_RENDER,
      error_type: ERROR_TYPES.UNKNOWN,
      source: source || '',
      lineno: lineno || null,
      colno: colno || null
    });
    return false; // 不阻止浏览器默认处理
  };

  // 未捕获的 Promise 异常
  window.addEventListener('unhandledrejection', function (event) {
    var reason = event && event.reason;
    var message, stack;
    if (reason instanceof Error) {
      message = reason.message || String(reason);
      stack = reason.stack || '';
    } else {
      try { message = JSON.stringify(reason); } catch (e) { message = String(reason); }
      stack = '';
    }
    report('client_page', message, stack, {
      event: EVENTS.FRONTEND_RUNTIME_ERROR,
      stage: STAGES.FRONTEND_RENDER,
      error_type: ERROR_TYPES.UNKNOWN,
      type: 'unhandledrejection'
    });
  });

  // 资源加载失败（图片 / 脚本 / 样式等）
  window.addEventListener('error', function (event) {
    var t = event && event.target;
    if (t && t !== window && (t.src || t.href)) {
      report('client_resource', '资源加载失败: ' + (t.src || t.href), '', {
        event: EVENTS.FRONTEND_RESOURCE_ERROR,
        stage: STAGES.FRONTEND_RENDER,
        error_type: ERROR_TYPES.RESOURCE_LOAD,
        tagName: t.tagName || '',
        src: t.src || t.href || ''
      });
    }
  }, true); // 捕获阶段，才能捕获资源加载错误

  // fetch / XHR 非 2xx 拦截：把接口错误回传给后端（跳过日志上报接口本身，避免死循环）
  (function hookFetch() {
    if (!window.fetch) return;
    var originalFetch = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var requestHeaders = (init && init.headers) || (input && input.headers);
      var hasAuthorization = false;
      if (requestHeaders) {
        if (typeof requestHeaders.get === 'function') {
          hasAuthorization = !!requestHeaders.get('Authorization');
        } else {
          hasAuthorization = Object.keys(requestHeaders).some(function (key) {
            return key.toLowerCase() === 'authorization' && !!requestHeaders[key];
          });
        }
      }
      if (url.indexOf('/api/logs/client') >= 0) {
        return originalFetch.apply(this, arguments);
      }
      return originalFetch.apply(this, arguments).then(function (res) {
        try {
          if (res && res.status === 401 && hasAuthorization && localStorage.getItem('auth_token')) {
            if (typeof window.showSessionKickedModal === 'function') {
              window.showSessionKickedModal();
            } else {
              window.__xsyySessionKickedPending = true;
            }
          }
          if (res && res.status >= 400 && res.status < 600) {
            report('client_api', '接口请求失败: ' + res.status + ' ' + url, '', {
              event: EVENTS.FRONTEND_API_ERROR,
              stage: STAGES.FRONTEND_RENDER,
              error_type: ERROR_TYPES.THIRD_PARTY_HTTP,
              networkStatus: res.status,
              apiUrl: url
            });
          }
        } catch (e) { /* ignore */ }
        return res;
      });
    };
  })();

  // 暴露手动上报接口，供业务代码按需调用：window.reportWebsiteError('...', {stack: '...'})
  window.reportWebsiteError = function (message, extra) {
    report('client_page', message, (extra && extra.stack) || '', extra);
  };

  // 通用上报接口：业务代码可上报任意级别/分类的事件（含结构化 event/stage/error_type）。
  // 例如：window.reportWebsiteLog('INFO', 'animation_generation', '任务创建成功',
  //        { event: 'task_created', stage: 'home_submit', task_id: 'xxx' })
  window.reportWebsiteLog = function (level, category, message, extra) {
    try {
      if (!message) return;
      var payload = {
        level: String(level || 'INFO').toUpperCase().slice(0, 20),
        category: String(category || 'app_event').slice(0, 50),
        message: String(message).slice(0, 4000),
        page_url: location.href,
        page_title: document.title || '',
        device: navigator.userAgent,
        context: buildContext(extra)
      };
      if (extra) {
        if (extra.event) payload.event = extra.event;
        if (extra.stage) payload.stage = extra.stage;
        if (extra.error_type) payload.errorType = extra.error_type;
        if (extra.task_id) payload.task_id = extra.task_id;
      }
      send(payload);
    } catch (e) { /* 绝不影响页面 */ }
  };

  // 供业务代码记录"最近任务"：创建任务成功后调用，保证后续错误上报自动带链路 ID
  window.reportSetTaskId = setTaskId;

  // 暴露事件字典（供业务埋点使用枚举名，避免手写字符串）
  window.LOG_EVENTS = EVENTS;
  window.LOG_STAGES = STAGES;
  window.LOG_ERROR_TYPES = ERROR_TYPES;
})();
