import { createRouter, createWebHashHistory } from 'vue-router'

import { useAppStore } from '../stores/app'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    crumb?: string
    public?: boolean
    icon?: string
    badge?: 'review' | 'pending'
    section?: string
  }
}

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
      meta: { title: '登录', crumb: '本地单用户', public: true },
    },
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('../views/DashboardView.vue'),
      meta: { title: '仪表盘', crumb: '今日学习概览', section: '学习' },
    },
    {
      path: '/practice',
      name: 'practice',
      component: () => import('../views/PracticeView.vue'),
      meta: { title: '主动刷题', crumb: '筛选题目 · 自测 · 三档自评', section: '学习' },
    },
    {
      path: '/review',
      name: 'review',
      component: () => import('../views/ReviewView.vue'),
      meta: { title: '今日复习', crumb: 'SM-2 到期队列', section: '学习', badge: 'review' },
    },
    {
      path: '/mistakes',
      name: 'mistakes',
      component: () => import('../views/MistakesView.vue'),
      meta: { title: '错题本', crumb: '自评不熟自动收录', section: '学习' },
    },
    {
      path: '/bookmarks',
      name: 'bookmarks',
      component: () => import('../views/BookmarksView.vue'),
      meta: { title: '收藏夹', crumb: '重点题目随时回看', section: '学习' },
    },
    {
      path: '/sprint',
      name: 'sprint',
      component: () => import('../views/SprintView.vue'),
      meta: { title: '考前冲刺', crumb: '忽略到期日期 · 按频率抽题', section: '学习' },
    },
    {
      path: '/interview',
      name: 'interview',
      component: () => import('../views/InterviewView.vue'),
      meta: { title: '仿真面试', crumb: '随机组卷 · 文字作答 · 复盘报告', section: '学习' },
    },
    {
      path: '/library',
      name: 'library',
      component: () => import('../views/LibraryView.vue'),
      meta: { title: '题库管理', crumb: '结构化题目 · 组合筛选', section: '题库来源' },
    },
    {
      path: '/knowledge',
      name: 'knowledge',
      component: () => import('../views/KnowledgeView.vue'),
      meta: { title: '知识库', crumb: '独立知识条目 · 题-知识关联', section: '题库来源' },
    },
    {
      path: '/import',
      name: 'import',
      component: () => import('../views/ImportView.vue'),
      meta: { title: '本地导入', crumb: 'Markdown / CSV / JSON', section: '题库来源' },
    },
    {
      path: '/crawl',
      name: 'crawl',
      component: () => import('../views/CrawlView.vue'),
      meta: { title: '采集任务', crumb: 'GitHub Markdown · 逐文件状态', section: '题库来源' },
    },
    {
      path: '/pending',
      name: 'pending',
      component: () => import('../views/PendingView.vue'),
      meta: { title: '采集待审', crumb: '导入与爬虫统一审核入口', section: '题库来源', badge: 'pending' },
    },
    {
      path: '/stats',
      name: 'stats',
      component: () => import('../views/StatsView.vue'),
      meta: { title: '统计复盘', crumb: '掌握度与趋势', section: '分析与设置' },
    },
    {
      path: '/graph',
      name: 'graph',
      component: () => import('../views/GraphView.vue'),
      meta: { title: '知识图谱', crumb: '题-知识关联网络', section: '分析与设置' },
    },
    {
      path: '/weekly',
      name: 'weekly',
      component: () => import('../views/WeeklyView.vue'),
      meta: { title: '周学习报告', crumb: '薄弱点 · 下周计划', section: '分析与设置' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
      meta: { title: '设置', crumb: 'SM-2 参数与偏好', section: '分析与设置' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach(async (to) => {
  const store = useAppStore()
  if (to.meta.public) {
    if (store.token && to.path === '/login') return { path: '/dashboard' }
    return true
  }
  if (!store.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!store.user) {
    try {
      await store.fetchMe()
    } catch {
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  if (!store.tree.length) {
    try {
      await store.fetchTree()
      await store.loadBadges()
    } catch {
      // 页面自身会处理错误
    }
  }
  return true
})

router.afterEach(() => {
  const store = useAppStore()
  store.sidebarOpen = false
})

export default router
