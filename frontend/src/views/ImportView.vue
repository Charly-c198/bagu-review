<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { api } from '../api/client'
import type { ImportBatch } from '../api/types'
import Modal from '../components/Modal.vue'
import { useAppStore } from '../stores/app'
import {
  batchStatusText,
  batchStatusTone,
  formatDateTime,
} from '../utils/labels'

const store = useAppStore()

const fileInput = ref<HTMLInputElement | null>(null)
const dragging = ref(false)
const importing = ref(false)
const result = ref<any | null>(null)
const pasteText = ref('')
const pasteFormat = ref('md')

const batches = ref<ImportBatch[]>([])
const batchesLoading = ref(true)
const batchDetail = ref<any | null>(null)
const batchDetailOpen = ref(false)

const templates: Record<string, string> = {
  md: `## 题目：什么是 TCP 三次握手？
**答案**：客户端发送 SYN，服务端返回 SYN-ACK，客户端再发送 ACK。
**要点**：确认双方收发能力；防止历史连接；资源分配时机
**标签**：TCP,计算机网络
**难度**：3
**频率**：high
**公司**：腾讯,字节
**分类**：后端开发/计算机网络/TCP

## 知识：TCP 三次握手
**类型**：process
**分类**：后端开发/计算机网络/TCP
**别名**：三次握手,TCP握手
**内容**：客户端发送 SYN，服务端返回 SYN-ACK，客户端再发送 ACK。
`,
  csv: `stem,answer,key_points,category_path,tags,difficulty,frequency,companies
什么是进程？,进程是资源分配的最小单位,资源分配单位；独立地址空间,后端开发/操作系统/进程管理,操作系统,2,high,阿里
`,
  json: `{
  "schema_version": 1,
  "questions": [
    {
      "stem": "什么是 RAG？",
      "answer": "检索增强生成。",
      "key_points": ["检索", "生成"],
      "category_path": ["AI-Agent", "Agent", "RAG"],
      "tags": ["RAG"],
      "difficulty": 2,
      "frequency": "high"
    }
  ],
  "knowledge": [
    {
      "ref": "kp-rag",
      "title": "RAG",
      "content": "检索增强生成：先检索相关片段，再交给大模型生成答案。",
      "kind": "concept",
      "category_path": ["AI-Agent", "Agent", "RAG"]
    }
  ],
  "links": [
    {"question_index": 0, "knowledge_ref": "kp-rag", "relation_type": "related"}
  ]
}
`,
}

function formatFromName(name: string): string | null {
  const lower = name.toLowerCase()
  if (lower.endsWith('.md') || lower.endsWith('.markdown') || lower.endsWith('.txt')) return 'md'
  if (lower.endsWith('.csv')) return 'csv'
  if (lower.endsWith('.json')) return 'json'
  return null
}

async function importFile(file: File): Promise<void> {
  if (file.name.toLowerCase().endsWith('.xlsx') || file.name.toLowerCase().endsWith('.xls')) {
    store.toast('M1 不直接解析 Excel，请另存为 UTF-8 CSV 后导入', 'error')
    return
  }
  const format = formatFromName(file.name)
  if (!format) {
    store.toast('仅支持 Markdown / CSV / JSON 文件', 'error')
    return
  }
  importing.value = true
  result.value = null
  const form = new FormData()
  form.append('file', file)
  form.append('filename', file.name)
  try {
    result.value = await api.upload(`/import/${format}`, form)
    store.toast('导入完成，题目与知识已进入待审区', 'success')
    await Promise.all([loadBatches(), store.loadBadges()])
  } catch (err: any) {
    if (err?.data?.batch) result.value = { batch: err.data.batch, errors: [{ message: err.message }], warnings: [] }
    store.toast(err?.message || '导入失败', 'error')
  } finally {
    importing.value = false
    if (fileInput.value) fileInput.value.value = ''
  }
}

function onFileChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) importFile(file)
}

function onDrop(event: DragEvent): void {
  dragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) importFile(file)
}

async function importPaste(): Promise<void> {
  if (!pasteText.value.trim()) {
    store.toast('请先粘贴内容', 'error')
    return
  }
  importing.value = true
  result.value = null
  const form = new FormData()
  form.append('text', pasteText.value)
  form.append('filename', `paste.${pasteFormat.value === 'md' ? 'md' : pasteFormat.value}`)
  try {
    result.value = await api.upload(`/import/${pasteFormat.value}`, form)
    store.toast('粘贴内容已导入', 'success')
    await Promise.all([loadBatches(), store.loadBadges()])
  } catch (err: any) {
    if (err?.data?.batch) result.value = { batch: err.data.batch, errors: [{ message: err.message }], warnings: [] }
    store.toast(err?.message || '导入失败', 'error')
  } finally {
    importing.value = false
  }
}

