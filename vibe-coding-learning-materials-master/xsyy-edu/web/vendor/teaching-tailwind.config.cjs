/**
 * 教学动画播放器(teaching_template.html)专用 Tailwind 构建配置。
 * 独立于主站 web/tailwind.config.js：仅扫描模板，预编译出静态 CSS，
 * 以取代 https://cdn.tailwindcss.com 的运行时 JIT（公网/国内不可达时整页裸奔）。
 * 重新生成：见 teaching-build-tailwind.sh
 */
module.exports = {
  content: [
    "E:/象数演易/1/xsyy/vibe-coding-learning-materials-master/xsyy-edu/backend/prompt/teaching_template.html",
  ],
  theme: { extend: {} },
  plugins: [],
  corePlugins: { preflight: true },
};
