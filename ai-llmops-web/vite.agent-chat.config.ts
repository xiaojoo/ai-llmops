import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { vitePluginForArco } from '@arco-plugins/vite-vue'
import { viteSingleFile } from 'vite-plugin-singlefile'

/**
 * AgentChat 嵌入构建配置
 * 产出单文件 index.html（JS/CSS 全部内联），供 IDEA 插件 JCEF 通过 file:// 加载。
 * 单文件方案规避 module 脚本在自定义 scheme 下被 Chromium 跨源拦截的问题。
 * 用法：vite build --config vite.agent-chat.config.ts
 * 输出：dist/agent-chat-embed/index.html
 *   （vite 保留输入相对项目根的路径：输入 agent-chat-embed/index.html + outDir=dist）
 * 注意：outDir 与主应用构建共用 dist/，故 emptyOutDir 必须为 false，
 *       避免 agent-chat 构建清空主应用的生产产物。
 */
export default defineConfig({
  plugins: [
    vue(),
    // Arco 按需引入（图标按使用打包）
    vitePluginForArco({ style: 'css' }),
    // 关键：把所有 JS/CSS 内联进 index.html（生产构建时生效）
    viteSingleFile(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  base: './', // 相对路径
  build: {
    outDir: 'dist',
    emptyOutDir: false,
    rollupOptions: {
      input: fileURLToPath(new URL('./agent-chat-embed/index.html', import.meta.url)),
      output: {
        manualChunks: undefined,
        entryFileNames: 'assets/[name].js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/[name][extname]',
      },
    },
    chunkSizeWarningLimit: 2000,
  },
})
