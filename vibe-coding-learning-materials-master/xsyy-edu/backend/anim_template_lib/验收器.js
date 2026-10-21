#!/usr/bin/env node
/**
 * 验收器 —— 检查一份「填空」能不能安全地用、装出来的页面会不会出错。
 *
 * 用法：
 *   node 验收器.js <模板.html> <填空.json> [生成产物.html]
 *
 * 它做四件事（前两件不需要模板跑起来，后两件要把模板真跑一遍）：
 *   ① 冻结   —— 生成的页面里，除了填空题块，其他部分必须和模板逐字符一致
 *   ② 安全   —— 所有表达式过白名单，不许出现 window / document / eval / new / 引号 / 方括号
 *   ③ 编译   —— 在沙箱里把模板真跑一遍，看模板是否正常编译、steps 引用是否真的有对应元素
 *   ④ 扫参   —— 滑块取遍两端和中间，每一步都画一次，看会不会崩、算出 NaN
 */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');

/* ══════════════════ 与模板同源的安全闸（独立写一遍，交叉验证） ══════════════════ */
const SAFE_CHARS = /^[0-9A-Za-z_$+\-*/%().,<>=!?:&| \t]*$/;
const BANNED = /\b(window|document|globalThis|self|top|parent|eval|Function|new|this|constructor|__proto__|prototype|import|require|fetch|XMLHttpRequest|WebSocket|Worker|localStorage|sessionStorage|indexedDB|cookie|location|navigator|alert|console|setTimeout|setInterval|debugger)\b/;
const MATH_CALL = /Math\.(abs|cbrt|ceil|cos|exp|floor|hypot|log|log10|log2|max|min|pow|round|sign|sin|sqrt|tan|PI|E)\b/g;
const IDENT = /[A-Za-z_$][\w$]*/g;
const FORMATTERS = ['trim2', 'trim3', 'trim4', 'fixed1', 'fixed2', 'int', 'pct'];

function guard(src, allowed, where, issues) {
  if (typeof src !== 'string') { issues.push(where + ' 必须是字符串'); return; }
  if (!src.trim()) { issues.push(where + ' 是空的'); return; }
  if (src.length > 200) { issues.push(where + ' 太长（' + src.length + ' > 200）'); return; }
  if (!SAFE_CHARS.test(src)) { issues.push(where + ' 有不安全字符 → ' + src); return; }
  const b = src.match(BANNED);
  if (b) { issues.push(where + ' 命中禁用词「' + b[0] + '」→ ' + src); return; }
  const rest = src.replace(MATH_CALL, ' ');
  (rest.match(IDENT) || []).forEach(id => {
    if (id === 'Math') return;
    if (allowed.indexOf(id) < 0) issues.push(where + ' 用了没定义的量「' + id + '」→ ' + src);
  });
}

/* ══════════════════ 够用的假 DOM ══════════════════ */
function makeDom() {
  const byId = {};
  function El(tag, ns) {
    this.tagName = String(tag || '').toUpperCase();
    this.ns = ns || null;
    this.children = [];
    this.attrs = {};
    this._text = '';
    this._html = '';
    this.className = '';
    this.style = {};
    this.dataset = {};
  }
  const P = El.prototype;
  P.appendChild = function (c) { this.children.push(c); return c; };
  P.removeChild = function (c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; };
  P.insertBefore = function (c, ref) { const i = this.children.indexOf(ref); this.children.splice(i < 0 ? this.children.length : i, 0, c); return c; };
  P.setAttribute = function (k, v) { this.attrs[k] = v; };
  P.getAttribute = function (k) { return this.attrs[k] === undefined ? null : this.attrs[k]; };
  P.removeAttribute = function (k) { delete this.attrs[k]; };
  P.addEventListener = function () {};
  P.removeEventListener = function () {};
  P.dispatchEvent = function () {};
  P.querySelector = function () { return new El('div'); };
  P.querySelectorAll = function () { return []; };
  P.getBoundingClientRect = function () { return { left: 0, top: 0, width: 1400, height: 800, right: 1400, bottom: 800 }; };
  P.getBBox = function () { return { x: 0, y: 0, width: 10, height: 10 }; };
  P.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
  Object.defineProperty(P, 'textContent', {
    get() { return this._text; }, set(v) { this._text = String(v); this.children.length = 0; } });
  Object.defineProperty(P, 'innerHTML', {
    get() { return this._html; }, set(v) { this._html = String(v); } });
  Object.defineProperty(P, 'firstChild', { get() { return this.children[0] || null; } });
  Object.defineProperty(P, 'lastChild', { get() { return this.children[this.children.length - 1] || null; } });

  const doc = new El('#document');
  doc.createElement = t => new El(t);
  doc.createElementNS = (ns, t) => new El(t, ns);
  doc.createTextNode = t => ({ nodeType: 3, textContent: String(t) });
  doc.getElementById = id => { if (!byId[id]) byId[id] = new El('div'); return byId[id]; };
  doc.querySelector = () => new El('div');
  doc.querySelectorAll = () => [];
  doc.addEventListener = () => {};
  doc.head = new El('head');
  doc.body = new El('body');
  doc.documentElement = new El('html');
  doc.title = '';

  return { doc, byId, El };
}

