<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { nextTick, ref, watch } from 'vue'

const route = useRoute()
const router = useRouter()
const createType = ref<string>('')
const searchWord = ref(route.query.search_word || '')
// 搜索框浮层状态：小视口下显示搜索图标，点击后浮出搜索框，鼠标移开恢复图标
const searchActive = ref(false)

const openSearch = async () => {
  searchActive.value = true
  await nextTick()
  document.querySelector<HTMLInputElement>('#input-search-sm input')?.focus()
}

const search = (value: string) => {
  router.push({
    path: route.path,
    query: {
      search_word: value,
    },
  })
}

const updateCreateType = (value: string) => {
  createType.value = value
}

watch(
  () => route.query?.search_word,
  () => {
    searchWord.value = route.query?.search_word || ''
  },
)
</script>

<template>
  <div class="px-6 flex flex-col overflow-hidden h-full">
    <div class="pt-6 sticky top-0 z-20 bg-gray-50">
      <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-2">
          <a-avatar :size="32" class="bg-blue-700">
            <icon-user :size="18" />
          </a-avatar>
          <div class="text-lg font-medium text-gray-900">个人空间</div>
        </div>
        <!-- 创建按钮-->
        <a-button
          v-if="route.path.startsWith('/space/apps')"
          type="primary"
          class="rounded-lg"
          @click="createType = 'app'"
        >
          创建AI应用
        </a-button>
        <a-button
          @click="createType = 'skills'"
          v-if="route.path.startsWith('/space/skills')"
          type="primary"
          class="rounded-lg"
        >
          创建Skill
        </a-button>
        <a-button
          @click="createType = 'tool'"
          v-if="route.path.startsWith('/space/tools')"
          type="primary"
          class="rounded-lg"
        >
          创建API插件
        </a-button>
        <a-button
          v-if="route.path.startsWith('/space/workflows')"
          type="primary"
          class="rounded-lg"
          @click="createType = 'workflow'"
        >
          创建工作流
        </a-button>
        <a-button
          @click="createType = 'dataset'"
          v-if="route.path.startsWith('/space/datasets')"
          type="primary"
          class="rounded-lg"
        >
          创建知识库
        </a-button>
      </div>
      <!-- 导航按钮+搜索框-->
      <div class="flex items-center justify-between gap-3 mb-6">
        <!-- 左侧导航（单行不换行；视口缩小时字体/间距缩小压缩，不显示省略号） -->
        <div class="flex items-center gap-2 max-md:gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-w-none whitespace-nowrap">
          <router-link
            to="/space/apps"
            class="rounded-lg text-gray-700 text-sm max-md:text-[12px] px-3 max-md:px-2 h-8 leading-8 hover:bg-gray-200 transition-all flex-shrink-0 whitespace-nowrap"
            active-class="bg-gray-100"
          >
            AI应用
          </router-link>
          <router-link
            to="/space/tools"
            class="rounded-lg text-gray-700 text-sm max-md:text-[12px] px-3 max-md:px-2 h-8 leading-8 hover:bg-gray-200 transition-all flex-shrink-0 whitespace-nowrap"
            active-class="bg-gray-100"
          >
            API插件
          </router-link>
          <router-link
            to="/space/skills"
            class="rounded-lg text-gray-700 text-sm max-md:text-[12px] px-3 max-md:px-2 h-8 leading-8 hover:bg-gray-200 transition-all flex-shrink-0 whitespace-nowrap"
            active-class="bg-gray-100"
          >
            SKILLS
          </router-link>
          <router-link
            to="/space/workflows"
            class="rounded-lg text-gray-700 text-sm max-md:text-[12px] px-3 max-md:px-2 h-8 leading-8 hover:bg-gray-200 transition-all flex-shrink-0 whitespace-nowrap"
            active-class="bg-gray-100"
          >
            工作流
          </router-link>
          <router-link
            to="/space/datasets"
            class="rounded-lg text-gray-700 text-sm max-md:text-[12px] px-3 max-md:px-2 h-8 leading-8 hover:bg-gray-200 transition-all flex-shrink-0 whitespace-nowrap"
            active-class="bg-gray-100"
          >
            知识库
          </router-link>
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
              v-model="searchWord"
              placeholder="请输入搜索内容"
              size="small"
              class="bg-white rounded-lg border-gray-300"
              @search="search"
              @blur="searchActive = false"
            />
          </div>
        </div>
        <!-- 正常视口：完整搜索框（宽度放在外层 div：Arco 样式后注入会覆盖 a-input-search 上的 Tailwind 宽度类） -->
        <div class="hidden md:block w-[180px] shrink-0">
          <a-input-search
            id="input-search"
            name="input-search"
            v-model="searchWord"
            placeholder="请输入搜索内容"
            class="bg-white rounded-lg border-gray-300"
            @search="search"
          />
        </div>
      </div>
    </div>
    <!-- 中间内容-->
    <router-view :create-type="createType" @update-create-type="updateCreateType" />
  </div>
</template>

<style scoped></style>
