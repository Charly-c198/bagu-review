<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAppStore } from '../stores/app'

const store = useAppStore()
const route = useRoute()
const router = useRouter()

const todayTag = computed(() => {
  const date = new Date()
  return `${date.getMonth() + 1}月${date.getDate()}日 周${'日一二三四五六'[date.getDay()]}`
})

const selectedBoard = computed({
  get: () => store.boardId,
  set: (value: number) => {
    store.setBoard(value)
  },
})

async function logout(): Promise<void> {
  await store.logout()
  router.replace('/login')
}
</script>

<template>
  <div class="topbar">
    <button class="btn ghost sm menu-btn" @click="store.sidebarOpen = !store.sidebarOpen">菜单</button>
    <div>
      <h1>{{ route.meta.title }}</h1>
      <div class="crumb">{{ route.meta.crumb }}</div>
    </div>
    <div class="topbar-sp"></div>
    <select v-model.number="selectedBoard" class="board-switch" aria-label="切换岗位板块">
      <option :value="0">全部题目</option>
      <option v-for="board in store.boards" :key="board.id" :value="board.id">{{ board.name }}</option>
    </select>
    <span class="tag teal">{{ todayTag }}</span>
    <button class="btn ghost sm" title="退出登录" @click="logout">退出</button>
  </div>
</template>
