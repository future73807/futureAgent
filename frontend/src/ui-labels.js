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

// 五档运行模式；数组顺序即选择器展示顺序。
export const agentModes = ['chat', 'plan', 'agent', 'goal', 'loop']

const agentModeLabels = {
  chat: '对话',
  plan: '规划',
  agent: '自主',
  goal: '目标',
  loop: '循环',
}

const agentModeHints = {
  chat: '不挂载工具，纯模型对话。',
  plan: '只用只读工具调研并产出结构化计划，不改写文件。',
  agent: '挂载已选工具，自主规划并循环调用直到完成。',
  goal: '给定目标与达成标准，自主拆解并反复推进直到达成。',
  loop: '按停止条件反复迭代，每轮基于上一轮结果继续改进。',
}

export function agentModeDisplayName(mode) {
  return agentModeLabels[mode] || mode || '自主'
}

export function agentModeHint(mode) {
  return agentModeHints[mode] || ''
}

// goal 靠目标判定达成，loop 靠停止条件判定是否再迭代；
// 缺了对应字段服务端会直接 422，因此前端先拦。
export function agentModeRequirement(mode) {
  if (mode === 'goal') return 'goal'
  return mode === 'loop' ? 'criteria' : ''
}

const iterationVerdictLabels = {
  met: '已达成',
  not_met: '未达成，继续迭代',
  budget_exhausted: '已达轮次上限',
  judge_unavailable: '监督判定不可用，已停止',
}

export function iterationVerdictLabel(verdict) {
  return iterationVerdictLabels[verdict] || verdict || ''
}
