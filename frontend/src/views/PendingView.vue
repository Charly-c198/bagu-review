<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { api, withQuery } from '../api/client'
import type { PendingItem } from '../api/types'
import Modal from '../components/Modal.vue'
import Pagination from '../components/Pagination.vue'
import { useAppStore } from '../stores/app'
import {
  formatDateTime,
  frequencyText,
  frequencyTone,
  sourceText,
  sourceTone,
} from '../utils/labels'

const store = useAppStore()

const itemType = ref<'all' | 'question' | 'knowledge'>('all')
const status = ref('pending')
const source = ref('')
const search = ref('')
const lowConfidence = ref(false)
const page = ref(1)
const pageSize = 20
const items = ref<PendingItem[]>([])
const total = ref(0)
const counts = ref({ question: 0, knowledge: 0, total: 0 })
const loading = ref(true)
const selectedIds = ref<number[]>([])
const bulkRunning = ref(false)

const pendingOnPage = computed(() =>
  status.value === 'pending' ? items.value.filter((item) => item.status === 'pending') : [],
)
const allOnPageSelected = computed(
  () =>
    pendingOnPage.value.length > 0 &&
    pendingOnPage.value.every((item) => selectedIds.value.includes(item.id)),
)

function toggleSelect(id: number): void {
  const index = selectedIds.value.indexOf(id)
  if (index >= 0) selectedIds.value.splice(index, 1)
  else selectedIds.value.push(id)
}

function toggleSelectAll(): void {
  if (allOnPageSelected.value) {
    selectedIds.value = selectedIds.value.filter(
      (id) => !pendingOnPage.value.some((item) => item.id === id),
    )
  } else {
    const ids = new Set(selectedIds.value)
    pendingOnPage.value.forEach((item) => ids.add(item.id))
    selectedIds.value = [...ids]
  }
}

async function bulkApprove(): Promise<void> {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  if (!window.confirm(`确定批量通过 ${ids.length} 条待审项？内容重复的条目会单独提示，可用「合并」处理。`)) {
    return
  }
  bulkRunning.value = true
  try {
    const data = await api.post<{ results: { id: number; ok: boolean; message?: string }[] }>(
      '/pending/bulk-approve',
      { ids },
    )
    const failed = data.results.filter((row) => !row.ok)
    const okCount = data.results.length - failed.length
    if (failed.length) {
      store.toast(`已通过 ${okCount} 条，${failed.length} 条未通过（多为重复内容，请用合并处理）`, 'error')
    } else {
      store.toast(`已批量通过 ${okCount} 条`, 'success')
    }
    selectedIds.value = failed.map((row) => row.id)
    await Promise.all([load(), store.loadBadges(), store.fetchTree()])
  } catch (err: any) {
    store.toast(err?.message || '批量通过失败', 'error')
  } finally {
    bulkRunning.value = false
  }
}

const detail = ref<PendingItem | null>(null)
const detailOpen = ref(false)
const selectedKnowledge = ref<number[]>([])

const editOpen = ref(false)
const editSaving = ref(false)
const editing = ref<PendingItem | null>(null)
const editForm = reactive({
  stem: '',
  answer: '',
  knowledge_title: '',
  knowledge_content: '',
  tags_text: '',
  category_path: '',
  difficulty: '' as number | '',
  frequency: '',
  kind: 'concept',
  aliases_text: '',
  reviewer_note: '',
})

const mergeOpen = ref(false)
const merging = ref(false)
const mergeItem = ref<PendingItem | null>(null)
const mergeTargetType = ref<'question' | 'knowledge' | 'pending'>('question')
const mergeQuery = ref('')
const mergeResults = ref<any[]>([])
const mergeSelected = ref<number | null>(null)
const mergeLoading = ref(false)

const kindOptions = [
  { value: 'concept', label: '概念' },
  { value: 'principle', label: '原理' },
  { value: 'process', label: '流程' },
  { value: 'comparison', label: '对比' },
  { value: 'pitfall', label: '易错点' },
  { value: 'other', label: '其他' },
]

const pendingTabs = computed(() => [
  { key: 'all', label: `全部 ${counts.value.total}` },
  { key: 'question', label: `题目 ${counts.value.question}` },
  { key: 'knowledge', label: `知识 ${counts.value.knowledge}` },
])

