<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useGetLanguageModel, useGetLanguageModels } from '@/hooks/use-language-model.ts'
import { useUpdateDraftAppConfig } from '@/hooks/use-app.ts'
import { apiPrefix } from '@/config'

const props = defineProps({
  app_id: { type: String, default: '', required: true },
  model_config: { type: Object, default: () => ({}), required: true },
  dialog_round: { type: Number, default: 3, required: true },
})

const emits = defineEmits(['update:model_config'])

type ModelParameterValue =
  | string
  | number
  | boolean
  | Record<string, unknown>
  | (string | number | boolean | Record<string, unknown>)[]
  | undefined

interface ModelConfigForm {
  selectValue: string
  provider: string
  model: string
  parameters: Record<string, ModelParameterValue>
  dialog_round: number
}

// 模板表达式不支持 `as X | Y` 联合类型断言（会被解析为过滤器语法），用函数收窄
const asParamValue = (value: unknown) => value as ModelParameterValue
const asParamOptions = (value: unknown) =>
  value as { label: string; value: string | number | boolean }[] | undefined
const asSliderValue = (value: unknown) => value as number | [number, number] | undefined
const asStringValue = (value: unknown) => value as string | undefined

const form = ref<ModelConfigForm>({
  selectValue: '',
  provider: '',
  model: '',
  parameters: {},
  dialog_round: 3,
})
const {
  loading: getLanguageModelLoading,
  language_model,
  loadLanguageModel,
} = useGetLanguageModel()
const { language_models, loadLanguageModels } = useGetLanguageModels()
const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()

const modelOptions = computed(() => {
  return language_models.value.map((language_model) => {
    return {
      isGroup: true,
      label: language_model.label,
      options: language_model.models.map((model) => {
        return {
          label: model.label,
          value: `${language_model.name}/${model.model}`,
          // 供选中项/option 模板展示解析后的显示名（本地模型 → 实际 LOCAL_LLM_MODEL 值）
          provider_label: language_model.label,
          model_label: model.label,
        }
      }),
    }
  })
})

// 根据当前 form.provider/model 反查选中的显示名，供顶部 chip 使用（不暴露内部 key）
const selectedModelLabel = computed(() => {
  const provider = language_models.value.find(
    (lm) => lm.name === form.value.provider,
  )
  const model = provider?.models.find((m) => m.model === form.value.model)
  return model?.label ?? form.value.model ?? '选择模型'
})

const changeModel = (value: unknown): void => {
  const [provider_name = '', model_name = ''] = String(value).split('/')

  loadLanguageModel(provider_name, model_name).then(() => {
    form.value.parameters =
      language_model.value.parameters?.reduce(
        (acc: Record<string, ModelParameterValue>, parameter) => {
          acc[parameter.name] = (parameter.default ?? null) as ModelParameterValue
          return acc
        },
        {} as Record<string, ModelParameterValue>,
      ) ?? {}
  })
}

// 触发器隐藏处理器，提交数据进行更新
const hideModelTrigger = () => {
  if (!form.value.selectValue) {
    // 尚未选择模型时不做保存，避免用空值覆盖已有配置
    return
  }
  const [provider_name = '', model_name = ''] = form.value.selectValue.split('/')

  // 只保存当前模型仍支持的参数：丢弃已下线/不支持的字段（如 DeepSeek/Kimi 的
  // presence_penalty、frequency_penalty），避免把无效甚至报错参数提交给 API
  const allowedParams = new Set(
    (language_model.value?.parameters ?? []).map((parameter) => parameter.name),
  )
  const parameters = Object.fromEntries(
    Object.entries(form.value.parameters).filter(([name]) => allowedParams.has(name)),
  )

  const model_config = {
    provider: provider_name,
    model: model_name,
    parameters,
  }

  handleUpdateDraftAppConfig(props.app_id, {
    model_config: model_config,
    dialog_round: form.value.dialog_round,
  }).then(() => emits('update:model_config', model_config))
}

watch(
  () => props.model_config,
  (newValue) => {
    form.value['selectValue'] = `${newValue?.provider}/${newValue?.model}`
    form.value['provider'] = newValue?.provider
    form.value['model'] = newValue?.model
    form.value['parameters'] = newValue?.parameters

    if (newValue?.provider && newValue?.model) {
      loadLanguageModel(String(newValue.provider), String(newValue.model))
    }
  },
  { immediate: true },
)

watch(
  () => props.dialog_round,
  (newValue) => {
    form.value['dialog_round'] = newValue
  },
  { immediate: true },
)

onMounted(() => {
  loadLanguageModels()
})
</script>

