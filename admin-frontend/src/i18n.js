// 管理端文案的语言包：产品锁定中文。
//
// 此前是 zh-CN / en 双语言包：导航与登录页走语言包、页面正文全是硬编码中文，
// 切到英文必然中英混杂；且界面上的语言切换入口已经移除，只剩残留存储仍可
// 把界面切成半套英文。这里把文案来源固定为唯一一份中文；将来真要出海，
// 应当整体接入，而不是继续往这份文件里加第二种语言。
import zhCN from 'antd/es/locale/zh_CN'

// 旧版本会把用户选择写进 localStorage。锁定中文后不再读取它，但清理一次，
// 免得残留的 'en' 让后来的人误以为语言切换仍然生效。
const STORAGE_KEY = 'futureagent.admin.locale'

const messages = {
  'admin.tagline': '平台运营中心',
  'admin.nav.group.ops': '运营管理',
  'admin.nav.group.capability': '能力与治理',
  'admin.nav.dashboard': '平台概览',
  'admin.nav.users': '用户管理',
  'admin.nav.workspaces': '工作区',
  'admin.nav.audit': '审计轨迹',
  'admin.nav.usage': '用量统计',
  'admin.nav.models': '模型中心',
  'admin.nav.skills': '技能管理',
  'admin.nav.mcp': 'MCP 服务',
  'admin.nav.policies': '权限策略',
  'admin.nav.settings': '运行设置',
  'admin.auth.title': '欢迎回来',
  'admin.auth.subtitle': '登录平台运营中心',
  'admin.auth.submit': '进入管理后台',
  'admin.auth.note': '仅限已授权的平台管理员访问',
  'admin.auth.email': '管理员邮箱',
  'admin.auth.password': '密码',
  'admin.common.logout': '退出登录',
  'admin.common.refresh': '刷 新',
  'admin.header.userFrontend': '用户端',
  'admin.header.apiOk': 'API 正常',
  'admin.header.apiError': 'API 异常',
  'admin.header.currentWorkspace': '当前工作区',
  'admin.status.online': '服务运行正常',
  'admin.status.offline': '服务连接异常',
}

export function getLocale() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch { /* 隐私模式下忽略 */ }
  return 'zh-CN'
}

/**
 * 兼容旧调用点。语言已锁定，这里只负责清理历史存储，不再改变界面语言。
 */
export function applyLocale() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch { /* 隐私模式下忽略 */ }
  return 'zh-CN'
}

export function antdLocaleOf() {
  return zhCN
}

export function t(key) {
  return messages[key] ?? key
}
