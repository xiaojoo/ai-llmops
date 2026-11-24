<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useCancelPublish, useGetApp, usePublish } from '@/hooks/use-app.ts'
import { onMounted, ref } from 'vue'
import PublishHistoryDrawer from './components/PublishHistoryDrawer.vue'
import './components/app-builder.css'

const route = useRoute()
const { loading, app, loadApp } = useGetApp()
const { loading: publishLoading, handlePublish } = usePublish()
const { loading: publishCancelLoading, handleCancelPublish } = useCancelPublish()
const publishHistoryDrawerVisible = ref(false)

const onPublishClick = async () => {
  const app_id = String(route.params?.app_id)
  await handlePublish(app_id)
  await loadApp(app_id)
}

const onCancelPublishClick = async () => {
  const app_id = String(route.params?.app_id)

  await handleCancelPublish(app_id, async () => {
    await loadApp(app_id)
  })
}
onMounted(async () => await loadApp(String(route.params?.app_id)))
</script>

<template>
  <!-- 外层容器（ab-shell 提供 demo 设计令牌与基础字号） -->
  <div class="ab-shell min-h-screen flex flex-col h-full overflow-hidden bg-white">
    <!-- 顶部导航（对齐 demo topbar：白底 68px、左侧品牌信息、中间 pill 页签、右侧操作） -->
    <div class="ab-topbar">
      <!-- 左侧应用信息 -->
      <div class="flex items-center gap-3 min-w-0">
        <!-- 回退按钮 -->
        <router-link :to="{ name: 'space-apps-list' }">
          <a-button aria-label="返回" size="mini" class="!rounded-lg !w-8 !h-8">
            <template #icon>
              <icon-left />
            </template>
          </a-button>
        </router-link>
        <!-- 应用图标与信息（窄视口下整块隐藏，优先保证右侧操作按钮可见） -->
        <div class="ab-top-info flex items-center gap-3 min-w-0">
          <a-avatar :size="40" shape="square" class="rounded-lg shrink-0" :image-url="app?.icon" />
          <div class="flex flex-col justify-between h-[40px] min-w-0">
            <a-skeleton-line v-if="loading" :widths="[100]" />
            <div v-else class="ab-brand-name">{{ app?.name }}</div>
            <div v-if="loading" class="flex items-center gap-2">
              <a-skeleton-line :widths="[60]" :line-height="18" />
              <a-skeleton-line :widths="[60]" :line-height="18" />
            </div>
            <div v-else class="flex items-center gap-2 text-xs text-[#7a8496]">
              <span class="flex items-center gap-1">
                <icon-user :size="14" />
                个人空间
              </span>
              <span class="text-[#d0d5dd]">/</span>
              <span class="flex items-center gap-1">
                <icon-schedule :size="14" />
                {{ app?.status === 'draft' ? '草稿' : '已发布' }}
              </span>
            </div>
          </div>
        </div>
      </div>
      <!-- 中间页签（pill 样式，对齐 demo .top-tabs） -->
      <div class="absolute left-1/2 -translate-x-1/2">
        <div class="ab-top-tabs">
          <router-link
            :to="{ name: 'space-apps-detail', params: { app_id: String(route.params?.app_id) } }"
            class="ab-top-tab"
            exact-active-class="active"
          >
            应用编排
          </router-link>
          <router-link
            :to="{ name: 'space-apps-published', params: { app_id: String(route.params?.app_id) } }"
            class="ab-top-tab"
            active-class="active"
          >
            发布配置
          </router-link>
          <router-link
            :to="{ name: 'space-apps-analysis', params: { app_id: String(route.params?.app_id) } }"
            class="ab-top-tab"
            active-class="active"
          >
            统计分析
          </router-link>
        </div>
      </div>
      <!-- 右侧操作 -->
      <div class="flex items-center gap-2.5">
        <a-button
          aria-label="发布历史"
          :disabled="loading"
          class="!rounded-lg !w-9 !h-9 text-[#344054]!"
          @click="publishHistoryDrawerVisible = true"
        >
          <template #icon>
            <icon-schedule />
          </template>
        </a-button>
        <a-button-group>
          <a-button
            :disabled="loading"
            :loading="publishLoading"
            @click="onPublishClick"
            type="primary"
            class="!h-9 !rounded-tl-lg !rounded-bl-lg !text-sm !font-medium"
            >更新发布</a-button
          >
          <a-dropdown position="br">
            <a-button aria-label="下载" type="primary" class="!rounded-tr-lg !rounded-br-lg !w-5 !h-9">
              <template #icon>
                <icon-down />
              </template>
            </a-button>
            <template #content>
              <a-doption
                :loading="publishCancelLoading"
                :disabled="app?.status === 'draft'"
                @click="onCancelPublishClick"
                class="!text-red-700"
              >
                取消发布
              </a-doption>
            </template>
          </a-dropdown>
        </a-button-group>
      </div>
    </div>
    <!-- 底部内容区 -->
    <router-view :app="app" />
    <publish-history-drawer
      :app="app ?? {}"
      v-model:visible="publishHistoryDrawerVisible"
      @load-draft-app-config="() => {}"
    />
  </div>
</template>

<style scoped></style>
