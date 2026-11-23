import '@/assets/styles/index.css'
import { createApp, type Component } from 'vue'
import { createPinia } from 'pinia'

import App from '@/App.vue'
import router from '@/router'
import { setupA11yAutoFix } from '@/utils/a11y'
import {
  IconBranch,
  IconCode,
  IconDown,
  IconFile,
  IconFilePdf,
  IconFilter,
  IconHome,
  IconImage,
  IconLanguage,
  IconLeft,
  IconLink,
  IconRight,
  IconStorage,
  IconTool,
  IconUp,
} from '@arco-design/web-vue/es/icon'

const app = createApp(App)

app.use(createPinia())
app.use(router)

// 模板中通过字符串动态引用的 Arco 图标（<component :is="'icon-xxx'">）无法被
// @arco-plugins/vite-vue 静态转换，这里显式全局注册；其余图标/组件由插件按需引入
const dynamicIcons: Array<[string, Component]> = [
  ['icon-home', IconHome],
  ['icon-language', IconLanguage],
  ['icon-tool', IconTool],
  ['icon-storage', IconStorage],
  ['icon-branch', IconBranch],
  ['icon-link', IconLink],
  ['icon-code', IconCode],
  ['icon-filter', IconFilter],
  ['icon-left', IconLeft],
  ['icon-right', IconRight],
  ['icon-up', IconUp],
  ['icon-down', IconDown],
  ['icon-file', IconFile],
  ['icon-file-pdf', IconFilePdf],
  ['icon-image', IconImage],
]
dynamicIcons.forEach(([name, component]) => app.component(name, component))

app.mount('#app')

// 全局表单无障碍自动修复（为缺少 id/name 的控件分配唯一 id、为 <label> 补全 for，
// 并补全常见登录/注册字段的 autocomplete 以便浏览器自动填充）
setupA11yAutoFix()