/* ══════════════════ 把模板真跑一遍 ══════════════════ */
function runTemplate(tplText, fillObj, issues) {
  const { doc, byId, El } = makeDom();
  const fillEl = new El('script');
  fillEl.textContent = JSON.stringify(fillObj);
  byId['xsyy-fill'] = fillEl;

  const sandbox = {
    document: doc,
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1400, innerHeight: 800,
      matchMedia: () => ({ matches: false, addEventListener() {} }),
      getComputedStyle: () => ({ getPropertyValue: () => '' }),
      requestAnimationFrame: () => 0,
    },
    setTimeout: () => 0, setInterval: () => 0, clearTimeout() {}, clearInterval() {},
    requestAnimationFrame: () => 0,
    console: { log() {}, warn() {}, error() {} },
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;

  const Run = vm.createContext(sandbox);
  let ret = null;
  /* 取主脚本（跳过 JSON 填空块） */
  const scripts = [];
  const re = /<script([^>]*)>([\s\S]*?)<\/script>/g;
  let m;
  while ((m = re.exec(tplText))) {
    if (/type\s*=\s*"application\/json"/.test(m[1])) continue;
    scripts.push(m[2]);
  }
  if (!scripts.length) { issues.push('模板里没有找到脚本'); return null; }

  try {
    for (const s of scripts) {
      /* 模板的脚本是一个 IIFE，里面的 SCENE 等在外面取不到；
         所以在它收尾的 })(); 之前插一句，把关键对象挂到 global 上带出来 */
      const probe = 'globalThis.__XSYY = {' +
        ' SCENE: (typeof SCENE !== "undefined") ? SCENE : null,' +
        ' TEMPLATE: (typeof TEMPLATE !== "undefined") ? TEMPLATE : null,' +
        ' g: (typeof g !== "undefined") ? g : null,' +
        ' els: (typeof els !== "undefined") ? els : null,' +
        ' FILL: (typeof FILL !== "undefined") ? FILL : null,' +
        ' body: document.body, head: document.head };\n';
      const idx = s.lastIndexOf('})();');
      const code = (idx >= 0) ? (s.slice(0, idx) + probe + s.slice(idx)) : (s + '\n' + probe);
      vm.runInContext(code, Run, { filename: 'template.html' });
    }
  } catch (e) {
    issues.push('模板在沙箱里跑挂了 → ' + e.message);
    return null;
  }
  return Run.__XSYY || null;
}

/* ══════════════════ 主流程 ══════════════════ */
const args = process.argv.slice(2);
if (args.length < 2) {
  console.error('用法: node 验收器.js <模板.html> <填空.json> [生成产物.html]');
  process.exit(2);
}
const [tplPath, jsonPath, outPath] = args;
const tplText = fs.readFileSync(tplPath, 'utf8');
const fillRaw = fs.readFileSync(jsonPath, 'utf8');

const issues = [], notes = [];
const drawnNames = [];
let fill;
try { fill = JSON.parse(fillRaw); }
catch (e) { console.error('❌ 填空 JSON 语法错误：' + e.message); process.exit(1); }

