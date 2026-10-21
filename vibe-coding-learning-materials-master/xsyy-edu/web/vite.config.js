import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    build: {
        // 关键：dist 内含手工部署的静态文件（admin/、js/、images/、user_interface.html 等），
        // 绝不能清空整个目录，否则会被视为误删 dist。只覆盖 vite 自身产物。
        emptyOutDir: false,
    },
    server: {
        host: '0.0.0.0',
        port: 5173,
    },
});
