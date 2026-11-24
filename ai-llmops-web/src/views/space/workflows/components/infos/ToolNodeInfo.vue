<script setup lang="ts">
import type { ValidatedError } from '@arco-design/web-vue'
import { computed, ref, watch } from 'vue'
import cloneDeep from 'lodash/cloneDeep'
import { useVueFlow } from '@vue-flow/core'
import { getReferencedVariables } from '@/utils/helper.ts'
import { useGetApiTool, useGetApiToolProvidersWithPage } from '@/hooks/use-tool.ts'
import {
  useGetBuiltinTool,
  useGetBuiltinTools,
  useGetCategories,
} from '@/hooks/use-builtin-tool.ts'
import { apiPrefix } from '@/config'
import type { ToolMeta } from '@/models/builtin-tool.ts'
import type { ToolInput, ToolItem as ApiToolItem } from '@/models/api-tool.ts'

const props = defineProps({
  visible: { type: Boolean, required: true, default: false },
  node: { type: Object, required: true, default: () => ({}) },
  loading: { type: Boolean, required: true, default: false },
})

const emits = defineEmits(['updateNode', 'update:visible'])
const { nodes, edges } = useVueFlow()
const {
  loading: getApiToolProvidersLoading,
  paginator,
  api_tool_providers,
  loadApiToolProviders,
} = useGetApiToolProvidersWithPage()
const { builtin_tool, loadBuiltinTool } = useGetBuiltinTool()
const { api_tool, loadApiTool } = useGetApiTool()
const { builtin_tools, loadBuiltinTools } = useGetBuiltinTools()
const { categories } = useGetCategories()
const toolsModalVisible = ref(false)
const toolsActivateType = ref('')
const toolsActivateCategory = ref('all')
type BuiltinTool = {
  name: string
  label: string
  description: string
  params: { name: string; default: unknown }[]
}
type SelectedApiTool = ApiToolItem & { id: string; label: string }
type BuiltinParam = {
  name: string
  label: string
  type: string
  required: boolean
  default: unknown
  min: number
  max: number
  options: { value: string; label: string }[]
}
const computedBuiltinTools = computed(() => {
  const list =
    toolsActivateCategory.value === 'all'
      ? builtin_tools
      : builtin_tools.filter((item) => item.category === toolsActivateCategory.value)
  return list.map((item) => ({ ...item, tools: item.tools as BuiltinTool[] }))
})
type ToolNodeInput = { name: string; type: string; value_type: string; content: string; ref: string }
type ToolNodeParam = { key: string; value: unknown }
type ToolNodeForm = {
  id?: string
  type?: string
  title?: string
  description?: string
  tool?: ToolMeta
  tools?: { provider?: { id?: string }; tool?: { name?: string } }
  inputs: ToolNodeInput[]
  params: ToolNodeParam[]
  outputs?: { name: string; type: string; value: { type: string; content: string } }[]
}
const form = ref<ToolNodeForm>({ inputs: [], params: [] })
type PythonTypeMap = {
  str: string
  int: string
  float: string
  bool: string
  [key: string]: string
}

const pythonTypeMap: PythonTypeMap = {
  str: 'string',
  int: 'int',
  float: 'float',
  bool: 'boolean',
}

const defaultToolMeta: ToolMeta = {
  type: 'api_tool',
  provider: { id: '', name: '', label: '', icon: '', description: '' },
  tool: { id: '', name: '', label: '', description: '', params: {} },
}

const inputRefOptions = computed(() => {
  return getReferencedVariables(cloneDeep(nodes.value), cloneDeep(edges.value), props.node.id)
})

const handleShowToolsModal = async (tool_type?: string) => {
  toolsActivateType.value = tool_type ?? ''
  toolsModalVisible.value = true
  await loadApiToolProviders(true)
  await loadBuiltinTools()
}

const isToolSelected = (provider: { name: string }, tool: { name: string }) => {
  return (
    form.value.tool?.provider?.name === provider.name && form.value.tool?.tool?.name === tool.name
  )
}

