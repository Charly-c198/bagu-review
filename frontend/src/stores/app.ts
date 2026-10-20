import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { api, setToken } from '../api/client'
import type { CategoryNode } from '../api/types'

interface ToastItem {
  id: number
  message: string
  type: 'info' | 'success' | 'error'
}

const BOARD_DESCRIPTIONS: Record<string, string> = {
  后端开发: '网络 / 操作系统 / 数据库 / 并发 / 分布式',
  前端开发: '浏览器 / CSS / JS / 工程化',
  全栈: '前后端贯通 / 接口设计 / 认证',
  'AI-Agent': 'RAG / 工具调用 / 大模型应用',
  算法ML: '数据结构 / 复杂度 / 缓存策略',
  测试质量: '用例设计 / 测试分层 / 缺陷管理',
  '客户端C++': '内存 / 智能指针 / 面向对象',
  运维DevOps: '容器 / 流水线 / 代理与部署',
}

export const useAppStore = defineStore('app', () => {
  const token = ref(localStorage.getItem('bajiu_token') || '')
  const user = ref<{ id: number; username: string } | null>(null)
  const tree = ref<CategoryNode[]>([])
  const boardId = ref<number>(Number(localStorage.getItem('bajiu_board') || 0))
  const sidebarOpen = ref(false)
  const pendingCount = ref(0)
  const dueCount = ref(0)
  const toasts = ref<ToastItem[]>([])
  let toastSeq = 0

  const boards = computed(() => tree.value.map((node) => ({
    id: node.id,
    name: node.name,
    description: BOARD_DESCRIPTIONS[node.name] || `${node.question_count} 道题`,
    questionCount: node.question_count,
  })))

  const currentBoard = computed(() => boards.value.find((board) => board.id === boardId.value) || null)
  const boardName = computed(() => currentBoard.value?.name || '全部题目')
  const boardDesc = computed(() => currentBoard.value?.description || '所有岗位方向的题目与复习进度')
  const boardParam = computed<number | undefined>(() => (boardId.value ? boardId.value : undefined))

  function toast(message: string, type: ToastItem['type'] = 'info'): void {
    const id = ++toastSeq
    toasts.value.push({ id, message, type })
    window.setTimeout(() => {
      toasts.value = toasts.value.filter((item) => item.id !== id)
    }, 2600)
  }

  async function login(username: string, password: string): Promise<void> {
    const data = await api.post<{ token: string; user: { id: number; username: string } }>('/auth/login', {
      username,
      password,
    })
    setToken(data.token)
    token.value = data.token
    user.value = data.user
    await fetchTree()
    await loadBadges()
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/auth/logout')
    } catch {
      // 本地清理优先
    }
    setToken('')
    token.value = ''
    user.value = null
    tree.value = []
    boardId.value = 0
    localStorage.removeItem('bajiu_board')
  }

  async function fetchMe(): Promise<void> {
    user.value = await api.get<{ id: number; username: string }>('/auth/me')
  }

  async function fetchTree(): Promise<void> {
    tree.value = await api.get<CategoryNode[]>('/categories/tree')
    if (boardId.value && !tree.value.some((node) => node.id === boardId.value)) {
      boardId.value = tree.value[0]?.id || 0
      localStorage.setItem('bajiu_board', String(boardId.value))
    }
  }

  async function loadBadges(): Promise<void> {
    try {
      const [pending, summary] = await Promise.all([
        api.get<{ counts: { total: number } }>('/pending?status=pending&page_size=1'),
        api.get<{ due_total: number; backlog: number }>('/review/summary'),
      ])
      pendingCount.value = pending.counts?.total || 0
      dueCount.value = summary.due_total || 0
    } catch {
      // 徽标失败不阻塞页面
    }
  }

  function setBoard(id: number): void {
    boardId.value = id
    localStorage.setItem('bajiu_board', String(id))
  }

  return {
    token,
    user,
    tree,
    boardId,
    boards,
    currentBoard,
    boardName,
    boardDesc,
    boardParam,
    sidebarOpen,
    pendingCount,
    dueCount,
    toasts,
    toast,
    login,
    logout,
    fetchMe,
    fetchTree,
    loadBadges,
    setBoard,
  }
})
