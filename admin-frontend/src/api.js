const ACCESS_TOKEN_KEY = 'futureagent.access_token'
const WORKSPACE_KEY = 'futureagent.workspace_id'

export const getAccessToken = () => sessionStorage.getItem(ACCESS_TOKEN_KEY) || ''
export const getWorkspaceId = () => sessionStorage.getItem(WORKSPACE_KEY) || ''
export const setWorkspaceId = (id) => id ? sessionStorage.setItem(WORKSPACE_KEY, id) : sessionStorage.removeItem(WORKSPACE_KEY)
export const applyAuthSession = (payload) => { if (payload?.access_token) sessionStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token); return payload }
export const clearAuthSession = () => { sessionStorage.removeItem(ACCESS_TOKEN_KEY); sessionStorage.removeItem(WORKSPACE_KEY) }

const englishInfrastructureError = /(error|exception|failed|failure|refused|timeout|timed out|unavailable|connect(?:ion)?|network|upstream|provider|internal server|stack|traceback|econn|fetch|request)|https?:\/\/|\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)\b|\b[a-z0-9._-]+:\d{2,5}\b/i

export function toUserErrorMessage(error, fallback = '操作未能完成，请稍后重试。') {
  const raw = typeof error === 'string' ? error.trim() : String(error?.message || '').trim()
  if (!raw) return fallback

  const hasChinese = /[\u3400-\u9fff]/.test(raw)
  if (hasChinese && !englishInfrastructureError.test(raw)) return raw

  const normalized = raw.toLowerCase()
  if (/failed to fetch|networkerror|network request failed|load failed|connection refused|econnrefused|timeout|timed out|fetch failed|connect(?:ion)?|https?:\/\/|\b(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)\b|\b[a-z0-9._-]+:\d{2,5}\b/.test(normalized)) return '网络或内网服务连接失败，请检查服务状态后重试。'
  if (/(?:^|\D)401(?:\D|$)|unauthorized|not authenticated/.test(normalized)) return '登录状态已失效，请重新登录。'
  if (/(?:^|\D)403(?:\D|$)|forbidden|permission denied/.test(normalized)) return '当前账号没有执行此操作的权限。'
  if (/(?:^|\D)404(?:\D|$)|not found/.test(normalized)) return '请求的资源不存在或已被删除。'
  if (/(?:^|\D)409(?:\D|$)|conflict/.test(normalized)) return '操作未完成：当前数据状态已变化，请刷新后重试。'
  if (/(?:^|\D)413(?:\D|$)|payload too large/.test(normalized)) return '提交内容超过允许大小。'
  if (/(?:^|\D)415(?:\D|$)|unsupported media/.test(normalized)) return '提交内容格式不受支持。'
  if (/(?:^|\D)422(?:\D|$)|validation/.test(normalized)) return '提交内容不符合要求，请检查后重试。'
  if (/(?:^|\D)(429|502|503|504)(?:\D|$)|unavailable|upstream|provider|internal server/.test(normalized)) return '服务暂时不可用，请稍后重试。'
  return fallback
}

async function readError(response) {
  let detail = `请求失败（${response.status}）`
  try {
    const payload = await response.json()
    const candidate = payload?.detail ?? payload?.message ?? detail
    detail = typeof candidate === 'string' ? candidate : JSON.stringify(candidate)
  } catch { /* Non-JSON error. */ }
  return new Error(detail)
}

export async function refreshAccessToken() {
  const response = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' })
  if (!response.ok) throw await readError(response)
  return applyAuthSession(await response.json())
}

export async function apiFetch(path, options = {}, retry = true) {
  const headers = { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers }
  const token = getAccessToken()
  const workspaceId = options.workspaceId === undefined ? getWorkspaceId() : options.workspaceId
  if (token) headers.Authorization = `Bearer ${token}`
  if (workspaceId) headers['X-Workspace-ID'] = workspaceId
  const response = await fetch(path, { ...options, headers, credentials: 'include' })
  if (response.status === 401 && retry && !path.startsWith('/api/v1/auth/')) {
    try { await refreshAccessToken(); return apiFetch(path, options, false) } catch { clearAuthSession() }
  }
  if (!response.ok) throw await readError(response)
  if (response.status === 204) return null
  return response.json()
}

export function serviceUrl(port, path = '') { return `${window.location.protocol}//${window.location.hostname}:${port}${path}` }
