<script setup lang="ts">
import { useCredentialStore } from '@/stores/credential.ts'
import { useRoute, useRouter } from 'vue-router'
import { authorize } from '@/services/oauth.ts'
import { onMounted } from 'vue'
import { Message } from '@arco-design/web-vue'
import { showErrorToast } from '@/utils/http/error'

const route = useRoute()
const router = useRouter()
const credentialStore = useCredentialStore()

onMounted(async () => {
  try {
    const resp = await authorize(route.params?.provider_name as string, route.query?.code as string)

    credentialStore.update(resp.data)
    // 回到发起登录的原页面（登录页暂存在 sessionStorage；仅站内路径）
    const saved = sessionStorage.getItem('llmops-oauth-redirect')
    sessionStorage.removeItem('llmops-oauth-redirect')
    const redirect = saved && saved.startsWith('/') && !saved.startsWith('//') ? saved : '/home'
    await router.replace(redirect)
    Message.success('登录成功，欢迎回来')
  } catch (error: unknown) {
    // 请求层 globalErrorHandler 已弹过该错误，这里走同文案去重，避免“服务器错误”弹两次
    showErrorToast(error instanceof Error ? error.message : String(error))
    await router.replace({ path: '/auth/login' })
  }
})
</script>

<template>
  <div class="w-full min-h-screen flex items-center justify-center bg-white">
    <a-spin tip="第三方授权登录中..."></a-spin>
  </div>
</template>

<style scoped></style>
