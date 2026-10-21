#!/usr/bin/env node
/**
 * 装配器 —— 把一份「填空 JSON」装进模板，产出可执行的教学动画页。
 *
 * 用法：
 *   node 装配器.js <模板.html> <填空.json> <输出.html>
 *   node 装配器.js --list                列出模板库里所有模板及其必需字段
 *
 * 它做的事只有一件：替换下面这个块的内容，别的一个字符都不动。
 *   <script type="application/json" id="xsyy-fill"> … </script>
 */
'use strict';
const fs = require('fs');
const path = require('path');

const FILL_RE = /(<script type="application\/json" id="xsyy-fill">)([\s\S]*?)(<\/script>)/;

function readFill(html) {
  const m = html.match(FILL_RE);
  if (!m) throw new Error('这个文件里没有填空题块（<script type="application/json" id="xsyy-fill">）');
  return m;
}

function fillText(fill) {
  const t = JSON.stringify(fill, null, 2);
  if (/<\/script/i.test(t)) throw new Error('填空题里不能出现 </script');
  return '\n' + t + '\n';
}

function assemble(tplPath, jsonPath, outPath) {
  const html = fs.readFileSync(tplPath, 'utf8');
  readFill(html);
  const raw = fs.readFileSync(jsonPath, 'utf8');
  JSON.parse(raw);                       // 先确认是合法 JSON
  if (/<\/script/i.test(raw)) throw new Error('填空题里不能出现 </script');
  const text = raw.replace(/[ \t]+$/gm, '').replace(/\s+$/, '');
  const out = html.replace(FILL_RE, (_, a, __, c) => a + '\n' + text + '\n' + c);
  fs.writeFileSync(outPath, out, 'utf8');
  return { bytes: Buffer.byteLength(out, 'utf8'), lines: out.split('\n').length };
}

function listTemplates(dir) {
  const out = [];
  (function walk(d) {
    for (const f of fs.readdirSync(d)) {
      const p = path.join(d, f);
      const st = fs.statSync(p);
      if (st.isDirectory()) walk(p);
      else if (f.endsWith('.html')) {
        const html = fs.readFileSync(p, 'utf8');
        const m = html.match(/var TEMPLATE = (\{[\s\S]*?\});/);
        const meta = m ? JSON.parse(m[1]) : null;
        out.push({ file: path.relative(dir, p), meta });
      }
    }
  })(dir);
  return out;
}

const args = process.argv.slice(2);
if (args[0] === '--list') {
  const dir = path.join(__dirname);
  for (const t of listTemplates(dir)) {
    console.log('\n' + t.file);
    if (!t.meta) { console.log('  （没有 TEMPLATE 自述）'); continue; }
    console.log('  模板 id : ' + t.meta.id);
    console.log('  必须要算出来 : ' + t.meta.needs.join(', '));
    console.log('  必须有的滑块 : ' + (t.meta.params.length ? t.meta.params.join(', ') : '（无）'));
    console.log('  必须出现在 show : ' + (t.meta.mustShow.length ? t.meta.mustShow.join(', ') : '（无）'));
    console.log('  可引用的元素 : ' + t.meta.slots.join(', '));
  }
  process.exit(0);
}

if (args.length < 3) {
  console.error('用法: node 装配器.js <模板.html> <填空.json> <输出.html>');
  process.exit(2);
}
try {
  const r = assemble(args[0], args[1], args[2]);
  console.log('已生成 ' + args[2] + '  (' + r.bytes + ' bytes, ' + r.lines + ' lines)');
} catch (e) {
  console.error('装配失败：' + e.message);
  process.exit(1);
}
