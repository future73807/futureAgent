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
    'work.title': '工作模式',
    'work.subtitle': '先制定执行计划，再批准执行；每个步骤都有明确责任与可追溯记录。',
    'work.card.plan': '执行前计划',
    'work.card.approved': '已批准的工作计划',
    'work.card.ai': 'AI 执行',
    'work.card.results': '成果与文件',
    'work.btn.saveDraft': '保存草稿',
    'work.btn.approve': '批准执行',
    'work.btn.executeStep': '执行选中步骤',
    'work.btn.executeParallel': '并行执行',
    'work.btn.registerDeliverable': '登记交付物',
    'work.btn.addContext': '添加上下文',
    'work.tab.deliverables': '交付物',
    'work.tab.files': '文件',
    'work.tab.preview': '预览',
    'work.tab.activity': '动态',
    'settings.title': '工作区设置',
    'settings.subtitle': '名称、所有权与通知出口都在这里集中管理；关键操作会写入审计记录。',
    'settings.card.basic': '基本信息',
    'settings.card.targets': '通知出口',
    'settings.card.transfer': '所有权转移',
    'settings.card.danger': '危险区',
    'settings.btn.saveName': '保存名称',
    'settings.btn.newTarget': '新建出口',
    'settings.btn.delete': '删除此工作区',
    'business.title': '经营助手',
    'business.subtitle': '将已授权的业务数据汇总为预警、生产日报与可追溯任务；不会绕过系统授权采集个人聊天记录。',
    'business.card.select': '选择业务助手',
    'business.isolation': '工作区隔离',
    'business.btn.refresh': '刷新数据',
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
    'work.title': 'Work Mode',
    'work.subtitle': 'Draft a plan, get it approved, then execute — every step has a clear owner and a traceable record.',
    'work.card.plan': 'Execution Plan (draft)',
    'work.card.approved': 'Approved Plan',
    'work.card.ai': 'AI Execution',
    'work.card.results': 'Results & Files',
    'work.btn.saveDraft': 'Save draft',
    'work.btn.approve': 'Approve & execute',
    'work.btn.executeStep': 'Run selected step',
    'work.btn.executeParallel': 'Run in parallel',
    'work.btn.registerDeliverable': 'Register deliverable',
    'work.btn.addContext': 'Add context',
    'work.tab.deliverables': 'Deliverables',
    'work.tab.files': 'Files',
    'work.tab.preview': 'Preview',
    'work.tab.activity': 'Activity',
    'settings.title': 'Workspace Settings',
    'settings.subtitle': 'Name, ownership and notification targets in one place; key actions are audited.',
    'settings.card.basic': 'Basic Info',
    'settings.card.targets': 'Notification Targets',
    'settings.card.transfer': 'Ownership Transfer',
    'settings.card.danger': 'Danger Zone',
    'settings.btn.saveName': 'Save name',
    'settings.btn.newTarget': 'New target',
    'settings.btn.delete': 'Delete workspace',
    'business.title': 'Business Assistants',
    'business.subtitle': 'Turn authorised business data into alerts, daily reports and traceable tasks — without bypassing system permissions.',
    'business.card.select': 'Choose an assistant',
    'business.isolation': 'Workspace isolation',
    'business.btn.refresh': 'Refresh data',
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