/* ---------- ① 冻结校验 ---------- */
const FILL_RE = /(<script type="application\/json" id="xsyy-fill">)([\s\S]*?)(<\/script>)/;
if (outPath && fs.existsSync(outPath)) {
  const outText = fs.readFileSync(outPath, 'utf8');
  const a = tplText.match(FILL_RE), b = outText.match(FILL_RE);
  if (!b) issues.push('产物里没有填空题块');
  else {
    const stripA = tplText.replace(FILL_RE, '@@FILL@@');
    const stripB = outText.replace(FILL_RE, '@@FILL@@');
    const nA = stripA.length, nB = stripB.length;
    if (stripA === stripB) {
      notes.push('冻结校验：去掉填空题后逐字符一致（' + nA + ' 字符，零改动）✔');
    } else {
      let i = 0; while (i < Math.min(nA, nB) && stripA[i] === stripB[i]) i++;
      const RunA = stripA.slice(Math.max(0, i - 40), i + 40).replace(/\n/g, '⏎');
      const RunB = stripB.slice(Math.max(0, i - 40), i + 40).replace(/\n/g, '⏎');
      issues.push('冻结被破坏：第 ' + i + ' 个字符起不一致\n      模板: …' + RunA + '\n      产物: …' + RunB);
    }
    /* 按语义比，不按空白比 —— 缩进格式不同不算问题 */
    let sameFill = false;
    try { sameFill = JSON.stringify(JSON.parse(b[2])) === JSON.stringify(fill); } catch (e) { /* 下面统一报 */ }
    if (!sameFill) issues.push('产物里的填空内容和给的 JSON 不一致（内容层面，不是排版）');
  }
} else if (outPath) {
  issues.push('产物文件不存在：' + outPath);
} else {
  notes.push('冻结校验：跳过（没给产物文件）');
}

/* ---------- ② 安全校验（表达式白名单） ---------- */
{
  const allowed = ['Math'];
  /* 无滑块的模板会写一个「示例取值」demo，引擎把它当常数注入 —— 白名单也要放行 */
  if (typeof fill.demo === 'number' && isFinite(fill.demo)) allowed.push('demo');
  (fill.params || []).forEach((c, i) => {
    const w = 'params[' + i + '](' + c.id + ')';
    if (!/^[A-Za-z_$][\w$]*$/.test(String(c.id || ''))) issues.push(w + ' id 不是合法变量名');
    if (allowed.indexOf(c.id) >= 0) issues.push(w + ' 参数名重复');
    else allowed.push(c.id);
    if (!c.label) issues.push(w + ' 少了 label（滑块旁边显示的名字）');
    if (typeof c.min !== 'number' || typeof c.max !== 'number') issues.push(w + ' 的 min / max 必须是数字');
    else if (!(c.min < c.max)) issues.push(w + ' 的 min 必须小于 max（现在 min=' + c.min + '，max=' + c.max + '）');
    if (typeof c.value !== 'number') issues.push(w + ' 的 value 必须是数字');
    else if (typeof c.min === 'number' && typeof c.max === 'number' && (c.value < c.min || c.value > c.max))
      issues.push(w + ' 的 value（' + c.value + '）超出了 min ~ max');
  });
  /* 曲线表达式可以吃滑块的量（F04 这类「滑块一拖整条线变形」的模板），
     所以白名单放行 params —— 只放 params，不放 expr（运行时 fn 拿不到它们） */
  const paramNames = allowed.slice();
  (fill.expr || []).forEach((it, i) => {
    const where = 'expr[' + i + '](' + (it.n || '?') + ')';
    if (!/^[A-Za-z_$][\w$]*$/.test(String(it.n || ''))) { issues.push(where + ' 变量名不合法'); return; }
    if (allowed.indexOf(it.n) >= 0) { issues.push(where + ' 变量名重复'); return; }
    if (it.fmt !== undefined && FORMATTERS.indexOf(it.fmt) < 0) issues.push(where + ' 的 fmt 不认识 → ' + it.fmt);
    guard(it.e, allowed, where, issues);
    allowed.push(it.n);
  });
  if (fill.curve && fill.curve.e !== undefined) guard(fill.curve.e, ['Math', 'x'].concat(paramNames), 'curve.e', issues);
  if (fill.line && fill.line.e !== undefined) guard(fill.line.e, ['Math', 'x'].concat(paramNames), 'line.e', issues);
  let blocks = 0;
  (fill.steps || []).forEach((s, i) => {
    ['p', 'd', 't', 'tip'].forEach(k => {   /* t/tip 也走 buildText 插值，占位符同样要过白名单 */
      const t = s[k];
      if (typeof t !== 'string') return;
      const re2 = /\{\{([\s\S]*?)\}\}/g; let mm;
      while ((mm = re2.exec(t))) {
        guard(mm[1].trim(), ['Math'].concat(allowed), 'steps[' + i + '].' + k + ' 里的 {{}}', issues);
        blocks++;
      }
    });
  });
  /* 实时数据条：一句话，里面必须有 {{量}}，否则拖滑块不会变、等于摆设 */
  if (fill.readout !== undefined) {
    if (typeof fill.readout !== 'string' || !fill.readout.trim()) {
      issues.push('readout 必须是「非空字符串」（一句话，用 {{量}} 写当前数据）');
    } else {
      const re3 = /\{\{([\s\S]*?)\}\}/g; let m3, n3 = 0;
      while ((m3 = re3.exec(fill.readout))) {
        guard(m3[1].trim(), ['Math'].concat(allowed), 'readout 里的 {{}}', issues);
        n3++;
      }
      if (!n3) issues.push('readout 里一个 {{量}} 都没有 —— 数据条不会随滑块变，等于摆设');
      if (n3 && !(fill.params || []).length)
        issues.push('readout 写了，但模板没有可拖参数（params 是空的）—— 没有滑块就没有「当前值」');
      blocks += n3;
    }
  }
  notes.push('安全校验：' + (fill.expr || []).length + ' 条算式 + ' + blocks + ' 处文案占位，全部通过白名单 ✔');
}

