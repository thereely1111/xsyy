#!/usr/bin/env bash
# 重建教学动画播放器的本地 Tailwind CSS。
# 触发时机：backend/prompt/teaching_template.html 新增/修改了 Tailwind 工具类后，
#           必须重新运行本脚本，并更新模板里对该 CSS 的引用（文件名版本化，匹配 CF 对 CSS 的缓存策略）。
set -euo pipefail
cd "$(dirname "$0")/../.."   # web/vendor -> xsyy-edu 根
DATE=$(date +%Y%m%d)
OUT="web/vendor/teaching-tailwind.${DATE}.css"
node web/node_modules/tailwindcss/lib/cli.js \
  -c web/vendor/teaching-tailwind.config.cjs \
  -i web/vendor/teaching-input.css \
  -o "$OUT" --minify
echo "已生成 $OUT"
echo "请同步把 backend/prompt/teaching_template.html 中的引用改为 /vendor/teaching-tailwind.${DATE}.css"
