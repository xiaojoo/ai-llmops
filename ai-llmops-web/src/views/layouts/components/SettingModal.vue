<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { useAccountStore } from '@/stores/account'
import {
  getCurrentUser,
  updateAvatar,
  updateNameService,
  updatePasswordService,
} from '@/services/account'
import { uploadImage } from '@/services/upload-file'
import { Message, type FileItem, type RequestOption, type UploadRequest } from '@arco-design/web-vue'

const visible = defineModel<boolean>('visible', { required: true })

const accountStore = useAccountStore()

const updateName = ref(false)
const updatePassword = ref(false)
const loading = ref(false)

const accountForm = reactive({
  fileList: [] as FileItem[],
  name: '',
  avatar: '',
  password: '',
  email: '',
})

const updateAccount = async () => {
  const resp = await getCurrentUser()
  accountStore.update(resp.data)
}

watch(visible, (isOpen) => {
  if (isOpen) {
    updateName.value = false
    updatePassword.value = false

    // 初始化表单数据
    Object.assign(accountForm, {
      fileList: [{ uid: '-1', name: '当前头像', url: accountStore.account.avatar }],
      name: accountStore.account.name,
      avatar: accountStore.account.avatar,
      password: '',
      email: accountStore.account.email,
    })
  }
})

const handleSaveUpdateName = async () => {
  if (!accountForm.name) return Message.warning('昵称不能为空')

  try {
    const resp = await updateNameService(accountForm.name)
    Message.success(resp.message)
    accountStore.account.name = accountForm.name
    updateName.value = false

    await updateAccount()
  } catch (error) {
    console.error(error)
  }
}

const handleSaveUpdatePassword = async () => {
  if (!accountForm.password) return Message.warning('密码不能为空')

  try {
    const resp = await updatePasswordService(accountForm.password)
    Message.success(resp.message)

    accountForm.password = ''
    updatePassword.value = false
  } catch (error) {
    console.error(error)
  }
}

const handleCancelUpdateName = () => {
  updateName.value = false
  accountForm.name = accountStore.account.name
}

// a-upload 的 custom-request 需同步返回 UploadRequest（{ abort }），异步逻辑在内部任务中执行
const handleAvatarUpload = (option: RequestOption): UploadRequest => {
  const { fileItem, onSuccess, onError } = option

  const uploadTask = async () => {
    try {
      const uploadResp = await uploadImage(fileItem.file as File)
      accountForm.avatar = uploadResp.data.image_url

      onSuccess(uploadResp)

      const updateResp = await updateAvatar(accountForm.avatar)
      Message.success(updateResp.message)

      accountStore.account.avatar = accountForm.avatar

      await updateAccount()
    } catch (err) {
      onError?.(err)
      Message.error('头像上传失败')
    }
  }
  uploadTask()

  return { abort: () => {} }
}
</script>

<template>
  <a-modal
    v-model:visible="visible"
    title="设置"
    :footer="false"
    :width="'clamp(200px, 80vw, 800px)'"
    :mask-closable="!loading"
    :closable="true"
    @cancel="visible = false"
  >
    <div class="flex min-h-[500px]">
      <!-- 左侧导航（视口缩小到 md 以下时隐藏，避免挤压右侧内容） -->
      <div class="w-[200px] border-r border-gray-100 pr-5 pt-4 hidden md:block">
        <div class="flex flex-col gap-2">
          <div class="bg-blue-50 text-blue-600 rounded-md h-9 leading-9 px-4 font-medium text-sm">
            账号设置
          </div>
        </div>
      </div>

      <!-- 右侧内容 -->
      <div class="flex-1 px-8 pt-4">
        <h3 class="text-lg font-bold text-gray-800 mb-6">账号设置</h3>

        <a-form
          :model="accountForm"
          layout="horizontal"
          label-align="left"
          auto-label-width
          class="max-w-[520px]"
        >
          <!-- 头像 -->
          <a-form-item field="avatar">
            <template #label>
              <span class="flex items-center gap-1">账号头像</span>
            </template>
            <a-upload
              v-model:file-list="accountForm.fileList"
              list-type="picture-card"
              :limit="1"
              image-preview
              :custom-request="handleAvatarUpload"
              :show-remove-button="true"
            />
          </a-form-item>

          <!-- 昵称 -->
          <a-form-item field="name" :label-attrs="{ for: 'setting-name' }">
            <template #label>
              <span class="flex items-center gap-1">账号昵称</span>
            </template>

            <!-- 编辑模式：始终渲染输入框（v-show），保证 <label for="setting-name"> 始终有关联控件 -->
            <div v-show="updateName" class="flex items-center gap-2 w-full animate-fade">
              <a-input
                v-model="accountForm.name"
                placeholder="请输入账号名称"
                allow-clear
                :input-attrs="{ id: 'setting-name', name: 'nickname', autocomplete: 'off' }"
                @press-enter="handleSaveUpdateName"
              />
              <div class="flex items-center gap-2 shrink-0">
                <a-button @click="handleCancelUpdateName">取消</a-button>
                <a-button type="primary" @click="handleSaveUpdateName">保存</a-button>
              </div>
            </div>

            <div
              v-show="!updateName"
              class="flex items-center justify-between w-full h-[32px] group"
            >
              <span class="text-gray-900 text-base font-medium">{{
                accountStore.account.name
              }}</span>
              <a-button
                size="mini"
                type="text"
                class="!text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity"
                @click="updateName = true"
              >
                <template #icon><icon-edit /></template> 修改
              </a-button>
            </div>
          </a-form-item>

          <!-- 密码 -->
          <a-form-item
            field="password"
            label="登录密码"
            :label-attrs="{ for: 'setting-password' }"
          >
            <!-- 编辑模式：始终渲染输入框（v-show），保证 <label for="setting-password"> 始终有关联控件 -->
            <div v-show="updatePassword" class="flex items-center gap-2 w-full animate-fade">
              <a-input-password
                v-model="accountForm.password"
                placeholder="请输入新密码"
                :input-attrs="{
                  id: 'setting-password',
                  name: 'new-password',
                  autocomplete: 'new-password',
                }"
                @press-enter="handleSaveUpdatePassword"
              />
              <div class="flex items-center gap-2 shrink-0">
                <a-button
                  @click="
                    () => {
                      updatePassword = false
                      accountForm.password = ''
                    }
                  "
                >
                  取消
                </a-button>
                <a-button type="primary" @click="handleSaveUpdatePassword">保存</a-button>
              </div>
            </div>

            <div
              v-show="!updatePassword"
              class="flex items-center justify-between w-full h-[32px] group"
            >
              <span class="text-gray-400 tracking-widest">●●●●●●</span>
              <a-button
                size="mini"
                type="text"
                class="!text-blue-600 opacity-0 group-hover:opacity-100 transition-opacity"
                @click="updatePassword = true"
              >
                <template #icon><icon-edit /></template>修改
              </a-button>
            </div>
          </a-form-item>

          <a-form-item field="email" label="绑定邮箱" :label-attrs="{ for: 'setting-email' }">
            <a-input
              :model-value="accountStore.account.email"
              readonly
              :input-attrs="{ id: 'setting-email' }"
              class="!bg-gray-50 text-gray-500 cursor-not-allowed pr-0 pl-0"
            />
          </a-form-item>
        </a-form>
      </div>
    </div>
  </a-modal>
</template>

<style scoped>
.animate-fade {
  animation: fadeIn 0.2s ease-out;
}
@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(-2px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
