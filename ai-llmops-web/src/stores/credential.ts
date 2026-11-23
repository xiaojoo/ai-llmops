import { defineStore } from 'pinia'
import { ref } from 'vue'
import storage from '@/utils/storage.ts'

// 定义基础授权凭证信息
const initCredential = {
  access_token: '',
  expire_at: 0,
}

interface UpdateParams {
  access_token: string
  expire_at: number
}

export const useCredentialStore = defineStore('credential', () => {
  const credential = ref(storage.get('credential', initCredential))

  const update = (params: UpdateParams) => {
    credential.value = params
    storage.set('credential', params)
  }

  const clear = () => {
    credential.value = initCredential
    storage.remove('credential')
  }

  return {
    credential,
    update,
    clear,
  }
})
