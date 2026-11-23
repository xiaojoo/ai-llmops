<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useCredentialStore } from '@/stores/credential.ts'
import { Message, type ValidatedError } from '@arco-design/web-vue'
import { provider } from '@/services/oauth.ts'
import { passwordLogin } from '@/services/auth.ts'
import TechLogo from '@/components/TechLogo.vue'
import ParticleText from '@/components/ParticleText.vue'

const errorMessage = ref('')
const passwordLoading = ref(false)
const githubLoading = ref(false)
const loginForm = reactive({ email: '', password: '' })
const credentialStore = useCredentialStore()
const route = useRoute()
const router = useRouter()

// 登录后跳回原页面：优先取 ?redirect=（仅站内路径），否则首页
const resolveRedirect = (): string => {
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  return redirect && redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/home'
}

// 定义忘记密码点击事件
const forgetPassword = () => Message.error('忘记密码请联系管理员')

// 定义github第三方授权认证登录
const githubLogin = async () => {
  try {
    const resp = await provider('github')
    // GitHub 回调页不带原 redirect，先暂存 sessionStorage 让 AuthorizeView 接力
    if (route.query.redirect) {
      sessionStorage.setItem('llmops-oauth-redirect', resolveRedirect())
    }
    window.location.href = resp.data.redirect_url
  } catch {
    githubLoading.value = false
  }
}

// 账号密码登录
const handleSubmit = async ({ errors }: { errors: Record<string, ValidatedError> | undefined }) => {
  if (errors) return

  try {
    passwordLoading.value = true
    const resp = await passwordLogin(loginForm.email, loginForm.password)
    credentialStore.update(resp.data)
    await router.replace(resolveRedirect())
    Message.success('登录成功，欢迎回来')
  } catch (error: unknown) {
    errorMessage.value = error instanceof Error ? error.message : String(error)
    loginForm.password = ''
  } finally {
    passwordLoading.value = false
  }
}

// 点击账号清除按钮：账号和密码一并清空
const handleClearAccount = () => {
  loginForm.email = ''
  loginForm.password = ''
}
</script>

<template>
  <div class="w-[520px]">
    <div class="flex items-center justify-center mb-5" style="height: 6rem; line-height: 6rem">
      <tech-logo :size="32" class="flex-shrink-0" />
      <div class="w-[520px] h-24 overflow-hidden">
        <particle-text
          text="Quantum Computing"
          :particle-size="2.5"
          :density="3"
          color="#22d3ee"
          highlight-color="#a78bfa"
          :scatter="120"
          :gather-duration="1400"
          :stagger="360"
          :pointer-repel="20"
          :repel-radius="100"
          :idle-drift="0.6"
          trigger="mount"
          :font-size="'clamp(2.5rem, 5vw, 3.5rem)'"
          :font-weight="800"
          font-family="inherit"
          :glow="false"
          align="left"
          class="login-form-title"
        />
      </div>
    </div>
    <!-- 登录错误提示：仅在出错时渲染，平时不留空 div -->
    <div v-if="errorMessage" class="h-8 text-red-700 leading-8 line-clamp-1">{{ errorMessage }}</div>
    <a-form
      :model="loginForm"
      @submit="handleSubmit"
      layout="vertical"
      size="large"
      class="flex flex-col w-full"
    >
      <a-form-item
        field="email"
        :rules="[{ type: 'email', required: true, message: '登录账号必须是合法的邮箱' }]"
        :validate-trigger="['input']"
        hide-label
      >
        <a-input
          v-model:model-value="loginForm.email"
          allow-clear
          size="large"
          placeholder="登录账号"
          :input-attrs="{
            id: 'login-email',
            name: 'email',
            autocomplete: 'email',
            'aria-label': '登录账号',
          }"
          @clear="handleClearAccount"
        >
          <template #prefix>
            <icon-user />
          </template>
        </a-input>
      </a-form-item>
      <a-form-item
        field="password"
        :validate-trigger="['input']"
        hide-label
        :rules="[{ required: true, message: '账号密码不能为空' }]"
      >
        <a-input-password
          v-model:model-value="loginForm.password"
          size="large"
          placeholder="账号密码"
          :input-attrs="{
            id: 'login-password',
            name: 'password',
            autocomplete: 'current-password',
            'aria-label': '账号密码',
          }"
        >
          <template #prefix>
            <icon-lock />
          </template>
        </a-input-password>
      </a-form-item>
      <a-space :size="16" direction="vertical">
        <div class="flex justify-between">
          <a-checkbox id="login-remember">记住密码</a-checkbox>
          <a-link @click="forgetPassword">忘记密码</a-link>
        </div>
        <a-button :loading="passwordLoading" size="large" type="primary" html-type="submit" long>
          登录
        </a-button>
        <a-divider>第三方授权</a-divider>
        <a-button @click="githubLogin" :loading="githubLoading" size="large" type="dashed" long>
          <template #icon>
            <icon-github />
            Github
          </template>
          Github
        </a-button>
      </a-space>
    </a-form>
  </div>
</template>

<style scoped>
/* 粒子文字：去掉组件默认的最小高度，贴合 96px 高的标题区 */
:deep(.login-form-title.particle-text) {
  min-height: 0;
  height: 96px;
}
</style>
