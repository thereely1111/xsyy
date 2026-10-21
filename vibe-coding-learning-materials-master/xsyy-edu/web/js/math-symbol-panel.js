/**
 * math-symbol-panel.js — 题目文本录入与展示适配（渲染辅助，零依赖）
 * =====================================================================
 * 版本演进（2026-09-01 v2）：
 *   v1 提供「Σ 符号面板 + 光标插入」。用户反馈实际使用以复制粘贴题目 / 识图
 *   分析为主，无需手输符号 → v2 移除符号按钮与面板，聚焦两项核心能力：
 *
 *  1. 幂等导出 window.renderMathText(text)：$...$ / $$...$$ 混合文本 → KaTeX 渲染；
 *     KaTeX 未加载时自动动态加载（CDN），失败/含中文的纯文本退化为 HTML 转义。
 *  2. 动态注入「完整题目展示」换行样式：white-space:pre-wrap + word-break:break-word
 *     + overflow-wrap:anywhere，保证粘贴的多行长题目（含 PDF 复制产生的逐字换行）
 *     在展示容器内保留换行结构、自动折行、不横向溢出。
 *     覆盖容器：.video-question（视频页题目详情）、.question-cell / .detail-grid .v
 *     （标签审核详情）、#questionPreview（管理端编辑实时预览）等。
 *
 * 部署约定：本文件放到 /var/www/xsyy/js/ 下，页面以
 *   <script src="/js/math-symbol-panel.js?v=YYYYMMDD"></script> 引入即可。
 * 样式由脚本动态注入 <style>，无需额外 CSS 文件（规避 Cloudflare 对 CSS query 的缓存坑）。
 */
