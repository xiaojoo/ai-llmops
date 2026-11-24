<script setup lang="ts">
import { Message, type ValidatedError } from '@arco-design/web-vue'
import { computed, ref, watch } from 'vue'
import cloneDeep from 'lodash/cloneDeep'
import { useVueFlow } from '@vue-flow/core'
import { getReferencedVariables } from '@/utils/helper.ts'

const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  node: { type: Object, required: true, default: () => ({}) },
  loading: { type: Boolean, required: true, default: false },
})

const emits = defineEmits(['updateNode', 'update:visible'])
const { nodes, edges } = useVueFlow()
type TemplateTransformFormInput = {
  name: string
  type: string
  content: string
  ref: string
  required?: boolean
}
type TemplateTransformForm = {
  id?: string
  type?: string
  title?: string
  description?: string
  template?: string
  model_config?: Record<string, unknown>
  inputs: TemplateTransformFormInput[]
  outputs?: { name: string; type: string; value: { type: string; content: string } }[]
}
const form = ref<TemplateTransformForm>({ inputs: [] })

const inputRefOptions = computed(() => {
  return getReferencedVariables(cloneDeep(nodes.value), cloneDeep(edges.value), props.node.id)
})

const addFormInputField = () => {
  form.value.inputs?.push({
    name: '',
    type: 'string',
    content: '',
    required: true,
    ref: '',
  })
  Message.success('新增输入字段成功')
}

const removeFormInputField = (idx: number) => {
  form.value?.inputs?.splice(idx, 1)
}

const onSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
// 检查表单是否出现错误，如果出现错误则直接结束
  if (errors) return

  const cloneInputs = cloneDeep(form.value.inputs) ?? []

// 数据校验通过，通过事件触发数据更新
  emits('updateNode', {
    id: props.node.id,
    title: form.value.title,
    description: form.value.description,
    template: form.value.template,
    inputs: cloneInputs.map((input) => {
      return {
        name: input.name,
        description: '',
        required: true,
        type: input.type === 'ref' ? 'string' : input.type,
        value: {
          type: input.type === 'ref' ? 'ref' : 'literal',
          content:
            input.type === 'ref'
              ? {
                  ref_node_id: input.ref.split('/')[0] || '',
                  ref_var_name: input.ref.split('/')[1] || '',
                }
              : input.content,
        },
        meta: {},
      }
    }),
    outputs: cloneDeep(form.value.outputs),
  })
}

// 节点数据输入（来自草稿图，含扩展字段）
type NodeSourceInput = {
  name: string
  type: string
  value: { type: string; content: unknown }
}

// 监听数据，将数据映射到表单模型上
watch(
  () => props.node,
  (newNode) => {
    const cloneInputs = cloneDeep(newNode.data.inputs)
    form.value = {
      id: newNode.id,
      type: newNode.type,
      title: newNode.data.title,
      description: newNode.data.description,
      template: newNode.data.template,
      model_config: {
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        parameters: {
          frequency_penalty: 0.2,
          max_tokens: 8192,
          presence_penalty: 0.2,
          temperature: 0.5,
          top_p: 0.85,
        },
      },
      inputs: cloneInputs.map((input: NodeSourceInput) => {
        const refContent = input.value.content as { ref_node_id: string; ref_var_name: string }
        const ref =
          input.value.type === 'ref'
            ? `${refContent.ref_node_id}/${refContent.ref_var_name}`
            : ''

// 判断引用的变量值信息是否存在，如果不存在则设置为空
        let refExists = false
        if (input.value.type === 'ref') {
          for (const inputRefOption of inputRefOptions.value) {
            for (const option of inputRefOption.options) {
              if (option.value === ref) {
                refExists = true
                break
              }
            }
          }
        }
        return {
          name: input.name, // 变量名
          type: input.value.type === 'literal' ? input.type : 'ref', // 数据类型(涵盖ref/string等)
          content: input.value.type === 'literal' ? (input.value.content as string) : '', // 变量值内容
          ref: input.value.type === 'ref' && refExists ? ref : '', // 变量引用信息，存储引用关系
        }
      }),
      outputs: [{ name: 'output', type: 'string', value: { type: 'generated', content: '' } }],
    }
  },
  { immediate: true },
)
</script>

