import storage from '@/utils/storage'

interface Credential {
  access_token: string
  expire_at: number
}

export default {
  isLogin: (): boolean => {
// 从LocalStorage中查找授权凭证信息
    const credential = storage.get<Credential>('credential')

// 判断授权凭证上是否存在access_token，并判断token是否过期
    const now = Math.floor(Date.now() / 1000)
    if (
      !credential ||
      !credential.access_token ||
      !credential.expire_at ||
      credential.expire_at < now
    ) {
// 账号未登录，直接移除LocalStorage中的数据，涵盖用户数据+授权凭证
      storage.clear()
      return false
    }
    return true
  },
}
