import { defineStore } from 'pinia'
import { ref } from 'vue'
import storage from '@/utils/storage.ts'

// 初始值
const initAccount = {
  name: '',
  email: '',
  avatar: '',
  last_login_ip: '',
  last_login_at: 0,
  created_at: 0,
}

interface UpdateParams {
  name?: string
  email?: string
  avatar?: string
  last_login_ip?: string
  last_login_at?: number
  created_at?: number
}

export const useAccountStore = defineStore('account', () => {
  // 定义数据源
  const account = ref(storage.get('account', initAccount))

  const update = (params: UpdateParams) => {
    // 同步合并进响应式状态，保证登录/拉取用户信息后界面立即刷新（此前只写 localStorage，刷新才生效）
    account.value = { ...account.value, ...params }
    storage.set('account', account.value)
  }

  const clear = () => {
    account.value = initAccount
    storage.remove('account')
  }

  return {
    account,
    update,
    clear,
  }
})
