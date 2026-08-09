export function skillDisplayName(name) {
  return name === 'default' ? '通用助手' : name
}

const mcpLabels = {
  local_tools: '工作区与联网工具',
  web: '联网工具',
  browser: '浏览器工具',
}

export function mcpDisplayName(name) {
  const value = String(name || '').trim()
  return mcpLabels[value] || value.replaceAll('_', ' ') || '未命名工具服务'
}

const mcpStatusLabels = {
  configured: '已配置',
  online: '在线',
  offline: '离线',
  degraded: '异常',
  disabled: '已禁用',
  unknown: '未知',
}

export function mcpServerUnavailable(server) {
  return ['offline', 'degraded', 'disabled'].includes(server?.status)
}

export function mcpOptionLabel(server) {
  const name = mcpDisplayName(server?.name || server)
  if (!server || typeof server === 'string') return name
  const status = mcpStatusLabels[server.status] || '状态未知'
  const toolCount = Array.isArray(server.tools) && server.tools.length ? ` · ${server.tools.length} 个工具` : ''
  return `${name} · ${status}${toolCount}`
}
