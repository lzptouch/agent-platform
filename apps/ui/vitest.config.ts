import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

/**
 * 单元测试配置（阶段 0 工程基建）。
 * 与 vite.config.ts 分离，避免测试配置污染生产构建。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    // 单测已归拢到仓库根 tests/unit/ui/，裸导入（pinia / @vue/test-utils …）
    // 从那里向上找不到 node_modules → 显式补充本包的模块目录
    modules: ['node_modules', fileURLToPath(new URL('./node_modules', import.meta.url))],
  },
  server: {
    // 单测已归拢到仓库根 tests/unit/ui/（在 app 根目录之外）→ 放行文件访问
    fs: { allow: [fileURLToPath(new URL('../..', import.meta.url))] },
  },
  test: {
    environment: 'jsdom',
    include: ['../../tests/unit/ui/**/*.spec.ts'],
    // tests/unit/ui/node_modules 是指向本包 node_modules 的软链（裸导入解析用），
    // 必须排除，否则会把依赖包自带的 *.spec.ts 跑进来
    exclude: ['../../tests/unit/ui/node_modules/**', '**/node_modules/**', '**/dist/**'],
    globals: true,
    restoreMocks: true,
  },
})
