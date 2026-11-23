<script setup lang="ts">
import { computed, type PropType, ref } from 'vue'
import { type GetDraftAppConfigResponse } from '@/models/app'
import { useUpdateDraftAppConfig } from '@/hooks/use-app'
import { useGetApiTool, useGetApiToolProvidersWithPage } from '@/hooks/use-tool'
import { apiPrefix, typeMap } from '@/config'
import {
  useGetBuiltinTool,
  useGetBuiltinTools,
  useGetCategories,
} from '@/hooks/use-builtin-tool.ts'
import { Message } from '@arco-design/web-vue'
import type { ToolMeta } from '@/models/builtin-tool.ts'

interface ToolInfoParam {
  name: string
  label: string
  type?: string
  required?: boolean
  description?: string
  default?:
    | string
    | number
    | boolean
    | Record<string, unknown>
    | (string | number | boolean | Record<string, unknown>)[]
    | undefined
  min?: number
  max?: number
  options?: { label: string; value: string | number | boolean }[]
}

interface BuiltinToolToolItem {
  name: string
  label: string
  description: string
  params?: { name: string; label: string; default: unknown }[]
}

interface ToolInfo {
  type: string
  provider: {
    id: string
    icon: string
    name: string
    label: string
    description: string
  }
  tool: {
    id: string
    name: string
    label: string
    description: string
    inputs?: { name: string; type: string; required: boolean; description: string }[]
    params?: ToolInfoParam[]
  }
}

// 模板表达式不支持 `as X | Y` 联合类型断言（会被解析为过滤器语法），用函数收窄
const asSelectValue = (value: unknown) =>
  value as string | number | boolean | Record<string, unknown> | undefined
const asRadioValue = (value: unknown) => value as string | number | boolean | undefined
const asStringValue = (value: unknown) => value as string | undefined
const asNumberValue = (value: unknown) => value as number | undefined

const props = defineProps({
  app_id: { type: String, default: '', required: true },
  tools: {
    type: Array as PropType<GetDraftAppConfigResponse['data']['tools']>,
    required: true,
    default: () => [],
  },
})

const emits = defineEmits(['update:tools'])
const { loading: updateDraftAppConfigLoading, handleUpdateDraftAppConfig } =
  useUpdateDraftAppConfig()
const { loading: getApiToolLoading, api_tool, loadApiTool } = useGetApiTool()
const { loading: getBuiltinToolLoading, builtin_tool, loadBuiltinTool } = useGetBuiltinTool()

const {
  loading: getApiToolProvidersLoading,
  paginator,
  api_tool_providers,
  loadApiToolProviders,
} = useGetApiToolProvidersWithPage()

const { categories } = useGetCategories()
const { builtin_tools, loadBuiltinTools } = useGetBuiltinTools()

const toolInfoModalVisible = ref(false)
const toolInfoNavType = ref('info')
const toolInfo = ref<ToolInfo>({
  type: '',
  provider: { id: '', icon: '', name: '', label: '', description: '' },
  tool: { id: '', name: '', label: '', description: '' },
})
const toolInfoIdx = ref(-1)
const toolInfoSettingForm = ref<Record<string, unknown>>({})

const toolsModalVisible = ref(false)
const toolsActivateType = ref<'api_tool' | 'builtin_tool' | 'installed'>('installed')
const toolsActivateCategory = ref('all')
const computedBuiltinTools = computed(() => {
  if (toolsActivateCategory.value == 'all') return builtin_tools
  return builtin_tools.filter((item) => item.category == toolsActivateCategory.value)
})