const handleSelectTool = async (provider_idx: number, tool_idx: number) => {
  let selectTool: ToolMeta

  if (toolsActivateType.value === 'api_tool') {
    const apiToolProvider = api_tool_providers[provider_idx]
    const apiTool = apiToolProvider?.tools?.[tool_idx] as SelectedApiTool | undefined

    if (!apiToolProvider || !apiTool) return

    selectTool = {
      type: 'api_tool',
      provider: {
        id: apiToolProvider.id,
        name: apiToolProvider.name,
        label: apiToolProvider.name,
        icon: apiToolProvider.icon,
        description: apiToolProvider.description,
      },
      tool: {
        id: apiTool.id,
        name: apiTool.name,
        label: apiTool.label,
        description: apiTool.description,
        params: {},
      },
    }
  } else {
    const builtinToolProvider = computedBuiltinTools.value[provider_idx]
    const builtinTool = builtinToolProvider?.tools?.[tool_idx]
    if (!builtinToolProvider || !builtinTool) return
    const params = builtinTool['params']
    selectTool = {
      type: 'builtin_tool',
      provider: {
        id: builtinToolProvider.name,
        name: builtinToolProvider.name,
        label: builtinToolProvider.label,
        icon: `${apiPrefix}/builtin_tools/${builtinToolProvider.name}/icon`,
        description: builtinToolProvider.description,
      },
      tool: {
        id: builtinTool.name,
        name: builtinTool.name,
        label: builtinTool.label,
        description: builtinTool.description,
        params: params.reduce<Record<string, unknown>>((newObj, item) => {
          newObj[item.name] = item.default
          return newObj
        }, {}),
      },
    }
  }
  if (
    form.value?.tools?.provider?.id === selectTool.provider.id &&
    form.value?.tools?.tool?.name === selectTool.tool.name
  ) {
    form.value.tool = defaultToolMeta
    form.value.inputs = []
    form.value.params = []
  } else {
    form.value.tool = selectTool

    if (selectTool.type === 'builtin_tool') {
      await loadBuiltinTool(selectTool.provider.name, selectTool.tool.name)
      const builtinToolDetail = builtin_tool as unknown as {
        inputs?: ToolInput[]
        params?: BuiltinParam[]
      }
      const inputs = builtinToolDetail.inputs ?? []
      const params = builtinToolDetail.params ?? []

      form.value.inputs = inputs.map((item) => {
        const inputType = pythonTypeMap[item.type] || 'string'
        return {
          name: item.name,
          type: inputType,
          value_type: inputType,
          content: '',
          ref: '',
        }
      })
      form.value.params = params.map((param) => {
        return { key: param.name, value: param.default }
      })
    } else {
      await loadApiTool(selectTool.provider.id, selectTool.tool.name)
      const inputs = (api_tool.inputs as unknown as ToolInput[]) ?? []

      form.value.inputs = inputs.map((item) => {
        return {
          name: item.name,
          type: pythonTypeMap[item.type] as string,
          value_type: 'ref',
          content: '',
          ref: '',
        }
      })
      form.value.params = []
    }
  }
}

const handleScroll = async (event: UIEvent) => {
// 获取滚动距离、可滚动最大距离、客户端/浏览器窗口高度
  const { scrollTop, scrollHeight, clientHeight } = event.target as HTMLElement
  if (scrollTop + clientHeight >= scrollHeight - 10) {
    if (getApiToolProvidersLoading.value) {
      return
    }
    await loadApiToolProviders()
  }
}

const onSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
// 检查表单是否出现错误，如果出现错误则直接结束
  if (errors) return

  const cloneInputs = cloneDeep(form.value.inputs) ?? []
  const cloneParams = cloneDeep(form.value.params) ?? []
  const params: Record<string, unknown> = {}
  cloneParams.forEach((param) => {
    params[param.key] = param.value
  })

