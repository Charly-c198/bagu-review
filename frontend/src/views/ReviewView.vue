<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { Question, ReviewPayload } from '../api/types'
import { useAppStore } from '../stores/app'
import {
  formatDate,
  frequencyText,
  frequencyTone,
  masteryText,
  masteryTone,
  sourceText,
  sourceTone,
} from '../utils/labels'

const store = useAppStore()

const payload = ref<ReviewPayload | null>(null)
const loading = ref(true)
const active = ref(false)
const finished = ref(false)
const queue = ref<Question[]>([])
const index = ref(0)
const revealed = ref(false)
const detail = ref<Question | null>(null)
const rating = ref(false)

const current = computed(() => queue.value[index.value] || null)
const currentDetail = computed(() => detail.value || current.value)
const totalQueue = computed(() => (payload.value ? payload.value.due.length + payload.value.new.length : 0))

async function load(): Promise<void> {
  loading.value = true
  try {
    payload.value = await api.get<ReviewPayload>(
      withQuery('/review/today', { category_id: store.boardParam }),
    )
  } catch (err: any) {
    store.toast(err?.message || '复习队列加载失败', 'error')
  } finally {
    loading.value = false
  }
}

function startReview(): void {
  if (!payload.value) return
  queue.value = [...payload.value.due, ...payload.value.new]
  if (!queue.value.length) {
    store.toast('当前没有待复习题目', 'info')
    return
  }
  active.value = true
  finished.value = false
  index.value = 0
  revealed.value = false
  detail.value = null
}

async function reveal(): Promise<void> {
  if (!current.value) return
  try {
    detail.value = await api.get<Question>(`/questions/${current.value.id}`)
    revealed.value = true
  } catch (err: any) {
    store.toast(err?.message || '答案加载失败', 'error')
  }
}

async function rate(q: number): Promise<void> {
  if (!current.value || rating.value) return
  rating.value = true
  try {
    const result = await api.post<{
      schedule_applied: boolean
      schedule: { next_review_date: string | null; interval_days: number }
    }>('/ratings', {
      question_id: current.value.id,
      q,
      mode: 'review',
    })
    if (result.schedule_applied) {
      store.toast(
        `下次复习 ${formatDate(result.schedule.next_review_date)}（间隔 ${result.schedule.interval_days} 天）`,
        'success',
      )
    } else {
      store.toast('今日排程已推进过，仅记录本次评分', 'info')
    }
    index.value += 1
    revealed.value = false
    detail.value = null
    if (index.value >= queue.value.length) {
      finished.value = true
      await load()
      await store.loadBadges()
    }
  } catch (err: any) {
    store.toast(err?.message || '评分失败', 'error')
  } finally {
    rating.value = false
  }
}

async function backToQueue(): Promise<void> {
  active.value = false
  finished.value = false
  await load()
}

onMounted(load)
watch(
  () => store.boardId,
  async () => {
    active.value = false
    finished.value = false
    await load()
  },
)
</script>