const handleShowToolInfoModal = async (idx: number) => {
  if (idx == -1) return
  toolInfoIdx.value = idx
  const tool = props.tools[idx]
  if (!tool) return

  // 先立即弹出弹窗，再异步加载详情，避免等待接口导致弹窗“卡顿”
  toolInfoModalVisible.value = true

// 检测不同的工具类型调用不同API接口
  if (tool.type == 'builtin_tool') {
    await loadBuiltinTool(tool.provider.name, tool.tool.name)
    const provider = builtin_tool.provider
    const builtinToolDetail = builtin_tool as unknown as {
      inputs?: { name: string; type: string; required: boolean; description: string }[]
    }
    toolInfo.value = {
      type: 'builtin_tool',
      provider: {
        id: provider?.name ?? '',
        icon: `${apiPrefix}/builtin_tools/${provider?.name ?? ''}/icon`,
        name: provider?.name ?? '',
        label: provider?.label ?? '',
        description: provider?.description ?? '',
      },
      tool: {
        id: builtin_tool.name ?? '',
        name: builtin_tool.name ?? '',
        label: builtin_tool.label ?? '',
        description: builtin_tool.description ?? '',
        inputs: builtinToolDetail.inputs,
        params: builtin_tool.params as unknown as ToolInfoParam[],
      },
    }
  } else {
    await loadApiTool(tool.provider.id, tool.tool.name)
    const provider = api_tool.provider
    toolInfo.value = {
      type: 'api_tool',
      provider: {
        id: provider?.id ?? '',
        icon: provider?.icon ?? '',
        name: provider?.name ?? '',
        label: provider?.name ?? '',
        description: provider?.description ?? '',
      },
      tool: {
        id: api_tool.name ?? '',
        name: api_tool.name ?? '',
        label: api_tool.name ?? '',
        description: api_tool.description ?? '',
        inputs: api_tool.inputs as unknown as {
          name: string
          type: string
          required: boolean
          description: string
        }[],
        params: [],
      },
    }
  }
// 更新工具设置表单，从草稿中获取配置，如果没有则设置默认值
  const params = tool.tool.params
  if (toolInfo.value.tool?.params) {
    toolInfo.value.tool.params.forEach((param) => {
      toolInfoSettingForm.value[param.name] = params[param.name] ?? param.default
    })
  }
}

const handleCancelToolInfoModal = () => {
  toolInfoIdx.value = -1
  toolInfoModalVisible.value = false
  toolInfoNavType.value = 'info'
  toolInfoSettingForm.value = {}
}

const handleSubmitToolInfo = async () => {
  const idx = toolInfoIdx.value
  if (idx < 0 || idx >= props.tools.length) return

  const tool = props.tools[idx]
  if (!tool) return

  if (tool.type === 'api_tool') {
    handleCancelToolInfoModal()
    return
  }

  const newTools = [...props.tools]
  if (newTools[idx]?.tool) {
    newTools[idx].tool.params = toolInfoSettingForm.value || {}
  }

  await handleUpdateDraftAppConfig(props.app_id, {
    tools: newTools.map((item) => {
      return {
        type: item.type,
        params: item.tool?.params || {},
        provider_id: item.provider?.id || '',
        tool_id: item.tool?.name || '',
      }
    }),
  })

  emits('update:tools', newTools)

  handleCancelToolInfoModal()
}

const handleDeleteTool = async (idx: number) => {
  const newTools = [...props.tools]
  newTools.splice(idx, 1)
  await handleUpdateDraftAppConfig(props.app_id, {
    tools: newTools.map((item) => {
      return {
        type: item.type,
        params: item.tool?.params || {},
        provider_id: item.provider?.id || '',
        tool_id: item.tool?.name || '',
      }
    }),
  })
  emits('update:tools', newTools)
}

const handleShowToolsModal = async () => {
  toolsModalVisible.value = true

  await loadApiToolProviders(true)
  await loadBuiltinTools()
}

// 供外部（左侧「扩展插件」导航）直接打开「添加插件」弹窗
defineExpose({ openAdd: handleShowToolsModal, openToolInfo: handleShowToolInfoModal })

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

