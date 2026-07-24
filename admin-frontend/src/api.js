const ACCESS_TOKEN_KEY = 'futureagent.access_token'
const WORKSPACE_KEY = 'futureagent.workspace_id'

export const getAccessToken = () => sessionStorage.getItem(ACCESS_TOKEN_KEY) || ''
export const getWorkspaceId = () => sessionStorage.getItem(WORKSPACE_KEY) || ''
export const setWorkspaceId = (id) => id ? sessionStorage.setItem(WORKSPACE_KEY, id) : sessionStorage.removeItem(WORKSPACE_KEY)
export const applyAuthSession = (payload) => { if (payload?.access_token) sessionStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token); return payload }
export const clearAuthSession = () => { sessionStorage.removeItem(ACCESS_TOKEN_KEY); sessionStorage.removeItem(WORKSPACE_KEY) }

async function readError(response) {
  let detail = `Request failed (${response.status})`
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
