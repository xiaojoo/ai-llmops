<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import type { FormInstance, ValidatedError } from '@arco-design/web-vue'
import {
  createCustomLlmModel,
  deleteCustomLlmModel,
  getCustomLlmModelProtocols,
  getCustomLlmModels,
  updateCustomLlmModel,
} from '@/services/custom-llm-model.ts'
import type { CustomLlmModel } from '@/models/custom-llm-model.ts'

// ============ 列表 ============
const models = ref<CustomLlmModel[]>([])
const loading = ref(false)
const deleting = ref('')

const PROTOCOL_LABELS: Record<string, string> = {
  openai: 'OpenAI',
  responses: 'Responses',
  anthropic: 'Anthropic',
}
const protocolLabel = (p: string) => PROTOCOL_LABELS[p] ?? p

const FEATURE_OPTIONS = [
  { label: '工具调用', value: 'tool_call' },
  { label: 'Agent 思考', value: 'agent_thought' },
  { label: '图片输入', value: 'image_input' },
]
const FEATURE_LABELS: Record<string, string> = {
  tool_call: '工具调用',
  agent_thought: 'Agent 思考',
  image_input: '图片输入',
}
const featureLabel = (f: string) => FEATURE_LABELS[f] ?? f

const loadModels = async () => {
  loading.value = true
  try {
    const resp = await getCustomLlmModels()
    models.value = resp.data || []
  } catch (err) {
    Message.error('加载自定义模型失败: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    loading.value = false
  }
}

// ============ 协议下拉选项 ============
const protocolOptions = ref<{ label: string; value: string }[]>([])
const loadProtocols = async () => {
  try {
    const resp = await getCustomLlmModelProtocols()
    protocolOptions.value = resp.data || []
  } catch (err) {
    Message.error('加载协议列表失败: ' + (err instanceof Error ? err.message : String(err)))
  }
}

// ============ 表单 ============
const modalVisible = ref(false)
const submitting = ref(false)
const editingId = ref('')
const editing = computed(() => Boolean(editingId.value))
// 编辑态下用户是否重新填写 API Key（false 表示保持原值：提交空字符串）
const apiKeyDirty = ref(false)
const formRef = ref<FormInstance | null>(null)

interface CustomLlmForm {
  name: string
  protocol: string
  model_id: string
  base_url: string
  api_key: string
  features: string[]
  context_window: number
  max_output_tokens: number
  remark: string
  icon: string
}

const form = reactive<CustomLlmForm>({
  name: '',
  protocol: 'openai',
  model_id: '',
  base_url: '',
  api_key: '',
  features: [],
  context_window: 0,
  max_output_tokens: 0,
  remark: '',
  icon: '',
})

const formRules = {
  name: [{ required: true, message: '请输入模型名称' }],
  protocol: [{ required: true, message: '请选择协议' }],
  model_id: [{ required: true, message: '请输入模型 ID' }],
}

const resetForm = () => {
  editingId.value = ''
  apiKeyDirty.value = false
  form.name = ''
  form.protocol = 'openai'
  form.model_id = ''
  form.base_url = ''
  form.api_key = ''
  form.features = []
  form.context_window = 0
  form.max_output_tokens = 0
  form.remark = ''
  form.icon = ''
}

const openCreate = () => {
  resetForm()
  modalVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
}

const openEdit = (row: CustomLlmModel) => {
  resetForm()
  editingId.value = row.id
  form.name = row.name || ''
  form.protocol = row.protocol || 'openai'
  form.model_id = row.model_id || ''
  form.base_url = row.base_url || ''
  form.features = row.features || []
  form.context_window = row.context_window ?? 0
  form.max_output_tokens = row.max_output_tokens ?? 0
  form.remark = row.remark || ''
  form.icon = row.icon || ''
  // 后端对 API Key 始终返回掩码 ********：编辑时置空，回显「已配置」，留空则保持原值
  form.api_key = ''
  apiKeyDirty.value = false
  modalVisible.value = true
  nextTick(() => formRef.value?.clearValidate())
}

const handleDelete = async (row: CustomLlmModel) => {
  deleting.value = row.id
  try {
    await deleteCustomLlmModel(row.id)
    Message.success('删除成功')
    await loadModels()
  } catch (err) {
    Message.error('删除失败: ' + (err instanceof Error ? err.message : String(err)))
  } finally {
    deleting.value = ''
  }
}

const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return
  submitting.value = true
  try {
    const payload = {
      name: form.name.trim(),
      protocol: form.protocol,
      model_id: form.model_id.trim(),
      base_url: form.base_url.trim(),
      // 编辑且用户未重新填写 Key → 提交空字符串，后端保持原值
      api_key: editing.value && !apiKeyDirty.value ? '' : form.api_key,
      features: form.features,
      context_window: form.context_window ?? 0,
      max_output_tokens: form.max_output_tokens ?? 0,
      remark: form.remark.trim(),
      icon: form.icon.trim(),
    }
    if (editing.value) {
      await updateCustomLlmModel(editingId.value, payload)
      Message.success('更新成功')
    } else {
      await createCustomLlmModel(payload)
      Message.success('新增成功')
    }
    modalVisible.value = false
    await loadModels()
  } catch (err) {
    Message.error(
      (editing.value ? '更新失败: ' : '新增失败: ') +
        (err instanceof Error ? err.message : String(err)),
    )
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadProtocols()
  loadModels()
})
</script>

