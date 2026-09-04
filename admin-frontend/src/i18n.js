// 管理端 i18n 最小脚手架：框架级文案的语言包与切换。
// 未翻译的 key 回退 zh-CN，再回退 key 本身。
import zhCN from 'antd/es/locale/zh_CN'
import enUS from 'antd/es/locale/en_US'

export const LOCALES = {
  'zh-CN': { label: '中文', antd: zhCN },
  en: { label: 'English', antd: enUS },
}

const STORAGE_KEY = 'futureagent.admin.locale'
const listeners = new Set()

const messages = {
  'zh-CN': {
    'admin.tagline': '平台运营中心',
    'admin.nav.group.ops': '运营管理',
    'admin.nav.group.capability': '能力与治理',
    'admin.nav.dashboard': '平台概览',
    'admin.nav.users': '用户管理',
    'admin.nav.workspaces': '工作区',
    'admin.nav.audit': '审计轨迹',
    'admin.nav.models': '模型中心',
    'admin.nav.skills': '技能管理',
    'admin.nav.mcp': 'MCP 服务',
    'admin.nav.policies': '权限策略',
    'admin.nav.settings': '运行设置',
    'admin.auth.title': '欢迎回来',
    'admin.auth.subtitle': '登录平台运营中心',
    'admin.auth.submit': '进入管理后台',
    'admin.auth.note': '仅限已授权的平台管理员访问',
    'admin.common.logout': '退出登录',
    'admin.common.healthOk': '服务运行正常',
    'admin.brand.tagline': '平台运营中心',
    'admin.auth.email': '管理员邮箱',
    'admin.auth.password': '密码',
    'admin.header.userFrontend': '用户端',
    'admin.header.apiOk': 'API 正常',
    'admin.header.apiError': 'API 异常',
    'admin.header.currentWorkspace': '当前工作区',
    'admin.common.refresh': '刷 新',
    'admin.status.online': '服务运行正常',
    'admin.status.offline': '服务连接异常',
  },
  en: {
    'admin.tagline': 'Platform Operations',
    'admin.nav.group.ops': 'Operations',
    'admin.nav.group.capability': 'Capability & Governance',
    'admin.nav.dashboard': 'Overview',
    'admin.nav.users': 'Users',
    'admin.nav.workspaces': 'Workspaces',
    'admin.nav.audit': 'Audit Trail',
    'admin.nav.models': 'Model Center',
    'admin.nav.skills': 'Skills',
    'admin.nav.mcp': 'MCP Services',
    'admin.nav.policies': 'Policies',
    'admin.nav.settings': 'Runtime Settings',
    'admin.auth.title': 'Welcome back',
    'admin.auth.subtitle': 'Sign in to the platform operations center',
    'admin.auth.submit': 'Enter admin console',
    'admin.auth.note': 'For authorized platform administrators only',
    'admin.auth.email': 'Admin email',
    'admin.auth.password': 'Password',
    'admin.header.userFrontend': 'User app',
    'admin.header.apiOk': 'API OK',
    'admin.header.apiError': 'API error',
    'admin.header.currentWorkspace': 'Workspace',
    'admin.common.refresh': 'Refresh',
    'admin.status.online': 'Services healthy',
    'admin.common.logout': 'Sign out',
    'admin.brand.tagline': 'Platform Operations',
    'admin.status.offline': 'Services unreachable',
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
  window.dispatchEvent(new CustomEvent('futureagent-admin-locale', { detail: next }))
  return next
}

export function toggleLocale() {
  return applyLocale(getLocale() === 'en' ? 'zh-CN' : 'en')
}

export function antdLocaleOf(locale) {
  return (LOCALES[locale] || LOCALES['zh-CN']).antd
}

export function t(key) {
  const locale = getLocale()
  return messages[locale]?.[key] ?? messages['zh-CN']?.[key] ?? key
}

export function subscribeLocale(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
