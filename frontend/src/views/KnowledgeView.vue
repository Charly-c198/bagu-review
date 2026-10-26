<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { api, withQuery } from '../api/client'
import type { GenerateQuestionsResult, Knowledge } from '../api/types'
import Modal from '../components/Modal.vue'
import Pagination from '../components/Pagination.vue'
import QualityPanel from '../components/QualityPanel.vue'
import { useAppStore } from '../stores/app'
import {
  formatDate,
  formatDateTime,
  kindText,
  masteryText,
  masteryTone,
  sourceText,
} from '../utils/labels'

const store = useAppStore()
const router = useRouter()

const items = ref<Knowledge[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(true)

const search = ref('')
const kind = ref('')
const status = ref('active')

const detail = ref<Knowledge | null>(null)
const detailOpen = ref(false)
const formOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)

// M3b 题库生产：围绕该知识点生成题目，结果一律进入待审区。
const genOpen = ref(false)
const genLoading = ref(false)
const genCount = ref(3)
const genDifficulty = ref<number | ''>('')
const genResult = ref<GenerateQuestionsResult | null>(null)

function openGenerate(item: Knowledge): void {
  genResult.value = null
  genCount.value = 3
  genDifficulty.value = ''
  genOpen.value = true
}

async function generateQuestions(item: Knowledge): Promise<void> {
  genLoading.value = true
  try {
    const result = await api.post<GenerateQuestionsResult>('/ai/generate-questions', {
      knowledge_id: item.id,
      count: genCount.value,
      difficulty: genDifficulty.value === '' ? null : Number(genDifficulty.value),
    })
    genResult.value = result
    if (result.generated) {
      store.toast(`已生成 ${result.generated} 道题进入待审区`, 'success')
      await store.loadBadges()
    } else {
      store.toast('没有生成新题目（可能与已有题目重复）', 'info')
    }
  } catch (err: any) {
    const reason =
      err?.code === 'AI_NOT_CONFIGURED'
        ? '未配置 AI，请在设置页检查 BAJIU_AI_* 环境变量'
        : err?.message || '生成失败'
    store.toast(reason, 'error')
  } finally {
    genLoading.value = false
  }
}

function goPending(): void {
  genOpen.value = false
  detailOpen.value = false
  router.push('/pending')
}

