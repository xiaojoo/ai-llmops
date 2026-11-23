<script setup lang="ts">
import moment from 'moment'
import { computed, nextTick, onMounted, ref } from 'vue'
import {
  useAddBuiltinAppToSpace,
  useGetBuiltinAppCategories,
  useGetBuiltinApps,
} from '@/hooks/use-builtin-app.ts'

const category = ref('all')
const search_word = ref('')
// 搜索框浮层状态：小视口下显示搜索图标，点击后浮出搜索框，鼠标移开恢复图标
const searchActive = ref(false)

const openSearch = async () => {
  searchActive.value = true
  await nextTick()
  document.querySelector<HTMLInputElement>('#input-search-sm input')?.focus()
}
const { categories, loadBuiltinAppCategories } = useGetBuiltinAppCategories()
const { loading: getBuiltinAppsLoading, apps, loadBuiltinApps } = useGetBuiltinApps()
const { handleAddBuiltinAppToSpace } = useAddBuiltinAppToSpace()

// 图标地址归一化：后端返回的相对路径（如 /default-app-icon）需加 /api 前缀才能经代理
// 到达后端；已带 /api 的相对路径与完整 URL（COS/http）保持原样。
const resolveIcon = (icon?: string): string => {
  if (!icon) return ''
  if (/^https?:\/\//i.test(icon) || icon.startsWith('/api/')) return icon
  if (icon.startsWith('/')) return `/api${icon}`
  return icon
}

const filterApps = computed(() => {
  return apps.value.filter((item) => {
    // 分别检索分类信息+搜索词，只有同时符合的时候才返回数据
    const matchCategory = category.value === 'all' || item.category === category.value
    const matchSearchWord =
      search_word.value === '' || item.name.toLowerCase().includes(search_word.value.toLowerCase())

    return matchCategory && matchSearchWord
  })
})

onMounted(() => {
  loadBuiltinAppCategories()
  loadBuiltinApps()
})
</script>

<template>
  <a-spin :loading="getBuiltinAppsLoading" class="block h-full w-full">
    <div class="p-6 flex flex-col">
      <!-- 顶层标题 -->
      <div class="flex items-center justify-between mb-6">
        <!-- 左侧标题 -->
        <div class="flex items-center gap-2">
          <a-avatar :size="32" class="bg-blue-700">
            <icon-common :size="18" />
          </a-avatar>
          <div class="text-lg font-medium text-gray-900">应用广场</div>
        </div>
      </div>
      <!-- 应用分类+搜索框 -->
      <div class="flex items-center justify-between gap-3 mb-6">
        <!-- 左侧分类（单行不换行；视口缩小时字体/间距缩小，不显示省略号） -->
        <div class="flex items-center gap-2 max-md:gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-w-none whitespace-nowrap">
          <a-button
            :type="category === 'all' ? 'secondary' : 'text'"
            class="rounded-lg !text-gray-700 text-sm max-md:!text-[12px] !px-3 max-md:!px-2 h-8 flex-shrink-0 whitespace-nowrap"
            @click="category = 'all'"
          >
            全部
          </a-button>
          <a-button
            v-for="item in categories"
            :key="item.category"
            :type="category === item.category ? 'secondary' : 'text'"
            class="rounded-lg !text-gray-700 text-sm max-md:!text-[12px] !px-3 max-md:!px-2 h-8 flex-shrink-0 whitespace-nowrap"
            @click="category = item.category"
          >
            {{ item.name }}
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
      <!-- 底部插件列表 -->
      <a-row :gutter="[20, 20]" class="flex-1">
        <!-- 有数据的UI状态（响应式：视口缩小自动换行 4/3/2/1 列） -->
        <a-col
          v-for="app in filterApps"
          :key="app.id"
          :xs="24"
          :sm="12"
          :md="8"
          :lg="6"
          :xl="6"
          :xxl="6"
        >
          <a-card hoverable class="cursor-pointer rounded-lg">
            <!-- 顶部应用名称 -->
            <div class="flex items-center gap-3 mb-3">
              <!-- 左侧图标（无图/加载中/加载失败显示默认应用图标；flex 容器保证图标水平垂直居中） -->
              <a-avatar :size="40" shape="square" :image-url="resolveIcon(app.icon)">
                <div class="w-full h-full flex items-center justify-center">
                  <icon-apps />
                </div>
              </a-avatar>
              <!-- 右侧App信息 -->
              <div class="flex flex-1 justify-between">
                <div class="flex flex-col">
                  <div class="text-base text-gray-900 font-bold line-clamp-1">{{ app.name }}</div>
                  <div class="text-xs text-gray-500 line-clamp-1">
                    {{ app.model_config.provider_label || app.model_config.provider }} · {{ app.model_config.model_label || app.model_config.model }}
                  </div>
                </div>

                <!-- 操作按钮 -->
                <a-dropdown position="br">
                  <a-button aria-label="更多操作" type="text" size="small" class="rounded-lg !text-gray-700">
                    <template #icon>
                      <icon-more />
                    </template>
                  </a-button>
                  <template #content>
                    <a-doption @click="async () => await handleAddBuiltinAppToSpace(app.id)">
                      添加到工作区
                    </a-doption>
                  </template>
                </a-dropdown>
              </div>
            </div>
            <!-- App的描述信息 -->
            <div class="leading-[18px] text-gray-500 h-[72px] line-clamp-4 mb-2 break-all">
              {{ app.description }}
            </div>
            <!-- 应用的归属者信息 -->
            <div class="flex items-center gap-1.5">
              <a-avatar :size="18" class="bg-blue-700">
                <icon-user />
              </a-avatar>
              <div class="text-xs text-gray-400">
                量子 · 发布时间 {{ moment(app.created_at * 1000).format('MM-DD HH:mm') }}
              </div>
            </div>
          </a-card>
        </a-col>
        <!-- 没数据的UI状态 -->
        <a-col v-if="filterApps.length === 0" :span="24">
          <a-empty
            description="没有可用的内置Agent智能体"
            class="h-[400px] flex flex-col items-center justify-center"
          />
        </a-col>
      </a-row>
    </div>
  </a-spin>
</template>

<style scoped></style>
