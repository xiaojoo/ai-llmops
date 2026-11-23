<script setup lang="ts">
import { useGetPublishedConfig, useRegenerateWebAppToken } from '@/hooks/use-app.ts'
import { useRoute, useRouter } from 'vue-router'
import { computed, onMounted } from 'vue'

const route = useRoute()
const router = useRouter()

const {
  loading: getPublishedConfigLoading,
  published_config,
  loadPublishedConfig,
} = useGetPublishedConfig()

const { token, handleRegenerateWebAppToken } = useRegenerateWebAppToken()

const webAppUrl = computed(() => {
  if (published_config.value?.web_app?.status === 'published') {
    return getFullPath('web-apps-index', {
      token: published_config.value?.web_app?.token,
    })
  }
  return ''
})

const getFullPath = (name: string, params = {}, query = {}) => {
  // 通过router.resolve获取路由的完整路径
  const { href } = router.resolve({
    name,
    params,
    query,
  })

  // 如果需要包括 host 部分，结合 window.location.origin
  return window.location.origin + href
}

// 单行表格数据（发布渠道固定为网页版）
const table_data = computed(() => [{ key: 'web_app' }])

const handleRegenerateWebAppTokenClick = async () => {
  await handleRegenerateWebAppToken(String(route.params?.app_id))
  if (published_config.value.web_app) {
    published_config.value.web_app.token = token.value
  }
}

onMounted(() => {
  loadPublishedConfig(String(route.params?.app_id))
})
</script>

<template>
  <div class="bg-white flex-1 w-full min-h-0 px-6 py-5">
    <!-- 顶部提示信息 -->
    <a-alert class="mb-5">
      如应用访问链接或二维码意外泄露，请及时重新生成或进行停止分发，避免资源出现异常消耗
    </a-alert>
    <!-- 发布渠道列表（样式与 api-keys 表格一致：圆角灰表头 + hover；仅操作列固定右侧） -->
    <a-table
      hoverable
      :loading="getPublishedConfigLoading"
      :pagination="false"
      :bordered="{ wrapper: false }"
      :scroll="{ x: '100%', minWidth: 1040 }"
      :data="table_data"
    >
      <template #columns>
        <a-table-column
          title="发布渠道"
          data-index="channel"
          :width="280"
          header-cell-class="rounded-tl-lg !bg-gray-200 text-gray-700"
          cell-class="bg-transparent text-gray-700"
        >
          <template #cell>
            <div class="flex items-center gap-2 whitespace-nowrap">
              <a-avatar :size="36" shape="square" class="bg-blue-100">
                <icon-compass :size="18" class="!text-blue-700" />
              </a-avatar>
              <div class="flex flex-col">
                <div class="text-gray-700 font-semibold">网页版</div>
                <div class="text-gray-500">可通过访问PC网页立即开始对话。</div>
              </div>
            </div>
          </template>
        </a-table-column>
        <a-table-column
          title="状态"
          data-index="status"
          :width="120"
          header-cell-class="!bg-gray-200 text-gray-700 whitespace-nowrap"
          cell-class="bg-transparent text-gray-700 whitespace-nowrap"
        >
          <template #cell>
            <a-tag v-if="published_config?.web_app?.status != 'published'" color="gray" bordered>
              <template #icon>
                <icon-minus-circle />
              </template>
              未发布
            </a-tag>
            <a-tag v-else color="blue" bordered>
              <template #icon>
                <icon-check-circle-fill />
              </template>
              已发布
            </a-tag>
          </template>
        </a-table-column>
        <!-- 地址列（不换行，视口过窄时随表格横向滚动） -->
        <a-table-column
          title="地址"
          data-index="address"
          header-cell-class="!bg-gray-200 text-gray-700"
          cell-class="bg-transparent text-gray-700"
        >
          <template #cell>
            <div class="whitespace-nowrap">
              <template v-if="published_config?.web_app?.status === 'published'">
                {{ webAppUrl }}
              </template>
              <template v-else>应用未发布，无可访问链接</template>
            </div>
          </template>
        </a-table-column>
        <!-- 操作列（固定不随滚动） -->
        <a-table-column
          title="操作"
          data-index="actions"
          :width="230"
          fixed="right"
          header-cell-class="rounded-tr-lg !bg-gray-200 text-gray-700"
          cell-class="bg-white"
        >
          <template #cell>
            <div class="flex items-center gap-2 whitespace-nowrap">
              <a-button
                :disabled="published_config?.web_app?.status !== 'published'"
                type="primary"
                class="rounded-lg px-2 btn-regenerate"
                @click="handleRegenerateWebAppTokenClick"
              >
                重新生成
              </a-button>
              <a-button type="primary" class="rounded-lg px-2 btn-visit">
                <template v-if="published_config?.web_app?.status !== 'published'">
                  立即访问
                </template>
                <template v-else>
                  <a :href="webAppUrl" target="_blank" class="no-underline">立即访问</a>
                </template>
              </a-button>
            </div>
          </template>
        </a-table-column>
      </template>
    </a-table>
  </div>
</template>

<style scoped>
/* 重新生成按钮：橙色背景（警示性操作，提醒链接/二维码泄露风险） */
.btn-regenerate {
  background-color: #f97316;
  border-color: #f97316;
  color: #fff;
}
.btn-regenerate:hover {
  background-color: #ea580c;
  border-color: #ea580c;
  color: #fff;
}
.btn-regenerate[disabled] {
  background-color: #fdba74;
  border-color: #fdba74;
  color: rgba(255, 255, 255, 0.9);
}
/* 立即访问按钮：品牌蓝背景（主要 CTA） */
.btn-visit {
  background-color: #2563eb;
  border-color: #2563eb;
  color: #fff;
}
.btn-visit:hover {
  background-color: #1d4ed8;
  border-color: #1d4ed8;
  color: #fff;
}
</style>
