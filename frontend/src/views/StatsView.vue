<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { DashboardStats } from '../api/types'
import BarRows from '../components/BarRows.vue'
import LineChart from '../components/LineChart.vue'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const dashboard = ref<DashboardStats | null>(null)
const distribution = ref<Record<string, number>>({})
const unfamiliar = ref<{ label: string; value: number }[]>([])
const coverage = ref<any>(null)
const loading = ref(true)

const masteryRows = computed(() => [
  { label: '精通', value: distribution.value.mastered || 0, color: '#16834f' },
  { label: '熟悉', value: distribution.value.familiar || 0, color: '#2f6f9f' },
  { label: '不熟', value: distribution.value.unfamiliar || 0, color: '#d9633a' },
  { label: '未学', value: distribution.value.unlearned || 0, color: '#93a19e' },
])

const trendValues = computed(() =>
  (dashboard.value?.trend || []).map((point) => (point.accuracy === null ? 0 : point.accuracy)),
)
const trendLabels = computed(() => (dashboard.value?.trend || []).map((point) => point.label))

async function load(): Promise<void> {
  loading.value = true
  try {
    const params = { category_id: store.boardParam }
    const [dashboardData, distributionData, unfamiliarData, coverageData] = await Promise.all([
      api.get<DashboardStats>(withQuery('/stats/dashboard', params)),
      api.get<Record<string, number>>(withQuery('/stats/mastery-distribution', params)),
      api.get<{ label: string; value: number }[]>(
        withQuery('/stats/unfamiliar-distribution', params),
      ),
      api.get<any>('/stats/knowledge-coverage'),
    ])
    dashboard.value = dashboardData
    distribution.value = distributionData
    unfamiliar.value = unfamiliarData
    coverage.value = coverageData
  } catch (err: any) {
    store.toast(err?.message || '统计加载失败', 'error')
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => store.boardId, load)
</script>

<template>
  <div>
    <div v-if="loading" class="card empty">加载中…</div>
    <template v-else-if="dashboard">
      <div class="section-title" style="justify-content: space-between">
        <span>{{ store.boardName }} · 统计复盘</span>
        <span class="tag gray">口径 {{ dashboard.definitions_version }}</span>
      </div>

      <div class="grid metrics" style="margin-bottom: 14px">
        <div class="metric card">
          <div class="m-label">题目总数</div>
          <div class="m-val num">{{ dashboard.total_questions }}</div>
          <div class="m-sub">已学 {{ dashboard.learned }} · 未学 {{ dashboard.unlearned }}</div>
        </div>
        <div class="metric card">
          <div class="m-label">今日到期</div>
          <div class="m-val num">{{ dashboard.due }}</div>
          <div class="m-sub">连续打卡 {{ dashboard.streak }} 天</div>
        </div>
        <div class="metric card">
          <div class="m-label">已精通</div>
          <div class="m-val num">{{ dashboard.mastered }}</div>
          <div class="m-sub">错题 {{ dashboard.mistakes }}</div>
        </div>
        <div class="metric card">
          <div class="m-label">知识条目</div>
          <div class="m-val num">{{ dashboard.knowledge_count }}</div>
          <div class="m-sub">题-知识覆盖率 {{ coverage?.coverage ?? 0 }}%</div>
        </div>
      </div>

      <div class="grid" style="grid-template-columns: 1fr 1fr; margin-bottom: 14px">
        <div class="card">
          <div style="font-weight: 700; margin-bottom: 8px">
            掌握度分布（共 {{ distribution.total || dashboard.total_questions }} 题）
          </div>
          <BarRows :rows="masteryRows" />
        </div>
        <div class="card">
          <div style="font-weight: 700; margin-bottom: 8px">近 7 天自评正确率（q≥3）</div>
          <LineChart :values="trendValues" :labels="trendLabels" :max-v="100" />
        </div>
      </div>

      <div class="grid" style="grid-template-columns: 1fr 1fr">
        <div class="card">
          <div style="font-weight: 700; margin-bottom: 8px">不熟知识点分布</div>
          <BarRows :rows="unfamiliar" color="#d9633a" />
        </div>
        <div class="card">
          <div style="font-weight: 700; margin-bottom: 8px">知识库覆盖</div>
          <div class="grid" style="grid-template-columns: 1fr 1fr; gap: 10px">
            <div class="metric card" style="box-shadow: none">
              <div class="m-label">知识条目</div>
              <div class="m-val num" style="font-size: 24px">{{ coverage?.knowledge_count ?? 0 }}</div>
            </div>
            <div class="metric card" style="box-shadow: none">
              <div class="m-label">已关联题目</div>
              <div class="m-val num" style="font-size: 24px">{{ coverage?.questions_linked ?? 0 }}</div>
            </div>
            <div class="metric card" style="box-shadow: none">
              <div class="m-label">未关联题目</div>
              <div class="m-val num" style="font-size: 24px">{{ coverage?.unlinked_questions ?? 0 }}</div>
            </div>
            <div class="metric card" style="box-shadow: none">
              <div class="m-label">覆盖率</div>
              <div class="m-val num" style="font-size: 24px">{{ coverage?.coverage ?? 0 }}%</div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
