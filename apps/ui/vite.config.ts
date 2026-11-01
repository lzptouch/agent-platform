import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'

// C7：base 必须为 '/'，assetsDir 一级目录为 'assets/'
export default defineConfig({
  plugins: [vue()],
  base: '/',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    // **改造要点（design/16 §2.9-⑧ / R14）**：sourcemap 会随 extraResources
    // 打进安装包（既占 ~10MB，也等于把源码原样发出去）→ 关闭。
    sourcemap: false,
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5185,
    host: true,
    proxy: {
      '/api': {
        // **改造要点（design/16 §11.6 P6-04）**：proxy 目标改指 TS server
        // （开发态 `cd apps/server && AGENT_PORT=18040 npm run dev`）。
        target: 'http://127.0.0.1:18040',
        changeOrigin: true,
      },
    },
  },
})