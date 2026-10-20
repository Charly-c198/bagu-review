<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../api/client'
import type { Question } from '../api/types'
import { useAppStore } from '../stores/app'
import { formatDate, masteryText, masteryTone } from '../utils/labels'

const store = useAppStore()
const router = useRouter()

const items = ref<Question[]>([])
const loading = ref(true)

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<{ items: Question[]; total: number }>('/bookmarks')
    items.value = data.items
  } catch (err: any) {
    store.toast(err?.message || '收藏夹加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function remove(question: Question): Promise<void> {
  try {
    await api.delete(`/bookmarks/${question.id}`)
    store.toast('已取消收藏', 'success')
    await load()
  } catch (err: any) {
    store.toast(err?.message || '操作失败', 'error')
  }
}

function practice(question: Question): void {
  router.push({ path: '/practice', query: { q: question.stem } })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <span class="tag teal">重点题目</span>
      <div style="flex: 1"></div>
      <button class="btn ghost sm" @click="load">刷新</button>
      <button class="btn" @click="router.push('/practice')">去刷题</button>
    </div>

    <div class="section-title">收藏夹（{{ items.length }}）</div>
    <div v-if="loading" class="card empty">加载中…</div>
    <div v-else class="card" style="padding: 6px 16px">
      <template v-if="items.length">
        <div v-for="question in items" :key="question.id" class="list-row">
          <div class="list-main">
            <div class="list-title">{{ question.stem }}</div>
            <div class="list-sub">
              {{ question.category_path || '未分类' }} · 收藏于
              {{ formatDate(String(question.bookmarked_at || '')) }}
            </div>
          </div>
          <span class="tag" :class="masteryTone(question.mastery)">{{ masteryText(question.mastery) }}</span>
          <button class="btn ghost sm" @click="practice(question)">刷题</button>
          <button class="btn danger-ghost sm" @click="remove(question)">取消收藏</button>
        </div>
      </template>
      <div v-else class="empty">还没有收藏题目，去题库里挑几道重点题吧</div>
    </div>
  </div>
</template>
