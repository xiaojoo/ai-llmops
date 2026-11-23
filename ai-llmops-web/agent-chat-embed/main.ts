/**
 * AgentChat 嵌入入口（供 IDEA 插件 JCEF 加载）
 * 挂载 AgentChatEmbed（SFC）——模板由 vite 编译期处理，不依赖运行时编译器。
 */
import { createApp } from 'vue'
import AgentChatEmbed from './AgentChatEmbed.vue'
import './style.css'

createApp(AgentChatEmbed).mount('#app')
