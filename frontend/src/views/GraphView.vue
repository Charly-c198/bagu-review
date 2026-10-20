<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import { api, withQuery } from '../api/client'
import type { GraphEdge, GraphNode, KnowledgeGraph } from '../api/types'
import { useAppStore } from '../stores/app'

interface LayoutNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
}

const store = useAppStore()
const loading = ref(true)
const includeQuestions = ref(false)
const limit = ref(50)
const graph = ref<KnowledgeGraph | null>(null)
const nodes = ref<LayoutNode[]>([])
const selected = ref<LayoutNode | null>(null)
const focusId = ref<number | null>(null)

const WIDTH = 920
const HEIGHT = 560

const knowledgeCount = computed(
  () => nodes.value.filter((node) => node.type === 'knowledge').length,
)
const questionCount = computed(
  () => nodes.value.filter((node) => node.type === 'question').length,
)

function layout(inputNodes: GraphNode[], edges: GraphEdge[]): LayoutNode[] {
  const radius = Math.min(WIDTH, HEIGHT) / 2 - 60
  const laid: LayoutNode[] = inputNodes.map((node, index) => {
    const angle = (index / Math.max(1, inputNodes.length)) * Math.PI * 2
    return {
      ...node,
      x: WIDTH / 2 + Math.cos(angle) * radius * (0.5 + (index % 3) * 0.18),
      y: HEIGHT / 2 + Math.sin(angle) * radius * (0.5 + (index % 3) * 0.18),
      vx: 0,
      vy: 0,
    }
  })
  const index = new Map(laid.map((node) => [node.id, node]))
  const springs = edges
    .map((edge) => ({ a: index.get(edge.source), b: index.get(edge.target), weight: edge.weight }))
    .filter((edge): edge is { a: LayoutNode; b: LayoutNode; weight: number } =>
      Boolean(edge.a && edge.b),
    )

  for (let step = 0; step < 260; step += 1) {
    const cooling = 1 - step / 300
    for (let i = 0; i < laid.length; i += 1) {
      for (let j = i + 1; j < laid.length; j += 1) {
        const a = laid[i]
        const b = laid[j]
        let dx = a.x - b.x
        let dy = a.y - b.y
        const dist2 = dx * dx + dy * dy || 0.01
        const dist = Math.sqrt(dist2)
        const force = 5200 / dist2
        dx = (dx / dist) * force
        dy = (dy / dist) * force
        a.vx += dx
        a.vy += dy
        b.vx -= dx
        b.vy -= dy
      }
    }
    for (const spring of springs) {
      const dx = spring.b.x - spring.a.x
      const dy = spring.b.y - spring.a.y
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01
      const target = spring.a.type === 'question' || spring.b.type === 'question' ? 88 : 128
      const strength = 0.012 * Math.min(3, spring.weight)
      const force = (dist - target) * strength
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      spring.a.vx += fx
      spring.a.vy += fy
      spring.b.vx -= fx
      spring.b.vy -= fy
    }
    for (const node of laid) {
      node.vx += (WIDTH / 2 - node.x) * 0.002
      node.vy += (HEIGHT / 2 - node.y) * 0.002
      node.x += node.vx * 0.35 * cooling
      node.y += node.vy * 0.35 * cooling
      node.vx *= 0.72
      node.vy *= 0.72
      node.x = Math.max(46, Math.min(WIDTH - 46, node.x))
      node.y = Math.max(34, Math.min(HEIGHT - 34, node.y))
    }
  }
  return laid
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await api.get<KnowledgeGraph>(
      withQuery('/graph', {
        knowledge_id: focusId.value || undefined,
        category_id: store.boardParam,
        include_questions: includeQuestions.value,
        limit: limit.value,
      }),
    )
    graph.value = data
    nodes.value = layout(data.nodes, data.edges)
    selected.value = null
  } catch (err: any) {
    store.toast(err?.message || '知识图谱加载失败', 'error')
  } finally {
    loading.value = false
  }
}

function nodeRadius(node: LayoutNode): number {
  return node.type === 'question' ? 6 : 11
}

function findNode(id: string): LayoutNode | undefined {
  return nodes.value.find((node) => node.id === id)
}

function edgeLine(edge: GraphEdge): { x1: number; y1: number; x2: number; y2: number } | null {
  const source = findNode(edge.source)
  const target = findNode(edge.target)
  if (!source || !target) return null
  return { x1: source.x, y1: source.y, x2: target.x, y2: target.y }
}

function edgeWidth(edge: GraphEdge): number {
  return edge.type === 'co_occurrence' ? Math.min(4, 1 + edge.weight * 0.5) : 0.8
}

