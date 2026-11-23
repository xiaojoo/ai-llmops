// 本地加密存储工具（Web Crypto API AES-GCM）
// 用于加密保存敏感配置（如 OCR API Key），避免明文写入 localStorage。
// 加密密钥（AES-GCM 256bit）持久化在独立键中；密文 = base64(iv + ciphertext)。

const ENC_KEY_STORAGE = 'llmops_enc_key_v1'

// 生成随机 256bit AES 密钥并持久化（仅在首次调用时生成）
let cachedKey: CryptoKey | null = null

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i] ?? 0)
  }
  return btoa(binary)
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

async function getOrCreateKey(): Promise<CryptoKey> {
  if (cachedKey) return cachedKey
  const saved = localStorage.getItem(ENC_KEY_STORAGE)
  if (saved) {
    const raw = base64ToBytes(saved).buffer as ArrayBuffer
    cachedKey = await crypto.subtle.importKey(
      'raw',
      raw,
      { name: 'AES-GCM' },
      false,
      ['encrypt', 'decrypt'],
    )
    return cachedKey
  }
  // 首次：生成密钥并持久化
  const key = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 },
    true,
    ['encrypt', 'decrypt'],
  )
  const raw = await crypto.subtle.exportKey('raw', key)
  localStorage.setItem(ENC_KEY_STORAGE, bytesToBase64(new Uint8Array(raw)))
  cachedKey = key
  return key
}

// 加密字符串，返回 base64(iv + ciphertext)
export async function encryptText(plain: string): Promise<string> {
  const key = await getOrCreateKey()
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const data = new TextEncoder().encode(plain)
  const cipher = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv },
    key,
    data,
  )
  const combined = new Uint8Array(iv.length + cipher.byteLength)
  combined.set(iv, 0)
  combined.set(new Uint8Array(cipher), iv.length)
  return bytesToBase64(combined)
}

// 解密 base64(iv + ciphertext)，失败返回原值（兼容历史明文数据）
export async function decryptText(encoded: string): Promise<string> {
  try {
    const key = await getOrCreateKey()
    const combined = base64ToBytes(encoded)
    const iv = combined.slice(0, 12).buffer as ArrayBuffer
    const cipher = combined.slice(12).buffer as ArrayBuffer
    const plain = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      key,
      cipher,
    )
    return new TextDecoder().decode(plain)
  } catch {
    return encoded
  }
}