(function () {
  'use strict';

  /* ─────────────────────────── 配置 ─────────────────────────── */

  var KATEX_CSS = '/katex/katex.min.css';
  var KATEX_JS = '/katex/katex.min.js';

  /* ────────────────────── 动态注入样式 ────────────────────── */

  var STYLE_ID = 'math-symbol-panel-style';
  if (!document.getElementById(STYLE_ID)) {
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      /* 完整题目展示：保留粘贴换行 + 长内容自动折行，不横向溢出。
         注意：不作用于卡片摘要容器（.masonry-card-question 等，它们用 line-clamp 截断）。 */
      '.video-question, .question-cell, .detail-grid .v, #questionPreview, .msp-full{',
      'white-space:pre-wrap;word-break:break-word;overflow-wrap:anywhere;',
      '}'
    ].join('\n');
    document.head.appendChild(style);
  }

  /* ──────────────────── KaTeX 按需加载 ──────────────────── */

  var katexLoading = false;
  var katexWaiters = [];

  function ensureKatex(cb) {
    if (typeof window.katex !== 'undefined') {
      cb && cb();
      return;
    }
    katexWaiters.push(cb || null);
    if (katexLoading) return;
    katexLoading = true;
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = KATEX_CSS;
    document.head.appendChild(link);
    var script = document.createElement('script');
    script.src = KATEX_JS;
    script.async = true;
    script.onload = function () {
      katexLoading = false;
      var ws = katexWaiters.splice(0);
      ws.forEach(function (w) { try { w && w(); } catch (e) {} });
    };
    script.onerror = function () {
      katexLoading = false;
      katexWaiters.splice(0);
    };
    document.head.appendChild(script);
  }

  /* ────────────────── HTML 转义（渲染兜底） ────────────────── */

  function escapeHtml(text) {
    if (text == null) return '';
    var div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
  }

  /* ─────────────── ASCII 数学记号 → Unicode（x^2 → x²） ─────────────── */

  // 上标映射（覆盖常用数字/字母/符号；无映射的字符保持原样）
  var SUPER_MAP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    'a': 'ᵃ', 'b': 'ᵇ', 'c': 'ᶜ', 'd': 'ᵈ', 'e': 'ᵉ',
    'f': 'ᶠ', 'g': 'ᵍ', 'h': 'ʰ', 'i': 'ⁱ', 'j': 'ʲ',
    'k': 'ᵏ', 'l': 'ˡ', 'm': 'ᵐ', 'n': 'ⁿ', 'o': 'ᵒ',
    'p': 'ᵖ', 'r': 'ʳ', 's': 'ˢ', 't': 'ᵗ', 'u': 'ᵘ',
    'v': 'ᵛ', 'w': 'ʷ', 'x': 'ˣ', 'y': 'ʸ', 'z': 'ᶻ',
    '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾'
  };
  // 下标映射（数字 + 常用字母）
  var SUB_MAP = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    'a': 'ₐ', 'e': 'ₑ', 'i': 'ᵢ', 'j': 'ⱼ', 'n': 'ₙ',
    'o': 'ₒ', 'r': 'ᵣ', 't': 'ₜ', 'u': 'ᵤ', 'v': 'ᵥ', 'x': 'ₓ'
  };

  function mapRun(s, map) {
    var out = '';
    for (var i = 0; i < s.length; i++) {
      var c = map[s[i]];
      if (!c) return null; // 有字符不支持 → 整段不转换（避免半吊子结果）
      out += c;
    }
    return out;
  }

  /**
   * normalizeMathNotation(text)：把纯文本中的 ASCII 数学记号转换为 Unicode 显示形式。
   *  - x^2 → x²；x^23 → x²³；x^-2 → x⁻²；x^{2} → x²
   *  - x^a → xᵃ（仅映射表内字母；不支持的原样保留 ^ 记法）
   *  - x_1 → x₁；x_{ab} → xₐᵦ（仅映射表内；不支持原样）
   *  - $...$ / $$...$$ LaTeX 段不转换（保留给 KaTeX/MathJax 渲染）
   * 注意：本函数只做「录入记号 → 展示形式」的显示层转换，存储仍为原文。
   */
  function normalizeMathNotation(text) {
    if (text == null) return '';
    var raw = String(text);
    // 保护 LaTeX 段：split 捕获组让奇偶索引为公式段
    var segments = raw.split(/(\$\$[\s\S]+?\$\$|\$[^$\n]+\$)/);
    for (var i = 0; i < segments.length; i++) {
      if (i % 2 === 1) continue; // $...$ 段跳过
      segments[i] = segments[i]
        .replace(/\^\{([^{}]*)\}/g, function (_, inner) {
          var m = mapRun(inner, SUPER_MAP);
          return m !== null ? m : '^{' + inner + '}';
        })
        .replace(/\^(-?[0-9]+)/g, function (_, d) {
          var m = mapRun(d, SUPER_MAP);
          return m !== null ? m : '^' + d;
        })
        .replace(/\^([a-zA-Z]+)/g, function (_, s) {
          var m = mapRun(s, SUPER_MAP);
          return m !== null ? m : '^' + s;
        })
        .replace(/_\{([^{}]*)\}/g, function (_, inner) {
          var m = mapRun(inner, SUB_MAP);
          return m !== null ? m : '_{' + inner + '}';
        })
        .replace(/_([0-9]+)/g, function (_, d) {
          var m = mapRun(d, SUB_MAP);
          return m !== null ? m : '_' + d;
        })
        .replace(/_([a-zA-Z]+)/g, function (_, s) {
          var m = mapRun(s, SUB_MAP);
          return m !== null ? m : '_' + s;
        });
    }
    return segments.join('');
  }

  if (typeof window.normalizeMathNotation === 'undefined') {
    window.normalizeMathNotation = normalizeMathNotation;
  }

  /* ─────────────── 公式渲染：幂等导出 ─────────────── */

  // 仅当页面未定义 renderMathText 时才提供（index.html 已有同名函数，不覆盖）
  function renderMathText(text) {
    if (text == null) return '';
    // 先做 ASCII 记号 → Unicode 显示转换（x^2 → x²）；$...$ 段自动跳过
    var raw = normalizeMathNotation(text);
    var hasDelimiter = /\$\$[\s\S]+?\$\$|\$[^$\n]+\$/.test(raw);
    if (hasDelimiter) {
      var mathBlocks = [];
      var idx = 0;
      raw = raw.replace(/\$\$([\s\S]+?)\$\$/g, function (_, f) {
        try {
          var h = window.katex.renderToString(f.trim(), { throwOnError: false, displayMode: true });
          mathBlocks.push(h);
          return '__MSP_MATH_' + (idx++) + '__';
        } catch (e) { return _; }
      });
      raw = raw.replace(/\$([^$\n]+)\$/g, function (_, f) {
        try {
          var h = window.katex.renderToString(f.trim(), { throwOnError: false, displayMode: false });
          mathBlocks.push(h);
          return '__MSP_MATH_' + (idx++) + '__';
        } catch (e) { return _; }
      });
      raw = escapeHtml(raw);
      mathBlocks.forEach(function (h, i) { raw = raw.replace('__MSP_MATH_' + i + '__', h); });
      return raw;
    }
    if (typeof window.katex !== 'undefined') {
      // 纯 LaTeX 整体渲染仅限"像公式"的内容：含中文（普通句子/题目）一律走转义，
      // 避免 "求解方程 x+5=10" 这类中文题目被 KaTeX 渲染成报错红字
      if (/[\u4e00-\u9fff]/.test(raw)) return escapeHtml(raw);
      try {
        return window.katex.renderToString(raw, { throwOnError: false, strict: 'ignore' });
      } catch (e) {}
    }
    return escapeHtml(raw);
  }

  if (typeof window.renderMathText === 'undefined') {
    window.renderMathText = renderMathText;
  }

  /* ──────────────────── 初始化 ──────────────────── */

  // 延迟加载 KaTeX，避免阻塞首屏
  function init() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () {
        setTimeout(function () { ensureKatex(null); }, 1200);
      });
    } else {
      setTimeout(function () { ensureKatex(null); }, 1200);
    }
  }

  init();
})();
