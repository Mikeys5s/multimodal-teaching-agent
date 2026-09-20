import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 析知 XiZhi 前端构建配置
// - 开发端口固定 5173（已同步给 P2 作为开发期 CORS 白名单）
// - 开发期通过 proxy 把 /api 转发到后端 127.0.0.1:8000，避免跨域
// - 生产构建产物为 dist/，由后端容器以静态文件方式挂载在 /
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_DEV_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
