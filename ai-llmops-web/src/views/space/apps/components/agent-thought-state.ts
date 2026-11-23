// 运行流程各消息的展开状态（module 级共享：虚拟滚动卸载/重挂载组件时状态不丢失）
import { reactive } from 'vue'

export const mainExpandedMap = reactive<Record<string, boolean>>({})
export const stepExpandedMap = reactive<Record<string, boolean>>({})
export const planExpandedMap = reactive<Record<string, boolean>>({})
export const subTaskExpandedMap = reactive<Record<string, boolean>>({})
export const stepContentExpandedMap = reactive<Record<string, boolean>>({})
export const traceExpandedMap = reactive<Record<string, boolean>>({})

// 运行流程 → 任务详情 跳转焦点（跨组件共享：AgentThought 点击某一步，SubAgentDetail 高亮定位）
export const focusState = reactive<{
  messageId: string | null
  thoughtId: string | null
  nonce: number // 连续点击同一事件时也能触发 watch
}>({
  messageId: null,
  thoughtId: null,
  nonce: 0,
})

export const setFocusThought = (messageId: string, thoughtId: string) => {
  focusState.messageId = messageId
  focusState.thoughtId = thoughtId
  focusState.nonce += 1
}

export const clearFocusThought = () => {
  focusState.messageId = null
  focusState.thoughtId = null
}

