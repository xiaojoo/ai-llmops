<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { getBuiltinTools, getCategories } from '@/services/builtin-tool.ts'
import { apiPrefix, typeMap } from '@/config'
import moment from 'moment'

// 内置插件数据结构（模板所需字段，与 models/builtin-tool.ts 对齐）
interface BuiltinToolInput {
  name: string
  type: string
  required: boolean
  description: string
}

interface BuiltinTool {
  name: string
  label: string
  description: string
  inputs: BuiltinToolInput[]
}

interface BuiltinProvider {
  background: string
  backgroud?: string
  category: string
  created_at: number
  description: string
  label: string
  name: string
  tools: BuiltinTool[]
}

interface BuiltinCategory {
  category: string
  icon: string
  name: string
}

const categories = reactive<BuiltinCategory[]>([])
const providers = reactive<BuiltinProvider[]>([])
const loading = ref<boolean>()
const category = ref<string>('all')
const search_word = ref<string>('')
const showIdx = ref<number>(-1)
// 搜索框浮层状态：小视口下显示搜索图标，点击后浮出搜索框，鼠标移开恢复图标
const searchActive = ref(false)

const openSearch = async () => {
  searchActive.value = true
  await nextTick()
  document.querySelector<HTMLInputElement>('#input-search-sm input')?.focus()
}

// 图标加载失败集合（无图/404 时显示默认图标兜底）
const iconErrors = reactive<Set<string>>(new Set())
const onIconError = (name: string) => {
  iconErrors.add(name)
}

const filterProviders = computed(() => {
  return providers.filter((item) => {
    // 分别检索分类信息+搜索词，只有同时符合的时候才返回数据
    const matchCategory = category.value === 'all' || item.category === category.value
    const matchSearchWord =
      search_word.value === '' ||
      item.label.toLowerCase().includes(search_word.value.toLowerCase())

    return matchCategory && matchSearchWord
  })
})

// 当前抽屉中选中的提供商（仅在 showIdx != -1 的 UI 分支中访问，运行时安全）
const currentProvider = computed<BuiltinProvider>(() => filterProviders.value[showIdx.value]!)