/* ---------- ③ 编译 + 沙箱跑 ---------- */
const Run = runTemplate(tplText, fill, issues);
let mathOk = false;
if (Run) {
  const SCENE = Run.SCENE, TEMPLATE = Run.TEMPLATE;
  if (!SCENE || !SCENE.meta || !SCENE.meta.title) {
    /* 模板会把出错原因写进页面，把它捞出来，别只说"失败了" */
    let hint = '';
    try {
      const flat = [];
      (function walk(n) { (n.children || []).forEach(c => { if (c._text) flat.push(c._text); walk(c); }); })(Run.body);
      const f = flat.find(t => t.indexOf('⚠') >= 0);
      if (f) hint = '\n        ↗ 模板报的错：' + f;
    } catch (e) { /* 捞不到就算了 */ }
    issues.push('模板没能编译出场景（多半是必填项缺了或写法不对）' + hint);
  } else {
    notes.push('编译：场景构造成功 → 「' + SCENE.meta.title + '」，' + SCENE.steps.length + ' 步');

    /* ③-1 模板要求的量都算出来了 */
    const initP = {};
    (fill.params || []).forEach(c => { initP[c.id] = c.value; });
    let M = null;
    try { M = SCENE.math(initP); } catch (e) { issues.push('math() 抛错：' + e.message); }
    if (M) {
      /* 注意：带 fmt 的量会被格式化成**字符串**，NaN / Infinity 就藏在字符串里 ——
         "≈ NaN" 印到页面上比报错还糟，所以这里两种类型都要查。 */
      const bad = Object.keys(M).filter(k => {
        const v = M[k];
        if (typeof v === 'number') return !isFinite(v);
        return typeof v === 'string' && /^-?(Infinity|NaN)$/.test(v);
      });
      if (bad.length) issues.push('算出了 NaN / Infinity → ' + bad.join(', '));
      else { notes.push('数值：' + Object.keys(M).map(k => k + '=' + M[k]).join(', ')); mathOk = true; }
    }

    /* ③-2 包一层画笔，记下模板到底画了哪些名字，用来核对 steps 的引用 */
    const PRIMS = ['point', 'seg', 'poly', 'square', 'rightAngle', 'label',
                   'vline', 'hline', 'markPoint', 'curve', 'axes', 'intersect',
                   'region', 'tangent', 'trend', 'legend', 'group', 'balance', 'tile',
                   /* 数与式包 */
                   'formula', 'text', 'rect', 'strikes', 'line'];
    if (Run.g) PRIMS.forEach(k => {
      if (typeof Run.g[k] !== 'function') return;
      const orig = Run.g[k];
      Run.g[k] = function (name) { if (typeof name === 'string') drawnNames.push(name); return orig.apply(this, arguments); };
    });
  }
}