<template>
  <div
    v-if="props.visible"
    id="start-node-info"
    class="absolute top-0 right-0 bottom-0 w-[400px] border-l z-50 bg-white overflow-scroll scrollbar-w-none p-3"
  >
    <!-- 顶部标题信息 -->
    <div class="flex items-center justify-between gap-3 mb-2">
      <!-- 左侧标题 -->
      <div class="flex items-center gap-1 flex-1">
        <a-avatar :size="30" shape="square" class="!bg-blue-700 rounded-lg shrink-0">
          <icon-home />
        </a-avatar>
        <a-input
          v-model:model-value="form.title"
          placeholder="请输入标题"
          class="!bg-white text-gray-700 font-semibold px-2"
        />
      </div>
      <!-- 右侧关闭按钮 -->
      <a-button
        type="text"
        size="mini"
        class="!text-gray-700 shrink-0"
        @click="() => emits('update:visible', false)"
      >
        <template #icon>
          <icon-close />
        </template>
      </a-button>
    </div>
    <!-- 描述信息 -->
    <a-textarea
      :auto-size="{ minRows: 3, maxRows: 5 }"
      v-model="form.description"
      class="rounded-lg text-gray-700 !text-xs"
      placeholder="输入描述..."
    />
    <!-- 分隔符 -->
    <a-divider class="my-2" />
    <!-- 输入数据表单 -->
    <a-form :model="form" size="mini" layout="vertical" @submit="onSubmit">
      <!-- 输入参数 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="a">输入参数</div>
            <a-tooltip
              content="输入给大模型的参数，可在下方提示词中引l用。所有输入参数会被转为string输入。"
            >
              <icon-question-circle />
            </a-tooltip>
          </div>
          <!-- 右侧新增字段按钮 -->
          <a-button aria-label="添加" type="text" size="mini" class="!text-gray-700" @click="addFormInputField">
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </div>
        <!-- 字段名 -->
        <div class="flex items-center gap-1 text-xs text-gray-500 mb-2">
          <div class="w-[20%]">参数名</div>
          <div class="w-[25%]">类型</div>
          <div class="w-[47%]">值</div>
          <div class="w-[8%]"></div>
        </div>
        <div v-for="(input, idx) in form?.inputs" :key="idx" class="flex items-center gap-1">
          <div class="w-[20%] shrink-0">
            <a-input v-model="input.name" size="mini" placeholder="请输入参数名" class="!px-2" />
          </div>
          <div class="w-[25%] shrink-0">
            <a-select
              size="mini"
              v-model="input.type"
              class="px-2"
              :options="[
                { label: '引用', value: 'ref' },
                { label: 'STRING', value: 'string' },
                { label: 'INT', value: 'int' },
                { label: 'FLOAT', value: 'float' },
                { label: 'BOOLEAN', value: 'boolean' },
              ]"
            />
          </div>
          <div class="w-[47%] shrink-0 flex items-center gap-1">
            <a-input
              v-if="input.type !== 'ref'"
              size="mini"
              v-model="input.content"
              placeholder="请输入参数值"
            />
            <a-select
              v-else
              placeholder="请选择引用变量"
              size="mini"
              tag-nowrap
              v-model="input.ref"
              :options="inputRefOptions"
            />
          </div>
          <div class="w-[8%] text-right">
            <icon-minus-circle
              class="!text-gray-500 hover:!text-gray-700 cursor-pointer shrink-0"
              @click="() => removeFormInputField(Number(idx))"
            />
          </div>
        </div>
        <!-- 空数据信息 -->
        <a-empty v-if="form?.inputs.length <= 0" class="my-4">该节点暂无输入数据</a-empty>
      </div>
      <a-divider class="my-4" />
      <!-- 转换模版 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">转换模版</div>
            <a-tooltip
              content="需要处理并转换字符串的模板，格式必须符合jinja2的模板要求，可以使用{{参数名}}引起来。"
            >
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <!-- 转换模版输入框 -->
        <a-form-item field="template" hide-label hide-asterisk required>
          <a-textarea
            :auto-size="{ minRows: 5, maxRows: 10 }"
            v-model="form.template"
            placeholder="支持使用连接符拼接输入框中输入的参数，组合成字符串输出。通过插入{{参数名}}可实现"
            class="rounded-lg"
          />
        </a-form-item>
      </div>
      <a-divider class="my-4" />
      <!-- 输出参数 -->
      <div class="flex flex-col gap-2">
        <!-- 输出标题 -->
        <div class="font-semibold text-gray-700">输出数据</div>
        <!-- 字段标题 -->
        <div class="text-gray-500 text-xs">参数名</div>
        <!-- 输出参数列表 -->
        <div v-for="(output, idx) in form?.outputs" :key="idx" class="flex flex-col gap-2">
          <div class="flex items-center gap-2">
            <div class="text-gray-700">{{ output.name }}</div>
            <div class="text-gray-500 bg-gray-200 px-1 py-0.5 rounded">{{ output.type }}</div>
          </div>
        </div>
      </div>
      <a-divider class="my-4" />
      <!-- 保存按钮 -->
      <a-button
        :loading="props.loading"
        type="primary"
        size="small"
        html-type="submit"
        long
        class="rounded-lg"
      >
        保存
      </a-button>
    </a-form>
  </div>
</template>

<style>
@reference "../../../../../assets/styles/index.css";
#template-node-info {
  .arco-textarea {
    @apply text-xs!;
  }
}
</style>