<template>
  <a-trigger
    trigger="click"
    position="bl"
    :popup-translate="[0, 12]"
    @hide="hideModelTrigger"
  >
    <!-- 模型 chip（对齐 demo .model 选择器） -->
    <div class="ab-model-chip">
      <a-avatar
        v-if="form?.provider"
        :size="16"
        shape="square"
        :image-url="`${apiPrefix}/language_models/${form?.provider}/icon`"
      />
      <span>{{ selectedModelLabel }}</span>
      <icon-down :size="12" />
    </div>
    <template #content>
      <div class="bg-white px-6 py-5 shadow rounded-lg w-[460px]">
        <!-- 标题 -->
        <div class="text-gray-700 text-base font-semibold mb-3">模型设置</div>
        <!-- 模型选择 -->
        <div class="flex flex-col gap-2 mb-2">
          <div class="text-gray-700">模型</div>
          <a-select
            v-model:model-value="form.selectValue"
            :options="modelOptions"
            size="small"
            class="rounded-lg mb-2"
            placeholder="请选择Agent使用的大语言模型"
            @change="changeModel"
          >
            <template #label="{ data }">
              <div class="flex items-center gap-2">
                <a-avatar
                  :size="16"
                  shape="square"
                  :image-url="`${apiPrefix}/language_models/${data.value.split('/')[0]}/icon`"
                />
                <a-space :size="4">
                  <div class="text-xs text-gray-700">{{ data.provider_label ?? data.value.split('/')[0] }}</div>
                  <div class="text-xs text-gray-500">·</div>
                  <div class="text-xs text-gray-700">{{ data.model_label ?? data.value.split('/')[1] }}</div>
                </a-space>
              </div>
            </template>
            <template #option="{ data }">
              <div class="flex items-center gap-2">
                <a-avatar
                  :size="16"
                  shape="square"
                  :image-url="`${apiPrefix}/language_models/${data.value.split('/')[0]}/icon`"
                />
                <div class="text-xs text-gray-700 py-2">{{ data.label }}</div>
              </div>
            </template>
          </a-select>
        </div>
        <!-- 参数列表 -->
        <div class="text-gray-700 mb-2">参数</div>
        <a-spin :loading="getLanguageModelLoading" class="w-full">
          <div
            v-for="parameter in language_model?.parameters"
            :key="parameter.name"
            class="flex items-center gap-2 h-8 mb-4"
          >
            <!-- 字段标签 -->
            <div class="flex items-center gap-2 text-gray-500 w-[120px] flex-shrink-0">
              <div class="text-xs">{{ parameter?.label }}</div>
              <a-tooltip :content="parameter?.help">
                <icon-question-circle />
              </a-tooltip>
            </div>
            <!-- 字段输入框 -->
            <template v-if="parameter?.options?.length > 0">
              <a-select
                v-model:model-value="form.parameters[parameter.name]"
                :default-value="asParamValue(parameter.default)"
                placeholder="请选择参数值"
                :options="asParamOptions(parameter.options)"
              />
            </template>
            <template v-else-if="parameter.type === 'boolean'">
              <a-select
                v-model:model-value="form.parameters[parameter.name]"
                :default-value="asParamValue(parameter.default)"
                placeholder="请选择参数值"
                :options="[
                  { label: '是', value: true },
                  { label: '否', value: false },
                ]"
              />
            </template>
            <template v-else-if="['int', 'float'].includes(parameter.type)">
              <a-slider
                :model-value="asSliderValue(form.parameters[parameter.name])"
                @update:model-value="(value: unknown) => { form.parameters[parameter.name] = asSliderValue(value) }"
                :default-value="asSliderValue(parameter.default)"
                :min="parameter?.min"
                :max="parameter?.max"
                :step="parameter?.type === 'float' ? 0.1 : 1"
                show-input
              />
            </template>
            <template v-else-if="parameter.type === 'string'">
              <a-input
                :model-value="asStringValue(form.parameters[parameter.name])"
                @update:model-value="(value: string) => { form.parameters[parameter.name] = value }"
                :default-value="asStringValue(parameter.default)"
                placeholder="请输入参数值"
              />
            </template>
          </div>
        </a-spin>
        <!-- 携带上下文轮数 -->
        <div class="text-gray-700 mb-2">输入及输出设置</div>
        <div class="flex items-center gap-2 h-8">
          <!-- 字段标签 -->
          <div class="flex items-center gap-2 text-gray-500 w-[120px] flex-shrink-0">
            <div class="text-xs">携带上下文轮数</div>
            <a-tooltip content="每次向Agent提问时需要携带的最近消息对话轮数，默认为3。">
              <icon-question-circle />
            </a-tooltip>
          </div>
          <!-- 滑动输入框 -->
          <a-slider
            v-model:model-value="form.dialog_round"
            :default-value="3"
            :min="0"
            :max="10"
            :step="1"
            show-input
          />
        </div>
      </div>
    </template>
  </a-trigger>
</template>

<style scoped></style>