/* ---------- ④ 扫参：滑块取遍两端，每一步都画一次 ---------- */
if (Run && Run.SCENE && Run.SCENE.meta && Run.SCENE.meta.title) {
  const SCENE = Run.SCENE;
  const params = fill.params || [];
  const grid = params.map(c => {
    const vs = [c.min, c.value, c.max];
    return vs.filter((v, i) => vs.indexOf(v) === i);
  });
  const all = [];
  (function cart(i, cur) {
    if (i === params.length) { all.push(Object.assign({}, cur)); return; }
    grid[i].forEach(v => { cur[params[i].id] = v; cart(i + 1, cur); });
  })(0, {});
  if (!all.length) all.push({});
  let drawErr = 0, mathErr = 0, firstErr = null;
  all.forEach(p => {
    let M;
    try { M = SCENE.math(p); } catch (e) { mathErr++; if (!firstErr) firstErr = 'math ' + JSON.stringify(p) + ' → ' + e.message; return; }
    /* 扫参点上也要查 NaN / Infinity（含 fmt 转成的字符串形态）——
       没抛错但算出 NaN，比抛错更隐蔽，比如 Math.sqrt(负数) */
    const bad = Object.keys(M).filter(k => {
      const v = M[k];
      if (typeof v === 'number') return !isFinite(v);
      return typeof v === 'string' && /^-?(Infinity|NaN)$/.test(v);
    });
    if (bad.length) {
      mathErr++; if (!firstErr) firstErr = 'math ' + JSON.stringify(p) + ' → 算出了 NaN / Infinity: ' + bad.join(', ');
      return;
    }
    for (let s = 0; s < SCENE.steps.length; s++) {
      try { SCENE.draw(Run.g, M, s); }
      catch (e) { drawErr++; if (!firstErr) firstErr = 'draw step' + s + ' ' + JSON.stringify(p) + ' → ' + e.message; break; }
    }
  });
  const total = all.length * SCENE.steps.length;
  if (mathErr || drawErr) issues.push('扫参失败：' + mathErr + ' 次算数出错 / ' + drawErr + ' 次画图出错\n      ' + firstErr);
  else notes.push('扫参：' + all.length + ' 组参数 × ' + SCENE.steps.length + ' 步 = ' + total + ' 次，全部正常 ✔');
}

/* ---------- ④-2 steps 引用的元素，模板真的画出来了吗 ---------- */
if (Run && Run.SCENE && Run.SCENE.meta && Run.SCENE.meta.title) {
  /* 画过的 = 画笔原语记的账 ∪ 引擎登记表 els 的键。
     els 是 reg() 的活登记表（reg 是 DRAW 闭包内的词法引用，包不住，
     但 els 本身被探针引用出来了）—— 画法包用 mk + reg 直绘自定义元素
     （如 <image> 卡通贴图）时，只有 els 能作准。 */
  const drawn = new Set(drawnNames);
  if (Run.els) Object.keys(Run.els).forEach(k => drawn.add(k));
  const used = new Set();
  const missing = [];
  Run.SCENE.steps.forEach((s, i) => {
    (s.show || []).concat(s.hi || []).forEach(id => {
      used.add(id);
      if (!drawn.has(id)) missing.push('steps[' + i + '] 提到了「' + id + '」，但模板从没画过它');
    });
  });
  if (missing.length) issues.push('步骤引用了画不出来的元素：\n      ' + missing.join('\n      '));
  else if (used.size) notes.push('引用：steps 里提到的 ' + used.size + ' 个元素 id（' + [...used].join(', ') + '）都真的画出来了 ✔');
}

/* ---------- ④-3 综合画法专属断言 E1 / E2（只在「按问分节」的模板上生效）----------
   E1：每一小问至少有 1 个「答案类元素」（mustShow 里的）在其对应问的步骤里进入 show
   E2：同一次绘制里元素 id 不得重复创建（共享图形只画一次，第二问不得重建）
   判定入口：steps[].t 里出现「【第(1)问】」这种按问分节的写法（≥2 问才检查）。 */
