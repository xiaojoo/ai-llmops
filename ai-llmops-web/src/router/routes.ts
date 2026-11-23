import type { RouteRecordRaw } from 'vue-router'
import BlankLayout from '@/views/layouts/BlankLayout.vue'
import DefaultLayout from '@/views/layouts/DefaultLayout.vue'

export enum RouteNames {
  AUTH_LOGIN = 'auth-login',
  PAGES_HOME = 'pages-home',
  SPACE_APPS_LIST = 'space-apps-list',
  SPACE_APPS_DETAIL = 'space-apps-detail',
  SPACE_APPS_DETAIL_PUBLISHED = 'space-apps-published',
  SPACE_APPS_DETAIL_ANALYSIS = 'space-apps-analysis',
  SPACE_TOOLS_LIST = 'space-tools-list',
  STORE_APPS_LIST = 'store-apps-list',
  STORE_TOOLS_LIST = 'store-tools-list',
  SPACE_SKILLS_LIST = 'store-skills-list',
  SPACE_LAYOUT_VIEW = 'space-layout-view',
  SPACE_WORKFLOWS_LIST = 'space-workflows-list',
  SPACE_DATASETS_LIST = 'space-datasets-list',
  SPACE_DATASETS_DOCUMENTS_LIST = 'space-datasets-documents-list',
  SPACE_DATASETS_DOCUMENTS_CREATE = 'space-datasets-documents-create',
  SPACE_DATASETS_DOCUMENTS_SEGMENTS = 'space-datasets-documents-segments',
  SPACE_WORKFLOWS_DETAIL = 'space-workflows-detail',
  SPACE_SKILLS_DETAIL = 'space-skills-detail',
  SPACE_APPS_LAYOUT = 'space-apps-layout',
  AUTH_AUTHORIZE = 'auth-authorize',
  SYSTEM_SETTINGS = 'system-settings',
  CHROMA = 'chroma',
  WEAVIATE = 'weaviate',
  OPEN_API = 'open-api',
  OPEN_API_INDEX = 'open-api-index',
  OPEN_API_KEYS_LIST = 'open-api-keys-list',
  WEB_APPS = 'web-apps-index',
  NOT_FOUND = 'not-found',
}

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    component: DefaultLayout,
    children: [
      {
        path: '',
        redirect: { name: RouteNames.PAGES_HOME },
      },
      {
        path: 'home',
        name: RouteNames.PAGES_HOME,
        component: () => import('@/views/pages/HomeView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: '首页',
        },
      },
      {
        path: '/space/datasets/:dataset_id/documents/:document_id/segments',
        name: RouteNames.SPACE_DATASETS_DOCUMENTS_SEGMENTS,
        component: () => import('@/views/space/datasets/documents/segments/ListView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: '文档片段',
        },
      },
      {
        path: 'space/datasets/:dataset_id/documents/create',
        name: RouteNames.SPACE_DATASETS_DOCUMENTS_CREATE,
        component: () => import('@/views/space/datasets/documents/CreateView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: '新增文档',
        },
      },
      {
        path: 'space/datasets/:dataset_id/documents',
        name: RouteNames.SPACE_DATASETS_DOCUMENTS_LIST,
        component: () => import('@/views/space/datasets/documents/ListView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: '文档列表',
        },
      },
      {
        path: 'space',
        name: RouteNames.SPACE_LAYOUT_VIEW,
        component: () => import('@/views/space/SpaceLayoutView.vue'),
        children: [
          {
            path: 'apps',
            name: RouteNames.SPACE_APPS_LIST,
            component: () => import('@/views/space/apps/ListView.vue'),
            meta: {
              requiresAuth: true, // 需要登录
              title: '应用列表',
            },
          },
          {
            path: 'tools',
            name: RouteNames.SPACE_TOOLS_LIST,
            component: () => import('@/views/space/tools/ListView.vue'),
            meta: {
              requiresAuth: true,
              title: '自定义API插件',
            },
          },
          {
            path: 'workflows',
            name: RouteNames.SPACE_WORKFLOWS_LIST,
            component: () => import('@/views/space/workflows/ListView.vue'),
            meta: {
              requiresAuth: true,
              title: '工作流列表',
            },
          },
          {
            path: 'datasets',
            name: RouteNames.SPACE_DATASETS_LIST,
            component: () => import('@/views/space/datasets/ListView.vue'),
            meta: {
              requiresAuth: true,
              title: '知识库',
            },
          },
          {
            path: 'skills',
            name: RouteNames.SPACE_SKILLS_LIST,
            component: () => import('@/views/space/skills/ListView.vue'),
            meta: {
              requiresAuth: true,
              title: 'SKILLS',
            },
          },
        ],
      },
      {
        path: 'store/apps',
        name: RouteNames.STORE_APPS_LIST,
        component: () => import('@/views/store/apps/ListView.vue'),
        meta: {
          requiresAuth: true,
          title: '应用广场',
        },
      },
      {
        path: 'store/tools',
        name: RouteNames.STORE_TOOLS_LIST,
        component: () => import('@/views/store/tools/ListView.vue'),
        meta: {
          requiresAuth: true,
          title: '内置插件',
        },
      },
      {
        path: 'openapi',
        name: RouteNames.OPEN_API,
        component: () => import('@/views/openapi/OpenAPILayoutView.vue'),
        redirect: { name: RouteNames.OPEN_API_INDEX },
        meta: {
          requiresAuth: true,
          title: '开放API',
        },
        children: [
          {
            path: 'openapi-index',
            name: RouteNames.OPEN_API_INDEX,
            component: () => import('@/views/openapi/indexView.vue'),
            meta: {
              requiresAuth: true,
              title: '快速开始',
            },
          },
          {
            path: 'api-keys',
            name: RouteNames.OPEN_API_KEYS_LIST,
            component: () => import('@/views/openapi/api-keys/ListView.vue'),
            meta: {
              requiresAuth: true,
              title: '秘钥',
            },
          },
        ],
      },
      {
        path: 'settings',
        name: RouteNames.SYSTEM_SETTINGS,
        component: () => import('@/views/settings/SystemSettings.vue'),
        meta: {
          requiresAuth: true,
          title: '系统设置',
        },
      },
      {
        path: 'chroma',
        name: RouteNames.CHROMA,
        component: () => import('@/views/chroma/ListView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Chroma',
        },
      },
      {
        path: 'weaviate',
        name: RouteNames.WEAVIATE,
        component: () => import('@/views/weaviate/ListView.vue'),
        meta: {
          requiresAuth: true,
          title: 'Weaviate',
        },
      },
    ],
  },
  {
    path: '/',
    component: BlankLayout,
    children: [
      {
        path: '/auth/login',
        name: RouteNames.AUTH_LOGIN,
        component: () => import('@/views/auth/LoginView.vue'),
        meta: {
          requiresAuth: false, // 不需要登录
          guestOnly: true, // 仅限未登录用户访问
          title: '登录',
        },
      },
      {
        path: '/auth/authorize/:provider_name',
        name: RouteNames.AUTH_AUTHORIZE,
        component: () => import('@/views/auth/AuthorizeView.vue'),
        meta: {
          requiresAuth: false, // 不需要登录
          guestOnly: true, // 仅限未登录用户访问
          title: '登录跳转',
        },
      },
      {
        path: 'space/apps',
        name: RouteNames.SPACE_APPS_LAYOUT,
        component: () => import('@/views/space/apps/AppLayoutView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: '应用详情',
        },
        children: [
          {
            path: ':app_id',
            name: RouteNames.SPACE_APPS_DETAIL,
            component: () => import('@/views/space/apps/DetailView.vue'),
            meta: {
              requiresAuth: true, // 需要登录
              title: '应用编排',
            },
            props: true,
          },
          {
            path: ':app_id/published',
            name: RouteNames.SPACE_APPS_DETAIL_PUBLISHED,
            component: () => import('@/views/space/apps/PublishedView.vue'),
            meta: {
              requiresAuth: true, // 需要登录
              title: '应用发布',
            },
          },
          {
            path: ':app_id/analysis',
            name: RouteNames.SPACE_APPS_DETAIL_ANALYSIS,
            component: () => import('@/views/space/apps/AnalysisView.vue'),
            meta: {
              requiresAuth: true, // 需要登录
              title: '统计分析',
            },
          },
        ],
      },
      {
        path: 'space/workflows/:workflow_id',
        name: RouteNames.SPACE_WORKFLOWS_DETAIL,
        component: () => import('@/views/space/workflows/DetailView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: '工作流',
        },
      },
      {
        path: 'web-apps',
        name: RouteNames.WEB_APPS + '-index',
        component: () => import('@/views/web-apps/IndexView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: 'WabApp',
        },
      },
      {
        // 尾部斜杠兼容：/web-apps/ 与 /web-apps 等价（不报 404）
        path: 'web-apps/',
        component: () => import('@/views/web-apps/IndexView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: 'WabApp',
        },
      },
      {
        path: 'web-apps/:token',
        name: RouteNames.WEB_APPS,
        component: () => import('@/views/web-apps/IndexView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: 'WabApp',
        },
      },
      {
        path: 'space/skills/:skill_id',
        name: RouteNames.SPACE_SKILLS_DETAIL,
        component: () => import('@/views/space/skills/skillDetail/ListView.vue'),
        meta: {
          requiresAuth: true, // 需要登录
          title: 'Skill详情',
        },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: RouteNames.NOT_FOUND,
    component: () => import('@/views/errors/NotFound.vue'),
    meta: {
      requiresAuth: false, // 404页面不需要登录
      title: '页面未找到',
    },
  },
]
