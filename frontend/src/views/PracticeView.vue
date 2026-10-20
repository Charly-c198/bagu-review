<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { api } from '../api/client'
import type { Question } from '../api/types'
import MultiSelect from '../components/MultiSelect.vue'
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
const route = useRoute()

const queue = ref<Question[]>([])
const index = ref(0)
const revealed = ref(false)
const detail = ref<Question | null>(null)
const finished = ref(false)
const loading = ref(false)
const rating = ref(false)

const difficulties = ref<string[]>([])
const frequencies = ref<string[]>([])
const sources = ref<string[]>([])
const masteries = ref<string[]>([])
const tagIds = ref<string[]>([])
const companyIds = ref<string[]>([])
const tagOptions = ref<{ value: string; label: string }[]>([])
const companyOptions = ref<{ value: string; label: string }[]>([])

const difficultyOptions = [
  { value: '1', label: '1 入门' },
  { value: '2', label: '2' },
  { value: '3', label: '3' },
  { value: '4', label: '4' },
  { value: '5', label: '5 困难' },
]
const frequencyOptions = [
  { value: 'high', label: '高频' },
  { value: 'mid', label: '中频' },
  { value: 'low', label: '低频' },
]
const sourceOptions = [
  { value: 'crawler', label: '爬虫' },
  { value: 'import', label: '导入' },
  { value: 'manual', label: '手动' },
]
const masteryOptions = [
  { value: 'unlearned', label: '未学' },
  { value: 'unfamiliar', label: '只看不熟' },
  { value: 'familiar', label: '熟悉' },
  { value: 'mastered', label: '精通' },
]

const limit = ref(20)
const fixedQuery = typeof route.query.q === 'string' ? route.query.q : ''
const onlyMistakes = route.query.only_mistakes === '1'

async function loadOptions(): Promise<void> {
  try {
    const [tags, companies] = await Promise.all([
      api.get<{ id: number; name: string; question_count: number }[]>('/tags'),
      api.get<{ id: number; name: string; question_count: number }[]>('/companies'),
    ])
    tagOptions.value = tags.map((tag) => ({
      value: String(tag.id),
      label: `${tag.name} (${tag.question_count})`,
    }))
    companyOptions.value = companies.map((company) => ({
      value: String(company.id),
      label: `${company.name} (${company.question_count})`,
    }))
  } catch {
    // 选项加载失败不影响组卷。
  }
}

const current = computed(() => queue.value[index.value] || null)
const currentDetail = computed(() => detail.value || current.value)
const progressText = computed(() => `第 ${index.value + 1} / ${queue.value.length} 题`)

async function start(): Promise<void> {
  loading.value = true
  finished.value = false
  index.value = 0
  revealed.value = false
  detail.value = null
  try {
    const data = await api.post<{ items: Question[] }>('/practice/quiz', {
      category_id: store.boardParam,
      difficulties: difficulties.value.map(Number),
      frequencies: frequencies.value,
      sources: sources.value,
      masteries: masteries.value,
      tag_ids: tagIds.value.map(Number),
      company_ids: companyIds.value.map(Number),
      q: fixedQuery || undefined,
      limit: limit.value,
      mode: 'practice',
      exclude_mastered: masteries.value.length ? false : true,
      only_mistakes: onlyMistakes,
    })
    queue.value = data.items
    if (!queue.value.length) finished.value = false
  } catch (err: any) {
    store.toast(err?.message || '组卷失败', 'error')
    queue.value = []
  } finally {
    loading.value = false
  }
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
      schedule: { next_review_date: string | null }
      mistake_added: boolean
    }>('/ratings', {
      question_id: current.value.id,
      q,
      mode: 'practice',
    })
    if (q === 2) {
      store.toast('已记入错题本，排程已重置', 'info')
    } else if (result.schedule_applied) {
      store.toast(`已更新掌握度，下次复习 ${formatDate(result.schedule.next_review_date)}`, 'success')
    } else {
      store.toast('今日排程已推进过，仅记录本次评分', 'info')
    }
    index.value += 1
    revealed.value = false
    detail.value = null
    if (index.value >= queue.value.length) {
      finished.value = true
      store.loadBadges()
    }
  } catch (err: any) {
    store.toast(err?.message || '评分失败', 'error')
  } finally {
    rating.value = false
  }
}

onMounted(() => {
  start()
  loadOptions()
})
watch(() => store.boardId, start)
</script>

<template>
  <div>
    <div class="practice-stage">
      <div class="toolbar" style="justify-content: center">
        <MultiSelect v-model="difficulties" :options="difficultyOptions" placeholder="全部难度" @update:model-value="start" />
        <MultiSelect v-model="frequencies" :options="frequencyOptions" placeholder="全部频率" @update:model-value="start" />
        <MultiSelect v-model="sources" :options="sourceOptions" placeholder="全部来源" @update:model-value="start" />
        <MultiSelect v-model="masteries" :options="masteryOptions" placeholder="全部掌握度" @update:model-value="start" />
        <MultiSelect v-model="tagIds" :options="tagOptions" placeholder="全部标签" width="150px" @update:model-value="start" />
        <MultiSelect v-model="companyIds" :options="companyOptions" placeholder="全部公司" width="150px" @update:model-value="start" />
        <select v-model.number="limit" class="select" style="width: auto" @change="start">
          <option :value="10">10 题</option>
          <option :value="20">20 题</option>
          <option :value="30">30 题</option>
        </select>
        <button class="btn ghost sm" @click="start">重新组卷</button>
      </div>

      <div v-if="onlyMistakes" class="board-banner" style="justify-content: center">
        <b>错题重练</b><span>仅抽取错题本中的题目</span>
      </div>

      <div v-if="loading" class="pcard"><div class="empty">正在组卷…</div></div>

      <div v-else-if="finished" class="pcard" style="text-align: center; align-items: center">
        <div class="done-mark">完</div>
        <div style="font-size: 19px; font-weight: 700">本轮刷完了</div>
        <div style="color: var(--ink2); margin: 8px 0 18px">
          共 {{ queue.length }} 题，去复习或休息一下
        </div>
        <button class="btn" @click="start">再来一轮</button>
      </div>

      <div v-else-if="!current" class="pcard">
        <div class="empty">没有符合条件的题目，换个筛选条件试试</div>
      </div>

      <template v-else>
        <div class="p-progress">{{ progressText }}</div>
        <div class="pcard">
          <div class="p-meta">
            <span class="tag teal">{{ store.boardName }}</span>
            <span v-if="current.category_path" class="tag gray">{{ current.category_path }}</span>
            <span class="tag" :class="frequencyTone(current.frequency)">{{ frequencyText(current.frequency) }}</span>
            <span class="tag" :class="sourceTone(current.source_type)">{{ sourceText(current.source_type) }}</span>
            <span class="tag" :class="masteryTone(current.mastery)">{{ masteryText(current.mastery) }}</span>
            <span v-for="company in current.companies" :key="company.id" class="tag gray">{{ company.name }}</span>
          </div>
          <div class="p-stem">{{ current.stem }}</div>

          <div v-if="revealed && currentDetail" class="panswer">
            <b>参考答案：</b>{{ currentDetail.answer || '暂无参考答案' }}
            <template v-if="currentDetail.key_points?.length">
              <br /><br /><b>要点：</b>
              <span style="color: var(--ink3)">{{ currentDetail.key_points.join('；') }}</span>
            </template>
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
