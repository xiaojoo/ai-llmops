import type { RouteLocationNormalized, Router } from 'vue-router'
import { createRouter, createWebHistory } from 'vue-router'
import { RouteNames, routes } from './routes'
import auth from '@/utils/auth.ts'

const router: Router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    } else {
      return { top: 0 }
    }
  },
})

router.beforeEach(async (to: RouteLocationNormalized, from: RouteLocationNormalized) => {
  void from
  const isAuthenticated: boolean = auth.isLogin()

  // 需要认证但未登录
  if (to.meta.requiresAuth && !isAuthenticated) {
    return {
      name: RouteNames.AUTH_LOGIN,
      query: { redirect: to.fullPath },
    }
  }

  // 已登录但访问访客专用页面
  if (to.meta.guestOnly && isAuthenticated) {
    return { name: RouteNames.PAGES_HOME }
  }

  // 设置页面标题
  if (to.meta.title) {
    document.title = `${to.meta.title}-llmops`
  }

  // 开发环境日志
  // if (import.meta.env.DEV) {
  //   console.log('路由跳转:', {
  //     from: from.name?.toString(),
  //     to: to.name?.toString(),
  //   })
  // }
})

export default router
