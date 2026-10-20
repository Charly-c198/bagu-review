export type Tone = 'teal' | 'green' | 'blue' | 'orange' | 'amber' | 'gray'

export function masteryText(mastery: string): string {
  return ({ mastered: '精通', familiar: '熟悉', unfamiliar: '不熟' } as Record<string, string>)[mastery] || '未学'
}

export function masteryTone(mastery: string): Tone {
  return ({ mastered: 'green', familiar: 'blue', unfamiliar: 'orange' } as Record<string, Tone>)[mastery] || 'gray'
}

export function frequencyText(frequency: string | null): string {
  return ({ high: '高频', mid: '中频', low: '低频' } as Record<string, string>)[frequency || ''] || '未标注'
}

export function frequencyTone(frequency: string | null): Tone {
  return ({ high: 'orange', mid: 'amber', low: 'gray' } as Record<string, Tone>)[frequency || ''] || 'gray'
}

export function sourceText(source: string): string {
  return ({ crawler: '爬虫', import: '导入', manual: '手动', ai: 'AI' } as Record<string, string>)[source] || source
}

export function sourceTone(source: string): Tone {
  return ({ crawler: 'teal', import: 'blue', manual: 'gray', ai: 'amber' } as Record<string, Tone>)[source] || 'gray'
}

export function kindText(kind: string): string {
  return ({
    concept: '概念',
    principle: '原理',
    process: '流程',
    comparison: '对比',
    pitfall: '易错点',
    other: '其他',
  } as Record<string, string>)[kind] || kind
}

export function batchStatusText(status: string): string {
  return ({ processing: '处理中', success: '完成', partial: '部分成功', failed: '失败' } as Record<string, string>)[status] || status
}

export function batchStatusTone(status: string): Tone {
  return ({ processing: 'amber', success: 'green', partial: 'orange', failed: 'orange' } as Record<string, Tone>)[status] || 'gray'
}

export function taskStatusText(status: string): string {
  return ({
    pending: '待执行',
    running: '运行中',
    success: '成功',
    partial: '部分成功',
    failed: '失败',
    canceled: '已取消',
  } as Record<string, string>)[status] || status
}

export function taskStatusTone(status: string): Tone {
  return ({
    pending: 'gray',
    running: 'amber',
    success: 'green',
    partial: 'orange',
    failed: 'orange',
    canceled: 'gray',
  } as Record<string, Tone>)[status] || 'gray'
}

export function pendingStatusText(status: string): string {
  return ({ pending: '待审', approved: '已通过', rejected: '已拒绝', merged: '已合并' } as Record<string, string>)[status] || status
}

export function pendingStatusTone(status: string): Tone {
  return ({ pending: 'amber', approved: 'green', rejected: 'gray', merged: 'teal' } as Record<string, Tone>)[status] || 'gray'
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value.includes('Z') || value.includes('+') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value.includes('Z') || value.includes('+') ? value : `${value}Z`)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value)}%`
}