if (Run && Run.SCENE && Run.SCENE.meta && Run.SCENE.meta.title) {
  /* 用原始填空里的 steps（built 之后 .t 被换成了 title 函数，拿不到分节前缀） */
  const steps = (fill.steps || []);
  const RE_Q = /【第\s*[（(]?\s*(\d+)\s*[）)]?\s*问】/;
  const groups = [];
  steps.forEach((s, i) => {
    const mm = RE_Q.exec(String(s.t || ''));
    /* 同一问的连续几步合成一组；换了问号才开新组；无前缀的行归上一问 */
    if (mm && (!groups.length || groups[groups.length - 1].q !== mm[1])) groups.push({ q: mm[1], idx: [i] });
    else if (groups.length) groups[groups.length - 1].idx.push(i);
  });
  if (groups.length >= 2) {
    /* E1 */
    let ms = [];
    if (Run.TEMPLATE && Array.isArray(Run.TEMPLATE.mustShow)) ms = Run.TEMPLATE.mustShow;
    if (!ms.length) {   /* 沙箱没带出 TEMPLATE 时，从模板源码的 TEMPLATE 块里抠 */
      const mr = /mustShow\s*:\s*\[([\s\S]*?)\]/.exec(tplText);
      ms = mr ? (mr[1].match(/["']([^"']+)["']/g) || []).map(x => x.replace(/["']/g, '')) : [];
    }
    const mustShow = new Set(ms);
    const nogroup = [];
    groups.forEach(gp => {
      let hit = false;
      gp.idx.forEach(i => ((steps[i] && steps[i].show) || []).forEach(id => { if (mustShow.has(id)) hit = true; }));
      if (!hit) nogroup.push('第(' + gp.q + ')问');
    });
    if (nogroup.length) issues.push('E1 失败：' + nogroup.join('、') + ' 的步骤里没有任何「答案类元素」进入 show（该问在动画里没着落）');
    else notes.push('E1（综合画法）：' + groups.length + ' 问（mustShow ' + ms.length + ' 项），每问的答案元素都在其对应问的步骤里登场 ✔');

    /* E2：单次绘制里 id 唯一。先清空收集器，按默认参数把最后一步画一遍（元素最全）。 */
    const saved = drawnNames.slice();
    drawnNames.length = 0;
    const p0 = {};
    (fill.params || []).forEach(c => { p0[c.id] = c.value; });
    try {
      const M0 = Run.SCENE.math(p0);
      Run.SCENE.draw(Run.g, M0, steps.length - 1);
    } catch (e) { /* 单步绘制出错已在扫参里报过，这里忽略 */ }
    const cnt = {};
    drawnNames.forEach(n => { cnt[n] = (cnt[n] || 0) + 1; });
    const dup = Object.keys(cnt).filter(n => cnt[n] > 1).map(n => n + '×' + cnt[n]);
    if (dup.length) issues.push('E2 失败：同一次绘制里重复创建了元素 id → ' + dup.join(', ') + '（共享图形应只画一次，第二问不得重建）');
    else notes.push('E2（综合画法）：单次绘制元素 id 唯一，共享图形无重复创建 ✔');
    drawnNames.length = 0; Array.prototype.push.apply(drawnNames, saved);
  }
}

/* ---------- ⑤ 体量：模型到底改了多少 ---------- */
{
  const tplLines = tplText.split('\n').length;
  const fillLines = tplText.match(FILL_RE)[2].trim().split('\n').length;
  const pct = (fillLines / tplLines * 100).toFixed(1);
  notes.push('体量：模板共 ' + tplLines + ' 行，其中填空区 ' + fillLines + ' 行（占 ' + pct + '%），冻结区 ' + (tplLines - fillLines) + ' 行');
}

/* ---------- 报告 ---------- */
console.log('\n模板 : ' + path.basename(tplPath));
console.log('填空 : ' + path.basename(jsonPath));
if (outPath) console.log('产物 : ' + path.basename(outPath));
console.log('─'.repeat(64));
if (notes.length) notes.forEach(n => console.log('  · ' + n));
console.log('─'.repeat(64));
if (issues.length) {
  console.log('❌ ' + issues.length + ' 个问题：');
  issues.forEach(i => console.log('   - ' + i));
  process.exit(1);
} else {
  console.log('✅ 全部通过');
}
