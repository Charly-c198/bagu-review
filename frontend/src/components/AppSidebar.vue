<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAppStore } from '../stores/app'

const store = useAppStore()
const route = useRoute()
const router = useRouter()

interface NavItem {
  id: string
  name: string
  icon: string
  badge?: 'review' | 'pending'
}

const navSections = computed(() => [
  {
    section: '学习',
    items: [
      { id: 'dashboard', name: '仪表盘', icon: 'M4 13h6V4H4v9zm10 7h6v-9h-6v9zM4 20h6v-5H4v5zm10-16v5h6V4h-6z' },
      { id: 'practice', name: '主动刷题', icon: 'M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5L12 3z' },
      { id: 'review', name: '今日复习', icon: 'M12 8v5l3 2M12 21a9 9 0 100-18 9 9 0 000 18z', badge: 'review' },
      { id: 'mistakes', name: '错题本', icon: 'M12 9v4m0 4h.01M10.3 3.9L2.6 17a2 2 0 001.7 3h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z' },
      { id: 'bookmarks', name: '收藏夹', icon: 'M6 4h12v17l-6-4-6 4V4z' },
      { id: 'sprint', name: '考前冲刺', icon: 'M13 2L4 14h6l-1 8 9-12h-6l1-8z' },
    ] as NavItem[],
  },
  {
    section: '题库来源',
    items: [
      { id: 'library', name: '题库管理', icon: 'M4 4h16v16H4zM8 8h8M8 12h8M8 16h5' },
      { id: 'knowledge', name: '知识库', icon: 'M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3V4zM8 8h8M8 12h8M8 16h5' },
      { id: 'import', name: '本地导入', icon: 'M12 16V4m0 0l-4 4m4-4l4 4M4 20h16' },
      { id: 'crawl', name: '采集任务', icon: 'M4 6h16M4 12h16M4 18h10' },
      { id: 'pending', name: '采集待审', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 012-2h2a2 2 0 012 2M9 5h6', badge: 'pending' },
    ] as NavItem[],
  },
  {
    section: '分析与设置',
    items: [
      { id: 'stats', name: '统计复盘', icon: 'M4 20V10M10 20V4M16 20v-7M22 20H2' },
      { id: 'graph', name: '知识图谱', icon: 'M12 4a2 2 0 100 4 2 2 0 000-4zM5 16a2 2 0 100 4 2 2 0 000-4zM19 16a2 2 0 100 4 2 2 0 000-4zM12 8v4M10 12L6.5 15.5M14 12l3.5 3.5' },
      { id: 'settings', name: '设置', icon: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.2a1.7 1.7 0 00-1-1.5 1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.2a1.7 1.7 0 001.5-1 1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3h0a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.2a1.7 1.7 0 001 1.5 1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9v0a1.7 1.7 0 001.5 1h.2a2 2 0 110 4h-.2a1.7 1.7 0 00-1.5 1z' },
    ] as NavItem[],
  },
])

function badgeCount(badge?: 'review' | 'pending'): number {
  if (badge === 'review') return store.dueCount
  if (badge === 'pending') return store.pendingCount
  return 0
}

function go(id: string): void {
  if (route.path !== `/${id}`) router.push(`/${id}`)
  store.sidebarOpen = false
}
</script>

<template>
  <aside class="sidebar" :class="{ open: store.sidebarOpen }">
    <div class="brand">
      <div class="brand-mark">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none">
          <path d="M5 7h14M5 12h14M5 17h9" stroke="#fff" stroke-width="2.2" stroke-linecap="round" />
        </svg>
      </div>
      <div>
        <div class="brand-name">八股文复习系统</div>
        <div class="brand-sub">本地优先 · v1.0</div>
      </div>
    </div>
    <nav class="nav">
      <template v-for="group in navSections" :key="group.section">
        <div class="nav-section">{{ group.section }}</div>
        <div
          v-for="item in group.items"
          :key="item.id"
          class="nav-item"
          :class="{ active: route.path === `/${item.id}` }"
          @click="go(item.id)"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path :d="item.icon" />
          </svg>
          {{ item.name }}
          <span v-if="badgeCount(item.badge) > 0" class="nav-badge">{{ badgeCount(item.badge) }}</span>
        </div>
      </template>
    </nav>
    <div class="side-foot">本地优先 · 无 AI 可用 · SM-2</div>
  </aside>
</template>
