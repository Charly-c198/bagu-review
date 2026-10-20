<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, withQuery } from '../api/client'
import type { DashboardStats, ReviewPayload } from '../api/types'
import LineChart from '../components/LineChart.vue'
import { useAppStore } from '../stores/app'
import { formatDate, masteryText, masteryTone, sourceText, sourceTone } from '../utils/labels'

const store = useAppStore()
const router = useRouter()

const stats = ref<DashboardStats | null>(null)
const review = ref<ReviewPayload | null>(null)
const loading = ref(true)

const dueItems = computed(() => review.value?.due || [])
const trendLabels = computed(() => (stats.value?.trend || []).map((point) => point.label))
const trendValues = computed(() => (stats.value?.trend || []).map((point) => point.reviews))

async function load(): Promise<void> {
  loading.value = true
  try {
    const params = { category_id: store.boardParam }
    const [statsData, reviewData] = await Promise.all([
      api.get<DashboardStats>(withQuery('/stats/dashboard', params)),
      api.get<ReviewPayload>(withQuery('/review/today', params)),
    ])
    stats.value = statsData
    review.value = reviewData
  } catch (err: any) {
    store.toast(err?.message || '仪表盘加载失败', 'error')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => store.boardId, load)
</script>

<template>
  <div>
    <div class="board-banner">
      <b>{{ store.boardName }}</b>
      <span>{{ store.boardDesc }}</span>
      <span class="tag gray" style="margin-left: auto">
        本板块 {{ stats?.total_questions ?? 0 }} 题
      </span>
    </div>

    <div v-if="loading" class="card empty">加载中…</div>
    <template v-else-if="stats">
      <div class="grid metrics metrics-6">
        <div class="metric accent card">
          <div class="m-label">今日到期</div>
          <div class="m-val num">{{ review?.counts.due_total ?? stats.due }}</div>
          <div class="m-sub">SM-2 待复习 · 积压 {{ review?.counts.backlog ?? 0 }}</div>
        </div>
        <div class="metric card">
          <div class="m-label">已学</div>
          <div class="m-val num">{{ stats.learned }}</div>
          <div class="m-sub">本板块共 {{ stats.total_questions }} 题</div>
        </div>
        <div class="metric card">
          <div class="m-label">已精通</div>
          <div class="m-val num">{{ stats.mastered }}</div>
          <div class="m-sub">最近一次评分 q=5</div>
        </div>
        <div class="metric card">
          <div class="m-label">错题</div>
          <div class="m-val num" style="color: var(--orange)">{{ stats.mistakes }}</div>
          <div class="m-sub">待重练</div>
        </div>
        <div class="metric card">
          <div class="m-label">连续打卡</div>
          <div class="m-val num">{{ stats.streak }}</div>
          <div class="m-sub">天 · 每日至少一条掌握记录</div>
        </div>
        <div class="metric card">
          <div class="m-label">知识条目</div>
          <div class="m-val num">{{ stats.knowledge_count }}</div>
          <div class="m-sub">可独立检索与关联</div>
        </div>
      </div>

      <div class="section-title">近 7 天复习量</div>
      <div class="card" style="padding: 16px">
        <LineChart :values="trendValues" :labels="trendLabels" />
      </div>

      <div class="section-title">
        今日到期队列（{{ dueItems.length }}）
        <span v-if="review && review.counts.new_total" class="tag blue">
          另有 {{ review.counts.new_total }} 道新题
        </span>
      </div>
      <div class="card" style="padding: 6px 16px">
        <template v-if="dueItems.length">
          <div v-for="question in dueItems" :key="question.id" class="list-row">
            <div class="list-main">
              <div class="list-title">{{ question.stem }}</div>
              <div class="list-sub">
                {{ question.category_path || '未分类' }} · 下次复习
                {{ formatDate(question.schedule.next_review_date) }}
              </div>
            </div>
            <span class="tag" :class="masteryTone(question.mastery)">{{ masteryText(question.mastery) }}</span>
            <span class="tag" :class="sourceTone(question.source_type)">{{ sourceText(question.source_type) }}</span>
            <button class="btn sm" @click="router.push('/review')">去复习</button>
          </div>
        </template>
        <div v-else class="empty">今日没有到期题，去主动刷题吧</div>
      </div>
    </template>
  </div>
</template>
