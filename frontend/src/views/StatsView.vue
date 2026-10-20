<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { CategoryMasteryRow, DashboardStats, ReviewHeatmap } from '../api/types'
import BarRows from '../components/BarRows.vue'
import LineChart from '../components/LineChart.vue'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const dashboard = ref<DashboardStats | null>(null)
const distribution = ref<Record<string, number>>({})
const unfamiliar = ref<{ label: string; value: number }[]>([])
const coverage = ref<any>(null)
const heatmap = ref<ReviewHeatmap | null>(null)
const categoryRows = ref<CategoryMasteryRow[]>([])
const loading = ref(true)

const heatMax = computed(() =>
  Math.max(1, ...(heatmap.value?.items || []).map((item) => item.reviews)),
)

function heatLevel(reviews: number): number {
  if (!reviews) return 0
  const ratio = reviews / heatMax.value
  if (ratio > 0.75) return 4
  if (ratio > 0.5) return 3
  if (ratio > 0.25) return 2
  return 1
}

function heatTitle(item: { date: string; reviews: number; accuracy: number | null }): string {
  const accuracy = item.accuracy === null ? '—' : `${item.accuracy}%`
  return `${item.date} · 复习 ${item.reviews} 次 · 正确率 ${accuracy}`
}

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
    const [
      dashboardData,
      distributionData,
      unfamiliarData,
      coverageData,
      heatmapData,
      categoryMasteryData,
    ] = await Promise.all([
      api.get<DashboardStats>(withQuery('/stats/dashboard', params)),
      api.get<Record<string, number>>(withQuery('/stats/mastery-distribution', params)),
      api.get<{ label: string; value: number }[]>(
        withQuery('/stats/unfamiliar-distribution', params),
      ),
      api.get<any>('/stats/knowledge-coverage'),
      api.get<ReviewHeatmap>(withQuery('/stats/review-heatmap', { ...params, days: 30 })),
      api.get<CategoryMasteryRow[]>(
        withQuery('/stats/category-mastery', params),
      ),
    ])
    dashboard.value = dashboardData
    distribution.value = distributionData
    unfamiliar.value = unfamiliarData
    coverage.value = coverageData
    heatmap.value = heatmapData
    categoryRows.value = categoryMasteryData
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
      <div class="grid" style="grid-template-columns: 1.15fr 1fr; margin-top: 14px">
        <div class="card">
          <div class="chart-head">
            <div style="font-weight: 700">近 30 天复习热力</div>
            <span class="tag gray">
              共 {{ heatmap?.total_reviews ?? 0 }} 次 · 活跃 {{ heatmap?.active_days ?? 0 }} 天
            </span>
          </div>
          <div class="heatmap">
            <div
              v-for="item in heatmap?.items || []"
              :key="item.date"
              class="heat-cell"
              :class="`level-${heatLevel(item.reviews)}`"
              :title="heatTitle(item)"
            ></div>
          </div>
          <div class="heat-legend">
            <span>少</span>
            <span class="heat-cell level-0"></span>
            <span class="heat-cell level-1"></span>
            <span class="heat-cell level-2"></span>
            <span class="heat-cell level-3"></span>
            <span class="heat-cell level-4"></span>
            <span>多</span>
          </div>
        </div>
        <div class="card">
          <div style="font-weight: 700; margin-bottom: 10px">各技术栈掌握度</div>
          <div v-if="!categoryRows.length" class="empty">暂无分类掌握度数据</div>
          <div v-for="row in categoryRows" :key="row.label" class="stack-row">
            <div class="stack-label">
              <span>{{ row.label }}</span>
              <span class="num">{{ row.total }}</span>
            </div>
            <div class="stack-bar">
              <span
                v-if="row.mastered"
                class="seg mastered"
                :style="{ flex: row.mastered }"
                :title="`精通 ${row.mastered}`"
              ></span>
              <span
                v-if="row.familiar"
                class="seg familiar"
                :style="{ flex: row.familiar }"
                :title="`熟悉 ${row.familiar}`"
              ></span>
              <span
                v-if="row.unfamiliar"
                class="seg unfamiliar"
                :style="{ flex: row.unfamiliar }"
                :title="`不熟 ${row.unfamiliar}`"
              ></span>
              <span
                v-if="row.unlearned"
                class="seg unlearned"
                :style="{ flex: row.unlearned }"
                :title="`未学 ${row.unlearned}`"
              ></span>
            </div>
          </div>
          <div v-if="categoryRows.length" class="stack-legend">
            <span><i class="dot mastered"></i>精通</span>
            <span><i class="dot familiar"></i>熟悉</span>
            <span><i class="dot unfamiliar"></i>不熟</span>
            <span><i class="dot unlearned"></i>未学</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}
.heatmap {
  display: grid;
  grid-template-columns: repeat(15, 1fr);
  gap: 5px;
}
.heat-cell {
  aspect-ratio: 1;
  border-radius: 4px;
  background: #eef2f1;
}
.heat-cell.level-1 { background: #cfe7e3; }
.heat-cell.level-2 { background: #8fc9c2; }
.heat-cell.level-3 { background: #3f9d96; }
.heat-cell.level-4 { background: var(--teal); }
.heat-legend {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
  margin-top: 10px;
  color: var(--ink3);
  font-size: 12px;
}
.heat-legend .heat-cell {
  width: 12px;
  height: 12px;
  aspect-ratio: auto;
}
.stack-row {
  margin-bottom: 9px;
}
.stack-label {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--ink2);
  margin-bottom: 4px;
}
.stack-bar {
  display: flex;
  height: 10px;
  gap: 2px;
  overflow: hidden;
  border-radius: 6px;
  background: #eef2f1;
}
.seg { display: block; height: 100%; }
.seg.mastered { background: var(--green); }
.seg.familiar { background: var(--blue); }
.seg.unfamiliar { background: var(--orange); }
.seg.unlearned { background: #b9c5c2; }
.stack-legend {
  display: flex;
  gap: 12px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--ink2);
}
.stack-legend .dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}
.dot.mastered { background: var(--green); }
.dot.familiar { background: var(--blue); }
.dot.unfamiliar { background: var(--orange); }
.dot.unlearned { background: #b9c5c2; }
</style>
