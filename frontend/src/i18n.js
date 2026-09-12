// 框架级文案的语言包。
//
// 产品锁定中文。此前只有框架级文案进了语言包，业务文案全是硬编码中文，
// 于是切到英文必然出现"导航英文、正文中文"的混杂界面——半套 i18n 比没有
// i18n 更容易误导。这里把文案来源固定为唯一一份中文；将来真要出海，应当
// 整体接入而不是继续往这份文件里加第二种语言。
import zhCN from 'antd/es/locale/zh_CN'

// 旧版本会把用户选择写进 localStorage。锁定中文后不再读取它，但清理一次，
// 免得残留的 'en' 让后来的人误以为语言切换仍然生效。
const STORAGE_KEY = 'futureagent.locale'

const messages = {
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
  'work.btn.saveAndApprove': '保存并批准',
  'work.btn.revisePlan': '修订计划',
  'work.btn.approve': '批准执行',
  'work.btn.executeStep': '执行选中步骤',
  'work.btn.executeParallel': '并行执行',
  'work.btn.registerDeliverable': '登记交付物',
  'work.btn.addContext': '添加上下文',
  'work.tab.outputs': '产出',
  'work.tab.changes': '变更',
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
}

export function getLocale() {
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

export function t(key) {
  return messages[key] ?? key
}

export function antdLocaleOf() {
  return zhCN
}
