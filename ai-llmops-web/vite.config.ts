import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import { visualizer } from 'rollup-plugin-visualizer'
import { vitePluginForArco } from '@arco-plugins/vite-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    // Arco Design 按需引入：组件/图标 JS 按实际使用打包，样式按需注入。
    // 注意 style 不能为 false —— 插件会用 style===false 短路整个 JS 转换，
    // 导致 dev 下 a-* 组件全部不解析
    vitePluginForArco({ style: 'css' }),
    vueDevTools(),
    visualizer({
      filename: 'dist/stats.html', // 输出文件
      open: false, // 不在构建完成后自动打开浏览器
      gzipSize: true, // 显示 gzip 后大小
      brotliSize: true, // 显示 brotli 后大小
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        rewrite(path) {
          return path.replace(/^\/api/, '')
        },
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 大依赖单独拆 chunk：避免单个 chunk 超过 500KB，并利于浏览器缓存
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('@arco-design/web-vue')) return 'arco'
          if (id.includes('echarts') || id.includes('zrender')) return 'echarts'
          if (
            id.includes('markdown-it') ||
            id.includes('dompurify') ||
            id.includes('github-markdown-css')
          ) {
            return 'markdown'
          }
          if (id.includes('highlight.js')) return 'highlight'
          if (id.includes('@vue-flow') || id.includes('dagre')) return 'flow'
          if (id.includes('vue-virtual-scroller')) return 'virtual-scroller'
          return 'vendor'
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
})
