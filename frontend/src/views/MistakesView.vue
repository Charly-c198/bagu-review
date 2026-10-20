<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, withQuery } from '../api/client'
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
    const data = await api.get<{ items: Question[]; total: number }>(
      withQuery('/mistakes', { category_id: store.boardParam }),
    )
    items.value = data.items
  } catch (err: any) {
    store.toast(err?.message || '错题本加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function remove(question: Question): Promise<void> {
  if (!window.confirm('确定移出错题本？移出后会保留流水记录。')) return
  try {
    await api.post(`/mistakes/${question.id}/remove`)
    store.toast('已移出错题本', 'success')
    await load()
    await store.loadBadges()
  } catch (err: any) {
    store.toast(err?.message || '操作失败', 'error')
  }
}

function retry(question: Question): void {
  router.push({ path: '/practice', query: { q: question.stem, only_mistakes: '1' } })
}

async function exportMarkdown(): Promise<void> {
  try {
    await api.download(
      withQuery('/mistakes/export', { category_id: store.boardParam }),
    )
    store.toast('错题本已导出', 'success')
  } catch (err: any) {
    store.toast(err?.message || '导出失败', 'error')
  }
}

onMounted(load)
watch(() => store.boardId, load)
</script>

<template>
  <div>
    <div class="toolbar">
      <span class="tag orange">不熟自动收录</span>
      <div style="flex: 1"></div>
      <button class="btn ghost sm" @click="load">刷新</button>
      <button class="btn ghost sm" :disabled="!items.length" @click="exportMarkdown">导出 Markdown</button>
      <button class="btn" @click="router.push({ path: '/practice', query: { only_mistakes: '1' } })">
        开始错题重练
      </button>
    </div>

    <div class="section-title">{{ store.boardName }} · 错题本（{{ items.length }}）</div>
    <div v-if="loading" class="card empty">加载中…</div>
    <div v-else class="card" style="padding: 6px 16px">
      <template v-if="items.length">
        <div v-for="question in items" :key="question.id" class="list-row">
          <div class="list-main">
            <div class="list-title">{{ question.stem }}</div>
            <div class="list-sub">
              {{ question.category_path || '未分类' }} · 收录于
              {{ formatDate(String(question.added_at || '')) }}
            </div>
          </div>
          <span class="tag" :class="masteryTone(question.mastery)">{{ masteryText(question.mastery) }}</span>
          <button class="btn ghost sm" @click="retry(question)">重练</button>
          <button class="btn danger-ghost sm" @click="remove(question)">移出</button>
        </div>
      </template>
      <div v-else class="empty">错题本已清空，继续保持</div>
    </div>
  </div>
</template>