function edgeOpacity(edge: GraphEdge): number {
  return edge.type === 'co_occurrence' ? 0.35 : 0.14
}

function selectNode(node: LayoutNode): void {
  selected.value = selected.value?.id === node.id ? null : node
}

function focusKnowledge(node: LayoutNode): void {
  if (node.type !== 'knowledge') return
  focusId.value = Number(node.id.slice(1))
  load()
}

function clearFocus(): void {
  focusId.value = null
  load()
}

onMounted(load)
watch(() => store.boardId, load)
watch([includeQuestions, limit], load)
</script>

<template>
  <div>
    <div class="section-title" style="justify-content: space-between">
      <span>知识图谱 · {{ store.boardName }}</span>
      <span class="tag gray">节点 {{ knowledgeCount }} 知识 / {{ questionCount }} 题</span>
    </div>
    <div class="toolbar">
      <label class="check">
        <input v-model="includeQuestions" type="checkbox" />
        显示题目节点
      </label>
      <select v-model.number="limit" class="select" style="width: auto">
        <option :value="30">30 个知识</option>
        <option :value="50">50 个知识</option>
        <option :value="80">80 个知识</option>
        <option :value="120">120 个知识</option>
      </select>
      <button v-if="focusId" class="btn ghost sm" @click="clearFocus">取消聚焦</button>
      <div style="flex: 1"></div>
      <span class="hint">连线表示共同关联同一道题，线越粗共现越多</span>
      <button class="btn ghost sm" @click="load">刷新</button>
    </div>

    <div v-if="loading" class="card empty">加载中…</div>
    <div v-else class="graph-layout">
      <div class="card graph-card">
        <div v-if="!nodes.length" class="empty">
          暂无关联数据。先在知识库或题目详情里建立题-知识关联。
        </div>
        <svg v-else :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" class="graph-svg">
          <g>
            <template v-for="edge in graph?.edges || []" :key="edge.id">
              <line
                v-if="edgeLine(edge)"
                :x1="edgeLine(edge)!.x1"
                :y1="edgeLine(edge)!.y1"
                :x2="edgeLine(edge)!.x2"
                :y2="edgeLine(edge)!.y2"
                :stroke-width="edgeWidth(edge)"
                :stroke-opacity="edgeOpacity(edge)"
                stroke="#0d7377"
              />
            </template>
          </g>
          <g>
            <g
              v-for="node in nodes"
              :key="node.id"
              class="graph-node"
              :class="{ selected: selected?.id === node.id }"
              @click="selectNode(node)"
            >
              <circle
                :cx="node.x"
                :cy="node.y"
                :r="nodeRadius(node)"
                :fill="node.type === 'question' ? '#2f6f9f' : '#0d7377'"
                :fill-opacity="node.type === 'question' ? 0.72 : 0.9"
              />
              <text
                :x="node.x"
                :y="node.y - nodeRadius(node) - 5"
                text-anchor="middle"
                class="node-label"
              >
                {{ node.label }}
              </text>
            </g>
          </g>
        </svg>
      </div>

      <div class="card graph-side">
        <div v-if="!selected" class="empty" style="padding: 30px 8px">
          点击节点查看详情
        </div>
        <template v-else>
          <div class="tag" :class="selected.type === 'knowledge' ? 'teal' : 'blue'">
            {{ selected.type === 'knowledge' ? '知识条目' : '题目' }}
          </div>
          <div style="font-weight: 700; margin: 10px 0 6px">{{ selected.label }}</div>
          <div v-if="selected.category_path" class="hint">{{ selected.category_path }}</div>
          <div v-if="selected.type === 'knowledge'" style="margin-top: 12px">
            <div class="hint">相关连线</div>
            <div class="num" style="font-size: 22px">
              {{ (graph?.edges || []).filter((edge) => edge.source === selected!.id || edge.target === selected!.id).length }}
            </div>
            <button class="btn sm" style="margin-top: 12px" @click="focusKnowledge(selected)">
              以此为中心
            </button>
          </div>
          <div v-else class="hint" style="margin-top: 12px">
            掌握度：{{ selected.mastery || '未学' }}
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13.5px;
  color: var(--ink2);
}
.graph-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 14px;
  align-items: start;
}
.graph-card {
  padding: 8px;
  min-height: 480px;
}
.graph-svg {
  width: 100%;
  height: auto;
  display: block;
}
.graph-node {
  cursor: pointer;
}
.graph-node circle {
  transition: stroke-width 0.15s ease;
}
.graph-node.selected circle {
  stroke: var(--orange);
  stroke-width: 3;
}
.node-label {
  font-size: 10.5px;
  fill: var(--ink2);
  pointer-events: none;
}
.graph-side {
  min-height: 200px;
}
</style>