const form = reactive({
  title: '',
  content: '',
  kind: 'concept',
  category_path: '',
  aliases_text: '',
  status: 'active',
  send_to_pending: false,
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

const kindOptions = [
  { value: 'concept', label: '概念' },
  { value: 'principle', label: '原理' },
  { value: 'process', label: '流程' },
  { value: 'comparison', label: '对比' },
  { value: 'pitfall', label: '易错点' },
  { value: 'other', label: '其他' },
]

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<{ items: Knowledge[]; total: number }>(
      withQuery('/knowledge', {
        category_id: store.boardParam,
        q: search.value.trim() || undefined,
        kind: kind.value || undefined,
        status: status.value,
        page: page.value,
        page_size: pageSize,
      }),
    )
    items.value = data.items
    total.value = data.total
  } catch (err: any) {
    store.toast(err?.message || '知识库加载失败', 'error')
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
  form.title = ''
  form.content = ''
  form.kind = 'concept'
  form.category_path = ''
  form.aliases_text = ''
  form.status = 'active'
  form.send_to_pending = false
  editingId.value = null
}

function openCreate(): void {
  resetForm()
  formOpen.value = true
}

function openEdit(item: Knowledge): void {
  editingId.value = item.id
  form.title = item.title
  form.content = item.content
  form.kind = item.kind
  form.category_path = item.category_path || ''
  form.aliases_text = (item.aliases || []).join(', ')
  form.status = item.status
  form.send_to_pending = false
  detailOpen.value = false
  formOpen.value = true
}

async function save(): Promise<void> {
  if (!form.title.trim() || !form.content.trim()) {
    store.toast('标题和内容不能为空', 'error')
    return
  }
  saving.value = true
  const payload: Record<string, unknown> = {
    title: form.title.trim(),
    content: form.content.trim(),
    kind: form.kind,
    category_path: form.category_path || null,
    aliases: form.aliases_text
      .split(/[,，、;；\n]+/)
      .map((item) => item.trim())
      .filter(Boolean),
    status: form.status,
  }
  if (!editingId.value) payload.send_to_pending = form.send_to_pending
  try {
    if (editingId.value) {
      await api.patch(`/knowledge/${editingId.value}`, payload)
      store.toast('知识条目已保存', 'success')
    } else {
      const result: any = await api.post('/knowledge', payload)
      store.toast(result?.pending ? '已进入待审区' : '知识条目已创建', 'success')
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

async function openDetail(item: Knowledge): Promise<void> {
  try {
    detail.value = await api.get<Knowledge>(`/knowledge/${item.id}`)
    detailOpen.value = true
  } catch (err: any) {
    store.toast(err?.message || '详情加载失败', 'error')
  }
}

async function archive(item: Knowledge): Promise<void> {
  if (!window.confirm('确定归档该知识条目？归档后不再出现在知识库默认列表。')) return
  try {
    await api.post(`/knowledge/${item.id}/archive`)
    store.toast('已归档', 'success')
    detailOpen.value = false
    await load()
  } catch (err: any) {
    store.toast(err?.message || '归档失败', 'error')
  }
}

async function remove(item: Knowledge): Promise<void> {
  if (!window.confirm('确定软删除该知识条目？关联的题目不会删除。')) return
  try {
    await api.delete(`/knowledge/${item.id}`)
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
      <input v-model="search" placeholder="搜索标题 / 内容 / 别名" @keyup.enter="applySearch" />
      <button class="btn ghost sm" @click="applySearch">搜索</button>
      <select v-model="kind" @change="applySearch">
        <option value="">全部类型</option>
        <option v-for="option in kindOptions" :key="option.value" :value="option.value">
          {{ option.label }}
        </option>
      </select>
      <select v-model="status" @change="applySearch">
        <option value="active">正式知识</option>
        <option value="draft">草稿</option>
        <option value="archived">已归档</option>
        <option value="all">全部状态</option>
      </select>
      <div style="flex: 1"></div>
      <button class="btn" @click="openCreate">+ 新建知识</button>
    </div>

    <div v-if="loading" class="card empty">加载中…</div>
    <div v-else class="card" style="padding: 6px 10px">
      <table>
        <colgroup>
          <col style="width: 38%" />
          <col style="width: 10%" />
          <col style="width: 18%" />
          <col style="width: 10%" />
          <col style="width: 12%" />
          <col style="width: 12%" />
        </colgroup>
        <thead>
          <tr>
            <th>知识条目</th>
            <th>类型</th>
            <th>分类</th>
            <th>关联题目</th>
            <th>来源</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td>
              <div style="font-weight: 600; cursor: pointer" @click="openDetail(item)">{{ item.title }}</div>
              <div class="list-sub" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ item.content }}
              </div>
            </td>
            <td><span class="tag blue">{{ kindText(item.kind) }}</span></td>
            <td style="color: var(--ink2); font-size: 13px">{{ item.category_path || '未分类' }}</td>
            <td><span class="tag gray">{{ item.question_count || 0 }} 题</span></td>
            <td><span class="tag gray">{{ sourceText(item.source_type) }}</span></td>
            <td>
              <div style="display: flex; gap: 6px">
                <button class="btn ghost sm" @click="openDetail(item)">详情</button>
                <button class="btn ghost sm" @click="openEdit(item)">编辑</button>
              </div>
            </td>
          </tr>
          <tr v-if="!items.length">
            <td colspan="6"><div class="empty">没有符合条件的知识条目</div></td>
          </tr>
        </tbody>
      </table>
    </div>
    <Pagination :page="page" :page-size="pageSize" :total="total" @update:page="changePage" />

    <Modal :open="formOpen" :title="editingId ? '编辑知识条目' : '新建知识条目'" wide @close="formOpen = false">
      <div class="form-grid">
        <div class="field full">
          <label>标题 *</label>
          <input v-model="form.title" class="input" placeholder="例如：TCP 三次握手" />
        </div>
        <div class="field">
          <label>类型</label>
          <select v-model="form.kind" class="select">
            <option v-for="option in kindOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>状态</label>
          <select v-model="form.status" class="select">
            <option value="active">正式知识</option>
            <option value="draft">草稿</option>
          </select>
        </div>
        <div class="field">
          <label>分类路径</label>
          <input v-model="form.category_path" class="input" list="knowledge-category-options" placeholder="后端开发/计算机网络/TCP" />
        </div>
        <div class="field">
          <label>别名 / 同义标题（逗号分隔）</label>
          <input v-model="form.aliases_text" class="input" placeholder="三次握手, TCP握手" />
        </div>
        <div class="field full">
          <label>内容 *</label>
          <textarea v-model="form.content" class="textarea" rows="7" placeholder="可独立复用的知识内容：定义、原理、流程、对比或易错点" />
        </div>
        <div v-if="!editingId" class="field full">
          <label style="display: flex; align-items: center; gap: 8px">
            <input v-model="form.send_to_pending" type="checkbox" />
            先进入待审区（默认直接入知识库）
          </label>
        </div>
      </div>
      <datalist id="knowledge-category-options">
        <option v-for="path in categoryPaths" :key="path" :value="path" />
      </datalist>
      <div class="form-actions">
        <button class="btn ghost" @click="formOpen = false">取消</button>
        <button class="btn" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
      </div>
    </Modal>

    <Modal :open="detailOpen" title="知识详情" wide @close="detailOpen = false">
      <template v-if="detail">
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px">
          <span class="tag blue">{{ kindText(detail.kind) }}</span>
          <span class="tag gray">{{ detail.category_path || '未分类' }}</span>
          <span class="tag gray">{{ sourceText(detail.source_type) }}</span>
          <span v-if="detail.status !== 'active'" class="tag amber">{{ detail.status }}</span>
        </div>
        <h3 style="font-size: 19px; margin-bottom: 12px">{{ detail.title }}</h3>
        <div class="panswer" style="margin-top: 0">{{ detail.content }}</div>
        <div v-if="detail.aliases?.length" style="margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap">
          <span v-for="alias in detail.aliases" :key="alias" class="tag gray">别名：{{ alias }}</span>
        </div>

        <div class="section-title" style="font-size: 14px">关联题目（{{ detail.questions?.length || 0 }}）</div>
        <div v-if="detail.questions?.length">
          <div v-for="question in detail.questions" :key="question.id" class="list-row">
            <div class="list-main">
              <div class="list-title">{{ question.stem }}</div>
              <div class="list-sub">关系：{{ question.relation_type }}</div>
            </div>
            <span class="tag" :class="masteryTone(question.mastery)">{{ masteryText(question.mastery) }}</span>
          </div>
        </div>
        <div v-else class="list-sub">暂无关联题目</div>

        <div class="section-title" style="font-size: 14px">来源溯源</div>
        <div v-if="detail.origins?.length">
          <div v-for="origin in detail.origins" :key="origin.id" class="list-sub mono">
            {{ sourceText(origin.source_type) }} · {{ origin.origin_ref || '—' }} ·
            {{ formatDateTime(origin.created_at) }}
          </div>
        </div>
        <div v-else class="list-sub">暂无来源记录</div>

        <div class="section-title" style="font-size: 14px">AI 质量审查</div>
        <QualityPanel target-type="knowledge" :target-id="detail.id" />

        <div class="section-title" style="font-size: 14px">AI 出题（M3b）</div>
        <div class="list-sub">
          围绕本知识点生成新题；AI 产出的题目只进入待审区，审核通过后才写入题库。
        </div>
        <div class="form-actions" style="justify-content: flex-start; margin-top: 10px">
          <button class="btn ghost" @click="openGenerate(detail)">AI 生成题目</button>
        </div>

        <div class="form-actions" style="margin-top: 20px">
          <button class="btn ghost" @click="openEdit(detail)">编辑</button>
          <button class="btn ghost" @click="archive(detail)">归档</button>
          <button class="btn danger-ghost" @click="remove(detail)">删除</button>
        </div>
      </template>
    </Modal>

    <Modal :open="genOpen" title="AI 生成题目" wide @close="genOpen = false">
      <template v-if="detail">
        <div class="board-banner" style="margin-bottom: 14px">
          <b>知识点</b>
          <span>{{ detail.title }}</span>
        </div>
        <div class="form-grid">
          <div class="field">
            <label>生成数量</label>
            <select v-model.number="genCount" class="select">
              <option v-for="n in [1, 2, 3, 5, 8]" :key="n" :value="n">{{ n }} 道</option>
            </select>
          </div>
          <div class="field">
            <label>目标难度</label>
            <select v-model="genDifficulty" class="select">
              <option value="">由 AI 决定</option>
              <option :value="1">1 入门</option>
              <option :value="2">2</option>
              <option :value="3">3</option>
              <option :value="4">4</option>
              <option :value="5">5 困难</option>
            </select>
          </div>
        </div>
        <div v-if="genResult" class="gen-result">
          <div class="list-sub">
            请求 {{ genResult.requested }} 道，生成 {{ genResult.generated }} 道，
            跳过 {{ genResult.skipped }} 道（重复或为空）。
          </div>
          <div v-for="item in genResult.items" :key="item.id" class="gen-item">
            <div style="font-weight: 500">{{ item.stem }}</div>
            <div class="list-sub">
              {{ item.suggested_meta?.category_path || '未分类' }} ·
              难度 {{ item.suggested_meta?.difficulty ?? '—' }} ·
              置信度 {{ Math.round((item.parse_confidence ?? 0) * 100) }}%
            </div>
            <div class="suggestion-text">{{ item.answer }}</div>
          </div>
        </div>
        <div class="form-actions">
          <button class="btn ghost" @click="genOpen = false">关闭</button>
          <button
            v-if="genResult?.generated"
            class="btn green"
            @click="goPending"
          >前往待审区审核</button>
          <button class="btn" :disabled="genLoading" @click="generateQuestions(detail)">
            {{ genLoading ? '生成中，可能需要数十秒…' : '开始生成' }}
          </button>
        </div>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.gen-result {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 6px;
}
.gen-item {
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
