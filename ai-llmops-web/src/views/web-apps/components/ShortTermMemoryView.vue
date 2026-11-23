<script setup lang="ts">
// 短期记忆视图：只读展示当前短期记忆窗口内的消息（未归档的最近 N 轮，即参与模型上下文的部分）。
// 短期记忆 = 对话时携带的最近 dialog_round 轮上下文；窗口外的旧消息已归档（is_archived=true），不在此展示。
import { computed, type PropType } from 'vue'
import type { GetConversationMessagesWithPageResponse } from '@/models/conversation.ts'

type MessageItem = GetConversationMessagesWithPageResponse['data']['list'][number]

const props = defineProps({
  messages: {
    type: Array as PropType<MessageItem[]>,
    required: true,
    default: () => [],
  },
  // 当前生效的短期记忆轮数（会话覆盖值或应用默认值）
  dialogRound: { type: Number, required: true },
})

// 记忆窗口 = 未归档消息，且排除点踩消息（点踩不参与短期记忆，按时间正序展示）
const windowMessages = computed<MessageItem[]>(() =>
  props.messages.filter((m) => !m.is_archived && m.feedback !== 'dislike'),
)
</script>

<template>
  <div class="flex-1 min-h-0 w-full overflow-y-auto bg-white">
    <div class="max-w-[976px] mx-auto px-6 py-4">
      <!-- 顶部说明：当前记忆窗口轮数 -->
      <div class="flex items-center justify-between mb-3">
        <div class="text-sm text-gray-700">
          短期记忆
          <span class="text-gray-400">· 对话时携带最近 {{ dialogRound }} 轮上下文</span>
        </div>
        <span class="text-xs text-gray-400 flex-shrink-0 ml-3">窗口内 {{ windowMessages.length }} 条消息</span>
      </div>

      <!-- 空态 -->
      <div v-if="windowMessages.length === 0" class="py-16 text-center text-gray-400 text-sm">
        当前短期记忆窗口为空
      </div>

      <!-- 记忆窗口内消息（只读：用户问题 + AI 回答） -->
      <div v-else class="flex flex-col gap-3">
        <div v-for="(msg, i) in windowMessages" :key="msg.id" class="rounded-2xl border p-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs text-gray-400">第 {{ i + 1 }} 轮</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">记忆窗口内</span>
          </div>
          <div class="text-sm">
            <div class="flex gap-2">
              <span class="flex-none text-gray-400">用户</span>
              <span class="min-w-0 text-gray-800 break-all">{{ msg.query || '—' }}</span>
            </div>
            <div class="flex gap-2 mt-1.5">
              <span class="flex-none text-gray-400">AI</span>
              <span class="min-w-0 break-all" :class="msg.error ? 'text-red-600' : 'text-gray-800'">
                {{ msg.error || msg.answer || '—' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
