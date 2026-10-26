<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { api } from '../api/client'
import type { WeeklyReport } from '../api/types'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const reports = ref<WeeklyReport[]>([])
const loading = ref(true)
const generating = ref(false)
const selectedId = ref<number | null>(null)
const weekStart = ref('')
const mode = ref<'auto' | 'basic'>('auto')

const current = computed(
  () => reports.value.find((row) => row.id === selectedId.value) || null,
)

function weekLabel(value: string): string {
  const start = new Date(`${value}T00:00:00`)
  const end = new Date(start.getTime() + 6 * 86400000)
  const fmt = (date: Date) => `${date.getMonth() + 1}月${date.getDate()}日`
  return `${fmt(start)} – ${fmt(end)}`
}

function currentWeekStart(): string {
  const today = new Date()
  const day = today.getDay() === 0 ? 7 : today.getDay()
  today.setDate(today.getDate() - (day - 1))
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<{ items: WeeklyReport[] }>('/reports/weekly?limit=16')
    reports.value = data.items
    if (!selectedId.value && data.items.length) selectedId.value = data.items[0].id
  } catch (err: any) {
    store.toast(err?.message || '周报告加载失败', 'error')
  } finally {
    loading.value = false
  }
}

async function generate(): Promise<void> {
  generating.value = true
  try {
    const report = await api.post<WeeklyReport>('/reports/weekly', {
      week_start: weekStart.value || null,
      mode: mode.value,
    })
    selectedId.value = report.id
    if (report.generated_by === 'ai') {
      store.toast('AI 周报告已生成', 'success')
    } else if (report.ai_error_code) {
      store.toast(`AI 不可用（${report.ai_error_code}），已生成基础报告`, 'info')
    } else {
      store.toast('基础周报告已生成', 'success')
    }
    await load()
  } catch (err: any) {
    store.toast(err?.message || '生成失败', 'error')
  } finally {
    generating.value = false
  }
}

function accuracyTone(value: number): string {
  if (value >= 80) return 'green'
  if (value >= 60) return 'amber'
  return 'orange'
}

function selectReport(id: number): void {
  selectedId.value = id
}

onMounted(() => {
  weekStart.value = currentWeekStart()
  load()
})
</script>