function metaOf(item: PendingItem): Record<string, any> {
  return item.suggested_meta || {}
}

function confidence(item: PendingItem): number {
  return Math.round((item.parse_confidence ?? 0) * 100)
}

function confidenceTone(item: PendingItem): string {
  const value = item.parse_confidence ?? 0
  if (value < 0.6) return 'orange'
  if (value < 0.85) return 'amber'
  return 'green'
}

function dupText(item: PendingItem): string {
  if (item.dup_of) return `与题目 #${item.dup_of} 重复`
  if (item.dup_of_pending_id) return `与待审项 #${item.dup_of_pending_id} 重复`
  if (item.dup_of_knowledge_id) return `与知识 #${item.dup_of_knowledge_id} 相似`
  return ''
}

function itemTitle(item: PendingItem): string {
  return item.item_type === 'question' ? item.stem || '（无题干）' : item.knowledge_title || '（无标题）'
}

function itemBody(item: PendingItem): string {
  return item.item_type === 'question' ? item.answer || '' : item.knowledge_content || ''
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<{
      items: PendingItem[]
      total: number
      counts: typeof counts.value
    }>(
      withQuery('/pending', {
        item_type: itemType.value === 'all' ? undefined : itemType.value,
        status: status.value,
        source_type: source.value || undefined,
        q: search.value.trim() || undefined,
        low_confidence: lowConfidence.value || undefined,
        page: page.value,
        page_size: pageSize,
      }),
    )
    items.value = data.items
    const stillPending = new Set(
      data.items.filter((item) => item.status === 'pending').map((item) => item.id),
    )
    selectedIds.value = selectedIds.value.filter((id) => stillPending.has(id))
    total.value = data.total
    counts.value = data.counts || { question: 0, knowledge: 0, total: 0 }
  } catch (err: any) {
    store.toast(err?.message || '待审列表加载失败', 'error')
  } finally {
    loading.value = false
  }
}

function applyFilters(): void {
  page.value = 1
  selectedIds.value = []
  load()
}

function changePage(value: number): void {
  page.value = value
  load()
}

function setItemType(value: 'all' | 'question' | 'knowledge'): void {
  itemType.value = value
  applyFilters()
}

async function openDetail(item: PendingItem): Promise<void> {
  try {
    detail.value = await api.get<PendingItem>(`/pending/${item.id}`)
    selectedKnowledge.value = []
    detailOpen.value = true
  } catch (err: any) {
    store.toast(err?.message || '详情加载失败', 'error')
  }
}

async function approve(item: PendingItem, knowledgeIds: number[] = []): Promise<void> {
  try {
    await api.post(`/pending/${item.id}/approve`, { knowledge_ids: knowledgeIds })
    store.toast('已通过并写入正式库', 'success')
    detailOpen.value = false
    await Promise.all([load(), store.loadBadges(), store.fetchTree()])
  } catch (err: any) {
    if (err?.status === 409) {
      store.toast('已存在相同内容，请使用「合并」', 'error')
      openMerge(item)
    } else {
      store.toast(err?.message || '通过失败', 'error')
    }
  }
}

async function reject(item: PendingItem): Promise<void> {
  const note = window.prompt('拒绝原因（可留空）：', '')
  if (note === null) return
  try {
    await api.post(`/pending/${item.id}/reject`, { reviewer_note: note })
    store.toast('已拒绝，保留审计记录', 'success')
    detailOpen.value = false
    await Promise.all([load(), store.loadBadges()])
  } catch (err: any) {
    store.toast(err?.message || '拒绝失败', 'error')
  }
}

function openEdit(item: PendingItem): void {
  editing.value = item
  const meta = metaOf(item)
  editForm.stem = item.stem || ''
  editForm.answer = item.answer || ''
  editForm.knowledge_title = item.knowledge_title || ''
  editForm.knowledge_content = item.knowledge_content || ''
  editForm.tags_text = (meta.tags || []).join(', ')
  editForm.category_path = meta.category_path || meta.knowledge_category_path || ''
  editForm.difficulty = meta.difficulty ?? ''
  editForm.frequency = meta.frequency || ''
  editForm.kind = meta.kind || 'concept'
  editForm.aliases_text = (meta.aliases || []).join(', ')
  editForm.reviewer_note = item.reviewer_note || ''
  detailOpen.value = false
  editOpen.value = true
}

