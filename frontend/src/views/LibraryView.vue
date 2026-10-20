<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { Question } from '../api/types'
import DifficultyBars from '../components/DifficultyBars.vue'
import Modal from '../components/Modal.vue'
import Pagination from '../components/Pagination.vue'
import { useAppStore } from '../stores/app'
import {
  formatDate,
  formatDateTime,
  frequencyText,
  frequencyTone,
  masteryText,
  masteryTone,
  sourceText,
  sourceTone,
} from '../utils/labels'

const store = useAppStore()

const items = ref<Question[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(true)

const search = ref('')
const difficulty = ref('')
const frequency = ref('')
const source = ref('')
const mastery = ref('')
const status = ref('active')

const detail = ref<Question | null>(null)
const detailOpen = ref(false)
const formOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)

interface QuestionForm {
  stem: string
  answer: string
  key_points_text: string
  notes: string
  category_path: string
  tags_text: string
  companies_text: string
  difficulty: number | null
  frequency: string
  status: string
}

const form = reactive<QuestionForm>({
  stem: '',
  answer: '',
  key_points_text: '',
  notes: '',
  category_path: '',
  tags_text: '',
  companies_text: '',
  difficulty: null,
  frequency: '',
  status: 'active',
})

const categoryPaths = computed(() => {
  const result: string[] = []
  const walk = (nodes: typeof store.tree): void => {
    nodes.forEach((node) => {
      result.push(node.path)
      walk(node.children)
    })
  }
  walk(store.tree)
  return result
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<{ items: Question[]; total: number }>(
      withQuery('/questions', {
        category_id: store.boardParam,
        q: search.value.trim() || undefined,
        difficulty: difficulty.value || undefined,
        frequency: frequency.value || undefined,
        source_type: source.value || undefined,
        mastery: mastery.value || undefined,
        status: status.value,
        page: page.value,
        page_size: pageSize,
      }),
    )
    items.value = data.items
    total.value = data.total
  } catch (err: any) {
    store.toast(err?.message || '题库加载失败', 'error')
  } finally {
    loading.value = false
  }
}

function applySearch(): void {
  page.value = 1
  load()
}

function changePage(value: number): void {
  page.value = value
  load()
}

function resetForm(): void {
  form.stem = ''
  form.answer = ''
  form.key_points_text = ''
  form.notes = ''
  form.category_path = ''
  form.tags_text = ''
  form.companies_text = ''
  form.difficulty = null
  form.frequency = ''
  form.status = 'active'
  editingId.value = null
}

function openCreate(): void {
  resetForm()
  formOpen.value = true
}

async function openEdit(question: Question): Promise<void> {
  try {
    const full = await api.get<Question>(`/questions/${question.id}`)
    editingId.value = full.id
    form.stem = full.stem
    form.answer = full.answer || ''
    form.key_points_text = (full.key_points || []).join('\n')
    form.notes = full.notes || ''
    form.category_path = full.category_path || ''
    form.tags_text = (full.tags || []).map((tag) => tag.name).join(', ')
    form.companies_text = (full.companies || []).map((company) => company.name).join(', ')
    form.difficulty = full.difficulty
    form.frequency = full.frequency || ''
    form.status = full.status
    formOpen.value = true
  } catch (err: any) {
    store.toast(err?.message || '题目加载失败', 'error')
  }
}

