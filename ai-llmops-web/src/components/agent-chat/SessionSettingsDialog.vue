<script setup lang="ts">
/**
 * SessionSettingsDialog — 会话设置弹框（短期记忆轮数，按会话独立保存）
 * 深色主题模态框：数字输入 0-100 + 跟随应用默认；保存由父级处理（saving/saveError props 回传）。
 * 打开时按当前会话覆盖值初始化表单。
 */
import { ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    visible: boolean
    /** 当前会话 id；空 = 尚无会话（首次发送前），禁用保存 */
    conversationId?: string
    /** 当前会话的覆盖值（未设置 = null） */
    currentDialogRound?: number | null
    /** 应用默认轮数 */
    appDefaultRound?: number
    saving?: boolean
    saveError?: string
  }>(),
  {
    conversationId: '',
    currentDialogRound: null,
    appDefaultRound: 3,
    saving: false,
    saveError: '',
  },
)

const emit = defineEmits<{
  'update:visible': [value: boolean]
  save: [round: number | null]
}>()

const round = ref(3)
const useDefault = ref(true)

// 打开时按当前会话覆盖值初始化表单（null → 跟随应用默认）
watch(
  () => props.visible,
  (v) => {
    if (!v) return
    const override = props.currentDialogRound
    useDefault.value = override === null || override === undefined
    round.value = override ?? props.appDefaultRound
  },
)

// 数字输入（0-100 截断；空/非数字视为 0）
const onRoundInput = (e: Event) => {
  const raw = (e.target as HTMLInputElement).value
  const n = Number(raw)
  if (raw === '' || Number.isNaN(n)) {
    round.value = 0
    return
  }
  round.value = Math.min(100, Math.max(0, Math.trunc(n)))
}

const onSave = () => emit('save', useDefault.value ? null : round.value)
</script>

<template>
  <div v-if="props.visible" class="settings-mask" @click.self="emit('update:visible', false)">
    <div class="settings-dialog" role="dialog" aria-modal="true">
      <div class="settings-dialog__title">设置</div>
      <div class="settings-dialog__body">
        <div class="settings-field">
          <div class="settings-field__label">短期记忆</div>
          <div class="settings-field__desc">
            对话时携带最近 {{ useDefault ? props.appDefaultRound : round }} 轮上下文作为短期记忆
            （0 表示不携带历史；不设置时使用应用默认 {{ props.appDefaultRound }} 轮，按会话独立保存、下次对话生效）。
          </div>
          <div class="settings-field__row">
            <input
              type="range"
              min="0"
              max="100"
              step="1"
              :value="round"
              :disabled="useDefault"
              class="settings-slider"
              @input="onRoundInput"
            />
            <input
              type="number"
              min="0"
              max="100"
              step="1"
              :value="round"
              :disabled="useDefault"
              class="settings-number"
              aria-label="短期记忆轮数"
              @input="onRoundInput"
            />
          </div>
          <label class="settings-field__check">
            <input type="checkbox" v-model="useDefault" />
            <span>跟随应用默认（{{ props.appDefaultRound }} 轮）</span>
          </label>
        </div>
        <div v-if="props.saveError" class="settings-error">{{ props.saveError }}</div>
      </div>
      <div v-if="!props.conversationId" class="settings-hint">发送一条消息后即可设置</div>
      <div class="settings-dialog__footer">
        <button
          type="button"
          class="settings-btn"
          :disabled="props.saving"
          @click="emit('update:visible', false)"
        >
          取消
        </button>
        <button
          type="button"
          class="settings-btn settings-btn--primary"
          :disabled="props.saving || !props.conversationId"
          @click="onSave"
        >
          {{ props.saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-mask {
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
}

.settings-dialog {
  width: min(340px, calc(100vw - 40px));
  background: #1d1e20;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  box-shadow: 0 10px 32px rgba(0, 0, 0, 0.55);
  padding: 16px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.settings-dialog__title {
  font-size: 14px;
  font-weight: 600;
  color: #e0e0e0;
}

.settings-dialog__body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.settings-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.settings-field__label {
  font-size: 13px;
  font-weight: 500;
  color: #e0e0e0;
}

.settings-field__desc {
  font-size: 11.5px;
  line-height: 1.6;
  color: #9aa3b2;
}

.settings-field__row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.settings-slider {
  flex: 1;
  min-width: 0;
  accent-color: #2563eb;
}

.settings-slider:disabled {
  accent-color: #4b5563;
}

.settings-number {
  width: 72px;
  flex-shrink: 0;
  height: 30px;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 6px;
  background: #232425;
  color: #e0e0e0;
  font-size: 13px;
  padding: 0 8px;
  outline: none;
  box-sizing: border-box;
}

.settings-number:focus {
  border-color: #2563eb;
}

.settings-number:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.settings-field__check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #b8b8b8;
  cursor: pointer;
  user-select: none;
}

.settings-field__check input {
  accent-color: #2563eb;
}

.settings-error {
  font-size: 12px;
  color: #fca5a5;
  word-break: break-word;
}

.settings-hint {
  font-size: 11.5px;
  color: #8a93a3;
}

.settings-dialog__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.settings-btn {
  border-radius: 6px;
  padding: 6px 16px;
  font-size: 12.5px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
  transition: background 0.15s ease;
}

.settings-btn:hover:not(:disabled) {
  background: #2a2d31;
}

.settings-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.settings-btn--primary {
  border: none;
  background: #2563eb;
  color: #ffffff;
}

.settings-btn--primary:hover:not(:disabled) {
  background: #1d4ed8;
}
</style>