function splitList(value: string): string[] {
  return value
    .split(/[,，、;；\n]+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

async function saveEdit(thenApprove = false): Promise<void> {
  if (!editing.value) return
  const item = editing.value
  const meta: Record<string, any> = { ...(item.suggested_meta || {}) }
  meta.tags = splitList(editForm.tags_text)
  meta.difficulty = editForm.difficulty === '' ? null : Number(editForm.difficulty)
  meta.frequency = editForm.frequency || null
  if (editForm.category_path) {
    meta.category_path = editForm.category_path
    delete meta.category_id
    delete meta.knowledge_category_id
  }
  if (item.item_type === 'knowledge') {
    meta.kind = editForm.kind
    meta.aliases = splitList(editForm.aliases_text)
  }
  const patchPayload: Record<string, unknown> = {
    suggested_meta: meta,
    reviewer_note: editForm.reviewer_note || null,
  }
  if (item.item_type === 'question') {
    patchPayload.stem = editForm.stem
    patchPayload.answer = editForm.answer
  } else {
    patchPayload.knowledge_title = editForm.knowledge_title
    patchPayload.knowledge_content = editForm.knowledge_content
  }
  editSaving.value = true
  try {
    await api.patch(`/pending/${item.id}`, patchPayload)
    if (thenApprove) {
      const approvePayload: Record<string, unknown> = {
        category_path: editForm.category_path || undefined,
        tags: splitList(editForm.tags_text),
        difficulty: editForm.difficulty === '' ? null : Number(editForm.difficulty),
        frequency: editForm.frequency || null,
      }
      if (item.item_type === 'question') {
        approvePayload.stem = editForm.stem
        approvePayload.answer = editForm.answer
      } else {
        approvePayload.knowledge_title = editForm.knowledge_title
        approvePayload.knowledge_content = editForm.knowledge_content
        approvePayload.kind = editForm.kind
        approvePayload.aliases = splitList(editForm.aliases_text)
      }
      await api.post(`/pending/${item.id}/approve`, approvePayload)
      store.toast('已保存并通过入库', 'success')
    } else {
      store.toast('待审项已保存', 'success')
    }
    editOpen.value = false
    await Promise.all([load(), store.loadBadges(), store.fetchTree()])
  } catch (err: any) {
    store.toast(err?.message || '保存失败', 'error')
  } finally {
    editSaving.value = false
  }
}

function openMerge(item: PendingItem): void {
  mergeItem.value = item
  mergeTargetType.value = item.item_type
  mergeQuery.value = item.item_type === 'question' ? item.stem || '' : item.knowledge_title || ''
  mergeResults.value = []
  mergeSelected.value = null
  mergeOpen.value = true
  searchMerge()
}

async function searchMerge(): Promise<void> {
  mergeLoading.value = true
  try {
    if (mergeTargetType.value === 'question') {
      const data = await api.get<any>(
        withQuery('/questions', {
          q: mergeQuery.value.trim() || undefined,
          status: 'all',
          page_size: 20,
        }),
      )
      mergeResults.value = data.items.map((row: any) => ({ id: row.id, title: row.stem, sub: row.category_path }))
    } else if (mergeTargetType.value === 'knowledge') {
      const data = await api.get<any>(
        withQuery('/knowledge', {
          q: mergeQuery.value.trim() || undefined,
          status: 'all',
          page_size: 20,
        }),
      )
      mergeResults.value = data.items.map((row: any) => ({ id: row.id, title: row.title, sub: row.category_path }))
    } else {
      const data = await api.get<any>(
        withQuery('/pending', {
          q: mergeQuery.value.trim() || undefined,
          status: 'pending',
          page_size: 20,
        }),
      )
      mergeResults.value = data.items
        .filter((row: any) => row.id !== mergeItem.value?.id)
        .map((row: any) => ({
          id: row.id,
          title: row.item_type === 'question' ? row.stem : row.knowledge_title,
          sub: `#${row.id} · ${row.item_type}`,
        }))
    }
  } catch (err: any) {
    store.toast(err?.message || '搜索目标失败', 'error')
  } finally {
    mergeLoading.value = false
  }
}

async function merge(): Promise<void> {
  if (!mergeItem.value || !mergeSelected.value) {
    store.toast('请选择合并目标', 'error')
    return
  }
  merging.value = true
  try {
    await api.post(`/pending/${mergeItem.value.id}/merge`, {
      target_type: mergeTargetType.value,
      target_id: mergeSelected.value,
    })
    store.toast('已合并，来源已保留', 'success')
    mergeOpen.value = false
    detailOpen.value = false
    await Promise.all([load(), store.loadBadges()])
  } catch (err: any) {
    store.toast(err?.message || '合并失败', 'error')
  } finally {
    merging.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <button
        v-for="tab in pendingTabs"
        :key="tab.key"
        class="btn sm"
        :class="{ ghost: itemType !== tab.key }"
        @click="setItemType(tab.key as any)"
      >
        {{ tab.label }}
      </button>
      <select v-model="status" @change="applyFilters">
        <option value="pending">待审</option>
        <option value="approved">已通过</option>
        <option value="rejected">已拒绝</option>
        <option value="merged">已合并</option>
        <option value="all">全部</option>
      </select>
      <select v-model="source" @change="applyFilters">
        <option value="">全部来源</option>
        <option value="crawler">爬虫</option>
        <option value="import">导入</option>
        <option value="manual">手动</option>
        <option value="ai">AI</option>
      </select>
      <input v-model="search" placeholder="搜索题干 / 标题 / 来源" @keyup.enter="applyFilters" />
      <button class="btn ghost sm" @click="applyFilters">搜索</button>
      <label style="display: flex; align-items: center; gap: 6px; font-size: 13.5px; color: var(--ink2)">
        <input v-model="lowConfidence" type="checkbox" @change="applyFilters" />
        只看低置信度
      </label>
      <div style="flex: 1"></div>
      <template v-if="status === 'pending' && items.length">
        <label style="display: flex; align-items: center; gap: 6px; font-size: 13.5px; color: var(--ink2)">
          <input type="checkbox" :checked="allOnPageSelected" @change="toggleSelectAll" />
          全选本页
        </label>
        <button
          class="btn green sm"
          :disabled="!selectedIds.length || bulkRunning"
          @click="bulkApprove"
        >
          批量通过（{{ selectedIds.length }}）
        </button>
      </template>
      <button class="btn ghost sm" @click="load">刷新</button>
    </div>

    <div class="section-title">
      {{ status === 'pending' ? '待审队列' : '审核记录' }}（{{ total }}）
    </div>
    <div v-if="loading" class="card empty">加载中…</div>
    <div v-else-if="!items.length" class="card empty">暂无待审项，导入或采集后会自动进入这里</div>
    <div v-else>
      <div v-for="item in items" :key="item.id" class="pend-item">
        <div class="pend-head">
          <input
            v-if="item.status === 'pending' && status === 'pending'"
            type="checkbox"
            :checked="selectedIds.includes(item.id)"
            title="选中后可在工具栏批量通过"
            @change="toggleSelect(item.id)"
          />
          <span class="tag teal">{{ item.source_type === 'crawler' ? '爬虫' : item.source_type === 'import' ? '导入' : item.source_type === 'manual' ? '手动' : 'AI' }}</span>
          <span class="tag blue">{{ item.item_type === 'question' ? '题目' : '知识' }}</span>
          <span class="tag" :class="confidenceTone(item)">置信度 {{ confidence(item) }}%</span>
          <span v-if="dupText(item)" class="tag orange">{{ dupText(item) }}</span>
          <span v-if="item.status !== 'pending'" class="tag gray">{{ item.status }}</span>
        </div>
        <div class="pend-stem">{{ itemTitle(item) }}</div>
        <div style="font-size: 14px; color: var(--ink2); white-space: pre-wrap">{{ itemBody(item) }}</div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px">
          <span v-for="tag in metaOf(item).tags || []" :key="tag" class="tag teal">{{ tag }}</span>
          <span v-if="metaOf(item).category_path" class="tag gray">{{ metaOf(item).category_path }}</span>
          <span v-if="metaOf(item).difficulty" class="tag gray">难度 {{ metaOf(item).difficulty }}</span>
          <span v-if="metaOf(item).frequency" class="tag" :class="frequencyTone(metaOf(item).frequency)">
            {{ frequencyText(metaOf(item).frequency) }}
          </span>
        </div>
        <div class="pend-origin" style="margin-top: 6px">
          来源：{{ item.origin_ref || '—' }} · 进入待审 {{ formatDateTime(item.created_at) }}
        </div>
        <div class="pend-actions">
          <button class="btn sm green" @click="approve(item)">通过入库</button>
          <button class="btn ghost sm" @click="openMerge(item)">合并重复</button>
          <button class="btn ghost sm" @click="openEdit(item)">编辑</button>
          <button class="btn ghost sm" @click="openDetail(item)">详情</button>
          <button class="btn danger-ghost sm" @click="reject(item)">拒绝</button>
        </div>
      </div>
    </div>
    <Pagination :page="page" :page-size="pageSize" :total="total" @update:page="changePage" />

    <Modal :open="detailOpen" title="待审详情" wide @close="detailOpen = false">
      <template v-if="detail">
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px">
          <span class="tag teal">{{ sourceText(detail.source_type) }}</span>
          <span class="tag blue">{{ detail.item_type === 'question' ? '题目' : '知识' }}</span>
          <span class="tag" :class="confidenceTone(detail)">置信度 {{ confidence(detail) }}%</span>
          <span v-if="dupText(detail)" class="tag orange">{{ dupText(detail) }}</span>
        </div>
        <h3 style="font-size: 18px; margin-bottom: 10px">{{ itemTitle(detail) }}</h3>
        <div class="panswer" style="margin-top: 0">{{ itemBody(detail) || '—' }}</div>
        <div class="list-sub" style="margin-top: 10px">来源：{{ detail.origin_ref || '—' }}</div>

        <div class="section-title" style="font-size: 14px">建议元数据</div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <span v-for="tag in metaOf(detail).tags || []" :key="tag" class="tag teal">{{ tag }}</span>
          <span v-if="metaOf(detail).category_path" class="tag gray">{{ metaOf(detail).category_path }}</span>
          <span v-if="metaOf(detail).difficulty" class="tag gray">难度 {{ metaOf(detail).difficulty }}</span>
          <span v-if="metaOf(detail).frequency" class="tag amber">{{ frequencyText(metaOf(detail).frequency) }}</span>
          <span class="tag gray">规则命中 {{ (metaOf(detail).matched_rules || []).length }}</span>
        </div>

        <div class="section-title" style="font-size: 14px">相似内容</div>
        <div v-if="detail.similar?.length">
          <div v-for="similar in detail.similar" :key="`${similar.type}-${similar.id}`" class="list-row">
            <div class="list-main">
              <div class="list-title">{{ similar.title }}</div>
              <div class="list-sub">
                {{ similar.type }} #{{ similar.id }} ·
                {{ similar.exact ? '精确命中' : `汉明距离 ${similar.distance}` }}
              </div>
            </div>
          </div>
        </div>
        <div v-else class="list-sub">没有发现相似内容</div>

        <template v-if="detail.item_type === 'question' && detail.suggested_knowledge?.length">
          <div class="section-title" style="font-size: 14px">建议关联知识（可勾选）</div>
          <label
            v-for="knowledge in detail.suggested_knowledge"
            :key="knowledge.id"
            class="list-row"
            style="cursor: pointer"
          >
            <input v-model="selectedKnowledge" type="checkbox" :value="knowledge.id" />
            <div class="list-main">
              <div class="list-title">{{ knowledge.title }}</div>
              <div class="list-sub">{{ knowledge.category_path }} · {{ knowledge.kind }}</div>
            </div>
            <span class="tag blue">{{ knowledge.relation_type }}</span>
          </label>
        </template>

        <div v-if="detail.raw_text" class="section-title" style="font-size: 14px">原始内容快照</div>
        <div v-if="detail.raw_text" class="log-box">{{ detail.raw_text }}</div>

        <div class="form-actions" style="margin-top: 20px">
          <button class="btn green" @click="approve(detail, selectedKnowledge)">通过入库</button>
          <button class="btn ghost" @click="openMerge(detail)">合并</button>
          <button class="btn ghost" @click="openEdit(detail)">编辑</button>
          <button class="btn danger-ghost" @click="reject(detail)">拒绝</button>
        </div>
      </template>
    </Modal>

    <Modal :open="editOpen" title="编辑待审项" wide @close="editOpen = false">
      <template v-if="editing">
        <div class="form-grid">
          <template v-if="editing.item_type === 'question'">
            <div class="field full">
              <label>题干</label>
              <textarea v-model="editForm.stem" class="textarea" rows="2" />
            </div>
            <div class="field full">
              <label>答案</label>
              <textarea v-model="editForm.answer" class="textarea" rows="4" />
            </div>
          </template>
          <template v-else>
            <div class="field full">
              <label>知识标题</label>
              <input v-model="editForm.knowledge_title" class="input" />
            </div>
            <div class="field full">
              <label>知识内容</label>
              <textarea v-model="editForm.knowledge_content" class="textarea" rows="5" />
            </div>
            <div class="field">
              <label>知识类型</label>
              <select v-model="editForm.kind" class="select">
                <option v-for="option in kindOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>别名</label>
              <input v-model="editForm.aliases_text" class="input" placeholder="逗号分隔" />
            </div>
          </template>
          <div class="field">
            <label>分类路径</label>
            <input v-model="editForm.category_path" class="input" placeholder="后端开发/计算机网络/TCP" />
          </div>
          <div class="field">
            <label>标签</label>
            <input v-model="editForm.tags_text" class="input" placeholder="逗号分隔" />
          </div>
          <div class="field">
            <label>难度</label>
            <select v-model="editForm.difficulty" class="select">
              <option value="">未标注</option>
              <option :value="1">1</option>
              <option :value="2">2</option>
              <option :value="3">3</option>
              <option :value="4">4</option>
              <option :value="5">5</option>
            </select>
          </div>
          <div class="field">
            <label>频率</label>
            <select v-model="editForm.frequency" class="select">
              <option value="">未标注</option>
              <option value="high">高频</option>
              <option value="mid">中频</option>
              <option value="low">低频</option>
            </select>
          </div>
          <div class="field full">
            <label>审核备注</label>
            <input v-model="editForm.reviewer_note" class="input" placeholder="可留空" />
          </div>
        </div>
        <div class="form-actions">
          <button class="btn ghost" @click="editOpen = false">取消</button>
          <button class="btn ghost" :disabled="editSaving" @click="saveEdit(false)">仅保存</button>
          <button class="btn green" :disabled="editSaving" @click="saveEdit(true)">保存并通过</button>
        </div>
      </template>
    </Modal>

    <Modal :open="mergeOpen" title="合并重复内容" wide @close="mergeOpen = false">
      <template v-if="mergeItem">
        <div class="board-banner" style="margin-bottom: 14px">
          <b>待合并</b>
          <span>{{ itemTitle(mergeItem) }}</span>
        </div>
        <div class="toolbar">
          <select v-model="mergeTargetType" @change="searchMerge">
            <option value="question">已有题目</option>
            <option value="knowledge">已有知识</option>
            <option value="pending">其他待审项</option>
          </select>
          <input v-model="mergeQuery" placeholder="搜索目标" @keyup.enter="searchMerge" />
          <button class="btn ghost sm" @click="searchMerge">搜索</button>
        </div>
        <div v-if="mergeLoading" class="empty">搜索中…</div>
        <div v-else style="max-height: 340px; overflow-y: auto">
          <label
            v-for="target in mergeResults"
            :key="target.id"
            class="list-row"
            style="cursor: pointer"
          >
            <input v-model="mergeSelected" type="radio" :value="target.id" />
            <div class="list-main">
              <div class="list-title">{{ target.title }}</div>
              <div class="list-sub">{{ target.sub }}</div>
            </div>
          </label>
          <div v-if="!mergeResults.length" class="empty">没有搜索结果</div>
        </div>
        <div class="form-actions" style="margin-top: 16px">
          <button class="btn ghost" @click="mergeOpen = false">取消</button>
          <button class="btn" :disabled="merging || !mergeSelected" @click="merge">
            {{ merging ? '合并中…' : '确认合并（保留来源）' }}
          </button>
        </div>
      </template>
    </Modal>
  </div>
</template>
