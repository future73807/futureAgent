const ACCESS_TOKEN_KEY = 'futureagent.access_token'
const WORKSPACE_KEY = 'futureagent.workspace_id'

export function getAccessToken() {
  return sessionStorage.getItem(ACCESS_TOKEN_KEY) || ''
}

export function getWorkspaceId() {
  return sessionStorage.getItem(WORKSPACE_KEY) || ''
}

export function setWorkspaceId(workspaceId) {
  if (workspaceId) sessionStorage.setItem(WORKSPACE_KEY, workspaceId)
  else sessionStorage.removeItem(WORKSPACE_KEY)
}

export function applyAuthSession(payload) {
  if (payload?.access_token) sessionStorage.setItem(ACCESS_TOKEN_KEY, payload.access_token)
  return payload
}

export function clearAuthSession() {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY)
  sessionStorage.removeItem(WORKSPACE_KEY)
}

async function errorFrom(response) {
  let detail = `Request failed (${response.status})`
  try {
    const payload = await response.json()
    const candidate = payload?.detail ?? payload?.message ?? detail
    detail = typeof candidate === 'string' ? candidate : JSON.stringify(candidate)
  } catch { /* Non-JSON error response. */ }
  return new Error(detail)
}

export async function refreshAccessToken() {
  const response = await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' })
  if (!response.ok) throw await errorFrom(response)
  return applyAuthSession(await response.json())
}

function requestHeaders(options = {}) {
  const headers = { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers }
  const token = getAccessToken()
  const workspaceId = options.workspaceId === undefined ? getWorkspaceId() : options.workspaceId
  if (token) headers.Authorization = `Bearer ${token}`
  if (workspaceId) headers['X-Workspace-ID'] = workspaceId
  return headers
}

export async function apiFetch(path, options = {}, retry = true) {
  const response = await fetch(path, { ...options, headers: requestHeaders(options), credentials: 'include' })
  if (response.status === 401 && retry && !path.startsWith('/api/v1/auth/')) {
    try {
      await refreshAccessToken()
      return apiFetch(path, options, false)
    } catch {
      clearAuthSession()
    }
  }
  if (!response.ok) throw await errorFrom(response)
  if (response.status === 204) return null
  return response.json()
}

export async function uploadAttachment(file, target) {
  const body = new FormData()
  body.append('file', file)
  if (target.task_id) body.append('task_id', target.task_id)
  if (target.conversation_id) body.append('conversation_id', target.conversation_id)
  return apiFetch('/api/v1/attachments', { method: 'POST', body })
}

export async function downloadAttachment(attachment) {
  const response = await fetch(attachment.download_url, { headers: requestHeaders(), credentials: 'include' })
  if (!response.ok) throw await errorFrom(response)
  const blob = await response.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = attachment.original_name || 'download'
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(link.href)
}

export async function streamSSE(path, body, handlers = {}, retried = false) {
  const response = await fetch(path, {
    method: 'POST',
    headers: requestHeaders({ body: JSON.stringify(body) }),
    body: JSON.stringify(body),
    signal: handlers.signal,
    credentials: 'include',
  })
  if (response.status === 401 && !retried) {
    await refreshAccessToken()
    return streamSSE(path, body, handlers, true)
  }
  if (!response.ok) throw await errorFrom(response)
  if (!response.body) throw new Error('This browser does not support streaming responses')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const dispatch = (block) => {
    if (!block.trim()) return
    let event = 'message'
    const data = []
    block.split(/\r?\n/).forEach((line) => {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
    })
    handlers.onEvent?.(event, data.join('\n'))
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach(dispatch)
      if (done) break
    }
    dispatch(buffer)
  } finally {
    try { await reader.cancel() } catch { /* Stream is already closed. */ }
    reader.releaseLock()
  }
}
