import storage from '@/utils/storage'

interface Credential {
  access_token: string
  expire_at: number
}

const initCredential: Credential = {
  access_token: '',
  expire_at: 0,
}

export function getAccessToken(): string {
  const credential = storage.get('credential', initCredential)
  return credential?.access_token || ''
}