<template>
  <div class="weekly-page">
    <div class="toolbar">
      <input v-model="weekStart" type="date" title="所属周的任意一天（自动归一为周一）" />
      <select v-model="mode">
        <option value="auto">AI 生成（不可用时自动降级）</option>
        <option value="basic">仅基础统计报告</option>
      </select>
      <button class="btn" :disabled="generating" @click="generate">
        {{ generating ? '生成中，可能需要数十秒…' : '生成本周报告' }}
      </button>
      <div style="flex: 1"></div>
      <button class="btn ghost sm" @click="load">刷新</button>
    </div>

    <div class="weekly-grid">
      <div class="card weekly-list">
        <div class="weekly-list-title">历史周报（{{ reports.length }}）</div>
        <div v-if="loading" class="empty">加载中…</div>
        <template v-else-if="reports.length">
          <div
            v-for="report in reports"
            :key="report.id"
            class="weekly-list-item"
            :class="{ active: report.id === selectedId }"
            @click="selectReport(report.id)"
          >
            <div class="weekly-list-week">{{ weekLabel(report.week_start) }}</div>
            <div class="list-sub">
              {{ report.generated_by === 'ai' ? 'AI' : '基础' }} ·
              {{ report.reviews }} 次 · 正确率 {{ report.accuracy === null ? '—' : `${report.accuracy}%` }}
            </div>
          </div>
        </template>
        <div v-else class="empty">还没有周报告</div>
      </div>

      <div class="card weekly-main">
        <template v-if="current">
          <div class="weekly-head">
            <h3>{{ weekLabel(current.week_start) }} 学习周报</h3>
            <span class="tag" :class="current.generated_by === 'ai' ? 'teal' : 'gray'">
              {{ current.generated_by === 'ai' ? 'AI 复盘' : '基础报告' }}
            </span>
            <span v-if="current.ai_error_code" class="tag amber">
              AI 不可用（{{ current.ai_error_code }}）
            </span>
          </div>

          <div class="weekly-stats">
            <div class="weekly-stat">
              <div class="weekly-stat-value">{{ current.reviews }}</div>
              <div class="list-sub">自评次数</div>
            </div>
            <div class="weekly-stat">
              <div class="weekly-stat-value">
                {{ current.accuracy === null ? '—' : `${current.accuracy}%` }}
              </div>
              <div class="list-sub">正确率</div>
            </div>
            <div class="weekly-stat">
              <div class="weekly-stat-value">{{ current.active_days }}<small>/7</small></div>
              <div class="list-sub">活跃天数</div>
            </div>
            <div class="weekly-stat">
              <div class="weekly-stat-value">{{ current.new_learned }}</div>
              <div class="list-sub">新学题目</div>
            </div>
            <div class="weekly-stat">
              <div class="weekly-stat-value">{{ current.mistakes_added }}</div>
              <div class="list-sub">新增错题</div>
            </div>
            <div class="weekly-stat">
              <div class="weekly-stat-value">{{ current.due_total }}</div>
              <div class="list-sub">当前到期</div>
            </div>
            <div class="weekly-stat">
              <div class="weekly-stat-value">
                {{ current.interviews.count ? current.interviews.average_score : '—' }}
              </div>
              <div class="list-sub">面试均分（{{ current.interviews.count }} 次）</div>
            </div>
          </div>

          <p class="weekly-summary">{{ current.summary }}</p>

          <div class="weekly-section">
            <div class="weekly-label">本周亮点</div>
            <ul class="weekly-list-text">
              <li v-for="(item, index) in current.highlights" :key="index">{{ item }}</li>
            </ul>
          </div>

          <div class="weekly-section">
            <div class="weekly-label">薄弱点</div>
            <div v-if="current.weak_points.length" class="weekly-weak">
              <div v-for="(point, index) in current.weak_points" :key="index" class="weekly-weak-item">
                <span class="tag orange">{{ point.label }}</span>
                <div>{{ point.reason }}</div>
                <div class="list-sub">建议：{{ point.suggestion }}</div>
              </div>
            </div>
            <div v-else class="list-sub">暂无明显薄弱点</div>
          </div>

          <div class="weekly-section">
            <div class="weekly-label">下周计划</div>
            <ul class="weekly-list-text">
              <li v-for="(item, index) in current.plan" :key="index">{{ item }}</li>
            </ul>
          </div>

          <div v-if="current.categories.length" class="weekly-section">
            <div class="weekly-label">分类正确率</div>
            <div class="weekly-cats">
              <div v-for="row in current.categories" :key="row.label" class="weekly-cat">
                <span class="weekly-cat-label">{{ row.label }}</span>
                <span class="weekly-cat-bar">
                  <span
                    class="weekly-cat-fill"
                    :style="{ width: `${row.accuracy}%` }"
                  />
                </span>
                <span class="tag" :class="accuracyTone(row.accuracy)">{{ row.accuracy }}%</span>
                <span class="list-sub">{{ row.reviews }} 次</span>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="empty">
          选择左侧周报，或点击「生成本周报告」；AI 不可用时会自动生成本地统计版。
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.weekly-grid {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  align-items: start;
}
.weekly-list {
  padding: 10px;
}
.weekly-list-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink2);
  padding: 4px 8px 10px;
}
.weekly-list-item {
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
}
.weekly-list-item:hover {
  background: var(--bg);
}
.weekly-list-item.active {
  background: var(--teal-bg);
}
.weekly-list-week {
  font-size: 14px;
  font-weight: 600;
}
.weekly-main {
  padding: 20px 24px;
}
.weekly-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.weekly-head h3 {
  font-size: 18px;
}
.weekly-stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.weekly-stat {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--bg);
}
.weekly-stat-value {
  font-size: 24px;
  font-weight: 700;
  color: var(--ink);
}
.weekly-stat-value small {
  font-size: 12px;
  font-weight: 500;
  color: var(--ink3);
}
.weekly-summary {
  font-size: 14.5px;
  line-height: 1.75;
  color: var(--ink2);
  margin-bottom: 14px;
}
.weekly-section {
  margin-bottom: 12px;
}
.weekly-label {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink2);
  margin-bottom: 6px;
}
.weekly-list-text {
  margin: 0;
  padding-left: 20px;
  font-size: 13.5px;
  line-height: 1.7;
}
.weekly-weak {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.weekly-weak-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13.5px;
}
.weekly-cats {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.weekly-cat {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13.5px;
}
.weekly-cat-label {
  width: 100px;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.weekly-cat-bar {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  background: #eef1f0;
  overflow: hidden;
}
.weekly-cat-fill {
  display: block;
  height: 100%;
  background: var(--teal);
}
@media (max-width: 960px) {
  .weekly-grid {
    grid-template-columns: 1fr;
  }
}
</style>