const handleSelectTool = async (provider_idx: number, tool_idx: number) => {
// 根据不同的类型获取特定的工具信息
  let selectTool: ToolMeta

  if (toolsActivateType.value === 'api_tool') {
    const apiToolProvider = api_tool_providers[provider_idx]
    const apiTool = apiToolProvider?.tools?.[tool_idx]
    if (!apiToolProvider || !apiTool) return

    selectTool = {
      type: 'api_tool',
      provider: {
        id: apiToolProvider.id,
        name: apiToolProvider.name,
        label: apiToolProvider.name,
        icon: apiToolProvider.icon || '',
        description: apiToolProvider.description || '',
      },
      tool: {
        id: apiTool.name,
        name: apiTool.name,
        label: apiTool.name,
        description: apiTool.description || '',
        params: {},
      },
    }
  } else {
    const builtinToolProvider = computedBuiltinTools.value[provider_idx]
    const builtinTool = builtinToolProvider?.tools?.[tool_idx] as BuiltinToolToolItem | undefined
    if (!builtinToolProvider || !builtinTool) return

    const params = builtinTool.params || []
    selectTool = {
      type: 'builtin_tool',
      provider: {
        id: builtinToolProvider.name,
        name: builtinToolProvider.name,
        label: builtinToolProvider.label,
        icon: `${apiPrefix}/builtin_tools/${builtinToolProvider.name}/icon`,
        description: builtinToolProvider.description || '',
      },
      tool: {
        id: builtinTool.name,
        name: builtinTool.name,
        label: builtinTool.label,
        description: builtinTool.description || '',
        params: params.reduce((newObj: Record<string, unknown>, item) => {
          newObj[item.name] = item.default
          return newObj
        }, {}),
      },
    }
  }

  const isSelected = props.tools.some((item) => {
    return item.provider?.id === selectTool.provider.id && item.tool?.name === selectTool.tool.name
  })

  if (isSelected) {
// 删除关联的工具，筛选数据后更新
    const newTools = [...props.tools].filter((item) => {
      return !(
        item.provider?.id === selectTool.provider.id && item.tool?.name === selectTool.tool.name
      )
    })

    await handleUpdateDraftAppConfig(props.app_id, {
      tools: newTools.map((item) => {
        return {
          type: item.type,
          params: item.tool?.params || {},
          provider_id: item.provider?.id || '',
          tool_id: item.tool?.name || '',
        }
      }),
    })
    emits('update:tools', newTools)
    return
  } else {
// 新增数据，检测关联插件数是否大于等于12
    if (props.tools.length >= 12) {
      Message.warning('一个Agent应用最多关联12个扩展插件')
      return
    }

    const newTools = [...props.tools]
    newTools.push(selectTool as unknown as GetDraftAppConfigResponse['data']['tools'][number])

    await handleUpdateDraftAppConfig(props.app_id, {
      tools: newTools.map((item) => {
        return {
          type: item.type,
          params: item.tool?.params || {},
          provider_id: item.provider?.id || '',
          tool_id: item.tool?.name || '',
        }
      }),
    })
    emits('update:tools', newTools)
  }
}

const isToolSelected = (provider: unknown, tool: unknown) => {
  const p = provider as { name?: string }
  const t = tool as { name?: string }
  return props.tools.some(
    (item) => item.provider?.name === p.name && item.tool?.name === t.name,
  )
}
</script>