// 数据校验通过，通过事件触发数据更新
  emits('updateNode', {
    id: props.node.id,
    title: form.value.title,
    description: form.value.description,
    tool_type: form.value.tool?.type,
    provider_id: form.value.tool?.provider?.id,
    tool_id: form.value.tool?.tool?.name,
    meta: cloneDeep(form.value.tool),
    params: params, // 将列表转换成字典
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

const normalizeToolMeta = (meta: ToolMeta) => {
  if (meta?.type === 'builtin_tool' && meta?.provider?.name) {
    meta.provider.icon = `${apiPrefix}/builtin_tools/${meta.provider.name}/icon`
  }
  return meta
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
    const cloneParams = cloneDeep(newNode.data.params)
    form.value = {
      id: newNode.id,
      type: newNode.type,
      title: newNode.data.title,
      description: newNode.data.description,
      tool: normalizeToolMeta(cloneDeep(newNode.data.meta) ?? defaultToolMeta),
      params: Object.entries(cloneParams).map(([key, value]) => ({
        key: key,
        value: value,
      })), // 将字典转换成列表
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
        const rawContent = input.value.type === 'literal' ? input.value.content : ''
        const safeContent = typeof rawContent === 'object' && rawContent !== null ? '' : rawContent

        return {
          name: input.name,
          type: input.value.type === 'literal' ? input.type : 'ref',
          content: safeContent as string,
          ref: input.value.type === 'ref' && refExists ? ref : '',
        }
      }),
      outputs: [
        {
          name: 'text',
          type: 'string',
          value: { type: 'generated', content: '' },
        },
      ],
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
      <!-- 绑定插件 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="a">绑定插件</div>
            <a-tooltip content="为工具节点绑定指定的扩展插件，支持插件广场以及自定义API插件。">
              <icon-question-circle />
            </a-tooltip>
          </div>
          <!-- 右侧绑定插件按钮 -->
          <a-button aria-label="添加"
            size="mini"
            type="text"
            class="!text-gray-700"
            @click="handleShowToolsModal(form.tool?.type)"
          >
            <template #icon>
              <icon-plus />
            </template>
          </a-button>
        </div>
        <div v-if="form.tool?.provider?.id && form.tool?.tool?.name" class="flex flex-col gap-1">
          <div
            class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group"
          >
            <!-- 左侧工具信息 -->
            <div class="flex items-center gap-2">
              <!-- 图标 -->
              <a-avatar
                :size="36"
                shape="square"
                class="rounded shrink-0"
                :image-url="form?.tool?.provider?.icon"
              />
              <!-- 名称与描述信息 -->
              <div class="flex flex-col flex-1 gap-1 h-9">
                <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 break-all">
                  {{ form?.tool?.provider?.label }}/{{ form?.tool?.tool?.name }}
                </div>
                <div class="text-gray-500 text-xs line-clamp-1 break-all">
                  {{ form?.tool?.tool?.description }}
                </div>
              </div>
            </div>
          </div>
        </div>
        <!-- 主数据信息 -->
        <a-empty v-if="!form.tool?.provider?.id && !form.tool?.tool?.name" class="my-4">
          该节点暂无绑定插件
        </a-empty>
      </div>
      <a-divider class="my-4" />
      <!-- 输入参数 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">输入参数</div>
            <a-tooltip
              content="输入给大模型的参数，可在下方提示词中引l用。所有输入参数会被转为string输入。"
            >
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <!-- 字段名 -->
        <div
          v-if="form?.inputs.length > 0"
          class="flex items-center gap-1 text-xs text-gray-500 mb-2"
        >
          <div class="w-[30%]">参数名</div>
          <div class="w-[25%]">类型</div>
          <div class="w-[45%]">值</div>
        </div>
        <div v-for="(input, idx) in form?.inputs" :key="idx" class="flex items-center gap-1">
          <div class="w-[30%] shrink-0">
            <div class="flex items-center gap-1 text-xs text-gray-500">
              <div class="">{{ input.name }}</div>
              <div class="text-gray-500 bg-gray-200 px-1 py-0.5 rounded">{{ input.type }}</div>
            </div>
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
          <div class="w-[45%] shrink-0 flex items-center gap-1">
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
        </div>
        <!-- 空数据信息 -->
        <a-empty v-if="form?.inputs.length <= 0" class="my-4">该工具暂无输入数据</a-empty>
      </div>
      <a-divider class="my-4" />
      <!-- PARAMS参数 -->
      <div class="flex flex-col gap-2">
        <!-- 标题&操作按钮 -->
        <div class="flex items-center justify-between">
          <!-- 左侧标题 -->
          <div class="flex items-center gap-2 text-gray-700 font-semibold">
            <div class="">PARAMS参数</div>
            <a-tooltip content="内置工具使用的PARAMS参数，用于初始化内置工具。">
              <icon-question-circle />
            </a-tooltip>
          </div>
        </div>
        <!-- 字段名 -->
        <div
          v-if="form?.params?.length > 0"
          class="flex items-center gap-1 text-xs text-gray-500 mb-2"
        >
          <div class="w-[20%]">参数名</div>
          <div class="w-[80%]">值</div>
        </div>
        <div v-for="(param, idx) in form?.params" :key="idx" class="flex items-center gap-1">
          <div class="w-[20%] shrink-0">
            <div class="flex items-center gap-1 text-xs text-gray-500">
              <div class="">{{ param.key }}</div>
            </div>
          </div>
          <div class="w-[80%] shrink-0">
            <a-input
              size="mini"
              :model-value="String(param.value ?? '')"
              @update:model-value="(v: unknown) => (param.value = v as string)"
              class="px-2"
              placeholder="请输入参数值"
            />
          </div>
        </div>
        <!-- 空数据信息 -->
        <a-empty v-if="form?.params?.length <= 0" class="my-4">该工具暂无params数据</a-empty>
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
    <!-- 选择工具搜索窗口 -->
    <a-modal
      v-model:visible="toolsModalVisible"
      hide-title
      :footer="false"
      class="tools-modal"
      modal-class="right-4 h-[calc(100vh-36px)]"
    >
      <div class="flex w-full h-full">
        <!-- 左侧导航菜单 -->
        <div
          class="flex flex-col shrink-0 bg-gray-50 w-[200px] h-full px-3 py-4 overflow-scroll scrollbar-w-none"
        >
          <!-- 标题 -->
          <div class="text-gray-900 font-bold text-lg mb-4">关联插件</div>
          <!-- 添加插件按钮 -->
          <router-link :to="{ name: 'space-tools-list' }">
            <a-button long type="primary" class="rounded-lg mb-5">创建自定义插件</a-button>
          </router-link>
          <!-- 工具类别导航 -->
          <div class="flex flex-col gap-1 mb-4">
            <div
              :class="`rounded-lg h-8 leading-8 px-3 flex items-center gap-2 cursor-pointer hover:bg-white hover:text-blue-700 ${toolsActivateType === 'api_tool' ? 'text-blue-700 bg-white' : 'text-gray-700'}`"
              @click="toolsActivateType = 'api_tool'"
            >
              <icon-code />
              自定义插件
            </div>
            <div
              :class="`rounded-lg h-8 leading-8 px-3 flex items-center gap-2 cursor-pointer hover:bg-white hover:text-blue-700 ${toolsActivateType === 'builtin_tool' ? 'text-blue-700 bg-white' : 'text-gray-700'}`"
              @click="toolsActivateType = 'builtin_tool'"
            >
              <icon-translate />
              内置插件
            </div>
          </div>
          <!-- 内置工具分类 -->
          <div v-if="toolsActivateType == 'builtin_tool'" class="">
            <!-- 分类标题 -->
            <div class="text-xs text-gray-500 mb-3">类别</div>
            <!-- 分类列表 -->
            <div class="flex flex-col gap-1">
              <!-- 所有类别 -->
              <div
                :class="`rounded-lg h-8 leading-8 px-3 flex items-center gap-2 cursor-pointer hover:bg-white hover:text-blue-700 ${toolsActivateCategory === 'all' ? 'text-blue-700 bg-white' : 'text-gray-700'}`"
                @click="toolsActivateCategory = 'all'"
              >
                <icon-apps />
                全部
              </div>
              <div
                v-for="category in categories"
                :key="category.name"
                :class="`rounded-lg h-8 leading-8 px-3 flex items-center gap-2 cursor-pointer hover:bg-white hover:text-blue-700 ${toolsActivateCategory === category.category ? 'text-blue-700 bg-white' : 'text-gray-700'}`"
                @click="toolsActivateCategory = category.category"
              >
                <span v-html="category.icon"></span>
                {{ category.name }}
              </div>
            </div>
          </div>
        </div>
        <!-- 右侧工具列表（min-w-0：允许收缩到分配宽度，避免内容 min-content 把面板撑出弹框） -->
        <div class="flex-1 min-w-0 p-4">
          <!-- 标题与关闭按钮 -->
          <div class="w-full flex items-center justify-between gap-2 mb-7">
            <div class="text-lg font-bold text-gray-700">
              {{ toolsActivateType === 'api_tool' ? '自定义插件' : '内置插件' }}
            </div>
            <a-button aria-label="关闭"
              size="mini"
              type="text"
              class="text-gray-700 ml-6"
              @click="toolsModalVisible = false"
            >
              <template #icon>
                <icon-close />
              </template>
            </a-button>
          </div>
          <!-- 内置工具列表 -->
          <div
            v-if="toolsActivateType === 'builtin_tool'"
            class="h-[calc(100vh-130px)] overflow-scroll scrollbar-w-none"
          >
            <div
              v-for="(builtin_tool, builtin_tool_idx) in computedBuiltinTools"
              :key="builtin_tool.name"
              class="flex flex-col gap-3 mb-3"
            >
              <!-- 提供者信息 -->
              <div class="text-gray-900">{{ builtin_tool.label }}</div>
              <!-- 工具列表 -->
              <div class="flex flex-col gap-1">
                <div
                  v-for="(tool, tool_idx) in builtin_tool.tools"
                  :key="tool.name"
                  :class="`flex items-center justify-between px-2 h-8 rounded-lg cursor-pointer hover:bg-gray-50 group ${isToolSelected(builtin_tool, tool) ? 'bg-gray-50 border border-blue-700' : ''}`"
                >
                  <!-- 工具信息 -->
                  <div class="flex items-center gap-2 flex-1 min-w-0">
                    <a-avatar
                      :size="20"
                      shape="circle"
                      :image-url="`${apiPrefix}/builtin_tools/${builtin_tool.name}/icon`"
                    />
                    <div class="text-gray-900">{{ tool.label }}</div>
                  </div>
                  <!-- 添加按钮 -->
                  <a-button
                    v-if="!isToolSelected(builtin_tool, tool)"
                    size="mini"
                    class="invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity duration-150 rounded px-1.5 shrink-0"
                    @click="handleSelectTool(Number(builtin_tool_idx), Number(tool_idx))"
                  >
                    <template #icon>
                      <icon-plus />
                    </template>
                    添加
                  </a-button>
                </div>
              </div>
            </div>
            <div v-if="computedBuiltinTools.length === 0" class="">
              <a-empty
                description="没有可用的内置插件"
                class="h-[400px] flex flex-col items-center justify-center"
              />
            </div>
          </div>
          <!-- 自定义插件列表 -->
          <div v-if="toolsActivateType === 'api_tool'">
            <a-spin
              :loading="getApiToolProvidersLoading"
              class="block h-[calc(100vh-130px)] overflow-scroll scrollbar-w-none"
              @scroll="handleScroll"
            >
              <div
                v-for="(api_tool_provider, api_tool_provider_idx) in api_tool_providers"
                :key="api_tool_provider.id"
                class="flex flex-col gap-3 mb-3"
              >
                <!-- 提供者信息 -->
                <div class="text-gray-900">{{ api_tool_provider.name }}</div>
                <!-- 工具列表 -->
                <div class="flex flex-col gap-1">
                  <div
                    v-for="(tool, tool_idx) in api_tool_provider.tools"
                    :key="tool.name"
                    :class="`flex items-center justify-between px-2 h-8 rounded-lg cursor-pointer hover:bg-gray-50 group ${isToolSelected(api_tool_provider, tool) ? 'bg-gray-50 border border-blue-700' : ''}`"
                  >
                    <!-- 工具信息 -->
                    <div class="flex items-center gap-2 flex-1 min-w-0">
                      <a-avatar :size="20" shape="circle" :image-url="api_tool_provider.icon" />
                      <div class="text-gray-900">{{ tool.name }}</div>
                    </div>
                    <!-- 添加按钮 -->
                    <a-button
                      v-if="!isToolSelected(api_tool_provider, tool)"
                      size="mini"
                      class="invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity duration-150 rounded px-1.5 shrink-0"
                      @click="() => handleSelectTool(Number(api_tool_provider_idx), Number(tool_idx))"
                    >
                      <template #icon>
                        <icon-plus />
                      </template>
                      添加
                    </a-button>
                  </div>
                </div>
              </div>
              <div v-if="api_tool_providers.length == 0" class="">
                <a-empty
                  description="没有可用的API插件"
                  class="h-[400px] flex flex-col items-center justify-center"
                />
              </div>
              <!-- 加载器 -->
              <a-row v-if="paginator.total_page >= 2">
                <!-- 加载数据中 -->
                <a-col
                  v-if="paginator.current_page <= paginator.total_page"
                  :span="24"
                  class="text-center"
                >
                  <a-space class="my-4">
                    <a-spin />
                    <div class="text-gray-400">加载中</div>
                  </a-space>
                </a-col>
                <!-- 数据加载完成 -->
                <a-col v-else :span="24" class="text-center">
                  <div class="text-gray-400 my-4">数据已加载完成</div>
                </a-col>
              </a-row>
            </a-spin>
          </div>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<style>
@reference "../../../../../assets/styles/index.css";
#tool-node-info {
  .arco-textarea {
    @apply text-xs!;
  }
}

.tool-setting-modal {
  .arco-modal-wrapper {
    text-align: center;
  }
}

.tools-modal {
  .arco-modal-wrapper {
    text-align: center;
  }

  .arco-modal-body {
    padding: 0;
    height: 100%;
    width: 100%;
    border-radius: 8px;
  }
}
</style>