<template>
  <div>
    <div v-if="loading" class="card empty">正在计算今日队列…</div>
    <div v-else-if="active" class="practice-stage">
      <div v-if="finished" class="pcard" style="text-align: center; align-items: center">
        <div class="done-mark">完</div>
        <div style="font-size: 19px; font-weight: 700">今日复习完成</div>
        <div style="color: var(--ink2); margin: 8px 0 18px">共完成 {{ queue.length }} 题</div>
        <button class="btn" @click="backToQueue">返回队列</button>
      </div>
      <template v-else-if="current">
        <div class="p-progress">今日复习 · 第 {{ index + 1 }} / {{ queue.length }} 题</div>
        <div class="pcard">
          <div class="p-meta">
            <span class="tag teal">{{ store.boardName }}</span>
            <span v-if="current.category_path" class="tag gray">{{ current.category_path }}</span>
            <span class="tag" :class="frequencyTone(current.frequency)">{{ frequencyText(current.frequency) }}</span>
            <span class="tag" :class="sourceTone(current.source_type)">{{ sourceText(current.source_type) }}</span>
            <span class="tag" :class="masteryTone(current.mastery)">{{ masteryText(current.mastery) }}</span>
          </div>
          <div class="p-stem">{{ current.stem }}</div>

          <div v-if="revealed && currentDetail" class="panswer">
            <b>参考答案：</b>{{ currentDetail.answer || '暂无参考答案' }}
            <template v-if="currentDetail.key_points?.length">
              <br /><br /><b>要点：</b>
              <span style="color: var(--ink3)">{{ currentDetail.key_points.join('；') }}</span>
            </template>
            <div class="list-sub" style="margin-top: 10px">
              当前间隔 {{ current.schedule.interval_days }} 天 · EF {{ current.schedule.ef }}
            </div>
          </div>

          <div v-if="!revealed" class="rate-row">
            <button class="btn" style="max-width: 220px; margin: 0 auto; justify-content: center" @click="reveal">
              显示答案
            </button>
          </div>
          <div v-else class="rate-row">
            <button class="rate-btn hard" :disabled="rating" @click="rate(2)">不熟</button>
            <button class="rate-btn mid" :disabled="rating" @click="rate(4)">熟悉</button>
            <button class="rate-btn easy" :disabled="rating" @click="rate(5)">精通</button>
          </div>
        </div>
      </template>
    </div>

    <template v-else-if="payload">
      <div class="grid metrics" style="margin-bottom: 16px">
        <div class="metric accent card">
          <div class="m-label">今日到期</div>
          <div class="m-val num">{{ payload.counts.due_total }}</div>
          <div class="m-sub">返回 {{ payload.counts.due_returned }} 题</div>
        </div>
        <div class="metric card">
          <div class="m-label">积压</div>
          <div class="m-val num">{{ payload.counts.backlog }}</div>
          <div class="m-sub">超过每日复习上限</div>
        </div>
        <div class="metric card">
          <div class="m-label">新题</div>
          <div class="m-val num">{{ payload.counts.new_total }}</div>
          <div class="m-sub">今日新题上限 {{ payload.limits.daily_new_limit }}</div>
        </div>
        <div class="metric card">
          <div class="m-label">今日已完成</div>
          <div class="m-val num">{{ payload.counts.completed }}</div>
          <div class="m-sub">每日本地日期 {{ payload.date }}</div>
        </div>
      </div>

      <div class="section-title" style="justify-content: space-between">
        <span>{{ store.boardName }} · 到期队列</span>
        <button class="btn" :disabled="!totalQueue" @click="startReview">开始复习（{{ totalQueue }}）</button>
      </div>

      <div v-if="payload.counts.backlog > 0" class="board-banner" style="background: var(--amber-bg); border-color: #ecd9b5">
        <b style="color: var(--amber)">还有 {{ payload.counts.backlog }} 题积压</b>
        <span>受每日复习上限限制未返回，不会丢题；可调高设置后刷新。</span>
      </div>

      <div class="card" style="padding: 6px 16px">
        <template v-if="payload.due.length">
          <div v-for="question in payload.due" :key="question.id" class="list-row">
            <div style="width: 74px; flex-shrink: 0">
              <span class="tag orange">{{ formatDate(question.schedule.next_review_date) }}</span>
            </div>
            <div class="list-main">
              <div class="list-title">{{ question.stem }}</div>
              <div class="list-sub">
                {{ question.category_path || '未分类' }} · 间隔
                {{ question.schedule.interval_days }} 天 · EF {{ question.schedule.ef }}
              </div>
            </div>
            <span class="tag" :class="masteryTone(question.mastery)">{{ masteryText(question.mastery) }}</span>
          </div>
        </template>
        <div v-else class="empty">暂无到期题</div>
      </div>

      <div class="section-title">新题队列（{{ payload.new.length }}）</div>
      <div class="card" style="padding: 6px 16px">
        <template v-if="payload.new.length">
          <div v-for="question in payload.new" :key="question.id" class="list-row">
            <div class="list-main">
              <div class="list-title">{{ question.stem }}</div>
              <div class="list-sub">{{ question.category_path || '未分类' }} · 首次学习</div>
            </div>
            <span class="tag blue">新题</span>
            <span class="tag" :class="sourceTone(question.source_type)">{{ sourceText(question.source_type) }}</span>
          </div>
        </template>
        <div v-else class="empty">今日没有新题</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.done-mark {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--green-bg);
  color: var(--green);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  font-weight: 700;
  margin-bottom: 10px;
}
</style>