<template>
  <div class="">
    <!-- 折叠面板 -->
    <a-collapse-item key="tools" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">扩展插件</div>
      </template>
      <template #extra>
        <a-button aria-label="添加"
          @click="handleShowToolsModal"
          size="mini"
          type="text"
          class="!text-gray-700"
          @click.stop
        >
          <template #icon>
            <icon-plus />
          </template>
        </a-button>
      </template>
      <div v-if="props.tools.length > 0" class="flex flex-col gap-1">
        <div
          v-for="(tool, idx) in props.tools"
          :key="idx"
          class="flex items-center justify-between bg-white p-3 rounded-lg cursor-pointer hover:shadow-sm group"
        >
          <!-- 左侧工具信息 -->
          <div class="flex items-center gap-2">
            <!-- 图标（tool.provider.icon 为后端绝对地址（缺端口/缺 /api），改用 apiPrefix 重建） -->
            <a-avatar
              :size="36"
              shape="square"
              class="rounded flex-shrink-0"
              :style="{ backgroundColor: 'transparent' }"
              :image-url="`${apiPrefix}/builtin_tools/${tool.provider.name}/icon`"
            />
            <!-- 名称与描述信息 -->
            <div class="flex flex-col gap-1 h-9">
              <div class="text-gray-700 font-bold leading-[18px] line-clamp-1 break-all">
                {{ tool.provider.label }} / {{ tool.tool.label }}
              </div>
              <div class="text-gray-500 text-xs line-clamp-1 break-all">
                {{ tool.tool.description }}
              </div>
            </div>
          </div>
          <!-- 右侧按钮 -->
          <div class="hidden group-hover:flex items-center gap-1 flex-shrink-0 ml-2">
            <a-button
              :loading="getApiToolLoading || getBuiltinToolLoading"
              size="mini"
              type="text"
              class="!text-gray-700 rounded"
              @click="async () => handleShowToolInfoModal(idx)"
            >
              <template #icon>
                <icon-settings />
              </template>
            </a-button>
            <a-button
              :loading="updateDraftAppConfigLoading"
              size="mini"
              type="text"
              class="!text-red-700 rounded"
              @click="async () => await handleDeleteTool(idx)"
            >
              <template #icon>
                <icon-delete />
              </template>
            </a-button>
          </div>
        </div>
      </div>
      <div v-else class="text-xs text-gray-500 leading-[28px]">
        插件能够让智能体调用外部API，例如搜索信息、浏览网页、生成图片等，扩展智能体的能力和使用场景。
      </div>
    </a-collapse-item>
    <!-- 工具设置模态窗（复制文件/目录等已安装工具的详情/设置） -->
    <a-modal
      :visible="toolInfoModalVisible"
      hide-title
      :footer="false"
      width="max(440px, min(560px, calc(100vw - 32px)))"
      class="tool-setting-modal"
      modal-class="h-[calc(100vh-32px)] right-4"
      @cancel="handleCancelToolInfoModal"
    >
      <!-- 顶部标题&关闭按钮 -->
      <div class="flex items-center justify-between mb-6">
        <!-- 左侧标题&导航 -->
        <div class="flex items-center">
          <!-- 工具信息 -->
          <div class="flex items-center gap-2">
            <a-avatar :size="24" shape="circle" :image-url="toolInfo?.provider?.icon" />
            <div class="text-gray-700 font-bold max-w-[200px] line-clamp-1 break-all">
              {{ toolInfo?.tool?.label }}
            </div>
          </div>
          <!-- 分隔符 -->
          <div class="mx-4 text-gray-400">
            <icon-oblique-line :size="12" />
          </div>
          <!-- 导航菜单 -->
          <div class="flex items-center gap-6">
            <div
              :class="[
                `text-gray-700', 'pt-1', 'cursor-pointer', toolInfoNavType === 'info' ? 'border-b-4 border-blue-700 pt-1 font-bold' : hover:border-b-4 hover:pt-1 hover:font-bold ${toolInfoNavType === 'info' ? 'font-bold border-b-4' : ''}`,
              ]"
              @click="toolInfoNavType = 'info'"
            >
              信息
            </div>
            <div
              v-if="toolInfo.type == 'builtin_tool' && (toolInfo?.tool?.params?.length ?? 0) > 0"
              :class="[
                `text-gray-700', 'pt-1', 'cursor-pointer', toolInfoNavType === 'setting' ? 'border-b-4 border-blue-700 pt-1 font-bold' : 'hover:border-b-4 hover:pt-1 hover:font-bold ${toolInfoNavType === 'setting' ? 'font-bold border-b-4' : ''}`,
              ]"
              @click="toolInfoNavType = 'setting'"
            >
              设置
            </div>
          </div>
        </div>
        <!-- 右侧关闭按钮 -->
        <a-button aria-label="关闭" size="mini" type="text" class="text-gray-700" @click="handleCancelToolInfoModal">
          <template #icon>
            <icon-close />
          </template>
        </a-button>
      </div>
      <!-- 信息容器 -->
      <div
        v-if="toolInfoNavType == 'info'"
        class="h-[calc(100vh-170px)] pb-4 overflow-scroll scrollbar-w-none"
      >
        <!-- 工具描述 -->
        <div class="text-gray-700 font-bold mb-1">工具描述</div>
        <div class="text-gray-500 text-xs">{{ toolInfo?.tool?.description }}</div>
        <!-- 工具参数 -->
        <div v-if="(toolInfo?.tool?.inputs?.length ?? 0) > 0" class="#">
          <!-- 分隔符 -->
          <div class="flex items-center gap-2 my-4">
            <div class="text-xs font-bold text-gray-500">参数</div>
            <hr class="flex-1" />
          </div>
          <!-- 参数列表-->
          <div class="flex flex-col gap-4">
            <div
              v-for="input in toolInfo?.tool?.inputs"
              :key="input.name"
              class="flex flex-col gap-2"
            >
              <!-- 上半部分-->
              <div class="flex items-center gap-2 text-xs">
                <div class="text-gray-900 font-bold">{{ input.name }}</div>
                <div class="text-gray-500 font-bold">{{ typeMap[input.type] }}</div>
                <div v-if="input.required" class="text-red-700 font-bold">必填</div>
              </div>
              <!-- 参数描述信息-->
              <div class="text-xs text-gray-500">{{ input.description }}</div>
            </div>
          </div>
        </div>
      </div>
      <!-- 设置容器 -->
      <div
        v-if="toolInfoNavType == 'setting'"
        class="h-[calc(100vh-170px)] pb-4 overflow-scroll scrollbar-w-none"
      >
        <a-form v-model:model="toolInfoSettingForm" layout="vertical" class="">
          <a-form-item
            v-for="param in toolInfo?.tool?.params"
            :key="param.name"
            :field="param.name"
          >
            <template #label>
              <div class="flex items-center gap-1">
                <div class="text-gray-700">{{ param.label }}</div>
                <div v-if="param.required" class="text-red-700">*</div>
                <a-tooltip :content="param.description">
                  <icon-info-circle />
                </a-tooltip>
              </div>
            </template>
            <a-select
              v-if="param.type == 'select'"
              :model-value="asSelectValue(toolInfoSettingForm[param.name])"
              @update:model-value="(value: unknown) => (toolInfoSettingForm[param.name] = value)"
              :default-value="param.default"
              placeholder="请输入参数值"
              :options="param.options"
            />
            <a-input
              v-if="param.type === 'string'"
              placeholder="请输入参数值"
              :model-value="asStringValue(toolInfoSettingForm[param.name])"
              @update:model-value="(value: unknown) => (toolInfoSettingForm[param.name] = value)"
              :default-value="asStringValue(param.default)"
            />

            <a-input-number
              v-if="param.type === 'number'"
              placeholder="请输入参数值"
              :model-value="asNumberValue(toolInfoSettingForm[param.name])"
              @update:model-value="(value: unknown) => (toolInfoSettingForm[param.name] = value)"
              :default-value="asNumberValue(param.default)"
              :min="param.min"
              :max="param.max"
            />
            <a-radio-group
              v-if="param.type == 'boolean'"
              :model-value="asRadioValue(toolInfoSettingForm[param.name])"
              @update:model-value="(value: unknown) => (toolInfoSettingForm[param.name] = value)"
              :default-value="asRadioValue(param.default)"
            >
              <a-radio :value="true">开启</a-radio>
              <a-radio :value="false">关闭</a-radio>
            </a-radio-group>
          </a-form-item>
        </a-form>
      </div>
      <!-- 底部按钮 -->
      <div class="flex items-center justify-between">
        <div class=""></div>
        <a-space :size="12">
          <a-button class="rounded-lg" @click="handleCancelToolInfoModal">取消</a-button>
          <a-button
            :loading="updateDraftAppConfigLoading"
            type="primary"
            class="rounded-lg"
            @click="handleSubmitToolInfo"
            >保存
          </a-button>
        </a-space>
      </div>
    </a-modal>
    <!-- 选择工具搜索窗口（添加插件） -->
    <a-modal
      v-model:visible="toolsModalVisible"
      hide-title
      :footer="false"
      width="max(400px, min(520px, calc(100vw - 32px)))"
      class="tools-modal"
      modal-class="right-4 h-[calc(100vh-36px)]"
    >
      <div class="flex w-full h-full">
        <!-- 左侧导航菜单 -->
        <div
          class="flex flex-col flex-shrink-0 bg-gray-50 w-[200px] h-full px-3 py-4 overflow-scroll scrollbar-w-none"
        >
          <!-- 标题 -->
          <div class="text-gray-900 font-bold text-lg mb-4">添加插件</div>
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
            <!-- 已安装：展示当前已添加的插件 -->
            <div
              :class="`rounded-lg h-8 leading-8 px-3 flex items-center gap-2 cursor-pointer hover:bg-white hover:text-blue-700 ${toolsActivateType === 'installed' ? 'text-blue-700 bg-white' : 'text-gray-700'}`"
              @click="toolsActivateType = 'installed'"
            >
              <icon-check />
              已安装
              <span class="ml-auto text-xs text-gray-400">{{ props.tools.length }}</span>
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
              {{
                toolsActivateType === 'api_tool'
                  ? '自定义插件'
                  : toolsActivateType === 'installed'
                    ? '已安装'
                    : '内置插件'
              }}
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
                  v-for="(tool, tool_idx) in (builtin_tool.tools as BuiltinToolToolItem[])"
                  :key="tool.name"
                  :class="`flex items-center justify-between px-2 py-2 rounded-lg cursor-pointer hover:bg-gray-50 group border border-transparent ${isToolSelected(builtin_tool, tool) ? 'bg-gray-50' : ''}`"
                  :style="isToolSelected(builtin_tool, tool) ? { borderColor: '#1d4ed8' } : {}"
                >
                  <!-- 工具信息 -->
                  <div class="flex items-center gap-2 flex-1 min-w-0">
                    <a-avatar
                      :size="20"
                      shape="circle"
                      :style="{ backgroundColor: 'transparent' }"
                      :image-url="`${apiPrefix}/builtin_tools/${builtin_tool.name}/icon`"
                    />
                    <div class="flex flex-col flex-1 min-w-0">
                      <div class="line-clamp-1 text-gray-700 text-sm font-medium">
                        {{ tool.label }}
                      </div>
                      <div class="line-clamp-1 text-gray-400 text-xs">
                        {{ tool.description }}
                      </div>
                    </div>
                  </div>
                  <!-- 添加按钮 -->
                  <a-button
                    size="mini"
                    class="invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity duration-150 rounded px-1.5 flex-shrink-0"
                    @click="() => handleSelectTool(Number(builtin_tool_idx), Number(tool_idx))"
                  >
                    <template #icon>
                      <icon-plus />
                    </template>
                    {{ isToolSelected(builtin_tool, tool) ? '删除' : '添加' }}
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
          <!-- 已安装插件列表 -->
          <div v-if="toolsActivateType === 'installed'">
            <div v-if="props.tools.length > 0" class="flex flex-col gap-1">
              <div
                v-for="(tool, idx) in props.tools"
                :key="idx"
                class="flex items-center justify-between px-2 py-2 rounded-lg hover:bg-gray-50 group"
              >
                <!-- 工具信息 -->
                <div class="flex items-center gap-2 flex-1 min-w-0">
                  <a-avatar
                    :size="20"
                    shape="circle"
                    :style="{ backgroundColor: 'transparent' }"
                    :image-url="
                      tool.type === 'api_tool'
                        ? tool.provider?.icon || ''
                        : `${apiPrefix}/builtin_tools/${tool.provider?.name}/icon`
                    "
                  />
                  <div class="flex flex-col flex-1 min-w-0">
                    <div class="line-clamp-1 text-gray-700 text-sm font-medium">
                      {{ tool.provider?.label || tool.provider?.name }} /
                      {{ tool.tool?.label }}
                    </div>
                    <div class="line-clamp-1 text-gray-400 text-xs">
                      {{ tool.tool?.description }}
                    </div>
                  </div>
                </div>
                <!-- 操作按钮：固定显示在行右侧（仅删除图标） -->
                <div class="flex items-center flex-shrink-0 ml-1">
                  <a-button
                    aria-label="移除"
                    size="mini"
                    type="text"
                    class="!text-red-700 rounded"
                    @click="handleDeleteTool(idx)"
                  >
                    <template #icon>
                      <icon-delete />
                    </template>
                  </a-button>
                </div>
              </div>
            </div>
            <a-empty
              v-else
              description="还没有添加插件，可在「内置插件 / 自定义插件」中添加"
              class="h-[400px] flex flex-col items-center justify-center"
            />
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
                    :class="`flex items-center justify-between px-2 py-2 rounded-lg cursor-pointer hover:bg-gray-50 group border border-transparent ${isToolSelected(api_tool_provider, tool) ? 'bg-gray-50' : ''}`"
                    :style="isToolSelected(api_tool_provider, tool) ? { borderColor: '#1d4ed8' } : {}"
                  >
                    <!-- 工具信息 -->
                    <div class="flex items-center gap-2 flex-1 min-w-0">
                      <a-avatar :size="20" shape="circle" :image-url="api_tool_provider.icon" />
                      <div class="flex flex-col flex-1 min-w-0">
                        <div class="line-clamp-1 text-gray-700 text-sm font-medium">
                          {{ tool.name }}
                        </div>
                        <div class="line-clamp-1 text-gray-400 text-xs">
                          {{ tool.description }}
                        </div>
                      </div>
                    </div>
                    <!-- 添加按钮 -->
                    <a-button
                      size="mini"
                      class="invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-opacity duration-150 rounded px-1.5 flex-shrink-0"
                      @click="() => handleSelectTool(Number(api_tool_provider_idx), Number(tool_idx))"
                    >
                      <template #icon>
                        <icon-plus />
                      </template>
                      {{ isToolSelected(api_tool_provider, tool) ? '删除' : '添加' }}
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
.tool-setting-modal {
  .arco-modal-wrapper {
    text-align: right;
  }
}

.tools-modal {
  .arco-modal-wrapper {
    text-align: right;
  }

  .arco-modal-body {
    padding: 0;
    height: 100%;
    width: 100%;
    border-radius: 8px;
  }
}
</style>