<template>
  <div>
    <!-- 区块标题 + 新增按钮 -->
    <div class="flex items-center justify-between mb-3">
      <div>
        <div class="text-sm font-semibold text-gray-700">自定义 API 模型</div>
        <div class="text-xs text-gray-400 mt-0.5">
          按账号管理的自定义 LLM（OpenAI / Responses / Anthropic 协议）
        </div>
      </div>
      <a-button type="primary" size="small" @click="openCreate">新增模型</a-button>
    </div>

    <!-- 列表：模型卡片块（与上方 ConfigGroup 视觉一致） -->
    <div v-if="loading" class="py-6 text-center text-xs text-gray-400">加载中…</div>
    <div v-else>
      <div
        v-for="model in models"
        :key="model.id"
        class="mb-3 border border-gray-200 rounded-lg bg-white overflow-hidden"
      >
        <!-- 卡片头：名称 + 操作 -->
        <div class="flex items-center justify-between px-4 py-2.5 bg-gray-50 border-b border-gray-200">
          <div class="flex items-center gap-2 min-w-0">
            <a-tag v-if="model.protocol" size="small" color="arcoblue" class="shrink-0">
              {{ protocolLabel(model.protocol) }}
            </a-tag>
            <div class="text-sm font-medium text-gray-700 truncate">{{ model.name }}</div>
          </div>
          <a-space :size="4" class="shrink-0">
            <a-button size="mini" type="text" class="!text-gray-700" @click="openEdit(model)">
              编辑
            </a-button>
            <a-popconfirm
              content="确认删除该模型？"
              position="left"
              type="error"
              @ok="() => handleDelete(model)"
            >
              <a-button
                size="mini"
                type="text"
                class="!text-red-500 hover:!text-red-600"
                :loading="deleting === model.id"
              >
                删除
              </a-button>
            </a-popconfirm>
          </a-space>
        </div>

        <!-- 卡片体：label/value 行（与上方 ConfigRow 一致：w-48 label + 灰底内容） -->
        <div class="px-4 py-1">
          <div class="flex gap-3 py-2 border-b border-gray-100 last:border-0">
            <div class="w-48 shrink-0">
              <div class="text-xs font-medium text-gray-600">模型 ID</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700 font-mono break-all" style="min-height: 28px">
                {{ model.model_id || '-' }}
              </div>
            </div>
          </div>
          <div class="flex gap-3 py-2 border-b border-gray-100 last:border-0">
            <div class="w-48 shrink-0">
              <div class="text-xs font-medium text-gray-600">Base URL</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700 font-mono break-all" style="min-height: 28px">
                {{ model.base_url || '-' }}
              </div>
            </div>
          </div>
          <div class="flex gap-3 py-2 border-b border-gray-100 last:border-0">
            <div class="w-48 shrink-0">
              <div class="text-xs font-medium text-gray-600">能力</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700" style="min-height: 28px">
                <a-space v-if="model.features?.length" wrap>
                  <a-tag v-for="f in model.features" :key="f" size="small" color="blue">
                    {{ featureLabel(f) }}
                  </a-tag>
                </a-space>
                <span v-else class="text-gray-400">-</span>
              </div>
            </div>
          </div>
          <div class="flex gap-3 py-2 border-b border-gray-100 last:border-0">
            <div class="w-48 shrink-0">
              <div class="text-xs font-medium text-gray-600">上下文窗口</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700" style="min-height: 28px">
                {{ model.context_window ?? 0 }}
              </div>
            </div>
          </div>
          <div class="flex gap-3 py-2 border-b border-gray-100 last:border-0">
            <div class="w-48 shrink-0">
              <div class="text-xs font-medium text-gray-600">最大输出</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700" style="min-height: 28px">
                {{ model.max_output_tokens ?? 0 }}
              </div>
            </div>
          </div>
          <div class="flex gap-3 py-2 border-b border-gray-100 last:border-0">
            <div class="w-48 shrink-0">
              <div class="text-xs font-medium text-gray-600">备注</div>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center px-3 bg-gray-50 border border-gray-200 rounded text-xs text-gray-700 break-all" style="min-height: 28px">
                {{ model.remark || '-' }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新增/编辑弹窗 -->
    <a-modal
      :visible="modalVisible"
      hide-title
      :footer="false"
      :width="'clamp(320px, 90vw, 640px)'"
      @cancel="modalVisible = false"
      @update:visible="(v: boolean) => (modalVisible = v)"
    >
      <div class="flex items-center justify-between">
        <div class="text-lg font-bold text-gray-700">{{ editing ? '编辑模型' : '新增模型' }}</div>
        <a-button
          type="text"
          class="!text-gray-700"
          size="small"
          @click="modalVisible = false"
        >
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>

      <div class="pt-5">
        <a-form ref="formRef" :model="form" :rules="formRules" layout="vertical" @submit="handleSubmit">
          <a-form-item field="name" label="名称">
            <a-input
              v-model="form.name"
              allow-clear
              maxlength="100"
              placeholder="请输入模型名称"
            />
          </a-form-item>

          <a-form-item field="protocol" label="协议">
            <a-select v-model="form.protocol" placeholder="请选择协议">
              <a-option
                v-for="opt in protocolOptions"
                :key="opt.value"
                :value="opt.value"
              >
                {{ opt.label }}
              </a-option>
            </a-select>
          </a-form-item>

          <a-form-item field="model_id" label="模型 ID">
            <a-input
              v-model="form.model_id"
              allow-clear
              placeholder="请求体 model 字段，如 gpt-4o"
            />
          </a-form-item>

          <a-form-item field="base_url" label="Base URL">
            <a-input
              v-model="form.base_url"
              allow-clear
              placeholder="https://api.openai.com/v1"
            />
          </a-form-item>

          <a-form-item field="api_key" label="API Key">
            <!-- 编辑态：已有 Key 时掩码显示「已配置」，留空提交则保持原值 -->
            <div
              v-if="editing && !apiKeyDirty"
              class="flex items-center justify-between gap-2 px-3 text-xs text-gray-500 font-mono border border-gray-200 rounded bg-gray-50"
              style="height: 30px"
            >
              <span>已配置</span>
              <a-button size="mini" type="text" class="!text-blue-600" @click="apiKeyDirty = true">
                重新填写
              </a-button>
            </div>
            <a-input-password
              v-else
              v-model="form.api_key"
              allow-clear
              :placeholder="editing ? '留空则保持原有 Key' : '请输入 API Key'"
            />
            <div v-if="editing" class="text-xs text-gray-400 mt-1">
              已配置 Key 留空则不修改；输入新 Key 会覆盖原有配置
            </div>
          </a-form-item>

          <a-form-item field="features" label="能力标记">
            <a-checkbox-group v-model:model-value="form.features">
              <a-checkbox v-for="f in FEATURE_OPTIONS" :key="f.value" :value="f.value">
                {{ f.label }}
              </a-checkbox>
            </a-checkbox-group>
          </a-form-item>

          <div class="grid grid-cols-2 gap-4">
            <a-form-item field="context_window" label="上下文窗口">
              <a-input-number
                v-model="form.context_window"
                :min="0"
                class="w-full"
                placeholder="上下文窗口长度"
              />
            </a-form-item>
            <a-form-item field="max_output_tokens" label="最大输出 tokens">
              <a-input-number
                v-model="form.max_output_tokens"
                :min="0"
                class="w-full"
                placeholder="最大输出 tokens"
              />
            </a-form-item>
          </div>

          <a-form-item field="icon" label="图标 URL">
            <a-input v-model="form.icon" allow-clear placeholder="https://...（可选）" />
          </a-form-item>

          <a-form-item field="remark" label="备注">
            <a-textarea
              v-model="form.remark"
              :max-length="200"
              show-word-limit
              placeholder="备注信息（可选）"
            />
          </a-form-item>

          <div class="flex items-center justify-end gap-3">
            <a-button @click="modalVisible = false">取消</a-button>
            <a-button
              type="primary"
              html-type="submit"
              :loading="submitting"
            >
              保存
            </a-button>
          </div>
        </a-form>
      </div>
    </a-modal>
  </div>
</template>

<style scoped></style>