function splitList(value: string): string[] {
  return value
    .split(/[,，、;；\n]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

async function save(): Promise<void> {
  if (!form.stem.trim()) {
    store.toast('题干不能为空', 'error')
    return
  }
  saving.value = true
  const payload: Record<string, unknown> = {
    stem: form.stem.trim(),
    answer: form.answer || null,
    key_points: form.key_points_text
      .split('\n')
      .map((item) => item.trim())
      .filter(Boolean),
    notes: form.notes || null,
    category_path: form.category_path || null,
    tags: splitList(form.tags_text),
    companies: splitList(form.companies_text),
    difficulty: form.difficulty,
    frequency: form.frequency || null,
    status: form.status,
  }
  try {
    if (editingId.value) {
      await api.patch(`/questions/${editingId.value}`, payload)
      store.toast('题目已保存', 'success')
    } else {
      const result: any = await api.post('/questions', payload)
      store.toast(result?.pending ? '已进入待审区' : '题目已创建', 'success')
      if (result?.pending) await store.loadBadges()
    }
    formOpen.value = false
    await load()
  } catch (err: any) {
    store.toast(err?.message || '保存失败', 'error')
  } finally {
    saving.value = false
  }
}

async function openDetail(question: Question): Promise<void> {
  try {
    detail.value = await api.get<Question>(`/questions/${question.id}`)
    detailOpen.value = true
  } catch (err: any) {
    store.toast(err?.message || '详情加载失败', 'error')
  }
}

async function refreshDetail(): Promise<void> {
  if (!detail.value) return
  try {
    detail.value = await api.get<Question>(`/questions/${detail.value.id}`)
  } catch {
    detailOpen.value = false
  }
}

async function toggleBookmark(question: Question): Promise<void> {
  try {
    if (question.bookmarked) {
      await api.delete(`/bookmarks/${question.id}`)
      store.toast('已取消收藏', 'success')
    } else {
      await api.post('/bookmarks', { question_id: question.id })
      store.toast('已收藏', 'success')
    }
    await load()
    if (detail.value?.id === question.id) await refreshDetail()
  } catch (err: any) {
    store.toast(err?.message || '操作失败', 'error')
  }
}

async function archive(question: Question): Promise<void> {
  if (!window.confirm('确定归档该题？归档后不再进入练习与复习队列。')) return
  try {
    await api.post(`/questions/${question.id}/archive`)
    store.toast('已归档', 'success')
    detailOpen.value = false
    await load()
  } catch (err: any) {
    store.toast(err?.message || '归档失败', 'error')
  }
}

async function remove(question: Question): Promise<void> {
  if (!window.confirm('确定软删除该题？历史掌握记录会保留。')) return
  try {
    await api.delete(`/questions/${question.id}`)
    store.toast('已软删除', 'success')
    detailOpen.value = false
    await load()
  } catch (err: any) {
    store.toast(err?.message || '删除失败', 'error')
  }
}

onMounted(load)
watch(
  () => store.boardId,
  () => {
    page.value = 1
    load()
  },
)
</script>

<template>
  <div>
    <div class="toolbar">
      <input v-model="search" placeholder="搜索题干 / 答案 / 标签" @keyup.enter="applySearch" />
      <button class="btn ghost sm" @click="applySearch">搜索</button>
      <select v-model="difficulty" @change="applySearch">
        <option value="">全部难度</option>
        <option value="1">1 入门</option>
        <option value="2">2</option>
        <option value="3">3</option>
        <option value="4">4</option>
        <option value="5">5 困难</option>
      </select>
      <select v-model="frequency" @change="applySearch">
        <option value="">全部频率</option>
        <option value="high">高频</option>
        <option value="mid">中频</option>
        <option value="low">低频</option>
      </select>
      <select v-model="source" @change="applySearch">
        <option value="">全部来源</option>
        <option value="crawler">爬虫</option>
        <option value="import">导入</option>
        <option value="manual">手动</option>
      </select>
      <select v-model="mastery" @change="applySearch">
        <option value="">全部掌握度</option>
        <option value="unlearned">未学</option>
        <option value="unfamiliar">不熟</option>
        <option value="familiar">熟悉</option>
        <option value="mastered">精通</option>
      </select>
      <select v-model="status" @change="applySearch">
        <option value="active">正式题</option>
        <option value="draft">草稿</option>
        <option value="archived">已归档</option>
        <option value="all">全部状态</option>
      </select>
      <div style="flex: 1"></div>
      <button class="btn" @click="openCreate">+ 新建题目</button>
    </div>

    <div v-if="loading" class="card empty">加载中…</div>
    <div v-else class="card" style="padding: 6px 10px">
      <table>
        <colgroup>
          <col style="width: 34%" />
          <col style="width: 16%" />
          <col style="width: 10%" />
          <col style="width: 10%" />
          <col style="width: 10%" />
          <col style="width: 9%" />
          <col style="width: 11%" />
        </colgroup>
        <thead>
          <tr>
            <th>题干</th>
            <th>分类</th>
            <th>难度</th>
            <th>频率</th>
            <th>掌握度</th>
            <th>来源</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="question in items" :key="question.id">
            <td>
              <div style="font-weight: 500; cursor: pointer" @click="openDetail(question)">
                {{ question.stem }}
              </div>
              <div class="list-sub">{{ question.tags.map((tag) => tag.name).join(' · ') || '无标签' }}</div>
            </td>
            <td style="color: var(--ink2); font-size: 13px">{{ question.category_path || '未分类' }}</td>
            <td><DifficultyBars :value="question.difficulty" /></td>
            <td><span class="tag" :class="frequencyTone(question.frequency)">{{ frequencyText(question.frequency) }}</span></td>
            <td><span class="tag" :class="masteryTone(question.mastery)">{{ masteryText(question.mastery) }}</span></td>
            <td><span class="tag" :class="sourceTone(question.source_type)">{{ sourceText(question.source_type) }}</span></td>
            <td>
              <div style="display: flex; gap: 6px">
                <button class="btn ghost sm" @click="openDetail(question)">详情</button>
                <button class="btn ghost sm" @click="openEdit(question)">编辑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="7"><div class="empty">没有符合条件的题目</div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pagination :page="page" :page-size="pageSize" :total="total" @update:page="changePage" />

    <Modal :open="formOpen" :title="editingId ? '编辑题目' : '新建题目'" wide @close="formOpen = false">
      <div class="form-grid">
        <div class="field full">
          <label>题干 *</label>
          <textarea v-model="form.stem" class="textarea" rows="2" placeholder="例如：TCP 为什么需要三次握手？" />
        </div>
        <div class="field full">
          <label>参考答案</label>
          <textarea v-model="form.answer" class="textarea" rows="4" placeholder="面试时可复述的参考答案" />
        </div>
        <div class="field full">
          <label>要点拆解</label>
          <textarea v-model="form.key_points_text" class="textarea" rows="3" placeholder="每行一个要点" />
        </div>
        <div class="field">
          <label>分类路径</label>
          <input v-model="form.category_path" class="input" list="category-options" placeholder="后端开发/计算机网络/TCP" />
        </div>
        <div class="field">
          <label>状态</label>
          <select v-model="form.status" class="select">
            <option value="active">正式题</option>
            <option value="draft">草稿</option>
          </select>
        </div>
        <div class="field">
          <label>标签（逗号分隔）</label>
          <input v-model="form.tags_text" class="input" placeholder="TCP, 可靠性" />
        </div>
        <div class="field">
          <label>公司（逗号分隔）</label>
          <input v-model="form.companies_text" class="input" placeholder="腾讯, 字节" />
        </div>
        <div class="field">
          <label>难度</label>
          <select v-model="form.difficulty" class="select">
            <option :value="null">未标注</option>
            <option :value="1">1 入门</option>
            <option :value="2">2</option>
            <option :value="3">3</option>
            <option :value="4">4</option>
            <option :value="5">5 困难</option>
          </select>
        </div>
        <div class="field">
          <label>频率</label>
          <select v-model="form.frequency" class="select">
            <option value="">未标注</option>
            <option value="high">高频</option>
            <option value="mid">中频</option>
            <option value="low">低频</option>
          </select>
        </div>
        <div class="field full">
          <label>个人笔记</label>
          <textarea v-model="form.notes" class="textarea" rows="2" placeholder="口诀、易错点、面试表达" />
        </div>
      </div>
      <datalist id="category-options">
        <option v-for="path in categoryPaths" :key="path" :value="path" />
      </datalist>
      <div class="form-actions">
        <button class="btn ghost" @click="formOpen = false">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </Modal>

    <Modal :open="detailOpen" title="题目详情" wide @close="detailOpen = false">
      <template v-if="detail">
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px">
          <span class="tag" :class="masteryTone(detail.mastery)">{{ masteryText(detail.mastery) }}</span>
          <span class="tag" :class="frequencyTone(detail.frequency)">{{ frequencyText(detail.frequency) }}</span>
          <span class="tag" :class="sourceTone(detail.source_type)">{{ sourceText(detail.source_type) }}</span>
          <span class="tag gray">{{ detail.category_path || '未分类' }}</span>
          <span class="tag gray">{{ detail.status === 'active' ? '正式题' : detail.status === 'draft' ? '草稿' : '已归档' }}</span>
          <span v-for="tag in detail.tags" :key="tag.id" class="tag teal">{{ tag.name }}</span>
        </div>
        <h3 style="font-size: 18px; line-height: 1.6; margin-bottom: 14px">{{ detail.stem }}</h3>
        <div class="panswer" style="margin-top: 0">
          <b>参考答案：</b>{{ detail.answer || '暂无参考答案' }}
          <template v-if="detail.key_points?.length">
            <br /><br /><b>要点：</b>{{ detail.key_points.join('；') }}
          </template>
          <template v-if="detail.notes">
            <br /><br /><b>个人笔记：</b>{{ detail.notes }}
          </template>
        </div>

        <div class="section-title" style="font-size: 14px">复习排程</div>
        <div class="list-sub">
          状态 {{ detail.schedule.is_new ? '新题' : '已学' }} · reps {{ detail.schedule.reps }} ·
          EF {{ detail.schedule.ef }} · 间隔 {{ detail.schedule.interval_days }} 天 ·
          下次 {{ formatDate(detail.schedule.next_review_date) }}
        </div>

        <div class="section-title" style="font-size: 14px">掌握记录</div>
        <div v-if="detail.history?.length" style="display: flex; gap: 8px; flex-wrap: wrap">
          <span v-for="record in detail.history.slice(0, 8)" :key="record.id" class="tag gray">
            {{ record.local_date }} · q={{ record.q }} · {{ record.mode }}
          </span>
        </div>
        <div v-else class="list-sub">暂无评分记录</div>

        <div class="section-title" style="font-size: 14px">来源溯源</div>
        <div v-if="detail.origins?.length" style="display: flex; flex-direction: column; gap: 5px">
          <div v-for="origin in detail.origins" :key="origin.id" class="list-sub mono">
            {{ sourceText(origin.source_type) }} · {{ origin.origin_ref || '—' }} ·
            {{ formatDateTime(origin.created_at) }}
          </div>
        </div>
        <div v-else class="list-sub">暂无来源记录</div>

        <div class="section-title" style="font-size: 14px">关联知识</div>
        <div v-if="detail.knowledge?.length" style="display: flex; gap: 8px; flex-wrap: wrap">
          <span v-for="item in detail.knowledge" :key="item.id" class="tag blue">
            {{ item.title }} · {{ item.relation_type }}
          </span>
        </div>
        <div v-else class="list-sub">暂无关联知识</div>

        <div class="form-actions" style="margin-top: 20px">
          <button class="btn ghost" @click="toggleBookmark(detail)">
            {{ detail.bookmarked ? '取消收藏' : '收藏' }}
          </button>
          <button class="btn ghost" @click="openEdit(detail)">编辑</button>
          <button class="btn ghost" @click="archive(detail)">归档</button>
          <button class="btn danger-ghost" @click="remove(detail)">删除</button>
        </div>
      </template>
    </Modal>
  </div>
</template>
