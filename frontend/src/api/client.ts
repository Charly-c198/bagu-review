const BASE = '/api/v1'
const TOKEN_KEY = 'bajiu_token'

export class ApiError extends Error {
  status: number
  code: string
  data: any

  constructor(status: number, code: string, message: string, data: any = null) {
    super(message)
    this.status = status
    this.code = code
    this.data = data
  }
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token: string): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function withQuery(path: string, params: Record<string, string | number | boolean | null | undefined>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  const text = query.toString()
  return text ? `${path}?${text}` : path
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...authHeaders(),
    ...((options.headers as Record<string, string>) || {}),
  }
  if (options.body && !(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })
  let payload: any = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  if (!response.ok || (payload && payload.code !== 'OK')) {
    const message = payload?.message || `请求失败（HTTP ${response.status}）`
    if (response.status === 401 && path !== '/auth/login') {
      setToken('')
      if (!window.location.hash.startsWith('#/login')) window.location.hash = '#/login'
    }
    throw new ApiError(response.status, payload?.code || 'INTERNAL_ERROR', message, payload?.data)
  }
  return (payload?.data ?? null) as T
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path)
  },
  post<T>(path: string, body?: any): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  patch<T>(path: string, body: any): Promise<T> {
    return request<T>(path, { method: 'PATCH', body: JSON.stringify(body) })
  },
  delete<T>(path: string, body?: any): Promise<T> {
    return request<T>(path, {
      method: 'DELETE',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  },
  upload<T>(path: string, form: FormData): Promise<T> {
    return request<T>(path, { method: 'POST', body: form })
  },
  async download(path: string, options: RequestInit = {}): Promise<void> {
    const headers = { ...authHeaders(), ...((options.headers as Record<string, string>) || {}) }
    const response = await fetch(`${BASE}${path}`, {
      ...options,
      headers,
      credentials: 'include',
    })
    if (!response.ok) {
      let message = `下载失败（HTTP ${response.status}）`
      try {
        const payload = await response.json()
        message = payload?.message || message
      } catch {
        // ignore
      }
      if (response.status === 401) setToken('')
      throw new ApiError(response.status, 'DOWNLOAD_FAILED', message)
    }
    const blob = await response.blob()
    const disposition = response.headers.get('Content-Disposition') || ''
    const match = disposition.match(/filename="?([^"]+)"?/)
    const filename = match?.[1] || 'download.bin'
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  },
}

export { TOKEN_KEY }