async function loadBatches(): Promise<void> {
  batchesLoading.value = true
  try {
    const data = await api.get<{ items: ImportBatch[] }>('/import/batches?page_size=20')
    batches.value = data.items
  } catch (err: any) {
    store.toast(err?.message || '批次加载失败', 'error')
  } finally {
    batchesLoading.value = false
  }
}

async function openBatch(batch: ImportBatch): Promise<void> {
  try {
    batchDetail.value = await api.get(`/import/batches/${batch.id}`)
    batchDetailOpen.value = true
  } catch (err: any) {
    store.toast(err?.message || '批次详情加载失败', 'error')
  }
}

async function deleteBatch(batch: ImportBatch): Promise<void> {
  if (!window.confirm(`删除批次「${batch.filename}」？将移除该批次来源，无其他来源的内容会归档。`)) return
  try {
    const data = await api.delete<any>(`/import/batches/${batch.id}`)
    store.toast(
      `批次已删除，归档题目 ${data.archived_questions}、知识 ${data.archived_knowledge}`,
      'success',
    )
    await Promise.all([loadBatches(), store.loadBadges(), store.fetchTree()])
  } catch (err: any) {
    store.toast(err?.message || '删除失败', 'error')
  }
}

function downloadTemplate(format: string): void {
  const blob = new Blob([templates[format]], { type: 'text/plain;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `bajiu-template.${format}`
  link.click()
  URL.revokeObjectURL(link.href)
}

onMounted(loadBatches)
</script>

<template>
  <div>
    <div class="section-title">导入新题库</div>
    <div
      class="import-drop"
      :class="{ dragging }"
      @click="fileInput?.click()"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <div style="font-size: 34px; margin-bottom: 8px">↑</div>
      <div style="font-weight: 600; font-size: 16px">
        {{ importing ? '正在解析并导入…' : '拖拽文件到这里，或点击选择' }}
      </div>
      <div style="color: var(--ink3); font-size: 13.5px; margin-top: 6px">
        支持 Markdown（问答切分 + 知识抽取）、CSV（一行一题）、JSON（题目/知识/关联）；
        默认进待审区，逐行校验去重
      </div>
      <input ref="fileInput" type="file" accept=".md,.markdown,.txt,.csv,.json" style="display: none" @change="onFileChange" />
    </div>

    <div class="section-title">粘贴导入</div>
    <div class="card">
      <div class="toolbar" style="margin-bottom: 10px">
        <select v-model="pasteFormat" class="select" style="width: auto">
          <option value="md">Markdown</option>
          <option value="csv">CSV</option>
          <option value="json">JSON</option>
        </select>
        <div style="flex: 1"></div>
        <button class="btn" :disabled="importing" @click="importPaste">解析并导入</button>
      </div>
      <textarea v-model="pasteText" class="textarea" rows="6" placeholder="把面经 Markdown、CSV 或 JSON 粘贴到这里…" />
    </div>

    <div v-if="result" class="section-title">最近一次导入结果</div>
    <div v-if="result" class="card">
      <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center">
        <b>{{ result.batch?.filename || '粘贴内容' }}</b>
        <span class="tag" :class="batchStatusTone(result.batch?.status || 'failed')">
          {{ batchStatusText(result.batch?.status || 'failed') }}
        </span>
        <span class="tag gray">总行数 {{ result.batch?.total_rows ?? 0 }}</span>
        <span class="tag green">成功 {{ result.batch?.ok_rows ?? 0 }}</span>
        <span class="tag orange">失败 {{ result.batch?.fail_rows ?? 0 }}</span>
        <span v-if="result.outcome" class="tag blue">
          待审 {{ result.outcome.pending_created }} · 直接入库 {{ result.outcome.questions_created }} · 去重 {{ result.outcome.duplicates }}
        </span>
      </div>
      <ul v-if="result.errors?.length" class="error-list">
        <li v-for="(error, index) in result.errors" :key="index">
          行 {{ error.line ?? error.record ?? error.index ?? '—' }}：{{ error.message }}
        </li>
      </ul>
      <ul v-if="result.warnings?.length" class="error-list" style="color: var(--amber)">
        <li v-for="(warning, index) in result.warnings" :key="index">
          {{ warning.origin_ref ? warning.origin_ref + '：' : '' }}{{ warning.message }}
        </li>
      </ul>
    </div>

    <div class="section-title">最近导入批次</div>
    <div class="card" style="padding: 6px 10px">
      <div v-if="batchesLoading" class="empty">加载中…</div>
      <table v-else>
        <colgroup>
          <col style="width: 28%" />
          <col style="width: 9%" />
          <col style="width: 11%" />
          <col style="width: 11%" />
          <col style="width: 11%" />
          <col style="width: 18%" />
          <col style="width: 12%" />
        </colgroup>
        <thead>
          <tr>
            <th>文件</th>
            <th>格式</th>
            <th>总行数</th>
            <th>成功</th>
            <th>失败</th>
            <th>时间 / 状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch.id">
            <td style="font-weight: 500">{{ batch.filename }}</td>
            <td><span class="tag gray">{{ batch.format.toUpperCase() }}</span></td>
            <td class="num">{{ batch.total_rows }}</td>
            <td class="num" style="color: var(--green)">{{ batch.ok_rows }}</td>
            <td class="num" :style="{ color: batch.fail_rows ? 'var(--orange)' : 'var(--ink3)' }">{{ batch.fail_rows }}</td>
            <td style="font-size: 13px; color: var(--ink2)">
              {{ formatDateTime(batch.created_at) }} ·
              <span class="tag" :class="batchStatusTone(batch.status)">{{ batchStatusText(batch.status) }}</span>
            </td>
            <td>
              <div style="display: flex; gap: 6px">
                <button class="btn ghost sm" @click="openBatch(batch)">详情</button>
                <button class="btn danger-ghost sm" @click="deleteBatch(batch)">删除</button>
              </div>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td colspan="7"><div class="empty">还没有导入批次</div></td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="section-title">模板说明</div>
    <div class="grid" style="grid-template-columns: repeat(3, 1fr)">
      <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center">
          <b>Markdown</b>
          <button class="btn ghost sm" @click="downloadTemplate('md')">下载模板</button>
        </div>
        <div style="font-size: 13.5px; color: var(--ink2); margin-top: 6px">
          以「## 题目：」开头，答案/要点/标签/难度/频率/公司/分类可选；「## 知识：」定义独立知识条目，代码块内标题不切分。
        </div>
      </div>
      <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center">
          <b>CSV</b>
          <button class="btn ghost sm" @click="downloadTemplate('csv')">下载模板</button>
        </div>
        <div style="font-size: 13.5px; color: var(--ink2); margin-top: 6px">
          列：stem, answer, key_points（分号）, category_path（/）, tags（逗号）, difficulty, frequency, companies。M1 不解析 xlsx。
        </div>
      </div>
      <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center">
          <b>JSON</b>
          <button class="btn ghost sm" @click="downloadTemplate('json')">下载模板</button>
        </div>
        <div style="font-size: 13.5px; color: var(--ink2); margin-top: 6px">
          支持题目数组、知识数组，或组合对象 questions / knowledge / links；非法行返回下标与原因，不影响其他行。
        </div>
      </div>
    </div>

    <Modal :open="batchDetailOpen" title="批次详情" wide @close="batchDetailOpen = false">
      <template v-if="batchDetail?.batch">
        <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px">
          <b>{{ batchDetail.batch.filename }}</b>
          <span class="tag" :class="batchStatusTone(batchDetail.batch.status)">{{ batchStatusText(batchDetail.batch.status) }}</span>
          <span class="tag gray">总 {{ batchDetail.batch.total_rows }}</span>
          <span class="tag green">成功 {{ batchDetail.batch.ok_rows }}</span>
          <span class="tag orange">失败 {{ batchDetail.batch.fail_rows }}</span>
        </div>
        <div class="section-title" style="font-size: 14px">逐行错误</div>
        <ul v-if="batchDetail.report?.errors?.length" class="error-list">
          <li v-for="(error, index) in batchDetail.report.errors" :key="index">
            行 {{ error.line ?? error.record ?? error.index ?? '—' }}：{{ error.message }}
          </li>
        </ul>
        <div v-else class="list-sub">没有错误</div>
        <div class="section-title" style="font-size: 14px">提示</div>
        <ul v-if="batchDetail.report?.warnings?.length" class="error-list" style="color: var(--amber)">
          <li v-for="(warning, index) in batchDetail.report.warnings" :key="index">
            {{ warning.message }}
          </li>
        </ul>
        <div v-else class="list-sub">没有额外提示</div>
        <div class="section-title" style="font-size: 14px">待审区状态</div>
        <div style="display: flex; gap: 8px; flex-wrap: wrap">
          <span v-for="(count, key) in batchDetail.pending_counts" :key="key" class="tag gray">
            {{ key }} {{ count }}
          </span>
        </div>
      </template>
    </Modal>
  </div>
</template>
