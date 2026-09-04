// i18n 最小脚手架：框架级文案的语言包与切换。
// 覆盖范围逐步铺开；未翻译的 key 回退 zh-CN，再回退 key 本身。
import zhCN from 'antd/es/locale/zh_CN'
import enUS from 'antd/es/locale/en_US'

export const LOCALES = {
  'zh-CN': { label: '中文', antd: zhCN },
  en: { label: 'English', antd: enUS },
}

const STORAGE_KEY = 'futureagent.locale'
const listeners = new Set()

const messages = {
  'zh-CN': {
    'app.tagline': '团队 AI 工作空间',
    'nav.chat': 'AI 对话',
    'nav.business': '经营助手',
    'nav.report': '汇报智能体',
    'nav.board': '项目看板',
    'nav.work': '工作模式',
    'nav.team': '团队成员',
    'nav.settings': '工作区设置',
    'auth.title': '欢迎使用 futureAgent',
    'auth.subtitle': '面向团队协作的 AI 工作空间',
    'auth.tab.login': '登 录',
    'auth.tab.register': '创建工作区',
    'auth.email': '工作邮箱',
    'auth.password': '密码',
    'auth.submit.login': '登录工作区',
    'auth.submit.register': '创建安全工作区',
    'common.save': '保存名称',
    'common.refresh': '刷新工作区',
    'common.connected': '已安全连接',
    'common.syncing': '正在同步',
  },
  en: {
    'app.tagline': 'Team AI workspace',
    'nav.chat': 'AI Chat',
    'nav.business': 'Business Assistants',
    'nav.report': 'Report Agents',
    'nav.board': 'Project Board',
    'nav.work': 'Work Mode',
    'nav.team': 'Team Members',
    'nav.settings': 'Workspace Settings',
    'auth.title': 'Welcome to futureAgent',
    'auth.subtitle': 'AI workspace for team collaboration',
    'auth.tab.login': 'Sign in',
    'auth.tab.register': 'Create workspace',
    'auth.email': 'Work email',
    'auth.password': 'Password',
    'auth.submit.login': 'Sign in to workspace',
    'auth.submit.register': 'Create secure workspace',
    'common.save': 'Save name',
    'common.refresh': 'Refresh workspace',
    'common.connected': 'Connected',
    'common.syncing': 'Syncing',
  },
}

export function getLocale() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh-CN'
  } catch {
    return 'zh-CN'
  }
}

export function applyLocale(locale) {
  const next = LOCALES[locale] ? locale : 'zh-CN'
  try {
    localStorage.setItem(STORAGE_KEY, next)
  } catch { /* 隐私模式下仅会话内生效 */ }
  window.dispatchEvent(new CustomEvent('futureagent-locale', { detail: next }))
  return next
}

export function toggleLocale() {
  return applyLocale(getLocale() === 'en' ? 'zh-CN' : 'en')
}

export function t(key) {
  const locale = getLocale()
  return messages[locale]?.[key] ?? messages['zh-CN']?.[key] ?? key
}

export function antdLocaleOf(locale) {
  return (LOCALES[locale] || LOCALES['zh-CN']).antd
}

export function subscribeLocale(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function emitLocale(locale) {
  listeners.forEach((listener) => listener(locale))
}
