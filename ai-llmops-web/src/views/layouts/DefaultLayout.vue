<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useCredentialStore } from '@/stores/credential.ts'
import { onMounted, ref } from 'vue'
import { useAccountStore } from '@/stores/account.ts'
import { logout } from '@/services/auth.ts'
import { getCurrentUser } from '@/services/account.ts'
import SettingModal from '@/views/layouts/components/SettingModal.vue'
import CreateOrUpdateAppModal from '@/views/space/apps/components/CreateOrUpdateAppModal.vue'
import ParticleText from '@/components/ParticleText.vue'
import TechLogo from '@/components/TechLogo.vue'

const route = useRoute()
const router = useRouter()

const createAppModalVisible = ref(false)
const settingModalVisible = ref(false)
// 侧边栏折叠状态：breakpoint="xl"（视口 <1200px）时自动折叠为仅图标
const siderCollapsed = ref(false)
const credentialStore = useCredentialStore()
const accountStore = useAccountStore()

const handleLogout = async () => {
  await logout()

  credentialStore.clear()
  accountStore.clear()

  await router.replace({ name: 'auth-login' })
}

onMounted(async () => {
  const resp = await getCurrentUser()
  accountStore.update(resp.data)
})
</script>

<template>
  <a-layout has-sider class="overflow-hidden bg-gray-50" style="width: 100%; height: 100vh">
    <!--    style="width: 100%; height: calc(100vh - 16px)"-->
    <!-- 侧边栏 -->
    <a-layout-sider
      v-model:collapsed="siderCollapsed"
      :width="240"
      :collapsed-width="50"
      breakpoint="xl"
      class="h-full bg-gray-50 p-2 shadow-none"
    >
      <div
        class="bg-white h-full rounded-lg px-2 py-4 flex flex-col justify-between"
        :class="{ 'side-collapsed': siderCollapsed }"
      >
        <!-- 上半部分（折叠态 text-center 让行内元素如创建按钮居中，不影响导航项拉伸贴边） -->
        <div class="" :class="{ 'text-center': siderCollapsed }">
          <!-- 顶部logo（左侧量子图标 + 右侧粒子文字动画） -->
          <router-link
            to="/home"
            class="flex items-center gap-0 mb-5 group"
            :class="{ 'justify-center': siderCollapsed }"
          >
            <!-- 左侧：量子领域图标 -->
            <tech-logo :size="siderCollapsed ? 24 : 40" class="flex-shrink-0" />
            <!-- 右侧：粒子文字动画 -->
            <div v-show="!siderCollapsed" class="flex-1 min-w-0 h-10 overflow-hidden">
              <particle-text
                text="Quantum"
                :particle-size="2"
                :density="4"
                color="#22d3ee"
                highlight-color="#a78bfa"
                :scatter="120"
                :gather-duration="1400"
                :stagger="360"
                :pointer-repel="30"
                :repel-radius="100"
                :idle-drift="0.6"
                trigger="mount"
                :font-size="'clamp(1.4rem, 3vw, 2.1rem)'"
                :font-weight="800"
                font-family="inherit"
                :glow="false"
                align="left"
                class="particle-text-header"
              />
            </div>
          </router-link>
          <!-- 创意AI应用按钮（折叠态仅图标 + 气泡） -->
          <a-tooltip :content="'创建AI应用'" :disabled="!siderCollapsed" position="right">
            <a-button
              type="primary"
              :long="!siderCollapsed"
              class="rounded-lg mb-4 h-10"
              :class="siderCollapsed ? 'w-7 !px-0 collapsed-icon' : 'leading-10'"
              @click="createAppModalVisible = true"
            >
              <template #icon>
                <icon-plus style="width: 1rem; height: 1rem" />
              </template>
              <!-- v-if：折叠时文字彻底移除，图标成为末位子元素（无 Arco 图标右侧 margin，水平居中） -->
              <span v-if="!siderCollapsed">创建AI应用</span>
            </a-button>
          </a-tooltip>
          <!-- 侧边栏导航 -->
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'Agent Robot'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/home"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/home')" />
                <icon-robot-add v-else />
                <span v-show="!siderCollapsed">Agent Robot</span>
              </router-link>
            </a-tooltip>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'个人空间'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/space/apps"
                :class="`flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200 ${route.path.startsWith('/space') ? 'bg-gray-100' : ''} ${siderCollapsed ? 'justify-center !px-0' : ''}`"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/space')" />
                <icon-user v-else />
                <span v-show="!siderCollapsed">个人空间</span>
              </router-link>
            </a-tooltip>
            <div v-show="!siderCollapsed" class="text-gray-500 text-sm px-2">探索</div>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'应用广场'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/store/apps"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/store/apps')" />
                <icon-relation v-else />
                <span v-show="!siderCollapsed">应用广场</span>
              </router-link>
            </a-tooltip>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'插件广场'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/store/tools"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/store/tools')" />
                <icon-tool v-else />
                <span v-show="!siderCollapsed">插件广场</span>
              </router-link>
            </a-tooltip>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'开放API'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/openapi"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/openapi')" />
                <icon-branch v-else />
                <span v-show="!siderCollapsed">开放API</span>
              </router-link>
            </a-tooltip>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'Chroma'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/chroma"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/chroma')" />
                <icon-reply v-else />
                <span v-show="!siderCollapsed">Chroma</span>
              </router-link>
            </a-tooltip>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'Weaviate'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/weaviate"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/weaviate')" />
                <icon-font-colors v-else />
                <span v-show="!siderCollapsed">Weaviate</span>
              </router-link>
            </a-tooltip>
          </div>
          <div class="flex flex-col gap-2 nav-gap">
            <a-tooltip :content="'系统设置'" :disabled="!siderCollapsed" position="right">
              <router-link
                to="/settings"
                class="flex items-center gap-2 h-10 leading-10 rounded-lg transition-all px-2 text-gray-700 hover:text-gray-900 hover:bg-gray-200"
                :class="siderCollapsed ? 'justify-center !px-0' : ''"
                active-class="bg-gray-100"
              >
                <icon-pen-fill v-if="route.path.startsWith('/settings')" />
                <icon-settings v-else />
                <span v-show="!siderCollapsed">系统设置</span>
              </router-link>
            </a-tooltip>
          </div>
        </div>
        <!-- 账号设置 -->
        <a-dropdown position="tl">
          <div
            class="flex items-center p-2 gap-2 transition-all cursor-pointer rounded-lg hover:bg-gray-100"
            :class="{ 'justify-center': siderCollapsed }"
          >
            <!-- 头像（无图/加载失败时显示默认用户图标；flex 容器保证预加载阶段兜底图标水平垂直居中） -->
            <a-avatar
              :size="32"
              class="shrink-0 self-center align-middle text-sm bg-blue-700"
              :image-url="accountStore.account.avatar || ''"
            >
              <div class="w-full h-full flex items-center justify-center">
                <icon-user />
              </div>
            </a-avatar>
            <!-- 个人信息：与 32px 头像同高垂直居中，长昵称/邮箱截断 -->
            <div v-show="!siderCollapsed" class="flex min-w-0 flex-1 flex-col justify-center">
              <div class="truncate text-sm leading-4 text-gray-900">{{ accountStore.account.name }}</div>
              <div class="mt-1 truncate text-xs leading-3 text-gray-500">{{ accountStore.account.email }}</div>
            </div>
          </div>
          <template #content>
            <a-doption @click="settingModalVisible = true">
              <template #icon>
                <icon-settings />
              </template>
              账号设置
            </a-doption>
            <a-doption @click="handleLogout">
              <template #icon>
                <icon-poweroff />
              </template>
              退出登录
            </a-doption>
          </template>
        </a-dropdown>
      </div>
    </a-layout-sider>
    <a-layout-content class="h-full overflow-y-auto overflow-x-hidden">
      <router-view />
    </a-layout-content>
    <!-- 设置模态窗 -->
    <setting-modal v-model:visible="settingModalVisible" />
    <!-- 新建/修改模态窗口 -->
    <create-or-update-app-modal v-model:visible="createAppModalVisible" />
  </a-layout>
</template>

<style scoped>
.arco-icon {
  width: 1rem;
  height: 1rem;
}

/* 顶部 header 粒子文字：去掉组件默认的最小高度，贴合 40px 高的 logo 区 */
:deep(.particle-text-header.particle-text) {
  min-height: 0;
  height: 40px;
}

/* 侧边栏导航选项之间的间隙：只在相邻选项间加，首项上方/末项下方不加 */
.nav-gap + .nav-gap {
  margin-top: 6px;
}

/* 侧边栏折叠态：收窄内边距，为纯图标腾出空间（折叠宽 50px） */
.side-collapsed {
  padding-left: 2px;
  padding-right: 2px;
}

/* 折叠态创建按钮：去掉 Arco 图标的默认 8px 右侧 margin，保证图标水平居中 */
.collapsed-icon :deep(.arco-btn-icon) {
  margin-right: 0 !important;
}
</style>