onMounted(async () => {
  try {
    loading.value = true
    const [categoriesResp, providersResp] = await Promise.all([getCategories(), getBuiltinTools()])
    categories.push(...categoriesResp.data)
    providers.push(...(providersResp.data as BuiltinProvider[]))
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <a-spin :loading="loading" class="block h-full w-full">
    <div class="p-6 flex flex-col">
      <!-- 顶层标题+创建按钮-->
      <div class="flex items-center justify-between mb-6">
        <!-- 左侧标题-->
        <div class="flex items-center gap-2">
          <a-avatar :size="32" class="bg-blue-700">
            <icon-common :size="18" />
          </a-avatar>
          <div class="text-lg font-medium text-gray-900">插件广场</div>
        </div>
        <!-- 创建插件-->
        <a-button type="primary" class="rounded-lg">创建自定义插件</a-button>
      </div>
      <!-- 插件分类+搜索框-->
      <div class="flex items-center justify-between gap-3 mb-6">
        <!-- 左侧分类（单行不换行；视口缩小时字体/间距缩小，不显示省略号） -->
        <div class="flex items-center gap-2 max-md:gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-w-none whitespace-nowrap">
          <a-button
            :type="category === 'all' ? 'secondary' : 'text'"
            class="rounded-lg !text-gray-700 text-sm max-md:!text-[12px] !px-3 max-md:!px-2 h-8 flex-shrink-0 whitespace-nowrap"
            @click="category = 'all'"
            >全部</a-button
          >
          <a-button
            v-for="item in categories"
            :key="item.category"
            :type="category === item.category ? 'secondary' : 'text'"
            class="rounded-lg !text-gray-700 text-sm max-md:!text-[12px] !px-3 max-md:!px-2 h-8 flex-shrink-0 whitespace-nowrap"
            @click="category = item.category"
            >{{ item.name }}
          </a-button>
        </div>
        <!-- 右侧搜索：小视口(<768px)显示搜索图标，点击浮出搜索框，鼠标移开恢复图标 -->
        <div class="relative shrink-0 flex items-center md:hidden">
          <a-tooltip content="搜索" position="left" :disabled="searchActive">
            <a-button aria-label="搜索"
              v-show="!searchActive"
              type="text"
              class="!text-gray-500"
              @click="openSearch"
            >
              <template #icon>
                <icon-search />
              </template>
            </a-button>
          </a-tooltip>
          <div
            v-show="searchActive"
            class="absolute right-0 top-1/2 -translate-y-1/2 z-30 w-[220px]"
            @mouseleave="searchActive = false"
          >
            <a-input-search
              id="input-search-sm"
              name="input-search-sm"
              v-model="search_word"
              placeholder="请输入插件名称"
              size="small"
              class="bg-white rounded-lg border-gray-300"
              @blur="searchActive = false"
            />
          </div>
        </div>
        <!-- 正常视口：完整搜索框（宽度放在外层 div：Arco 样式后注入会覆盖 a-input-search 上的 Tailwind 宽度类）-->
        <div class="hidden md:block w-[180px] shrink-0">
          <a-input-search
            id="input-search"
            name="input-search"
            v-model="search_word"
            placeholder="请输入插件名称"
            class="bg-white rounded-lg border-gray-300"
          />
        </div>
      </div>
      <!-- 底部插件列表-->
      <a-row :gutter="[20, 20]" class="flex-1">
        <!-- 有数据的UI状态（响应式：视口缩小自动换行 4/3/2/1 列） -->
        <a-col
          v-for="(provider, idx) in filterProviders"
          :key="provider.name"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          :xl="6"
          :xxl="6"
        >
          <a-card hoverable class="cursor-pointer rounded-lg" @click="showIdx = idx">
            <!-- 顶部提供商名称-->
            <div class="flex items-center gap-3 mb-3">
              <!-- 左侧图标（无图/加载失败显示默认图标兜底；图片铺满 40x40 头像，flex 容器保证兜底图标水平垂直居中） -->
              <a-avatar :size="40" shape="square" :style="{ backgroundColor: 'transparent' }">
                <img
                  v-if="!iconErrors.has(provider.name)"
                  class="w-full h-full"
                  :src="`${apiPrefix}/builtin_tools/${provider.name}/icon`"
                  :alt="provider.name"
                  @error="onIconError(provider.name)"
                />
                <div v-else class="w-full h-full flex items-center justify-center">
                  <icon-apps />
                </div>
              </a-avatar>
              <!-- 右侧工具信息-->
              <div class="flex flex-col">
                <div class="text-base text-gray-900 font-bold line-clamp-1">{{ provider.label }}</div>
                <div class="text-xs text-gray-500 line-clamp-1">
                  提供商 {{ provider.name }} * {{ provider.tools.length }} 插件
                </div>
              </div>
            </div>
            <!-- 提供商的描述信息-->
            <div class="leading-[18px] text-gray-500 h-[72px] line-clamp-4 mb-2">
              {{ provider.description }}
            </div>
            <!-- 提供商的发布信息-->
            <div class="flex items-center gap-1.5">
              <a-avatar :size="18" class="bg-blue-700">
                <icon-user />
              </a-avatar>
              <div class="text-xs text-gray-400">
                DeepSeek · 发布时间 {{ moment(provider.created_at).format('MM-DD HH:mm:ss') }}
              </div>
            </div>
          </a-card>
        </a-col>
        <!-- 没数据的UI状态-->
        <a-col v-if="filterProviders.length === 0" :span="24">
          <a-empty
            description="没有可用的内置插件"
            class="h-[400px] flex flex-col items-center justify-center"
          />
        </a-col>
      </a-row>
      <!-- 卡片抽屉-->
      <a-drawer
        :visible="showIdx != -1"
        :width="350"
        :footer="false"
        title="工具详情"
        :drawer-style="{ background: '#F9FAFB' }"
        @cancel="showIdx = -1"
      >
        <!-- 外部容器，用于判断showIdx是否为-1，为-1的时候就不显示-->
        <div v-if="showIdx != -1">
          <!-- 顶部提供商名称-->
          <div class="flex items-center gap-3 mb-3">
            <!-- 左侧图标（无图/加载失败显示默认图标兜底；图片铺满 40x40 头像，flex 容器保证兜底图标水平垂直居中） -->
            <a-avatar
              :size="40"
              shape="square"
              :style="{ backgroundColor: currentProvider.backgroud }"
            >
              <img
                v-if="!iconErrors.has(currentProvider.name)"
                class="w-full h-full"
                :src="`${apiPrefix}/builtin_tools/${currentProvider.name}/icon`"
                :alt="currentProvider.name"
                @error="onIconError(currentProvider.name)"
              />
              <div v-else class="w-full h-full flex items-center justify-center">
                <icon-apps />
              </div>
            </a-avatar>
            <!-- 右侧工具信息-->
            <div class="flex flex-col">
              <div class="text-base text-gray-900 font-bold">
                {{ currentProvider.label }}
              </div>
              <div class="text-xs text-gray-500 line-clamp-1">
                提供商 {{ currentProvider.name }} *
                {{ currentProvider.tools.length }} 插件
              </div>
            </div>
          </div>
          <!-- 提供商的描述信息-->
          <div class="leading-[18px] text-gray-500 mb-2">
            {{ currentProvider.description }}
          </div>
          <!-- 分隔符-->
          <hr class="my-4" />
          <!-- 提供者工具-->
          <div class="flex flex-col gap-2">
            <div class="text-xs text-gray-500">
              包含 {{ currentProvider.tools.length }} 个工具
            </div>
            <!-- 工具列表-->
            <a-card
              v-for="tool in currentProvider.tools"
              :key="tool.name"
              class="cursor-pointer flex flex-col rounded-xl"
            >
              <!-- 工具名称-->
              <div class="font-bold text-gray-900 mb-2 line-clamp-1">{{ tool.label }}</div>
              <!-- 工具描述-->
              <div class="text-gray-500 text-xs">{{ tool.description }}</div>
              <!-- 工具参数-->
              <div v-if="tool.inputs.length > 0">
                <!-- 分隔符-->
                <div class="flex items-center gap-2 my-4">
                  <div class="text-xs font-bold text-gray-500">参数</div>
                  <hr class="flex-1" />
                </div>
                <!-- 参数列表-->
                <div class="flex flex-col gap-4">
                  <div v-for="input in tool.inputs" :key="input.name" class="flex flex-col gap-2">
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
            </a-card>
          </div>
        </div>
      </a-drawer>
    </div>
  </a-spin>
</template>

<style scoped></style>
