// 对话/执行控件的选择持久化。
// 对话页与工作模式共用同一份偏好：两处控件本来就该是同一套语义，
// 分开存会让用户在一处改完、另一处又回到默认值。
import { agentModes } from './ui-labels.js'

const KEY = 'futureagent.composer'

export const DEFAULT_COMPOSER_PREFS = {
  mode: 'agent',
  modelId: '',
  skillName: '',
  mcpServers: [],
  maxIterations: 5,
}

function sanitize(raw) {
  if (!raw || typeof raw !== 'object') return { ...DEFAULT_COMPOSER_PREFS }
  const mode = agentModes.includes(raw.mode) ? raw.mode : DEFAULT_COMPOSER_PREFS.mode
  const iterations = Number(raw.maxIterations)
  return {
    mode,
    modelId: typeof raw.modelId === 'string' ? raw.modelId : '',
    skillName: typeof raw.skillName === 'string' ? raw.skillName : '',
    // 只接受字符串数组，避免把上次会话里的脏数据带进请求体。
    mcpServers: Array.isArray(raw.mcpServers) ? raw.mcpServers.filter((item) => typeof item === 'string') : [],
    maxIterations: Number.isFinite(iterations) ? Math.min(20, Math.max(1, Math.round(iterations))) : DEFAULT_COMPOSER_PREFS.maxIterations,
  }
}

export function loadComposerPrefs() {
  try {
    return sanitize(JSON.parse(localStorage.getItem(KEY) || ''))
  } catch {
    // 隐私模式或损坏的 JSON 都退回默认值，不能让首屏因此白掉。
    return { ...DEFAULT_COMPOSER_PREFS }
  }
}

export function saveComposerPrefs(patch) {
  const next = sanitize({ ...loadComposerPrefs(), ...(patch || {}) })
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    /* 存储不可用时只在本次会话内生效。 */
  }
  return next
}

// 偏好里可能存着已经被删除或不再就绪的模型/技能。静默沿用会让请求
// 在服务端失败，用户却看不出原因；这里显式回退并告知调用方。
export function reconcileComposerPrefs(prefs, { models = [], skills = [], mcpServers = [] }) {
  const readyModels = models.filter((item) => item.ready !== false)
  const modelIds = models.map((item) => item.id || item)
  const fallbacks = []

  let modelId = prefs.modelId
  if (modelId && !modelIds.includes(modelId)) {
    modelId = readyModels[0]?.id || readyModels[0] || ''
    if (modelId) fallbacks.push('上次选择的模型已不可用，已切换到当前可用的模型')
  } else if (modelId && !readyModels.some((item) => (item.id || item) === modelId)) {
    const ready = readyModels[0]?.id || readyModels[0] || ''
    if (ready && ready !== modelId) {
      modelId = ready
      fallbacks.push('上次选择的模型当前未就绪，已切换到可用模型')
    }
  }
  if (!modelId && readyModels.length) modelId = readyModels[0].id || readyModels[0]

  const skillNames = skills.map((item) => item.name)
  let skillName = prefs.skillName
  if (skillName && !skillNames.includes(skillName)) {
    skillName = skillNames[0] || ''
    if (skillName) fallbacks.push('上次选择的技能已不存在，已切换到默认技能')
  }
  if (!skillName && skillNames.length) skillName = skillNames[0]

  const availableMcp = mcpServers
    .map((item) => item.name || item)
    .filter((name) => !mcpServers.some((item) => (item.name || item) === name && item.status && ['offline', 'degraded', 'disabled'].includes(item.status)))
  const kept = prefs.mcpServers.filter((name) => availableMcp.includes(name))
  if (kept.length !== prefs.mcpServers.length) {
    fallbacks.push('部分上次选择的工具服务当前不可用，已自动取消勾选')
  }

  return { prefs: { ...prefs, modelId, skillName, mcpServers: kept }, fallbacks }
}
