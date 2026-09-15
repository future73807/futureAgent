import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Alert from 'antd/es/alert'
import AntApp from 'antd/es/app'
import AutoComplete from 'antd/es/auto-complete'
import Collapse from 'antd/es/collapse'
import Avatar from 'antd/es/avatar'
import Badge from 'antd/es/badge'
import Button from 'antd/es/button'
import Card from 'antd/es/card'
import Checkbox from 'antd/es/checkbox'
import ConfigProvider from 'antd/es/config-provider'
import Descriptions from 'antd/es/descriptions'
import Drawer from 'antd/es/drawer'
import Dropdown from 'antd/es/dropdown'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Form from 'antd/es/form'
import Grid from 'antd/es/grid'
import Input from 'antd/es/input'
import InputNumber from 'antd/es/input-number'
import Layout from 'antd/es/layout'
import List from 'antd/es/list'
import Modal from 'antd/es/modal'
import Popconfirm from 'antd/es/popconfirm'
import Progress from 'antd/es/progress'
import Select from 'antd/es/select'
import Segmented from 'antd/es/segmented'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Statistic from 'antd/es/statistic'
import Steps from 'antd/es/steps'
import Switch from 'antd/es/switch'
import Tabs from 'antd/es/tabs'
import Tag from 'antd/es/tag'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import theme from 'antd/es/theme'
import {
  AppstoreOutlined,
  BarChartOutlined,
  BellOutlined,
  BulbOutlined,
  CheckCircleFilled,
  CheckCircleOutlined,
  ClockCircleOutlined,
  SearchOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  UndoOutlined,
  WarningOutlined,
  LogoutOutlined,
  MenuOutlined,
  MessageOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ProjectOutlined,
  ReloadOutlined,
  RobotOutlined,
  StopOutlined,
  SendOutlined,
  SettingOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  UserOutlined,
} from '@ant-design/icons'
import ErrorBoundary from './ErrorBoundary.jsx'
// 侧边栏常驻，不参与按需分包：对话列表是工作台主入口，不应等到进对话页才加载。
import SidebarConversations from './components/SidebarConversations.jsx'
import AgentStudioPage from './components/AgentStudioPage.jsx'
import BrandMark from './components/BrandMark.jsx'
import ComposerToolbar from './components/ComposerToolbar.jsx'
import MessageBlocks from './components/MessageBlocks.jsx'
import SettingsModal from './components/SettingsModal.jsx'
import WorkspaceChangesPanel from './components/WorkspaceChangesPanel.jsx'
import { loadComposerPrefs, reconcileComposerPrefs, saveComposerPrefs } from './composer-prefs.js'
import {
  apiFetch,
  applyAuthSession,
  clearAuthSession,
  downloadAttachment,
  downloadCsv,
  getAttachmentBlob,
  getAccessToken,
  getWorkspaceId,
  refreshAccessToken,
  setWorkspaceId,
  streamSSE,
  uploadAttachment,
} from './api.js'
import { agentModeDisplayName, agentModeHint, agentModeRequirement, agentModes, iterationVerdictLabel, mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from './ui-labels.js'
import { applyThemeMode, getThemeMode, toggleThemeMode } from './theme.js'
import { renderMarkdown } from './markdown.js'
import { applyLocale, t, antdLocaleOf } from './i18n.js'
import { formatRelativeTime, groupNotifications, notificationKind, notificationTone } from './notification-view.js'
import { validateUpload } from './upload-guard.js'

const { Header, Sider, Content } = Layout
const { Title, Text, Paragraph } = Typography

// 按需分包只在"第一次进入某页"时才下载。原先用 React.lazy + Suspense：
// React.lazy 的首次渲染一定会挂起并提交一次 Suspense 回退，**即使分包早已
// 下载到本地**——点一下导航整块内容被换成加载骨架，就是这么来的。
// 这里自己维护"已加载组件表"：预取完成后切页是同步渲染，预取尚未完成时
// 由调用方保留上一页，任何情况下都不会提交一个空的内容区。
const routeLoaders = {
  chat: () => import('./components/ChatPage.jsx'),
  business: () => import('./components/BusinessAssistantsPage.jsx'),
  report: () => import('./components/ReportAssistantsPage.jsx'),
  market: () => import('./components/MarketplacePage.jsx'),
}
const routeComponents = new Map()

function loadRoute(key) {
  const cached = routeComponents.get(key)
  if (cached) return Promise.resolve(cached)
  const loader = routeLoaders[key]
  if (!loader) return Promise.resolve(null)
  return loader().then((module) => {
    const Component = module.default || module
    routeComponents.set(key, Component)
    return Component
  })
}

function preloadRoutes() {
  Object.keys(routeLoaders).forEach((key) => { loadRoute(key).catch(() => {}) })
}

/**
 * 取当前路由对应的组件。
 *
 * 返回值里带上它属于哪个 key：分包组件表是按 key 缓存的一个共享变量，若只
 * 返回组件本身，"nav 已经切到 B、缓存还停在 A"的那一帧就会把 A 组件按 B 的
 * props 渲染出来（聊天页拿到插件市场的 props，直接崩在 models.map 上）。
 * 调用方用 `key` 比对后再决定是否渲染，宁可多等一帧也不张冠李戴。
 */
function useRouteComponent(key) {
  const [entry, setEntry] = useState(() => ({ key, Component: routeComponents.get(key) || null }))
  useEffect(() => {
    const cached = routeComponents.get(key)
    if (cached) { setEntry({ key, Component: cached }); return undefined }
    if (!routeLoaders[key]) { setEntry({ key, Component: null }); return undefined }
    let alive = true
    loadRoute(key)
      .then((Component) => { if (alive && Component) setEntry({ key, Component }) })
      .catch(() => {})
    return () => { alive = false }
  }, [key])
  return entry
}
const columns = [
  { key: 'backlog', title: '待梳理', color: '#8c8c8c' },
  { key: 'todo', title: '待处理', color: '#1677ff' },
  { key: 'in_progress', title: '进行中', color: '#fa8c16' },
  { key: 'review', title: '待审核', color: '#722ed1' },
  { key: 'done', title: '已完成', color: '#52c41a' },
]

const taskStatusLabels = Object.fromEntries(columns.map((item) => [item.key, item.title]))
const priorityLabels = { low: '低', medium: '中', high: '高', urgent: '紧急' }
const roleLabels = { owner: '所有者', admin: '管理员', member: '成员', viewer: '只读成员' }
// 通知中心的来源图标：图标表来源，颜色表强度（见 notification-view.js）。
const NOTIFICATION_ICONS = { task: <ProjectOutlined />, plan: <FileTextOutlined />, run: <RobotOutlined />, alert: <BellOutlined />, default: <InboxOutlined /> }
const planStatusLabels = { draft: '草稿', approved: '已批准', in_progress: '执行中', completed: '已完成' }
// 权限档位按宽松程度递增；超出部署上限的选项会被禁用。
const permissionModeOrder = ['default', 'auto_approve', 'full_access']
const permissionModeLabels = { default: '默认权限', auto_approve: '自动审批', full_access: '完全访问' }
const permissionModeHints = {
  default: '计划必须由所有者或管理员人工批准后才能执行。',
  auto_approve: '保存计划即视为批准，仍保留步骤级人工复核。',
  full_access: '自动批准且执行成功后直接把步骤标为完成，跳过人工复核。',
}
const permissionModeRisks = {
  default: '',
  auto_approve: '开启后任何成员保存的计划都会立即变为可执行，不再有人工门禁。',
  full_access: '开启后计划自动批准、步骤自动完成，AI 产出将不经人工确认直接计入计划进度。租户隔离、RBAC 与 run_python 禁用仍生效。',
}
const stepStatusLabels = { pending: '待执行', running: '执行中', blocked: '受阻', done: '已完成' }
const runStatusLabels = { running: '执行中', succeeded: '已完成', failed: '执行失败', cancelled: '已取消' }
const historicRunErrorLabels = {
  'The AI execution did not complete. Check model routing and retry.': 'AI 执行未完成，请检查模型路由后重试。',
  'The AI execution exceeded its allowed runtime and was stopped.': 'AI 执行超过允许时长，已被停止。',
  'The AI execution was cancelled by an authorised workspace member.': 'AI 执行已被有权限的工作区成员取消。',
}

// 顺序即侧边栏导航的展示顺序：看板与工作模式是主作业面，排在两个
// 助手之前。chat 仍保留在首位作为默认页与面包屑文案的参考项，但不在
// 导航里列项——对话列表本身就是它的入口。
// 工作模式与创造模式都不再单独占导航入口：前者是运行模式某几档的执行视图，
// 后者的入口在运行模式下拉的「创造」一项里。把同一个概念摆两处只会让人疑惑
// "这两个到底是不是同一个东西"。页面组件与路由都保留，只是不在导航露出。
const navigationKeys = ['chat', 'board', 'market', 'business', 'report', 'team', 'settings']
const navigationIcons = {
  chat: <MessageOutlined />,
  business: <BarChartOutlined />,
  report: <FileTextOutlined />,
  board: <ProjectOutlined />,
  work: <AppstoreOutlined />,
  market: <ThunderboltOutlined />,
  studio: <ExperimentOutlined />,
  team: <TeamOutlined />,
  settings: <SettingOutlined />,
}
const buildNavigationItems = () => navigationKeys.map((key) => ({
  key,
  icon: navigationIcons[key],
  label: t(`nav.${key}`),
}))

const navigationLabels = () => Object.fromEntries(
  navigationKeys.map((key) => [key, t(`nav.${key}`)]),
)

const emptyTask = { title: '', description: '', priority: 'medium', status: 'todo', labels: [] }

function chineseMessage(value, fallback) {
  const text = String(value || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : fallback
}

function readableError(error) {
  return chineseMessage(error?.message, '操作未完成，请稍后重试。')
}

function readableRunError(message) {
  return historicRunErrorLabels[message] || chineseMessage(message, 'AI 执行未完成，请检查模型配置后重试。')
}

function readableStatus(status) {
  return taskStatusLabels[status] || planStatusLabels[status] || stepStatusLabels[status] || runStatusLabels[status] || chineseMessage(status, '状态已更新')
}

function formatDateTime(value) {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '—' : date.toLocaleString('zh-CN', { hour12: false })
}

function recordedRunMcpServers(run) {
  const candidates = [run?.mcp_servers, run?.config?.mcp_servers, run?.metadata?.mcp_servers]
  return candidates.find((value) => Array.isArray(value)) ?? null
}

function AuthScreen({ onAuthenticated }) {
  const { message } = AntApp.useApp()
  const [mode, setMode] = useState('login')
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  const submit = async (values) => {
    setLoading(true)
    try {
      const payload = await apiFetch(`/api/v1/auth/${mode === 'login' ? 'login' : 'register'}`, {
        method: 'POST',
        body: JSON.stringify(values),
        workspaceId: '',
      })
      applyAuthSession(payload)
      message.success(mode === 'login' ? '欢迎回来' : '工作区已创建')
      onAuthenticated(payload)
    } catch (error) {
      if (error?.fieldErrors?.length) form.setFields(error.fieldErrors)
      message.error(readableError(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <section className="auth-intro" aria-label="产品简介">
        <div className="auth-intro-brand"><BrandMark size={38} className="brand-mark" /><span>futureAgent</span></div>
        <div className="auth-intro-hero">
          <Title level={1}>把对话、任务与交付<br />放进同一个 AI 工作区</Title>
          <Paragraph>规划、审批、执行、留痕：团队在一个有权限边界的工作区里，让 AI 真正接手可追溯的工作。</Paragraph>
        </div>
        <Space direction="vertical" size={10} className="auth-intro-points">
          <Text><CheckCircleFilled /> 多工作区隔离与角色权限</Text>
          <Text><CheckCircleFilled /> 计划-审批-执行的工作治理</Text>
          <Text><CheckCircleFilled /> 全程可审计的操作轨迹</Text>
        </Space>
      </section>
          <Card className="auth-card" variant="borderless">
            <Space direction="vertical" size={4} className="auth-heading">
              <Title level={3} style={{ marginBottom: 2 }}>{t('auth.title')}</Title>
              <Text type="secondary">{t('auth.subtitle')}</Text>
            </Space>
            <div className="auth-tabs">
              <Button type={mode === 'login' ? 'primary' : 'text'} onClick={() => { setMode('login'); form.resetFields() }}>{t('auth.tab.login')}</Button>
              <Button type={mode === 'register' ? 'primary' : 'text'} onClick={() => { setMode('register'); form.resetFields() }}>{t('auth.tab.register')}</Button>
            </div>
            <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
              {mode === 'register' && (
                <>
                  <Form.Item name="display_name" label="你的姓名" rules={[{ required: true, min: 2 }]}>
                    <Input autoComplete="name" placeholder="团队成员如何称呼你？" />
                  </Form.Item>
                  <Form.Item name="workspace_name" label="工作区名称" rules={[{ required: true, min: 2 }]}>
                    <Input placeholder="例如：产品研发中心" />
                  </Form.Item>
                </>
              )}
              <Form.Item name="email" label={t('auth.email')} rules={[{ required: true, type: 'email' }]}>
                <Input autoComplete="email" placeholder="name@company.com" />
              </Form.Item>
              {mode === 'login' ? (
                <Form.Item name="password" label={t('auth.password')} rules={[{ required: true, min: 10, message: '密码至少需要 10 个字符' }]}>
                  <Input.Password autoComplete="current-password" placeholder="至少 10 个字符" />
                </Form.Item>
              ) : (
                <Form.Item name="password" label={t('auth.password')} rules={[{ required: true, min: 10, message: '密码至少需要 10 个字符' }]}>
                  <Input.Password autoComplete="new-password" placeholder="至少 10 个字符" />
                </Form.Item>
              )}
              <Button type="primary" htmlType="submit" block size="large" loading={loading}>
                {mode === 'login' ? t('auth.submit.login') : t('auth.submit.register')}
              </Button>
            </Form>
        <Paragraph type="secondary" className="auth-footnote">
          浏览器仅保存短期访问令牌；续期会话由服务端通过仅服务器可访问的安全会话标记管理。
        </Paragraph>
      </Card>
    </div>
  )
}

function TaskCard({ task, members, onSelect, onMove }) {
  const assignee = members.find((item) => item.user.id === task.assignee_id)?.user
  return (
    <Card
      size="small"
      className={`task-card${task.archived ? ' is-archived' : ''}`}
      hoverable
      onClick={() => onSelect(task)}
      draggable={!task.archived}
      data-task-id={task.id}
      onDragStart={(event) => {
        if (task.archived) return
        event.dataTransfer.setData('text/futureagent-task', task.id)
        event.dataTransfer.effectAllowed = 'move'
      }}
    >
      <Flex justify="space-between" align="start" gap={8}>
        <Text strong>{task.title}</Text>
        {task.archived ? (
          <Tag bordered={false}>已归档</Tag>
        ) : (
          <Dropdown menu={{ items: columns.filter((item) => item.key !== task.status).map((item) => ({ key: item.key, label: `移动到「${item.title}」` })), onClick: ({ key }) => onMove(task, key) }} trigger={['click']}>
            <Button size="small" type="text" onClick={(event) => event.stopPropagation()}><SettingOutlined /></Button>
          </Dropdown>
        )}
      </Flex>
      {task.description && <Paragraph ellipsis={{ rows: 2 }} type="secondary" className="task-description">{task.description}</Paragraph>}
      <Flex justify="space-between" align="center" className="task-meta">
        <Space size={4}>
          {(task.labels || []).slice(0, 2).map((label) => <Tag key={label} bordered={false}>{label}</Tag>)}
          {task.comment_count > 0 && (
            <Tooltip title={`${task.comment_count} 条评论`}>
              <Tag icon={<MessageOutlined />} color="default">{task.comment_count}</Tag>
            </Tooltip>
          )}
        </Space>
        <Space size={4}>
          {task.due_date && <Tag icon={<ClockCircleOutlined />} color="default">{String(task.due_date).slice(5)}</Tag>}
          <Tag color={task.priority === 'urgent' ? 'red' : task.priority === 'high' ? 'orange' : 'default'}>{priorityLabels[task.priority] || task.priority}</Tag>
          {assignee && <Tooltip title={assignee.display_name}><Avatar size="small" icon={<UserOutlined />}/></Tooltip>}
        </Space>
      </Flex>
    </Card>
  )
}

function TaskCalendarView({ tasks, members, onSelect }) {
  const today = new Date()
  const [cursor, setCursor] = useState({ year: today.getFullYear(), month: today.getMonth() })
  const firstDay = new Date(cursor.year, cursor.month, 1)
  const startOffset = (firstDay.getDay() + 6) % 7
  const daysInMonth = new Date(cursor.year, cursor.month + 1, 0).getDate()
  const cells = []
  for (let index = 0; index < startOffset; index += 1) cells.push(null)
  for (let day = 1; day <= daysInMonth; day += 1) cells.push(day)
  while (cells.length % 7 !== 0) cells.push(null)
  const isoDate = (day) => `${cursor.year}-${String(cursor.month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
  const weekdayLabels = ['一', '二', '三', '四', '五', '六', '日']
  const shiftMonth = (delta) => setCursor((current) => {
    const next = new Date(current.year, current.month + delta, 1)
    return { year: next.getFullYear(), month: next.getMonth() }
  })
  return (
    <Card size="small" className="calendar-card">
      <Flex justify="space-between" align="center" gap={8} className="calendar-toolbar">
        <Button size="small" onClick={() => shiftMonth(-1)} aria-label="上个月">‹</Button>
        <Text strong>{cursor.year} 年 {cursor.month + 1} 月 · 按截止日期</Text>
        <Button size="small" onClick={() => shiftMonth(1)} aria-label="下个月">›</Button>
      </Flex>
      <div className="calendar-grid">
        {weekdayLabels.map((label) => <div key={label} className="calendar-weekday">{label}</div>)}
        {cells.map((day, index) => {
          if (!day) return <div key={`blank-${index}`} className="calendar-cell calendar-cell-blank" />
          const iso = isoDate(day)
          const dueTasks = tasks.filter((task) => String(task.due_date || '').startsWith(iso))
          const isToday = iso === `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
          return (
            <div key={iso} className={`calendar-cell${isToday ? ' calendar-cell-today' : ''}`}>
              <div className="calendar-day">{day}</div>
              {dueTasks.slice(0, 3).map((task) => (
                <Button key={task.id} type="text" size="small" className="calendar-task" onClick={() => onSelect(task)} title={task.title}>
                  {task.title}
                </Button>
              ))}
              {dueTasks.length > 3 && <Text type="secondary" className="calendar-more">还有 {dueTasks.length - 3} 项</Text>}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function TaskComments({ taskId }) {
  const { message } = AntApp.useApp()
  const [comments, setComments] = useState([])
  const [value, setValue] = useState('')
  useEffect(() => {
    let current = true
    setComments([])
    if (!taskId) return () => { current = false }
    apiFetch(`/api/v1/tasks/${taskId}/comments`)
      .then((data) => { if (current) setComments(data.comments || []) })
      .catch(() => { /* 评论加载失败不打开抽屉报错 */ })
    return () => { current = false }
  }, [taskId])
  const submit = async () => {
    const content = value.trim()
    if (!content || !taskId) return
    try {
      const data = await apiFetch(`/api/v1/tasks/${taskId}/comments`, { method: 'POST', body: JSON.stringify({ content }) })
      setComments((previous) => [...previous, data.comment])
      setValue('')
    } catch (error) { message.error(readableError(error)) }
  }
  return (
    <div className="task-comments">
      <Text strong>评论（{comments.length}）</Text>
      <List size="small" locale={{ emptyText: '暂无评论' }} dataSource={comments} renderItem={(comment) => (
        <List.Item><List.Item.Meta title={`${comment.author_name} · ${formatDateTime(comment.created_at)}`} description={comment.content} /></List.Item>
      )} />
      <Flex gap={8}>
        <Input value={value} onChange={(event) => setValue(event.target.value)} placeholder="写下评论，回车发送" onPressEnter={submit} />
        <Button type="primary" onClick={submit} disabled={!value.trim()}>发送</Button>
      </Flex>
    </div>
  )
}

function BoardPage({ projects, tasks, members, onRefresh, openTask, workspaceRole }) {
  const { message } = AntApp.useApp()
  const [projectId, setProjectId] = useState(projects[0]?.id || '')
  const [taskOpen, setTaskOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [view, setView] = useState('board')
  // 已归档的工作项默认不出现；打开开关时才按需拉一次（列表接口默认就过滤掉）。
  const [showArchived, setShowArchived] = useState(false)
  const [archivedTasks, setArchivedTasks] = useState([])
  const [form] = Form.useForm()
  const [projectForm] = Form.useForm()

  useEffect(() => {
    if (!showArchived) {
      setArchivedTasks([])
      return undefined
    }
    let cancelled = false
    apiFetch('/api/v1/tasks?include_archived=true')
      .then((data) => {
        if (!cancelled) setArchivedTasks((data.tasks || []).filter((task) => task.archived))
      })
      .catch(() => { if (!cancelled) setArchivedTasks([]) })
    return () => { cancelled = true }
  }, [showArchived, tasks])

  // 刚创建的项目在刷新回来之前不在 projects 里，如果不加保护，下面这个
  // 守卫会立刻把选中项打回 projects[0]，用户就停在旧项目的空看板上。
  const pendingProjectRef = useRef('')
  useEffect(() => {
    if (pendingProjectRef.current) {
      if (projects.some((item) => item.id === pendingProjectRef.current)) {
        setProjectId(pendingProjectRef.current)
        pendingProjectRef.current = ''
      }
      return
    }
    if (!projects.some((item) => item.id === projectId)) setProjectId(projects[0]?.id || '')
  }, [projects, projectId])

  // 归档列表是异步取回的，刷新前后可能短暂与 tasks 重叠；按 id 去重，
  // 否则同一张卡片会渲染两次（React 也会报 key 重复）。
  const projectTasks = (() => {
    const merged = new Map(tasks.map((task) => [task.id, task]))
    if (showArchived) {
      archivedTasks.forEach((task) => { if (!merged.has(task.id)) merged.set(task.id, task) })
    }
    return [...merged.values()]
  })().filter((task) => {
    const text = `${task.title} ${task.description || ''} ${(task.labels || []).join(' ')}`.toLowerCase()
    return task.project_id === projectId && (statusFilter === 'all' || task.status === statusFilter) && (!query.trim() || text.includes(query.trim().toLowerCase()))
  })
  const saveTask = async (values) => {
    try {
      await apiFetch('/api/v1/tasks', { method: 'POST', body: JSON.stringify({ ...values, project_id: projectId, labels: String(values.labels || '').split(',').map((item) => item.trim()).filter(Boolean) }) })
      message.success('任务已加入看板')
      setTaskOpen(false)
      form.resetFields()
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const saveProject = async (values) => {
    try {
      // 颜色只作为看板标识的占位，用中性灰：项目卡片不参与彩色装饰体系。
      const payload = await apiFetch('/api/v1/projects', { method: 'POST', body: JSON.stringify({ ...values, color: '#8a8f98' }) })
      message.success('项目已创建')
      setProjectOpen(false)
      projectForm.resetFields()
      // 建完直接切到新项目：否则用户会停在旧项目的空看板上，以为创建失败。
      if (payload?.project?.id) {
        pendingProjectRef.current = payload.project.id
        setProjectId(payload.project.id)
      }
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const moveTask = async (task, status) => {
    try {
      await apiFetch(`/api/v1/tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const reorderTask = async (dragged, overTask, columnKey) => {
    try {
      if (dragged.status === columnKey) {
        // 同列：与目标卡片交换排序值
        await Promise.all([
          apiFetch(`/api/v1/tasks/${dragged.id}`, { method: 'PATCH', body: JSON.stringify({ sort_order: overTask.sort_order ?? 0 }) }),
          apiFetch(`/api/v1/tasks/${overTask.id}`, { method: 'PATCH', body: JSON.stringify({ sort_order: dragged.sort_order ?? 0 }) }),
        ])
      } else {
        // 跨列：落到目标卡片的位置
        await apiFetch(`/api/v1/tasks/${dragged.id}`, { method: 'PATCH', body: JSON.stringify({ status: columnKey, sort_order: overTask.sort_order ?? 0 }) })
      }
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const canWrite = workspaceRole !== 'viewer'
  return (
    <div className="page-shell">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading">
        <div><Title level={2}>{t('nav.board')}</Title><Text type="secondary">把目标变成可见、可负责的工作；每一次变更都会写入工作区审计记录。</Text></div>
        <Space>
          <Button icon={<FileAddOutlined />} onClick={async () => { try { await downloadCsv(`/api/v1/tasks/export${projectId ? `?project_id=${projectId}` : ''}`, 'tasks.csv'); message.success('任务清单已导出') } catch (error) { message.error(readableError(error)) } }}>导出任务</Button>
          {canWrite && <Button icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>新建项目</Button>}
          {canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!projectId} onClick={() => setTaskOpen(true)}>新建任务</Button>}
        </Space>
      </Flex>
      {projects.length ? <Flex wrap="wrap" gap={10} className="board-filters"><Select value={projectId} onChange={setProjectId} className="project-selector" options={projects.map((item) => ({ value: item.id, label: item.name }))} /><Input.Search allowClear placeholder="搜索任务标题、上下文或标签" value={query} onChange={(event) => setQuery(event.target.value)} style={{ width: 280, maxWidth: '100%' }} /><Select value={statusFilter} onChange={setStatusFilter} style={{ width: 150 }} options={[{ value: 'all', label: '全部状态' }, ...columns.map((item) => ({ value: item.key, label: item.title }))]} /><Checkbox checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)}>显示已归档</Checkbox><Segmented value={view} onChange={setView} options={[{ label: '看板', value: 'board' }, { label: '日历', value: 'calendar' }]} /></Flex> : <Empty className="guided-empty" description="请先创建项目，再开始规划工作">{canWrite && <Button type="primary" icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>创建第一个项目</Button>}</Empty>}
      {projectId && view === 'calendar' && <TaskCalendarView tasks={projectTasks} members={members} onSelect={openTask} />}
      {projectId && view === 'board' && <div className="kanban-grid">{columns.map((column) => (
        <section
          key={column.key}
          className={`kanban-column kanban-column-${column.key}`}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move' }}
          onDrop={(event) => {
            event.preventDefault()
            if (!canWrite) return
            const draggedId = event.dataTransfer.getData('text/futureagent-task')
            const dragged = projectTasks.find((task) => task.id === draggedId)
            if (!dragged) return
            const overCard = event.target.closest?.('.task-card[data-task-id]')
            const overTask = overCard ? projectTasks.find((task) => task.id === overCard.dataset.taskId) : null
            if (overTask && overTask.id !== dragged.id) reorderTask(dragged, overTask, column.key)
            else if (dragged.status !== column.key) moveTask(dragged, column.key)
          }}
        >
          <Flex justify="space-between" align="center"><Text strong>{column.title}</Text><Badge color={column.color} count={projectTasks.filter((task) => task.status === column.key).length} /></Flex>
          <div className="task-stack">
            {projectTasks.filter((task) => task.status === column.key).map((task) => <TaskCard key={task.id} task={task} members={members} onSelect={openTask} onMove={moveTask} />)}
            {!projectTasks.some((task) => task.status === column.key) && <Text type="secondary" className="empty-column">暂无任务</Text>}
          </div>
        </section>
      ))}</div>}

      <Modal title="新建任务" open={taskOpen} onCancel={() => setTaskOpen(false)} onOk={() => form.submit()} okText="确认" cancelText="取消" destroyOnHidden>
        <Form form={form} layout="vertical" initialValues={emptyTask} onFinish={saveTask}>
          <Form.Item name="title" label="任务标题" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
          <Form.Item name="description" label="任务背景"><Input.TextArea rows={4} /></Form.Item>
          <Flex gap={12}><Form.Item name="priority" label="优先级" className="flex-field"><Select options={['low', 'medium', 'high', 'urgent'].map((value) => ({ value, label: priorityLabels[value] }))} /></Form.Item><Form.Item name="assignee_id" label="负责人" className="flex-field"><Select allowClear options={members.map((item) => ({ value: item.user.id, label: item.user.display_name }))} /></Form.Item></Flex>
          <Form.Item name="labels" label="标签"><Input placeholder="设计, 上线" /></Form.Item>
        </Form>
      </Modal>
      <Modal title="新建项目" open={projectOpen} onCancel={() => setProjectOpen(false)} onOk={() => projectForm.submit()} okText="确认" cancelText="取消" destroyOnHidden>
        <Form form={projectForm} layout="vertical" onFinish={saveProject}><Form.Item name="name" label="项目名称" rules={[{ required: true, min: 2 }]}><Input /></Form.Item><Form.Item name="description" label="项目说明"><Input.TextArea rows={4} /></Form.Item></Form>
      </Modal>
    </div>
  )
}

// 差异行的语义完全由前缀决定；表头行必须先判，否则会被当成增删。

function TaskResultsPanel({ taskId, canWrite, members, refreshKey }) {
  const { message } = AntApp.useApp()
  const [attachments, setAttachments] = useState([])
  const [events, setEvents] = useState([])
  const [deliverables, setDeliverables] = useState([])
  const [workspaceFiles, setWorkspaceFiles] = useState([])
  const [workspaceFilesLoading, setWorkspaceFilesLoading] = useState(false)
  const [registerOpen, setRegisterOpen] = useState(false)
  const [preview, setPreview] = useState(null)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('outputs')
  const [loading, setLoading] = useState(false)
  const previewUrlRef = useRef('')
  const resultsRequestIdRef = useRef(0)
  const previewRequestIdRef = useRef(0)
  const currentTaskIdRef = useRef(taskId)
  currentTaskIdRef.current = taskId
  const activityLabels = {
    'task.created': '已创建任务',
    'task.updated': '已更新任务',
    'work_plan.saved': '已保存工作计划',
    'work_plan.approved': '已批准工作计划',
    'work_plan.step_updated': '已更新执行步骤',
    'attachment.uploaded': '已添加文件',
    'agent_run.started': '已启动 AI 执行',
    'agent_run.completed': 'AI 执行已完成',
    'agent_run.failed': 'AI 执行需要处理',
    'agent_run.cancelled': '已取消 AI 执行',
  }
  const loadResults = useCallback(async (requestedTaskId = taskId) => {
    const requestId = ++resultsRequestIdRef.current
    if (!requestedTaskId) { setAttachments([]); setEvents([]); setDeliverables([]); setLoading(false); return false }
    setLoading(true)
    try {
      const [files, activity, deliverableData] = await Promise.all([
        apiFetch(`/api/v1/attachments?task_id=${requestedTaskId}`),
        apiFetch(`/api/v1/tasks/${requestedTaskId}/activity`),
        apiFetch(`/api/v1/deliverables?task_id=${requestedTaskId}`),
      ])
      if (requestId !== resultsRequestIdRef.current || currentTaskIdRef.current !== requestedTaskId) return false
      setAttachments(files.attachments || [])
      setEvents(activity.events || [])
      setDeliverables(deliverableData.deliverables || [])
      return true
    } catch (error) {
      if (requestId === resultsRequestIdRef.current && currentTaskIdRef.current === requestedTaskId) message.error(readableError(error))
      return false
    } finally {
      if (requestId === resultsRequestIdRef.current && currentTaskIdRef.current === requestedTaskId) setLoading(false)
    }
  }, [message, taskId])
  useEffect(() => {
    previewRequestIdRef.current += 1
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    previewUrlRef.current = ''
    setPreview(null)
    setPreviewOpen(false)
    loadResults()
  }, [loadResults, refreshKey])
  useEffect(() => () => { if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current) }, [])
  const attach = async ({ file, onSuccess, onError }) => {
    const requestedTaskId = taskId
    const invalid = validateUpload(file)
    if (invalid) { message.error(invalid); onError?.(new Error(invalid)); return }
    try {
      await uploadAttachment(file, { task_id: requestedTaskId })
      await loadResults(requestedTaskId)
      message.success('文件已添加到此工作项')
      onSuccess?.('ok')
    } catch (error) { message.error(readableError(error)); onError?.(error) }
  }
  // 关闭抽屉时立即释放 blob URL，不能等到下次刷新——长会话里会积压内存。
  const closePreview = () => {
    previewRequestIdRef.current += 1
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
    previewUrlRef.current = ''
    setPreviewOpen(false)
    setPreview(null)
  }
  const showPreview = async (attachment) => {
    const requestedTaskId = taskId
    const requestId = ++previewRequestIdRef.current
    let objectUrl = ''
    try {
      const data = await apiFetch(attachment.preview_url)
      if (data.preview_kind === 'image' || data.preview_kind === 'pdf') {
        objectUrl = URL.createObjectURL(await getAttachmentBlob(attachment))
      }
      if (requestId !== previewRequestIdRef.current || currentTaskIdRef.current !== requestedTaskId) {
        if (objectUrl) URL.revokeObjectURL(objectUrl)
        return
      }
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current)
      previewUrlRef.current = objectUrl
      setPreview({ ...data, objectUrl })
      setPreviewOpen(true)
    } catch (error) {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      if (requestId === previewRequestIdRef.current && currentTaskIdRef.current === requestedTaskId) message.error(readableError(error))
    }
  }
  const download = async (attachment) => {
    try { await downloadAttachment(attachment); message.success('已开始下载') } catch (error) { message.error(readableError(error)) }
  }
  const loadWorkspaceFiles = async () => {
    setWorkspaceFilesLoading(true)
    try {
      const data = await apiFetch('/api/v1/workspace/files')
      setWorkspaceFiles(data.files || [])
    } catch (error) {
      setWorkspaceFiles([])
      message.warning(readableError(error))
    } finally {
      setWorkspaceFilesLoading(false)
    }
  }
  const registerDeliverable = async (file) => {
    try {
      await apiFetch('/api/v1/deliverables', {
        method: 'POST',
        body: JSON.stringify({ path: file.path, name: file.name, task_id: taskId }),
      })
      message.success(`已登记交付物：${file.name}`)
      await loadResults(taskId)
      setRegisterOpen(false)
    } catch (error) { message.error(readableError(error)) }
  }
  const downloadDeliverable = async (deliverable) => {
    try { await downloadAttachment({ ...deliverable, original_name: deliverable.name }); message.success('已开始下载') } catch (error) { message.error(readableError(error)) }
  }
  const files = <List loading={loading} size="small" locale={{ emptyText: '暂无任务文件' }} dataSource={attachments} renderItem={(attachment) => <List.Item actions={[attachment.preview_available ? <Button key="preview" type="link" size="small" onClick={() => showPreview(attachment)}>预览</Button> : null, <Button key="download" type="link" size="small" onClick={() => download(attachment)}>下载</Button>, <Button key="changes" type="link" size="small" onClick={() => setActiveTab('changes')}>查看变更</Button>].filter(Boolean)}><List.Item.Meta title={attachment.original_name} description={`${Math.ceil(attachment.size_bytes / 1024)} KB · ${formatDateTime(attachment.created_at)}`} /></List.Item>} />
  const deliverableList = <List loading={loading} size="small" locale={{ emptyText: '尚无交付物；AI 执行或登记工作区文件后会出现在这里' }} dataSource={deliverables} renderItem={(deliverable) => <List.Item actions={[<Button key="download" type="link" size="small" onClick={() => downloadDeliverable(deliverable)}>下载</Button>, <Button key="changes" type="link" size="small" onClick={() => setActiveTab('changes')}>查看变更</Button>]}><List.Item.Meta title={<Space size={6}><Tag bordered={false}>{deliverable.kind}</Tag>{deliverable.name}</Space>} description={`${Math.ceil(deliverable.size_bytes / 1024)} KB · 来源 ${deliverable.source_path || '工作区'} · ${formatDateTime(deliverable.created_at)}`} /></List.Item>} />
  const activity = <List loading={loading} size="small" locale={{ emptyText: '暂无任务动态' }} dataSource={events} renderItem={(event) => {
    const actor = members.find((member) => member.user.id === event.actor_id)?.user.display_name || '工作区成员'
    const status = event.metadata?.status ? ` · ${readableStatus(event.metadata.status)}` : ''
    return <List.Item><List.Item.Meta title={activityLabels[event.action] || '工作区记录已更新'} description={`${actor} · ${formatDateTime(event.created_at)}${status}`} /></List.Item>
  }} />
  const previewContent = !preview ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择任务文件进行预览" /> : <Space direction="vertical" size="small" style={{ width: '100%' }}><Text strong>{preview.attachment.original_name}</Text>{preview.preview_kind === 'image' ? <img className="artifact-image-preview" src={preview.objectUrl} alt={preview.attachment.original_name} /> : preview.preview_kind === 'pdf' ? <iframe className="artifact-pdf-preview" title={preview.attachment.original_name} src={preview.objectUrl} /> : preview.preview_available ? <pre className="attachment-preview">{preview.text}</pre> : <Text type="secondary">{chineseMessage(preview.message, '此文件暂不支持在线预览。')}</Text>}</Space>
  // 产出段合并原“交付物 / 文件 / 预览”三个 Tab：两个列表 + 逐项动作，
  // 预览就地打开抽屉，不占 Tab 位，用户不再需要在三层入口之间找文件。
  const outputs = (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <div>
        <Text strong>交付物（{deliverables.length}）</Text>
        {deliverableList}
      </div>
      <div>
        <Text strong>任务文件（{attachments.length}）</Text>
        {files}
      </div>
    </Space>
  )
  return <Card className="work-results" title={t('work.card.results')} extra={canWrite && <Space><Button size="small" icon={<FileAddOutlined />} onClick={() => { setRegisterOpen(true); loadWorkspaceFiles() }}>{t('work.btn.registerDeliverable')}</Button><Upload showUploadList={false} customRequest={attach} beforeUpload={(file) => { const invalid = validateUpload(file); if (invalid) { message.error(invalid); return Upload.LIST_IGNORE } return true }}><Button size="small" icon={<PaperClipOutlined />}>{t('work.btn.addContext')}</Button></Upload></Space>}>
    <Tabs
      size="small"
      activeKey={activeTab}
      onChange={setActiveTab}
      items={[
        { key: 'outputs', label: `${t('work.tab.outputs')}（${deliverables.length + attachments.length}）`, children: outputs },
        { key: 'changes', label: t('work.tab.changes'), children: <WorkspaceChangesPanel /> },
        { key: 'activity', label: `${t('work.tab.activity')}（${events.length}）`, children: activity },
      ]}
    />
    <Drawer title={preview?.attachment?.original_name || '文件预览'} width={720} open={previewOpen} onClose={closePreview} destroyOnHidden>
      {previewContent}
    </Drawer>
    <Modal title="从工作区登记交付物" open={registerOpen} onCancel={() => setRegisterOpen(false)} footer={null} destroyOnHidden>
      <Alert type="info" showIcon message="这里列出 AI 执行期间在工作区生成的文件" description="登记后会复制到交付物库，可随时下载，并随任务留痕。" style={{ marginBottom: 12 }} />
      {workspaceFilesLoading ? <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div> : workspaceFiles.length ? (
        <List size="small" dataSource={workspaceFiles} renderItem={(file) => (
          <List.Item actions={[<Button key="register" type="link" size="small" onClick={() => registerDeliverable(file)}>登记</Button>]}>
            <List.Item.Meta title={file.name} description={`${file.path} · ${Math.max(1, Math.ceil((file.size_bytes || 0) / 1024))} KB`} />
          </List.Item>
        )} />
      ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="工作区暂无文件；先在工作模式执行一次 AI 任务" />}
    </Modal>
  </Card>
}

function TaskExecutionPanel({ taskId, plan, models, skills, mcpServers = [], canWrite, onPlanRefresh, onRunningChange }) {
  const { message } = AntApp.useApp()
  const [runs, setRuns] = useState([])
  const [modelId, setModelId] = useState('')
  const [skillName, setSkillName] = useState('')
  const [selectedMcpServers, setSelectedMcpServers] = useState([])
  const [mode, setMode] = useState('agent')
  const [goal, setGoal] = useState('')
  const [criteria, setCriteria] = useState('')
  const [maxIterations, setMaxIterations] = useState(5)
  const [iterations, setIterations] = useState([])
  const [stepId, setStepId] = useState('')
  const [running, setRunning] = useState(false)
  const [liveOutput, setLiveOutput] = useState('')
  const [activeRunId, setActiveRunId] = useState('')
  const [batchOutput, setBatchOutput] = useState([])
  const [failedStepIds, setFailedStepIds] = useState([])
  const [batchRunning, setBatchRunning] = useState(false)
  const [activeBatchId, setActiveBatchId] = useState('')
  const [batchHistory, setBatchHistory] = useState([])
  const [batchDetails, setBatchDetails] = useState({})
  const loadBatchHistory = useCallback(async (requestedTaskId = taskId) => {
    if (!requestedTaskId) { setBatchHistory([]); return }
    try {
      const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/batches`)
      setBatchHistory(data.batches || [])
    } catch { setBatchHistory([]) }
  }, [taskId])
  const fetchBatchRuns = useCallback(async (batchId) => {
    if (batchDetails[batchId]) return
    setBatchDetails((previous) => ({ ...previous, [batchId]: { loading: true, runs: [] } }))
    try {
      const data = await apiFetch(`/api/v1/tasks/${taskId}/batches/${batchId}`)
      setBatchDetails((previous) => ({ ...previous, [batchId]: { loading: false, runs: data.runs || [] } }))
    } catch {
      setBatchDetails((previous) => ({ ...previous, [batchId]: { loading: false, runs: [], error: true } }))
    }
  }, [taskId, batchDetails])
  useEffect(() => { loadBatchHistory() }, [loadBatchHistory])
  useEffect(() => { if (!batchRunning) loadBatchHistory() }, [batchRunning, loadBatchHistory])
  const executionAbortRef = useRef(null)
  const cancellationRequestedRef = useRef(false)
  const runsRequestIdRef = useRef(0)
  const currentTaskIdRef = useRef(taskId)
  currentTaskIdRef.current = taskId
  const loadRuns = useCallback(async (requestedTaskId = taskId) => {
    const requestId = ++runsRequestIdRef.current
    if (!requestedTaskId) { setRuns([]); return false }
    try {
      const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/runs`)
      if (requestId !== runsRequestIdRef.current || currentTaskIdRef.current !== requestedTaskId) return false
      setRuns(data.runs || [])
      return true
    } catch (error) {
      if (requestId === runsRequestIdRef.current && currentTaskIdRef.current === requestedTaskId) message.error(readableError(error))
      return false
    }
  }, [message, taskId])
  useEffect(() => { loadRuns() }, [loadRuns])
  useEffect(() => {
    if (!models.some((item) => item.id === modelId && item.ready)) setModelId(models.find((item) => item.ready)?.id || '')
    if (!skills.some((item) => item.name === skillName)) setSkillName(skills[0]?.name || '')
  }, [modelId, models, skillName, skills])
  useEffect(() => { setStepId(''); setRuns([]); setLiveOutput(''); setActiveRunId(''); setIterations([]) }, [taskId])
  useEffect(() => {
    const availableSteps = (plan?.steps || []).filter((item) => item.status !== 'done')
    if (!availableSteps.some((item) => item.id === stepId)) setStepId(availableSteps[0]?.id || '')
  }, [plan, stepId, taskId])
  useEffect(() => {
    setSelectedMcpServers((current) => current.filter((name) => mcpServers.some((item) => (item.name || item) === name && !mcpServerUnavailable(item))))
  }, [mcpServers])
  useEffect(() => { onRunningChange?.(running) }, [onRunningChange, running])
  useEffect(() => () => onRunningChange?.(false), [onRunningChange])
  useEffect(() => () => executionAbortRef.current?.abort(), [])
  const execute = async (retryRun = null) => {
    if (!plan || running || batchRunning || (!retryRun && (!modelId || !skillName))) return
    const executionTaskId = taskId
    const retryMcpServers = retryRun ? recordedRunMcpServers(retryRun) : null
    const execution = retryRun ? {
      modelId: retryRun.model_id,
      skillName: retryRun.skill_name,
      stepId: retryRun.step_id,
      retryOfId: retryRun.id,
      mcpServers: retryMcpServers ?? selectedMcpServers,
      hasRecordedMcpConfig: retryMcpServers !== null,
      // 重试复现原来的运行模式，否则一次 goal 执行重试后会变成普通 agent。
      mode: retryRun.agent_mode || 'agent',
      goal, criteria, maxIterations,
    } : { modelId, skillName, stepId, retryOfId: null, mcpServers: selectedMcpServers, hasRecordedMcpConfig: true, mode, goal, criteria, maxIterations }
    const requirement = agentModeRequirement(execution.mode)
    if (requirement === 'goal' && !execution.goal.trim()) { message.warning('目标模式需要先填写目标，否则无法判定是否达成'); return }
    if (requirement === 'criteria' && !execution.criteria.trim()) { message.warning('循环模式需要先填写停止条件，否则会一直迭代到轮次上限'); return }
    if (execution.stepId && !(plan.steps || []).some((item) => item.id === execution.stepId)) {
      message.warning('所选步骤不属于当前任务，已为你切换到当前计划的可执行步骤。')
      setStepId((plan.steps || []).find((item) => item.status !== 'done')?.id || '')
      return
    }
    if (retryRun && !execution.hasRecordedMcpConfig) message.info('历史执行未保存 MCP 配置；本次仅复用原模型、技能与步骤，并使用当前工具选择。')
    const abortController = new AbortController()
    let terminalStatus = 'succeeded'
    cancellationRequestedRef.current = false
    executionAbortRef.current = abortController
    setActiveRunId(''); setLiveOutput(''); setRunning(true); setIterations([])
    try {
      await streamSSE(`/api/v1/tasks/${executionTaskId}/execute`, { model_id: execution.modelId, skill_name: execution.skillName, step_id: execution.stepId || null, mcp_servers: execution.mcpServers, retry_of_id: execution.retryOfId, mode: execution.mode, goal: execution.goal.trim(), success_criteria: execution.criteria.trim(), max_iterations: execution.maxIterations, idempotency_key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }, { signal: abortController.signal, onEvent: (event, data) => {
        if (currentTaskIdRef.current !== executionTaskId) return
        if (event === 'meta') {
          try { setActiveRunId(JSON.parse(data)?.run?.id || '') } catch { /* The run list remains the source of truth. */ }
        }
        if (event === 'iteration') {
          try { setIterations((previous) => [...previous, JSON.parse(data)]) } catch { /* 单条轮次事件解析失败不影响正文。 */ }
        }
        if (event === 'token') setLiveOutput((previous) => previous + data)
        if (event === 'cancelled') terminalStatus = 'cancelled'
        if (event === 'error') { let detail = data; try { detail = JSON.parse(data).detail || data } catch { /* Keep plain SSE errors. */ } throw new Error(detail) }
      } })
      if (currentTaskIdRef.current === executionTaskId) {
        if (terminalStatus === 'cancelled') message.info('AI 执行已取消，取消记录已写入审计轨迹')
        else message.success('AI 执行结果已保存，等待人工审核')
        await Promise.all([loadRuns(executionTaskId), onPlanRefresh?.(executionTaskId)])
      }
    } catch (error) {
      if (currentTaskIdRef.current === executionTaskId) {
        if (cancellationRequestedRef.current || error?.name === 'AbortError') message.info('AI 执行已取消，取消记录已写入审计轨迹')
        else message.error(readableError(error))
        await loadRuns(executionTaskId)
      }
    } finally {
      if (executionAbortRef.current === abortController) executionAbortRef.current = null
      cancellationRequestedRef.current = false
      setActiveRunId('')
      setRunning(false)
    }
  }
  const cancelRun = async (runId) => {
    if (!runId) return
    const requestedTaskId = taskId
    cancellationRequestedRef.current = true
    try {
      await apiFetch(`/api/v1/tasks/${requestedTaskId}/runs/${runId}/cancel`, { method: 'POST' })
      if (currentTaskIdRef.current !== requestedTaskId) { cancellationRequestedRef.current = false; return }
      if (runId === activeRunId) executionAbortRef.current?.abort()
      await Promise.all([loadRuns(requestedTaskId), onPlanRefresh?.(requestedTaskId)])
      message.info('已记录取消操作，后续模型输出不会再被接收。')
    } catch (error) {
      cancellationRequestedRef.current = false
      if (currentTaskIdRef.current === requestedTaskId) message.error(readableError(error))
    }
  }
  const runItems = runs.map((run) => {
    const hasRecordedMcpConfig = recordedRunMcpServers(run) !== null
    const retryButton = <Button size="small" onClick={() => execute(run)} disabled={running || batchRunning}>{hasRecordedMcpConfig ? '使用原配置重试' : '复用原模型与技能重试'}</Button>
    return { key: run.id, label: <Space size={6}>{run.batch_id && <Tag bordered={false}>并行批次</Tag>}{run.agent_mode && run.agent_mode !== 'agent' && <Tag bordered={false}>{agentModeDisplayName(run.agent_mode)}</Tag>}{readableStatus(run.status)} · {formatDateTime(run.started_at)}</Space>, children: <Space direction="vertical" size="small" style={{ width: '100%' }}><Text type="secondary">{run.model_id} · {skillDisplayName(run.skill_name)} · 第 {run.attempt || 1} 次尝试{run.usage?.records ? '' : ' · 用量未上报'}</Text>{/* 用量、子代理与轮次时间线统一由 MessageBlocks 渲染，与对话页共用一套样式。 */}<MessageBlocks message={run} canWrite={canWrite} />{run.output ? <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(run.output) }} /> : <Text type="secondary">{readableRunError(run.error_message)}</Text>}<Space>{['failed', 'cancelled'].includes(run.status) && canWrite && (hasRecordedMcpConfig ? retryButton : <Tooltip title="历史记录未包含 MCP 配置，重试时会使用当前工具选择。">{retryButton}</Tooltip>)}{run.status === 'running' && canWrite && <Button size="small" danger onClick={() => cancelRun(run.id)} disabled={running && activeRunId && activeRunId !== run.id}>取消执行</Button>}</Space></Space> }
  })
  const executable = Boolean(plan && ['approved', 'in_progress'].includes(plan.status) && canWrite && models.some((item) => item.id === modelId && item.ready) && skillName && stepId)
  const pendingSteps = (plan?.steps || []).filter((step) => step.status === 'pending')
  const batchExecutable = Boolean(plan && ['approved', 'in_progress'].includes(plan.status) && canWrite && pendingSteps.length >= 2 && models.some((item) => item.id === modelId && item.ready) && skillName)
  const executeParallel = async (retryStepIds = null) => {
    const targets = retryStepIds
      ? (plan?.steps || []).filter((step) => retryStepIds.includes(step.id))
      : pendingSteps
    if (!plan || batchRunning || !targets.length) return
    if (!retryStepIds && targets.length < 2) return
    const executionTaskId = taskId
    const controller = new AbortController()
    executionAbortRef.current = controller
    setBatchOutput(targets.map((step) => ({ stepId: step.id, title: step.title, status: 'running', text: '' })))
    setBatchRunning(true)
    setActiveBatchId('')
    setFailedStepIds([])
    try {
      await streamSSE(
        `/api/v1/tasks/${executionTaskId}/execute-parallel`,
        { model_id: modelId, skill_name: skillName, mcp_servers: selectedMcpServers, step_ids: retryStepIds || undefined },
        {
          signal: controller.signal,
          onEvent: (event, data) => {
            if (event === 'error') {
              let detail = data
              try { detail = JSON.parse(data).detail || data } catch { /* plain SSE error */ }
              throw new Error(detail)
            }
            let parsed = null
            try { parsed = JSON.parse(data) } catch { return }
            if (event === 'meta') {
              setActiveBatchId(parsed.batch_id || '')
              setFailedStepIds([])
              setBatchOutput((previous) => previous.map((item) => ({
                ...item,
                runId: (parsed.runs || []).find((run) => run.step_id === item.stepId)?.id || '',
              })))
              return
            }
            if (event === 'done') {
              setFailedStepIds(parsed.failed_step_ids || [])
              return
            }
            const stepId = parsed.step_id
            setBatchOutput((previous) => previous.map((item) => {
              if (item.stepId !== stepId) return item
              if (event === 'step-token') return { ...item, text: item.text + (parsed.chunk || '') }
              if (event === 'step-done') return { ...item, status: 'succeeded' }
              if (event === 'step-cancelled') return { ...item, status: 'cancelled' }
              if (event === 'step-error') return { ...item, status: 'failed', error: parsed.message }
              return item
            }))
          }
        },
      )
      message.success('并行批次执行完成，请逐条审核结果')
      await Promise.all([loadRuns(executionTaskId), onPlanRefresh?.(executionTaskId)])
      setBatchOutput([])
    } catch (error) {
      message.error(readableError(error))
      await loadRuns(executionTaskId)
      await onPlanRefresh?.(executionTaskId)
    } finally {
      if (executionAbortRef.current === controller) executionAbortRef.current = null
      setBatchRunning(false)
    }
  }
  const cancelBatch = async () => {
    if (!activeBatchId || !batchRunning) return
    try {
      const result = await apiFetch(`/api/v1/tasks/${taskId}/runs/cancel-batch`, { method: 'POST', body: JSON.stringify({ batch_id: activeBatchId }) })
      message.info(`已请求取消 ${result.cancelled} 个并行执行`)
      executionAbortRef.current?.abort()
      await loadRuns(taskId)
    } catch (error) { message.error(readableError(error)) }
  }
  return <Card className="work-results" title={t('work.card.ai')} extra={<Space><Button type="primary" icon={<RobotOutlined />} loading={running} disabled={!executable} onClick={() => execute()}>{t('work.btn.executeStep')}</Button>{pendingSteps.length >= 2 && <Tooltip title={`并行执行 ${pendingSteps.length} 个待执行步骤，整批占用一个并发槽`}><Button icon={<ThunderboltOutlined />} loading={batchRunning} disabled={!batchExecutable || running} onClick={executeParallel}>{t('work.btn.executeParallel')}（{pendingSteps.length}）</Button></Tooltip>}{batchRunning && activeBatchId && <Button danger onClick={cancelBatch}>取消整批</Button>}{!batchRunning && failedStepIds.length > 0 && <Button type="primary" danger icon={<ThunderboltOutlined />} onClick={() => executeParallel(failedStepIds)}>重试失败步骤（{failedStepIds.length}）</Button>}{running && activeRunId && <Button danger icon={<StopOutlined />} onClick={() => cancelRun(activeRunId)}>取消</Button>}</Space>}>
    <Space direction="vertical" size="small" style={{ width: '100%' }}><Text type="secondary">AI 只会接收已批准任务、选中计划步骤和附件中的有限文本上下文；结果保存后必须由人工审核，不会自动通过步骤。</Text>{batchRunning && <Alert type="info" showIcon message={`并行批次执行中：${batchOutput.filter((item) => item.status !== 'running').length}/${batchOutput.length} 个步骤已完成`} />}{batchOutput.length > 0 && <div className="batch-output">{batchOutput.map((item) => (
      <Card key={item.stepId} size="small" className={`batch-step-card batch-step-${item.status}`} title={<Space size={6}>{item.title}<Tag color={item.status === 'succeeded' ? 'success' : item.status === 'failed' ? 'error' : item.status === 'cancelled' ? 'default' : 'processing'}>{item.status === 'running' ? '执行中' : item.status === 'succeeded' ? '已完成' : item.status === 'failed' ? '失败' : '已取消'}</Tag></Space>} extra={item.error ? <Text type="danger">{item.error}</Text> : undefined}>
        {item.text ? <pre className="attachment-preview">{item.text}</pre> : <Text type="secondary">等待模型输出…</Text>}
      </Card>
    ))}</div>}<Flex gap={8} wrap="wrap" className="execution-controls"><Select value={stepId || undefined} onChange={setStepId} placeholder="选择计划步骤" options={(plan?.steps || []).filter((step) => step.status !== 'done').map((step) => ({ value: step.id, label: `${stepStatusLabels[step.status] || step.status} · ${step.title}` }))} /><Select value={modelId || undefined} onChange={setModelId} placeholder="选择模型" options={models.map((item) => ({ value: item.id, label: `${item.id}${item.ready ? '' : '（未就绪）'}`, disabled: !item.ready }))} /><Select value={skillName || undefined} onChange={setSkillName} placeholder="选择技能" options={skills.map((item) => ({ value: item.name, label: skillDisplayName(item.name) }))} /><Select mode="multiple" value={selectedMcpServers} onChange={setSelectedMcpServers} maxTagCount="responsive" placeholder={mcpServers.length ? '按需启用 MCP 工具' : '暂无 MCP 工具'} disabled={!mcpServers.length} options={mcpServers.map((item) => ({ value: item.name || item, label: mcpOptionLabel(item), title: mcpOptionLabel(item), tools: Array.isArray(item.tools) ? item.tools : [], disabled: mcpServerUnavailable(item) }))} optionRender={(option) => <div className="mcp-option"><span>{option.label}</span><small>{option.data?.tools?.length ? option.data.tools.join(' · ') : option.data?.disabled ? '连接不可用' : '工具清单将在连接后显示'}</small></div>} /><Segmented value={mode} onChange={setMode} aria-label="选择运行模式" options={agentModes.map((item) => ({ value: item, label: agentModeDisplayName(item), title: agentModeHint(item) }))} /></Flex><Text type="secondary" className="execution-mode-hint">{agentModeHint(mode)}</Text>{(mode === 'goal' || mode === 'loop') && <Flex gap={8} wrap="wrap" className="execution-mode-fields">{mode === 'goal' && <Input size="small" style={{ width: 240, maxWidth: '100%' }} placeholder="目标（必填）" value={goal} onChange={(event) => setGoal(event.target.value)} aria-label="目标" />}<Input size="small" style={{ width: 240, maxWidth: '100%' }} placeholder={mode === 'goal' ? '达成标准（必填）' : '停止条件（必填）'} value={criteria} onChange={(event) => setCriteria(event.target.value)} aria-label="达成标准或停止条件" /><InputNumber size="small" min={1} max={20} value={maxIterations} onChange={(value) => setMaxIterations(value || 1)} aria-label="最大轮次" addonAfter="轮" /></Flex>}{iterations.length > 0 && <div className="execution-iterations">{iterations.map((item, index) => <Alert key={index} type={item.verdict === 'met' ? 'success' : item.verdict === 'not_met' ? 'info' : 'warning'} showIcon message={`第 ${item.iteration} 轮 · ${iterationVerdictLabel(item.verdict)}`} description={item.reason} />)}</div>}{liveOutput && <pre className="attachment-preview">{liveOutput}</pre>}{batchHistory.length > 0 && <Collapse size="small" className="batch-history" items={batchHistory.map((batch) => {
  const detail = batchDetails[batch.id]
  return {
    key: batch.id,
    label: <Space size={6}><Tag color={batch.status === 'succeeded' ? 'success' : batch.status === 'failed' ? 'error' : batch.status === 'cancelled' ? 'default' : 'processing'}>{batch.status === 'running' ? '执行中' : batch.status === 'succeeded' ? '全部成功' : batch.status === 'partial' ? '部分失败' : batch.status === 'failed' ? '全部失败' : '已取消'}</Tag>批次 · {formatDateTime(batch.created_at)}</Space>,
    children: (
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        <Text type="secondary">{batch.total_steps} 个步骤：成功 {batch.succeeded_count}、失败 {batch.failed_count}、取消 {batch.cancelled_count} · 模型 {batch.model_id}</Text>
        {detail === undefined ? (
          <Button size="small" onClick={() => fetchBatchRuns(batch.id)}>加载本批执行明细</Button>
        ) : detail.loading ? <Spin size="small" /> : (detail.runs || []).map((run) => {
          const stepTitle = plan?.steps?.find((step) => step.id === run.step_id)?.title || run.step_id || '未绑定步骤'
          const statusLabel = run.status === 'succeeded' ? '成功' : run.status === 'failed' ? '失败' : run.status === 'cancelled' ? '已取消' : run.status
          return (
            <div key={run.id} className="batch-run-row">
              <Space size={6} wrap>
                <Tag color={run.status === 'succeeded' ? 'success' : run.status === 'failed' ? 'error' : run.status === 'cancelled' ? 'default' : 'processing'}>{statusLabel}</Tag>
                <Text strong>{stepTitle}</Text>
              </Space>
              {run.error_message ? <Text type="danger">{run.error_message}</Text> : null}
            </div>
          )
        })}
      </Space>
    ),
  }
})} />}{runItems.length ? <Tabs size="small" items={runItems} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此任务尚无 AI 执行记录" />}</Space>
  </Card>
}

function WorkModePage({ tasks, members, models, skills, mcpServers, workspaceRole, profile, workspace, onRefresh, onOpenBoard, requestedTaskId, requestNonce }) {
  const { message } = AntApp.useApp()
  const [taskId, setTaskId] = useState(tasks[0]?.id || '')
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [executionRunning, setExecutionRunning] = useState(false)
  // 已批准计划的修订态：进入后复用草稿编辑器，保存前用 Modal 说明状态回退。
  const [revising, setRevising] = useState(false)
  const [reviseConfirm, setReviseConfirm] = useState(null)
  const [evidenceStep, setEvidenceStep] = useState(null)
  const [form] = Form.useForm()
  const [evidenceForm] = Form.useForm()
  const planRequestIdRef = useRef(0)
  const currentTaskIdRef = useRef(taskId)
  currentTaskIdRef.current = taskId
  // 从任务抽屉「在工作模式中打开」进来时，工作模式必须切到那个任务：这个页面
  // 自己记着上次选中的工作项，不接过来的话点开看到的是另一个任务。只在请求
  // nonce 变化时切换，工作区刷新不会把用户手动选的项冲掉。
  const appliedTaskRequestRef = useRef(null)
  useEffect(() => {
    if (!requestNonce || appliedTaskRequestRef.current === requestNonce) return
    if (!requestedTaskId || !tasks.some((item) => item.id === requestedTaskId)) return
    appliedTaskRequestRef.current = requestNonce
    setTaskId(requestedTaskId)
  }, [requestNonce, requestedTaskId, tasks])
  const selectedTask = tasks.find((item) => item.id === taskId)
  const canWrite = workspaceRole !== 'viewer'
  const canApprove = ['owner', 'admin'].includes(workspaceRole)
  // 保存按钮文案与修订说明随档位变化：自动批准档位下保存即批准。
  const autoApproves = ['auto_approve', 'full_access'].includes(workspace?.permission_mode || 'default')
  const planTemplates = [
    {
      value: 'delivery',
      label: '产品交付',
      objective: '交付已验证的变更，明确负责人、验收标准和发布证据。',
      steps: [
        { title: '澄清范围与验收标准', instructions: '记录客户目标、非目标、负责人和可衡量的验收标准。' },
        { title: '实现并验证变更', instructions: '完成已确认范围，并把测试或审核证据添加到步骤结果中。' },
        { title: '发布并同步信息', instructions: '记录发布状态、回滚考虑和干系人更新。' },
      ],
    },
    {
      value: 'investigation',
      label: '问题调研',
      objective: '使用可追溯证据解决开放问题，并形成可执行建议。',
      steps: [
        { title: '界定问题', instructions: '记录需要做出的决策、待验证假设和负责人员。' },
        { title: '收集并比较证据', instructions: '关联支持结论的资料、实验、客户反馈或数据。' },
        { title: '输出建议', instructions: '记录建议、取舍以及后续决策或执行任务。' },
      ],
    },
    {
      value: 'incident',
      label: '故障响应',
      objective: '安全恢复服务，保留故障记录，并预防同类问题再次发生。',
      steps: [
        { title: '评估影响并指定负责人', instructions: '记录受影响用户、严重等级、沟通负责人和当前假设。' },
        { title: '缓解并验证恢复', instructions: '记录缓解措施、验证信号和剩余风险。' },
        { title: '完成后续行动', instructions: '记录根因分析、防范任务、负责人和截止日期。' },
      ],
    },
  ]

  const selectTask = (nextTaskId) => {
    if (executionRunning) return
    planRequestIdRef.current += 1
    currentTaskIdRef.current = nextTaskId
    setPlan(null)
    setEvidenceStep(null)
    setRevising(false)
    setTaskId(nextTaskId)
  }
  useEffect(() => { if (!executionRunning && !tasks.some((item) => item.id === taskId)) selectTask(tasks[0]?.id || '') }, [executionRunning, tasks, taskId])
  const loadPlan = useCallback(async (requestedTaskId = taskId) => {
    const requestId = ++planRequestIdRef.current
    if (!requestedTaskId) { setPlan(null); setLoading(false); return false }
    setLoading(true)
    try {
      const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/plan`)
      if (requestId !== planRequestIdRef.current || currentTaskIdRef.current !== requestedTaskId) return false
      setPlan(data.plan)
      // 表单只回填写入契约允许的字段：完整 step 还带 status/latest_run_status 等
      // 只读字段，原样提交会被后端 extra=forbid 拒绝（422）。
      const formSteps = data.plan?.steps?.length
        ? data.plan.steps.map((step) => ({ id: step.id, title: step.title, instructions: step.instructions, assignee_id: step.assignee_id }))
        : [{ title: '', instructions: '', assignee_id: undefined }]
      form.setFieldsValue({ objective: data.plan?.objective || '', steps: formSteps })
      return true
    } catch (error) {
      if (requestId === planRequestIdRef.current && currentTaskIdRef.current === requestedTaskId) message.error(readableError(error))
      return false
    } finally {
      if (requestId === planRequestIdRef.current && currentTaskIdRef.current === requestedTaskId) setLoading(false)
    }
  }, [form, message, taskId])
  useEffect(() => { loadPlan() }, [loadPlan])
  const savePlan = async (values) => {
    const requestedTaskId = taskId
    try {
      // 提交前再裁剪一次：防御未来表单新增字段时重新引入只读字段。
      const payload = {
        objective: values.objective,
        steps: (values.steps || []).map((step) => ({
          ...(step?.id ? { id: step.id } : {}),
          title: step?.title,
          instructions: step?.instructions || '',
          assignee_id: step?.assignee_id ?? null,
        })),
      }
      const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/plan`, { method: 'PUT', body: JSON.stringify(payload) })
      if (currentTaskIdRef.current !== requestedTaskId) return
      setPlan(data.plan)
      setRevising(false)
      // 自动审批档位下保存即批准，写死的“已保存为草稿”会与实际状态矛盾。
      message.success(data.plan?.status === 'approved'
        ? '工作计划已保存，并按当前权限档位自动批准'
        : '工作计划已保存为草稿')
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  // 修订已批准计划要先确认状态回退；草稿直接保存。
  const submitPlan = (values) => {
    if (plan && plan.status !== 'draft') { setReviseConfirm(values); return }
    savePlan(values)
  }
  const confirmRevise = () => {
    const values = reviseConfirm
    setReviseConfirm(null)
    savePlan(values)
  }
  const approve = async () => {
    const requestedTaskId = taskId
    try { const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/plan/approve`, { method: 'POST' }); if (currentTaskIdRef.current !== requestedTaskId) return; setPlan(data.plan); message.success('计划已批准，可开始执行') } catch (error) { if (currentTaskIdRef.current === requestedTaskId) message.error(readableError(error)) }
  }
  const updateStep = async (step, patch) => {
    const requestedTaskId = taskId
    try {
      const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/plan/steps/${step.id}`, { method: 'PATCH', body: JSON.stringify(patch) })
      if (currentTaskIdRef.current !== requestedTaskId) return null
      setPlan(data.plan)
      onRefresh()
      return data.plan
    } catch (error) { if (currentTaskIdRef.current === requestedTaskId) message.error(readableError(error)) }
  }
  const canUpdateStep = (step) => canWrite && (
    ['owner', 'admin'].includes(workspaceRole)
    || step.assignee_id === profile?.id
    || selectedTask?.assignee_id === profile?.id
    || selectedTask?.reporter_id === profile?.id
  )
  const applyTemplate = (templateKey) => {
    const template = planTemplates.find((item) => item.value === templateKey)
    if (template) form.setFieldsValue({ objective: template.objective, steps: template.steps })
  }
  const openEvidence = (step) => {
    setEvidenceStep(step)
    evidenceForm.setFieldsValue({ output_summary: step.output_summary || '' })
  }
  const saveEvidence = async (values) => {
    if (!evidenceStep) return
    const savedPlan = await updateStep(evidenceStep, { output_summary: values.output_summary })
    if (savedPlan) {
      setEvidenceStep(null)
      message.success('步骤证据已保存到工作区审计轨迹')
    }
  }
  const planSteps = plan?.steps || []
  const doneCount = planSteps.filter((item) => item.status === 'done').length
  // AI 执行成功但还没人工复核的步骤按半步计入进度，消除“AI 跑完了进度还是 0%”的误解。
  const executedCount = planSteps.filter((item) => item.status !== 'done' && item.latest_run_status === 'succeeded').length
  const progress = planSteps.length ? Math.round(((doneCount + executedCount * 0.5) / planSteps.length) * 100) : 0
  return (
    <div className="page-shell work-mode">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading"><div><Title level={2}>{t('work.title')}</Title><Text type="secondary">{t('work.subtitle')}</Text></div><Badge status={plan?.status === 'approved' || plan?.status === 'in_progress' ? 'processing' : plan?.status === 'completed' ? 'success' : 'default'} text={plan ? (planStatusLabels[plan.status] || plan.status) : '尚未创建计划'} /></Flex>
      {!tasks.length ? <Empty className="guided-empty" description="请先在项目看板中创建任务">{canWrite && <Button type="primary" icon={<ProjectOutlined />} onClick={onOpenBoard}>前往项目看板</Button>}</Empty> : <>
        <Select value={taskId} onChange={selectTask} disabled={executionRunning} title={executionRunning ? 'AI 执行期间不可切换任务' : undefined} className="project-selector" options={tasks.map((task) => ({ value: task.id, label: task.title }))} />
        <Card className="work-context" size="small"><Descriptions size="small" column={{ xs: 1, md: 3 }}><Descriptions.Item label="任务">{selectedTask?.title}</Descriptions.Item><Descriptions.Item label="发起人">{members.find((item) => item.user.id === selectedTask?.reporter_id)?.user.display_name || '-'}</Descriptions.Item><Descriptions.Item label="状态"><Tag>{taskStatusLabels[selectedTask?.status] || selectedTask?.status}</Tag></Descriptions.Item></Descriptions></Card>
        <Spin spinning={loading}>
          {((plan?.status === 'approved' || plan?.status === 'in_progress' || plan?.status === 'completed') && !revising) ? (
            <Card className="plan-execution" title={t('work.card.approved')} extra={<Space size={6}><Tag color={plan.status === 'completed' ? 'success' : 'processing'}>{planStatusLabels[plan.status] || plan.status}</Tag>{canApprove && <Button size="small" icon={<EditOutlined />} disabled={executionRunning} title={executionRunning ? 'AI 执行期间不可修订计划' : undefined} onClick={() => setRevising(true)}>{t('work.btn.revisePlan')}</Button>}</Space>}>
              <Paragraph>{plan.objective || '尚未记录目标。'}</Paragraph>
              <Progress percent={progress} status={progress === 100 ? 'success' : 'active'} />
              {executedCount > 0 && <Text type="secondary" className="plan-executed-hint">{executedCount} 步已执行待复核</Text>}
              <Steps direction="vertical" size="small" current={Math.min(plan.steps.findIndex((step) => step.status !== 'done'), Math.max(plan.steps.length - 1, 0))} items={plan.steps.map((step) => ({ title: <Flex justify="space-between" gap={8}><span>{step.title}</span><Select value={step.status} size="small" style={{ width: 124 }} disabled={!canUpdateStep(step)} onChange={(value) => updateStep(step, { status: value })} options={['pending', 'running', 'blocked', 'done'].map((value) => ({ value, label: stepStatusLabels[value] }))} /></Flex>, description: <Space direction="vertical" size={2}><Text type="secondary">{step.instructions || '暂无补充说明。'}</Text><Text type="secondary">负责人：{members.find((item) => item.user.id === step.assignee_id)?.user.display_name || '未分配'}</Text>{step.output_summary && <Text>执行证据：{step.output_summary}</Text>}{canUpdateStep(step) && <Button type="link" size="small" style={{ paddingInline: 0, width: 'fit-content' }} onClick={() => openEvidence(step)}>记录结果或证据</Button>}</Space>, status: step.status === 'done' ? 'finish' : step.status === 'blocked' ? 'error' : step.status === 'running' ? 'process' : 'wait' }))} />
            </Card>
          ) : (
            <Card title={t('work.card.plan')} extra={plan && <Tag color={plan.status === 'draft' ? 'default' : 'processing'}>{planStatusLabels[plan.status] || plan.status}</Tag>}>
              <Form form={form} layout="vertical" onFinish={submitPlan}>
                <Form.Item label="选择可复用流程"><Select placeholder="选择交付、调研或故障响应流程" onChange={applyTemplate} disabled={!canWrite} options={planTemplates.map((item) => ({ value: item.value, label: item.label }))} /></Form.Item>
                <Form.Item name="objective" label="目标" rules={[{ required: true, min: 4 }]}><Input.TextArea rows={3} placeholder="这项工作要交付什么结果？" disabled={!canWrite} /></Form.Item>
                <Form.List name="steps">{(fields, { add, remove }) => <div className="plan-form-list"><Flex justify="space-between" align="center"><Text strong>执行步骤</Text>{canWrite && <Button size="small" icon={<PlusOutlined />} onClick={() => add({ title: '', instructions: '' })}>添加步骤</Button>}</Flex>{fields.map((field, index) => <Card size="small" key={field.key} className="plan-step-editor"><Flex gap={10} align="start"><Tag>{index + 1}</Tag><div className="plan-step-fields"><Form.Item name={[field.name, 'id']} hidden><Input /></Form.Item><Form.Item name={[field.name, 'title']} rules={[{ required: true, min: 2 }]}><Input placeholder="步骤标题" disabled={!canWrite} /></Form.Item><Form.Item name={[field.name, 'instructions']}><Input.TextArea rows={2} placeholder="预期工作、输入和验收证据" disabled={!canWrite} /></Form.Item><Form.Item name={[field.name, 'assignee_id']}><Select allowClear placeholder="负责人" disabled={!canWrite} options={members.map((item) => ({ value: item.user.id, label: item.user.display_name }))} /></Form.Item></div>{canWrite && <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(field.name)} />}</Flex></Card>)}</div>}</Form.List>
                <Flex justify="end" gap={8}>{revising && <Button onClick={() => setRevising(false)}>取消修订</Button>}<Button htmlType="submit" disabled={!canWrite}>{autoApproves ? t('work.btn.saveAndApprove') : t('work.btn.saveDraft')}</Button>{canApprove && plan && !revising && <Button type="primary" icon={<CheckCircleOutlined />} onClick={approve}>{t('work.btn.approve')}</Button>}</Flex>
              </Form>
            </Card>
          )}
        </Spin>
        <TaskExecutionPanel taskId={taskId} plan={plan} models={models} skills={skills} mcpServers={mcpServers} canWrite={canWrite} onPlanRefresh={loadPlan} onRunningChange={setExecutionRunning} />
        <TaskResultsPanel taskId={taskId} canWrite={canWrite} members={members} refreshKey={plan?.updated_at || ''} />
      </>}
      <Modal
        title="修订已批准计划"
        open={Boolean(reviseConfirm)}
        onCancel={() => setReviseConfirm(null)}
        onOk={confirmRevise}
        okText="确认修订"
        cancelText="取消"
        destroyOnHidden
      >
        <Text>
          {autoApproves
            ? `当前档位为“${permissionModeLabels[workspace?.permission_mode] || '自动审批'}”，保存后计划会自动重新批准，直接回到可执行状态。`
            : '保存后计划会回到草稿状态，需要重新批准才能执行；已完成的步骤记录会保留。'}
        </Text>
      </Modal>
      <Modal title="记录步骤结果" open={Boolean(evidenceStep)} onCancel={() => setEvidenceStep(null)} onOk={() => evidenceForm.submit()} okText="确认" cancelText="取消" destroyOnHidden>
        <Form form={evidenceForm} layout="vertical" onFinish={saveEvidence}><Form.Item name="output_summary" label="证据、决策或交接信息" rules={[{ required: true, min: 2 }]}><Input.TextArea rows={5} placeholder="完成了什么、哪些证据支持结果、下一步应做什么？" /></Form.Item></Form>
      </Modal>
    </div>
  )
}

function TeamPage({ workspace, members, workspaceRole, onRefresh }) {
  const { message } = AntApp.useApp()
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const manager = ['owner', 'admin'].includes(workspaceRole)
  const addMember = async (values) => {
    try { await apiFetch(`/api/v1/workspaces/${workspace.id}/members`, { method: 'POST', body: JSON.stringify(values) }); message.success('成员已添加'); setOpen(false); form.resetFields(); onRefresh() } catch (error) { message.error(readableError(error)) }
  }
  const removeMember = async (member) => {
    try { await apiFetch(`/api/v1/workspaces/${workspace.id}/members/${member.id}`, { method: 'DELETE' }); message.success('成员已移除'); onRefresh() } catch (error) { message.error(readableError(error)) }
  }
  return <div className="page-shell"><Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading"><div><Title level={2}>{t('nav.team')}</Title><Text type="secondary">成员归属工作区管理；管理员可添加已注册用户，并按最小权限原则分配角色。</Text></div>{manager && <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>添加成员</Button>}</Flex><Card><List dataSource={members} renderItem={(member) => <List.Item actions={manager && member.role !== 'owner' ? [<Popconfirm key="remove" title="确认移除此成员？" onConfirm={() => removeMember(member)} okText="确认" cancelText="取消"><Button danger type="link">移除</Button></Popconfirm>] : []}><List.Item.Meta avatar={<Avatar icon={<UserOutlined />} />} title={<Space><Text strong>{member.user.display_name}</Text>{member.user.is_platform_admin && <Tag bordered={false}>平台管理员</Tag>}</Space>} description={member.user.email} /><Tag bordered={false}>{roleLabels[member.role] || member.role}</Tag></List.Item>} /></Card><Modal title="添加已注册成员" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} okText="确认" cancelText="取消" destroyOnHidden><Form form={form} layout="vertical" onFinish={addMember} initialValues={{ role: 'member' }}><Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}><Input placeholder="对方需要先完成注册" /></Form.Item><Form.Item name="role" label="角色"><Select options={['admin', 'member', 'viewer'].map((value) => ({ value, label: roleLabels[value] }))} /></Form.Item></Form></Modal></div>
}

function WorkspaceUsageCard() {
  const [range, setRange] = useState('30d')
  const [data, setData] = useState({ totals: {}, groups: [] })
  const [loading, setLoading] = useState(false)
  const load = useCallback(async (nextRange) => {
    setLoading(true)
    try {
      setData(await apiFetch(`/api/v1/usage/summary?range=${nextRange ?? range}&group_by=model`))
    } catch { setData({ totals: {}, groups: [] }) } finally { setLoading(false) }
  }, [range])
  useEffect(() => { load(range) }, [range])
  const totals = data.totals || {}
  const partialPricing = (totals.priced_rows || 0) < (totals.runs || 0)
  return (
    <Card className="settings-card" title="模型用量" extra={<Segmented size="small" value={range} onChange={setRange} options={[{ label: '近 7 天', value: '7d' }, { label: '近 30 天', value: '30d' }, { label: '全部', value: 'all' }]} />}>
      <Paragraph type="secondary" style={{ marginTop: 0 }}>数字均为模型真实上报；未上报用量的调用不会计入，也不会被当成零消耗。</Paragraph>
      {loading ? <Spin /> : (
        <>
          <Flex gap={24} wrap="wrap" style={{ marginBottom: 12 }}>
            <Statistic title="调用记录" value={totals.runs || 0} />
            <Statistic title="模型调用" value={totals.llm_calls || 0} />
            <Statistic title="总 token" value={totals.total_tokens || 0} />
            <Statistic title="工具调用" value={totals.tool_calls || 0} />
          </Flex>
          {partialPricing && (totals.runs || 0) > 0 && <Alert type="info" showIcon style={{ marginBottom: 10 }} message={`共 ${totals.runs} 条记录，其中 ${totals.priced_rows || 0} 条已登记单价，成本数据不完整。`} />}
          {data.truncated && <Alert type="warning" showIcon style={{ marginBottom: 10 }} message="记录数超过单次汇总上限，请缩小时间范围。" />}
          {(data.groups || []).length ? (
            <List size="small" dataSource={data.groups} renderItem={(group) => (
              <List.Item>
                <List.Item.Meta title={<span className="code-text">{group.label || group.key}</span>} description={`${group.total_tokens} token（入 ${group.input_tokens} / 出 ${group.output_tokens}）· ${group.runs} 条记录`} />
                <Text type="secondary">{group.cost === null || group.cost === undefined ? '未定价' : Number(group.cost).toFixed(4)}</Text>
              </List.Item>
            )} />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="所选范围内暂无用量记录" />}
        </>
      )}
    </Card>
  )
}

function WorkspaceSettingsPage({ workspace, members, workspaceRole, onRefresh, onWorkspaceUpdated }) {
  const { message, modal } = AntApp.useApp()
  const isOwner = workspaceRole === 'owner'
  const isManager = ['owner', 'admin'].includes(workspaceRole)
  const [name, setName] = useState(workspace?.name || '')
  const [savingName, setSavingName] = useState(false)
  const [targets, setTargets] = useState([])
  const [targetsLoading, setTargetsLoading] = useState(false)
  const [targetOpen, setTargetOpen] = useState(false)
  const [creatingTarget, setCreatingTarget] = useState(false)
  const [transferMemberId, setTransferMemberId] = useState('')
  const [savingMode, setSavingMode] = useState(false)
  const [form] = Form.useForm()
  const [targetForm] = Form.useForm()
  useEffect(() => { setName(workspace?.name || '') }, [workspace?.id, workspace?.name])
  const loadTargets = useCallback(async () => {
    if (!isManager) return
    setTargetsLoading(true)
    try {
      const data = await apiFetch('/api/v1/notifications/targets')
      setTargets(data.targets || [])
    } catch { setTargets([]) } finally { setTargetsLoading(false) }
  }, [isManager])
  useEffect(() => { loadTargets() }, [loadTargets])
  const saveName = async () => {
    const next = name.trim()
    if (!next || next === workspace?.name) return
    setSavingName(true)
    try {
      await apiFetch(`/api/v1/workspaces/${workspace.id}`, { method: 'PATCH', body: JSON.stringify({ name: next }) })
      message.success('工作区名称已更新')
      onRefresh()
    } catch (error) { message.error(readableError(error)) } finally { setSavingName(false) }
  }
  const transferOwnership = async () => {
    const target = members.find((m) => m.id === transferMemberId)
    if (!target) return
    modal.confirm({
      title: `确认把所有权转移给「${target.user.display_name}」？`,
      content: '转移后你将变为管理员；若存在老板/私事经营数据，系统会拒绝转移并给出处理指引。',
      okText: '确认转移',
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/workspaces/${workspace.id}/transfer-owner`, { method: 'POST', body: JSON.stringify({ member_id: transferMemberId }) })
          message.success('所有权已转移')
          setTransferMemberId('')
          onRefresh()
        } catch (error) { message.error(readableError(error)) }
      },
    })
  }
  const createTarget = async (values) => {
    setCreatingTarget(true)
    try {
      await apiFetch('/api/v1/notifications/targets', { method: 'POST', body: JSON.stringify(values) })
      message.success('通知出口已创建')
      setTargetOpen(false)
      targetForm.resetFields()
      loadTargets()
    } catch (error) { message.error(readableError(error)) } finally { setCreatingTarget(false) }
  }
  const toggleTarget = async (target, enabled) => {
    try {
      await apiFetch(`/api/v1/notifications/targets/${target.id}`, { method: 'PATCH', body: JSON.stringify({ enabled }) })
      loadTargets()
    } catch (error) { message.error(readableError(error)) }
  }
  const testTarget = async (target) => {
    const hide = message.loading('正在发送测试推送…', 0)
    try {
      await apiFetch(`/api/v1/notifications/targets/${target.id}/test`, { method: 'POST' })
      message.success('测试推送已送达')
    } catch (error) { message.error(readableError(error)) } finally { hide() }
  }
  const removeTarget = (target) => {
    modal.confirm({
      title: `删除通知出口「${target.name}」？`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try { await apiFetch(`/api/v1/notifications/targets/${target.id}`, { method: 'DELETE' }); message.success('已删除'); loadTargets() } catch (error) { message.error(readableError(error)) }
      },
    })
  }
  const deleteWorkspace = () => {
    modal.confirm({
      title: `确认删除工作区「${workspace?.name}」？`,
      content: '将永久删除全部成员、项目、任务、对话、附件与审计记录，且不可恢复。',
      okText: '永久删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/workspaces/${workspace.id}`, { method: 'DELETE' })
          message.success('工作区已删除')
          setTimeout(() => window.location.reload(), 600)
        } catch (error) { message.error(readableError(error)) }
      },
    })
  }
  const transferCandidates = members.filter((m) => m.id !== workspace?.owner_id && m.role !== 'viewer')
  const targetKindLabels = { webhook: 'Webhook', wecom: '企业微信', feishu: '飞书', dingtalk: '钉钉' }
  const currentMode = workspace?.permission_mode || 'default'
  const capIndex = permissionModeOrder.indexOf(workspace?.max_permission_mode || 'full_access')
  const changePermissionMode = (mode) => {
    if (mode === currentMode) return
    const apply = async () => {
      setSavingMode(true)
      try {
        const data = await apiFetch(`/api/v1/workspaces/${workspace.id}/permission-mode`, { method: 'PUT', body: JSON.stringify({ permission_mode: mode }) })
        // 直接用响应里的权威值更新，而不是等 onRefresh 往返；
        // 否则 toast 已提示成功而选择器还停在旧档位，看起来像没生效。
        onWorkspaceUpdated?.(data.workspace)
        message.success(`权限档位已切换为${permissionModeLabels[mode]}`)
        onRefresh()
      } catch (error) { message.error(readableError(error)) } finally { setSavingMode(false) }
    }
    // 放宽档位会改变整个工作区的治理强度，必须先把代价说清楚再确认。
    const risk = permissionModeRisks[mode]
    if (!risk) { apply(); return }
    modal.confirm({
      title: `切换到${permissionModeLabels[mode]}？`,
      content: risk,
      okText: '确认切换',
      cancelText: '取消',
      okButtonProps: { danger: mode === 'full_access' },
      onOk: apply,
    })
  }
  return (
    <div className="page-shell settings-page">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading">
        <div><Title level={2}>{t('settings.title')}</Title><Text type="secondary">{t('settings.subtitle')}</Text></div>
      </Flex>
      <Card className="settings-card" title={t("settings.card.basic")}>
        <Flex gap={10} wrap="wrap">
          <Input value={name} onChange={(event) => setName(event.target.value)} style={{ width: 320, maxWidth: '100%' }} placeholder="工作区名称" disabled={!isManager} />
          <Button type="primary" loading={savingName} disabled={!isManager || !name.trim() || name.trim() === workspace?.name} onClick={saveName}>{t('settings.btn.saveName')}</Button>
        </Flex>
        <Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}><Text type="secondary">标识：{workspace?.slug || '-'} · 所有者：{members.find((m) => m.user.id === workspace?.owner_id)?.user.display_name || '未知'}</Text></Paragraph>
      </Card>
      <Card className="settings-card" title="权限档位">
        <Paragraph type="secondary" style={{ marginTop: 0 }}>档位只放宽人工审批环节：Casbin RBAC、租户目录隔离与 run_python 禁用在任何档位下都不变。</Paragraph>
        <Flex gap={12} align="center" wrap="wrap">
          {isOwner ? (
            <Segmented
              value={currentMode}
              onChange={changePermissionMode}
              disabled={savingMode}
              options={permissionModeOrder.map((mode) => ({
                value: mode,
                label: permissionModeLabels[mode],
                // 超出部署上限的档位直接禁用，而不是选了之后静默不生效。
                disabled: capIndex >= 0 && permissionModeOrder.indexOf(mode) > capIndex,
              }))}
            />
          ) : <Tag bordered={false}>{permissionModeLabels[currentMode]}</Tag>}
          {savingMode && <Spin size="small" />}
        </Flex>
        <Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}>{permissionModeHints[currentMode]}</Paragraph>
        {capIndex >= 0 && capIndex < permissionModeOrder.length - 1 && <Paragraph type="secondary" style={{ marginBottom: 0 }}>当前部署将档位上限设为{permissionModeLabels[permissionModeOrder[capIndex]]}，更宽松的档位不可选。</Paragraph>}
        {!isOwner && <Paragraph type="secondary" style={{ marginBottom: 0 }}>只有工作区所有者可以调整档位。</Paragraph>}
      </Card>
      <WorkspaceUsageCard />
      {isManager && (
        <Card className="settings-card" title={t("settings.card.targets")} extra={<Button size="small" icon={<PlusOutlined />} onClick={() => setTargetOpen(true)}>{t('settings.btn.newTarget')}</Button>}>
          <Paragraph type="secondary" style={{ marginTop: 0 }}>预警扫描与关键事件可推送到企业微信群机器人、飞书、钉钉或任意 Webhook。</Paragraph>
          {targetsLoading ? <Spin /> : targets.length ? (
            <List size="small" dataSource={targets} renderItem={(target) => (
              <List.Item actions={[
                <Button key="test" size="small" onClick={() => testTarget(target)}>测试</Button>,
                <Button key="delete" size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeTarget(target)} aria-label={`删除 ${target.name}`} />,
                <Switch key="switch" size="small" checked={target.enabled} onChange={(checked) => toggleTarget(target, checked)} aria-label={`启用 ${target.name}`} />,
              ]}>
                <List.Item.Meta title={<Space size={6}><Tag bordered={false}>{targetKindLabels[target.kind] || target.kind}</Tag>{target.name}</Space>} description={target.url} />
              </List.Item>
            )} />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未配置通知出口" />}
        </Card>
      )}
      {isOwner && (
        <>
          <Card className="settings-card" title={t("settings.card.transfer")}>
            <Paragraph type="secondary" style={{ marginTop: 0 }}>转移后你将变为管理员。存在老板/私事经营数据时系统会拒绝转移，需先归档或交接。</Paragraph>
            <Flex gap={10} wrap="wrap">
              <Select value={transferMemberId || undefined} onChange={setTransferMemberId} style={{ width: 280, maxWidth: '100%' }} placeholder="选择新的所有者（工作区成员）" options={transferCandidates.map((m) => ({ value: m.id, label: `${m.user.display_name}（${m.user.email}）` }))} />
              <Button type="primary" disabled={!transferMemberId} onClick={transferOwnership}>转移所有权</Button>
            </Flex>
          </Card>
          <Card className="settings-card settings-danger" title={t("settings.card.danger")}>
            <Paragraph type="secondary" style={{ marginTop: 0 }}>删除工作区会永久清除全部成员、项目、任务、对话、附件、交付物与审计记录。</Paragraph>
            <Button danger onClick={deleteWorkspace}>{t('settings.btn.delete')}</Button>
          </Card>
        </>
      )}
      <Modal title="新建通知出口" open={targetOpen} onCancel={() => setTargetOpen(false)} onOk={() => targetForm.submit()} confirmLoading={creatingTarget} okText="创建" cancelText="取消" destroyOnHidden>
        <Form form={targetForm} layout="vertical" onFinish={createTarget} initialValues={{ kind: 'wecom' }}>
          <Form.Item name="name" label="出口名称" rules={[{ required: true, min: 2 }]}><Input placeholder="例如：运维值班群机器人" /></Form.Item>
          <Form.Item name="kind" label="类型" rules={[{ required: true }]}><Select options={[{ value: 'wecom', label: '企业微信群机器人' }, { value: 'feishu', label: '飞书群机器人' }, { value: 'dingtalk', label: '钉钉群机器人' }, { value: 'webhook', label: '自定义 Webhook' }]} /></Form.Item>
          <Form.Item name="url" label="Webhook 地址" rules={[{ required: true, min: 10 }]}><Input placeholder="https://..." /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

function WorkspaceApp({ session, onLogout }) {
  // 侧边栏的会话列表需要 modal 做归档/删除确认，不能只取 message。
  const { message, modal } = AntApp.useApp()
  const screens = Grid.useBreakpoint()
  const [profile, setProfile] = useState(session?.user || null)
  const [workspaces, setWorkspaces] = useState(session?.workspaces || [])
  const [workspaceId, setActiveWorkspaceId] = useState(getWorkspaceId() || session?.workspaces?.[0]?.id || '')
  const [members, setMembers] = useState([])
  const [projects, setProjects] = useState([])
  const [tasks, setTasks] = useState([])
  const [conversations, setConversations] = useState([])
  const [activeConversationId, setActiveConversationId] = useState('')
  const [messages, setMessages] = useState([])
  const [models, setModels] = useState([])
  const [modelsLoading, setModelsLoading] = useState(true)
  // 服务端给出的部署级默认模型；列表首项是内置模型注册顺序，不代表本部署可用。
  const [defaultModel, setDefaultModel] = useState('')
  const [skills, setSkills] = useState([])
  const [mcpServers, setMcpServers] = useState([])
  const [mcpLoading, setMcpLoading] = useState(true)
  // 设置面板是一个覆盖在任意页面之上的弹窗：切页不该把它关掉，关掉也不该
  // 触发一次重新加载，所以它独立于 nav 之外。
  const [settingsOpen, setSettingsOpen] = useState(false)
  // 递增即让 ChatPage 重挂载，用于"从插件市场带一个技能进输入卡"这类
  // 需要重新读取本地偏好的场景。
  const [chatEpoch, setChatEpoch] = useState(0)
  // 当前正在使用的自建智能体（创造模式产出）。只影响人设注入与输入卡预设，
  // 不参与任何权限判定。
  const [activeAgent, setActiveAgent] = useState(null)
  const [nav, setNav] = useState('chat')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [workspaceError, setWorkspaceError] = useState('')
  const [taskDrawer, setTaskDrawer] = useState(null)
  // { id, nonce }：工作模式据此切到「从抽屉点开」的那个任务。
  const [workTaskRequest, setWorkTaskRequest] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)
  const [hasMoreMessages, setHasMoreMessages] = useState(false)
  const [globalQuery, setGlobalQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [notifications, setNotifications] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [notificationFilter, setNotificationFilter] = useState('all')
  const visibleNotifications = useMemo(
    () => (notificationFilter === 'unread' ? notifications.filter((item) => !item.read) : notifications),
    [notifications, notificationFilter],
  )
  const notificationGroups = useMemo(() => groupNotifications(visibleNotifications), [visibleNotifications])
  const [notificationOpen, setNotificationOpen] = useState(false)
  const [themeTick, setThemeTick] = useState(0)
  const searchInputRef = useRef(null)
  useEffect(() => {
    const handler = (event) => {
      if ((event.ctrlKey || event.metaKey) && String(event.key).toLowerCase() === 'k') {
        event.preventDefault()
        document.querySelector('.global-search input')?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])
  const loadedWorkspaceIdRef = useRef('')
  const workspaceRequestIdRef = useRef(0)
  const conversationRequestIdRef = useRef(0)
  const currentWorkspaceIdRef = useRef(workspaceId)
  const currentConversationIdRef = useRef(activeConversationId)
  currentWorkspaceIdRef.current = workspaceId
  currentConversationIdRef.current = activeConversationId
  const workspace = workspaces.find((item) => item.id === workspaceId) || workspaces[0]
  const activeConversation = conversations.find((item) => item.id === activeConversationId)
  // 写权限判定提到这一层：侧边栏的“新建任务”与权限档位都需要它。
  // 各页面原先各自算一遍，口径一致但容易遗漏（只读成员不能发起 AI 工作）。
  const canWrite = workspace?.role !== 'viewer'
  const canProbeMcp = ['owner', 'admin'].includes(workspace?.role)
  // 加载函数只按 workspaceId 重建。角色、message API 经 ref 读取：写进依赖
  // 会让 canProbeMcp 从 false 变 true 时再触发一次全量加载（首屏发两遍请求）。
  const canProbeMcpRef = useRef(canProbeMcp)
  canProbeMcpRef.current = canProbeMcp

  const clearWorkspaceData = useCallback(() => {
    conversationRequestIdRef.current += 1
    setMembers([])
    setProjects([])
    setTasks([])
    setConversations([])
    setMessages([])
    setModels([])
    setSkills([])
    setMcpServers([])
    setActiveConversationId('')
  }, [])

  // 工具探针会逐个连接 MCP 服务，服务没起来时要等到连接超时（实测 2.8s），
  // 模型探针同样要真实打一次供应商（实测 2s）。它们都不该卡住首屏：先把
  // 毫秒级返回的成员/任务/会话渲染出来，慢数据到了再补齐。
  const loadSlowWorkspaceData = useCallback((requestedWorkspaceId, isFresh) => {
    setModelsLoading(true)
    apiFetch('/api/v1/models', { workspaceId: requestedWorkspaceId })
      .then((data) => {
        if (!isFresh()) return
        // models 全线按"对象数组"消费（id/ready/能力字段），不要在这里退化成 id 列表。
        setModels(data.details || [])
        setDefaultModel(data.default_model || '')
      })
      .catch(() => { if (isFresh()) setModels([]) })
      .finally(() => { if (isFresh()) setModelsLoading(false) })
    setMcpLoading(true)
    apiFetch(`/api/v1/mcp/servers${canProbeMcpRef.current ? '?probe=true' : ''}`, { workspaceId: requestedWorkspaceId })
      .catch(() => apiFetch('/api/v1/mcp/servers', { workspaceId: requestedWorkspaceId }))
      .then((data) => { if (isFresh()) setMcpServers(data?.servers || []) })
      .catch(() => { if (isFresh()) setMcpServers([]) })
      .finally(() => { if (isFresh()) setMcpLoading(false) })
  }, [])

  const loadWorkspace = useCallback(async ({ quiet = false } = {}) => {
    const requestId = ++workspaceRequestIdRef.current
    const requestedWorkspaceId = workspaceId
    if (!requestedWorkspaceId) {
      clearWorkspaceData()
      setWorkspaceError('当前账号尚未加入可用工作区。')
      setLoading(false)
      return false
    }
    const switchingWorkspace = loadedWorkspaceIdRef.current !== requestedWorkspaceId
    if (switchingWorkspace) {
      clearWorkspaceData()
      setLoading(true)
    } else if (quiet) setRefreshing(true)
    setWorkspaceError('')
    const isFresh = () => requestId === workspaceRequestIdRef.current && currentWorkspaceIdRef.current === requestedWorkspaceId
    try {
      const [memberData, projectData, taskData, conversationData, skillData, workspaceListData] = await Promise.all([
        apiFetch(`/api/v1/workspaces/${requestedWorkspaceId}/members`, { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/projects', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/tasks', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/conversations', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/skills', { workspaceId: requestedWorkspaceId }),
        // 工作区自身的字段（名称、权限档位）以前只在登录时取一次，
        // 改完不重新拉取会让界面一直停在旧值。失败不拖垮其余数据。
        apiFetch('/api/v1/workspaces', { workspaceId: requestedWorkspaceId }).catch(() => null),
      ])
      if (!isFresh()) return false
      if (workspaceListData?.workspaces) setWorkspaces(workspaceListData.workspaces)
      setMembers(memberData.members || [])
      setProjects(projectData.projects || [])
      setTasks(taskData.tasks || [])
      setConversations(conversationData.conversations || [])
      setSkills(skillData.skills || [])
      setActiveConversationId((current) => current && conversationData.conversations?.some((item) => item.id === current) ? current : conversationData.conversations?.[0]?.id || '')
      loadedWorkspaceIdRef.current = requestedWorkspaceId
      loadSlowWorkspaceData(requestedWorkspaceId, isFresh)
      return true
    } catch (error) {
      if (!isFresh()) return false
      const detail = readableError(error)
      setWorkspaceError(detail)
      message.error(detail)
      return false
    } finally {
      if (requestId === workspaceRequestIdRef.current && currentWorkspaceIdRef.current === requestedWorkspaceId) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [clearWorkspaceData, loadSlowWorkspaceData, message, workspaceId])

  useEffect(() => { setWorkspaceId(workspaceId); loadWorkspace() }, [loadWorkspace, workspaceId])
  useEffect(() => { window.scrollTo(0, 0) }, [nav])
  // 首屏渲染完再预取其余路由：既不抢首屏带宽，也避免切页时出现骨架屏。
  useEffect(() => {
    const idle = window.requestIdleCallback || ((fn) => window.setTimeout(fn, 400))
    const cancel = window.cancelIdleCallback || window.clearTimeout
    const handle = idle(() => preloadRoutes())
    return () => cancel(handle)
  }, [])
  const loadConversationMessages = useCallback(async (conversationId = activeConversationId, { notify = false, beforeId = '', append = false } = {}) => {
    const requestId = ++conversationRequestIdRef.current
    const requestedWorkspaceId = workspaceId
    if (!conversationId || !requestedWorkspaceId) {
      setMessages([])
      setHasMoreMessages(false)
      return false
    }
    try {
      const query = beforeId ? `?limit=120&before_id=${encodeURIComponent(beforeId)}` : '?limit=120'
      const data = await apiFetch(`/api/v1/conversations/${conversationId}/messages${query}`, { workspaceId: requestedWorkspaceId })
      if (requestId !== conversationRequestIdRef.current || currentWorkspaceIdRef.current !== requestedWorkspaceId || currentConversationIdRef.current !== conversationId) return false
      setMessages((previous) => append ? [...(data.messages || []), ...previous] : (data.messages || []))
      setHasMoreMessages(Boolean(data.has_more))
      return true
    } catch (error) {
      const currentRequest = requestId === conversationRequestIdRef.current && currentWorkspaceIdRef.current === requestedWorkspaceId && currentConversationIdRef.current === conversationId
      if (!currentRequest) return false
      if (notify) message.error(readableError(error))
      throw error
    }
  }, [activeConversationId, message, workspaceId])
  const loadOlderMessages = useCallback(() => {
    const oldest = messages.find((item) => item.id && !String(item.id).startsWith('local-'))
    if (!oldest || !activeConversationId) return Promise.resolve(false)
    return loadConversationMessages(activeConversationId, { beforeId: oldest.id, append: true })
  }, [activeConversationId, loadConversationMessages, messages])
  const searchTimerRef = useRef('')
  const runGlobalSearch = useCallback((value) => {
    clearTimeout(searchTimerRef.current)
    const keyword = value.trim()
    if (!keyword) { setSearchResults([]); return }
    searchTimerRef.current = setTimeout(async () => {
      try {
        const data = await apiFetch(`/api/v1/search?q=${encodeURIComponent(keyword)}&limit=12`, { workspaceId })
        setSearchResults(data.results || [])
      } catch { setSearchResults([]) }
    }, 300)
  }, [workspaceId])
  const loadNotifications = useCallback(async () => {
    if (!workspaceId) return
    try {
      const data = await apiFetch('/api/v1/notifications?limit=30', { workspaceId })
      setNotifications(data.notifications || [])
      setUnreadCount(data.unread_count || 0)
    } catch { /* 通知加载失败不打断主界面 */ }
  }, [workspaceId])
  useEffect(() => { loadNotifications(); const timer = setInterval(loadNotifications, 60_000); return () => clearInterval(timer) }, [loadNotifications])
  const markNotificationRead = async (notification) => {
    if (notification.read) return
    setNotifications((previous) => previous.map((item) => item.id === notification.id ? { ...item, read: true } : item))
    setUnreadCount((count) => Math.max(0, count - 1))
    try {
      await apiFetch(`/api/v1/notifications/${notification.id}/read`, { method: 'POST', workspaceId })
      loadNotifications()
    } catch { loadNotifications() }
  }
  const markAllNotificationsRead = async () => {
    try { await apiFetch('/api/v1/notifications/read-all', { method: 'POST', workspaceId }); loadNotifications() } catch { /* 忽略 */ }
  }
  const openNotification = (notification) => {
    markNotificationRead(notification)
    if (notification.link && navigationLabels()[notification.link]) {
      setNav(notification.link)
      setNotificationOpen(false)
    }
  }
  useEffect(() => { loadConversationMessages(undefined, { notify: true }).catch(() => {}) }, [loadConversationMessages])

  const newConversation = async () => {
    try { const data = await apiFetch('/api/v1/conversations', { method: 'POST', body: JSON.stringify({ title: '新对话' }), workspaceId }); setConversations((previous) => [data.conversation, ...previous]); conversationRequestIdRef.current += 1; currentConversationIdRef.current = data.conversation.id; setActiveConversationId(data.conversation.id); setNav('chat') } catch (error) { message.error(readableError(error)) }
  }
  const selectConversation = (conversationId) => {
    conversationRequestIdRef.current += 1
    currentConversationIdRef.current = conversationId
    setActiveConversationId(conversationId)
  }
  const selectWorkspace = (nextWorkspaceId) => {
    workspaceRequestIdRef.current += 1
    conversationRequestIdRef.current += 1
    currentWorkspaceIdRef.current = nextWorkspaceId
    setActiveWorkspaceId(nextWorkspaceId)
  }
  const refreshWorkspace = () => loadWorkspace({ quiet: true })
  // 工作区自身字段（名称、权限档位）的即时更新入口：接口响应就是
  // 权威值，直接合并比等下一次全量刷新更及时。
  const patchWorkspace = useCallback((updated) => {
    if (!updated?.id) return
    setWorkspaces((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item))
  }, [])
  // 工作区偏好整体覆盖写。接口回包就是权威值，直接合并进工作区对象，
  // 免得设置面板下一次打开时显示的还是旧开关。
  const saveWorkspacePreferences = useCallback(async (next) => {
    if (!workspaceId) throw new Error('尚未选择工作区')
    const data = await apiFetch(`/api/v1/workspaces/${workspaceId}/preferences`, {
      method: 'PUT',
      workspaceId,
      body: next,
    })
    setWorkspaces((current) => current.map((item) => (
      item.id === workspaceId ? { ...item, preferences: data.preferences } : item
    )))
    return data.preferences
  }, [workspaceId])
  const savePermissionMode = useCallback(async (mode) => {
    if (!workspaceId) throw new Error('尚未选择工作区')
    const data = await apiFetch(`/api/v1/workspaces/${workspaceId}/permission-mode`, {
      method: 'PUT',
      workspaceId,
      body: { permission_mode: mode },
    })
    if (data.workspace) patchWorkspace(data.workspace)
    return data
  }, [workspaceId, patchWorkspace])
  // 插件市场点「使用」：把技能带到对话输入卡上，而不是弹一个说明就完事。
  // ChatPage 只在挂载时读一次输入卡偏好，所以这里换一个 key 让它重挂载，
  // 否则"已选择技能"的提示和实际发出的请求会对不上。
  const useSkillFromMarket = useCallback((skillName) => {
    saveComposerPrefs({ ...loadComposerPrefs(), skillName })
    setChatEpoch((value) => value + 1)
    setNav('chat')
    setMobileNav(false)
    message.success(`已选择技能：${skillDisplayName(skillName)}`)
  }, [message])
  // 创造模式：把智能体的运行预设灌进输入卡，并记住当前智能体。
  // 只覆盖它显式配过的项——模型留空表示"跟随默认"，那就不该把用户当前选的模型改掉。
  const useAgentFromStudio = useCallback((agent) => {
    const next = { ...loadComposerPrefs() }
    if (agent.model_id) next.modelId = agent.model_id
    if (agent.skill_name) next.skillName = agent.skill_name
    if (Array.isArray(agent.mcp_servers)) next.mcpServers = agent.mcp_servers
    saveComposerPrefs(next)
    setActiveAgent(agent)
    setChatEpoch((value) => value + 1)
    setNav('chat')
    setMobileNav(false)
    message.success(`已切换到智能体：${agent.name}`)
  }, [message])
  // 任务抽屉里的「在工作模式中打开」：把被点开的任务带进工作模式。
  const openTaskInWorkMode = useCallback((taskId) => {
    setWorkTaskRequest({ id: taskId, nonce: Date.now() })
    setNav('work')
    setTaskDrawer(null)
  }, [])
  const searchTypeLabels = { task: '任务', project: '项目', conversation: '对话', message: '消息', attachment: '附件', knowledge_base: '知识库' }
  const searchOptions = useMemo(() => searchResults.map((item) => ({
    value: `${item.type}:${item.id}`,
    label: (
      <div className="global-search-option">
        <Tag bordered={false} className="global-search-tag">{searchTypeLabels[item.type] || item.type}</Tag>
        <div className="global-search-copy"><span>{item.title}</span>{item.snippet && <small>{item.snippet}</small>}</div>
      </div>
    ),
  })), [searchResults])
  const handleSearchSelect = (value) => {
    const separator = value.indexOf(':')
    const type = value.slice(0, separator)
    const id = value.slice(separator + 1)
    const item = searchResults.find((result) => result.type === type && result.id === id)
    if (!item) return
    if (type === 'task') { setNav('board'); setTaskDrawer(tasks.find((task) => task.id === id) || null) }
    else if (type === 'conversation') { selectConversation(id); setNav('chat') }
    else if (type === 'message') { if (item.conversation_id) selectConversation(item.conversation_id); setNav('chat') }
    else if (type === 'project') setNav('board')
    else if (type === 'knowledge_base') setNav('report')
    else if (type === 'attachment') {
      if (item.task_id) { setNav('board'); setTaskDrawer(tasks.find((task) => task.id === item.task_id) || null) }
      else if (item.conversation_id) { selectConversation(item.conversation_id); setNav('chat') }
    }
    setGlobalQuery('')
    setSearchResults([])
  }
  // 参考稿的结构：侧边栏顶部是"新建任务"这个首要动作，随后是一组等权的
  // 功能入口，再往下是常驻的任务（对话）列表，最后才是账号区。
  // 本产品只有 code 一种形态，因此不提供模式切换器——顶部不做任何 tab。
  const sidebarNav = (
    <nav className="sidebar-nav" aria-label="工作区视图">
      <button
        type="button"
        className="sidebar-nav-item is-primary"
        onClick={() => { setNav('chat'); setMobileNav(false); newConversation() }}
        disabled={!canWrite}
        title={canWrite ? '新建一个任务' : '只读成员不能新建任务'}
      >
        <span className="sidebar-nav-icon"><PlusOutlined /></span>
        <span className="sidebar-nav-label">新建任务</span>
      </button>
      {buildNavigationItems().filter((item) => !['chat', 'settings'].includes(item.key)).map((item) => (
        <button
          key={item.key}
          type="button"
          className={`sidebar-nav-item${nav === item.key ? ' is-active' : ''}`}
          onClick={() => { setNav(item.key); setMobileNav(false) }}
          aria-current={nav === item.key ? 'page' : undefined}
        >
          <span className="sidebar-nav-icon">{item.icon}</span>
          <span className="sidebar-nav-label">{item.label}</span>
        </button>
      ))}
    </nav>
  )
  const accountMenu = {
    items: [
      // label 兜底：/auth/me 还没回来时 profile 为空，undefined 会让 antd 渲染出
      // 一个没有内容的空白菜单项，看着像"菜单是空的"。
      { key: 'profile', label: profile?.email || '正在加载账号…', disabled: true },
      { type: 'divider' },
      // 参考稿里"设置"是一个覆盖式面板，不是又一个页面；切页会丢掉
      // 正在看的内容，而设置属于随时开随时关的动作。
      { key: 'settings', icon: <SettingOutlined />, label: '设置', onClick: () => setSettingsOpen(true) },
      { key: 'workspace-settings', icon: <TeamOutlined />, label: t('nav.settings'), onClick: () => { setNav('settings'); setMobileNav(false) } },
      { key: 'theme', icon: <BulbOutlined />, label: getThemeMode() === 'dark' ? '切换到浅色' : '切换到深色', onClick: () => { toggleThemeMode(); setThemeTick((tick) => tick + 1) } },
      { type: 'divider' },
      { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout },
    ],
  }
  const layoutSider = <>
    <button type="button" className="workspace-brand" onClick={() => { setNav('chat'); setMobileNav(false) }} title="回到任务工作台">
      <BrandMark size={26} className="brand-mark" />
      <span className="workspace-brand-copy"><strong>futureAgent</strong><small>{workspace?.name || t('app.tagline')}</small></span>
    </button>
    {sidebarNav}
    <SidebarConversations
      conversations={conversations}
      activeConversationId={activeConversation?.id}
      canWrite={canWrite}
      isCurrentView={nav === 'chat'}
      messageApi={message}
      modal={modal}
      onRefresh={refreshWorkspace}
      onCreate={() => { setNav('chat'); setMobileNav(false); newConversation() }}
      onSelect={(conversationId) => { setNav('chat'); setMobileNav(false); selectConversation(conversationId) }}
    />
    <div className="sidebar-footer">
      {/* 侧边栏底部这两个浮层都在窗口最下沿，默认的 bottom* 放置没有向下空间，
          只能指望 rc-trigger 自动翻转；一旦它没翻（短窗口下很常见），菜单就落在
          视口之外，看起来就是"点了什么也没有"，同时把文档撑高冒出滚动条。
          这里直接指定向上展开，不再依赖自动判断。 */}
      <Select value={workspaceId || undefined} onChange={selectWorkspace} className="sidebar-workspace-select" size="small" placeholder="选择工作区" aria-label="切换工作区" placement="topLeft" options={workspaces.map((item) => ({ value: item.id, label: item.name }))} />
      <Flex align="center" justify="space-between" gap={6} className="sidebar-account-row">
        <Dropdown menu={accountMenu} trigger={['click']} placement="topRight">
          <Button type="text" size="small" className="sidebar-account" aria-label={'账号菜单：' + (profile?.display_name || '当前用户')}>
            <Avatar size={20} icon={<UserOutlined />} />
            <span>{profile?.display_name}</span>
            <Tag bordered={false}>{roleLabels[workspace?.role] || '成员'}</Tag>
          </Button>
        </Dropdown>
      </Flex>
    </div>
  </>

  // 分包页面走自己的路由缓存；看板/工作模式/团队/设置是同步组件。
  // JSX 里小写标签会被当成 HTML 标签，必须先赋给大写开头的变量。
  const { key: resolvedRouteKey, Component: RouteView } = useRouteComponent(
    ['chat', 'business', 'report', 'market'].includes(nav) ? nav : '',
  )
  // 只有"缓存里的组件就是当前这一页"时才渲染，避免把上一页的组件按这一页的
  // props 渲染出来。
  const routeViewFor = (key) => (resolvedRouteKey === key && RouteView ? RouteView : null)
  let content = null
  const ChatView = routeViewFor('chat')
  const BusinessView = routeViewFor('business')
  const ReportView = routeViewFor('report')
  const MarketView = routeViewFor('market')
  if (nav === 'chat') content = ChatView ? <ChatView key={chatEpoch} activeConversation={activeConversation} messages={messages} models={models} modelsLoading={modelsLoading} defaultModel={defaultModel} skills={skills} mcpServers={mcpServers} hasMoreMessages={hasMoreMessages} onLoadMoreMessages={loadOlderMessages} onRefreshMessages={loadConversationMessages} onRefresh={refreshWorkspace} workspace={workspace} onWorkspaceUpdated={patchWorkspace} onOpenBoard={() => setNav('board')} onCreateTask={newConversation} workspaceRole={workspace?.role} activeAgent={activeAgent} onClearAgent={() => setActiveAgent(null)} onOpenStudio={() => setNav('studio')} /> : null
  else if (nav === 'business') content = BusinessView ? <BusinessView workspaceRole={workspace?.role} members={members} currentUserId={profile?.id} /> : null
  else if (nav === 'report') content = ReportView ? <ReportView workspaceRole={workspace?.role} members={members} currentUserId={profile?.id} /> : null
  else if (nav === 'market') content = MarketView ? <MarketView mcpServers={mcpServers} skills={skills} mcpLoading={mcpLoading} preferences={workspace?.preferences} onSavePreferences={saveWorkspacePreferences} canManage={workspace?.role === 'owner' || workspace?.role === 'admin'} onUseSkill={useSkillFromMarket} onRefresh={refreshWorkspace} /> : null
  else if (nav === 'board') content = <BoardPage projects={projects} tasks={tasks} members={members} onRefresh={refreshWorkspace} openTask={(task) => setTaskDrawer(task)} workspaceRole={workspace?.role} />
  else if (nav === 'work') content = <WorkModePage tasks={tasks} members={members} models={models} skills={skills} mcpServers={mcpServers} workspaceRole={workspace?.role} profile={profile} workspace={workspace} onRefresh={refreshWorkspace} onOpenBoard={() => setNav('board')} requestedTaskId={workTaskRequest?.id} requestNonce={workTaskRequest?.nonce} />
  else if (nav === 'studio') content = <AgentStudioPage workspace={workspace} workspaceRole={workspace?.role} models={models} defaultModel={defaultModel} skills={skills} mcpServers={mcpServers} onUseAgent={useAgentFromStudio} onRefresh={refreshWorkspace} loading={mcpLoading} />
  else if (nav === 'team') content = <TeamPage workspace={workspace} members={members} workspaceRole={workspace?.role} onRefresh={refreshWorkspace} />
  else if (nav === 'settings') content = <WorkspaceSettingsPage workspace={workspace} members={members} workspaceRole={workspace?.role} onRefresh={refreshWorkspace} onWorkspaceUpdated={patchWorkspace} />

  // 分包还没就绪时保留上一页的节点：宁可短暂停在旧页面，也不提交一帧空内容。
  const lastRouteContentRef = useRef(null)
  if (content) lastRouteContentRef.current = content
  const stableContent = content || lastRouteContentRef.current
  const routeReady = Boolean(stableContent)

  const workspaceContent = loading || !routeReady ? (
    <div className="workspace-loading"><Space direction="vertical" align="center"><Spin size="large" /><Text type="secondary">正在加载工作区</Text></Space></div>
  ) : workspaceError && (!workspaceId || loadedWorkspaceIdRef.current !== workspaceId) ? (
    <div className="workspace-state-page"><Alert type="error" showIcon message="工作区加载失败" description={workspaceError} /><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请检查连接后重新加载"><Button type="primary" icon={<ReloadOutlined />} onClick={() => loadWorkspace()}>重新加载</Button></Empty></div>
  ) : (
    <>
      {workspaceError && <Alert className="workspace-error-strip" banner type="warning" showIcon message="刷新未完成，当前显示上次成功加载的数据。" action={<Button size="small" onClick={refreshWorkspace}>重试</Button>} />}
      <ErrorBoundary resetToken={nav}>{stableContent}</ErrorBoundary>
    </>
  )

  const updateDrawerTask = async (patch) => {
    if (!taskDrawer) return
    try {
      await apiFetch(`/api/v1/tasks/${taskDrawer.id}`, { method: 'PATCH', body: JSON.stringify(patch) })
      message.success('任务已更新')
      refreshWorkspace()
    } catch (error) { message.error(readableError(error)) }
  }
  // 归档/恢复：归档项从看板与搜索里收起，计划与执行记录不变，可随时恢复。
  // 两个动作都收起抽屉：归档后对象已不在看板上，恢复后抽屉又挡住了看板。
  const changeTaskArchive = async (task, archived) => {
    try {
      await apiFetch(`/api/v1/tasks/${task.id}/${archived ? 'archive' : 'unarchive'}`, { method: 'POST' })
      message.success(archived ? '工作项已归档' : '工作项已恢复')
      setTaskDrawer(null)
      await refreshWorkspace()
    } catch (error) { message.error(readableError(error)) }
  }
  const activeDrawerTask = taskDrawer ? tasks.find((task) => task.id === taskDrawer.id) || taskDrawer : null
  const drawerTask = taskDrawer && {
    ...activeDrawerTask,
    assignee_id: activeDrawerTask.assignee_id,
  }
  return (
    <Layout className="workspace-layout">
      {screens.lg ? (
        <Sider width={272} theme="dark" className="workspace-sider">{layoutSider}</Sider>
      ) : (
        <Drawer placement="left" open={mobileNav} onClose={() => setMobileNav(false)} width={280} rootClassName="mobile-workspace-drawer" styles={{ body: { padding: 0, background: '#111827' } }}>{layoutSider}</Drawer>
      )}
      <Layout>
        <Header className="workspace-header">
          <Flex align="center" gap={10} style={{ minWidth: 0 }}>
            {!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNav(true)} aria-label="打开主导航" />}
            {/* 顶栏只做上下文展示，不再承载任何业务选择器。 */}
            <div className="header-context">
              <Text type="secondary">{workspace?.name || '团队工作区'}</Text>
              <span className="header-context-sep" aria-hidden="true">/</span>
              <Text strong>
                {nav === 'chat'
                  ? (activeConversation?.title || '新对话')
                  : (navigationLabels()[nav] || navigationLabels().chat)}
              </Text>
            </div>
          </Flex>
          <Space size={6}>
            {/* 宽元素靠左、紧凑图标动作靠右，避开面包屑与按钮交错。 */}
            <AutoComplete
              className="global-search"
              value={globalQuery}
              onChange={(value) => { setGlobalQuery(value); runGlobalSearch(value) }}
              onSelect={handleSearchSelect}
              options={searchOptions}
              popupMatchSelectWidth={420}
              aria-label="全局搜索（Ctrl+K）"
            >
              <Input allowClear prefix={<SearchOutlined />} placeholder="搜索任务、对话、消息或文件" />
            </AutoComplete>
            <Tooltip title="通知中心">
              <Badge count={unreadCount} size="small" offset={[-3, 3]}>
                <Button type="text" icon={<BellOutlined />} onClick={() => { setNotificationOpen(true); loadNotifications() }} aria-label="通知中心" />
              </Badge>
            </Tooltip>
            <Tooltip title={refreshing ? t('common.syncing') : t('common.connected')}>
              <Button type="text" icon={<ReloadOutlined spin={refreshing} />} onClick={refreshWorkspace} disabled={refreshing || loading} aria-label={t('common.refresh')} />
            </Tooltip>
            <Tooltip title={getThemeMode() === 'dark' ? '切换到浅色' : '切换到深色'}>
              <Button
                type="text"
                icon={<BulbOutlined />}
                onClick={() => { toggleThemeMode(); setThemeTick((tick) => tick + 1) }}
                aria-label="切换深浅色主题"
              />
            </Tooltip>
          </Space>
        </Header>
        <Content className="workspace-content">{workspaceContent}</Content>
      </Layout>
      <Drawer
        className="notification-drawer"
        title={(
          <div className="notification-head">
            <span className="notification-head-title">通知中心</span>
            {unreadCount > 0 && <span className="notification-head-count">{unreadCount} 条未读</span>}
            {unreadCount > 0 && <Button size="small" className="notification-head-action" onClick={markAllNotificationsRead}>全部已读</Button>}
          </div>
        )}
        open={notificationOpen}
        onClose={() => setNotificationOpen(false)}
        width={screens.sm ? 420 : '100%'}
      >
        {notifications.length ? (
          <div className="notification-panel">
            <Segmented
              size="small"
              className="notification-filter"
              value={notificationFilter}
              onChange={setNotificationFilter}
              options={[{ value: 'all', label: '全部' }, { value: 'unread', label: unreadCount ? `未读 ${unreadCount}` : '未读' }]}
            />
            {visibleNotifications.length ? (
              <div className="notification-list">
                {notificationGroups.map((group) => (
                  <section key={group.bucket} className="notification-group">
                    <div className="notification-group-title">{group.bucket}</div>
                    {group.items.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className={`notification-row is-${notificationTone(item)}${item.read ? '' : ' is-unread'}`}
                        onClick={() => openNotification(item)}
                      >
                        <span className="notification-icon" aria-hidden>{NOTIFICATION_ICONS[notificationKind(item)] || NOTIFICATION_ICONS.default}</span>
                        <span className="notification-main">
                          <span className="notification-title">{item.title}</span>
                          {item.body && <span className="notification-body">{item.body}</span>}
                        </span>
                        <span className="notification-time" title={formatDateTime(item.created_at)}>{formatRelativeTime(item.created_at)}</span>
                        {!item.read && <span className="notification-dot" role="img" aria-label="未读" />}
                      </button>
                    ))}
                  </section>
                ))}
              </div>
            ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有未读通知" />}
          </div>
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />}
      </Drawer>
      {/* 设置面板挂在 ErrorBoundary 之外会连累整个工作台：面板里任何一处
          渲染异常都会把侧边栏和主区一起打成白屏，用户连"关掉设置"都点不到。 */}
      <ErrorBoundary resetToken={settingsOpen ? 'settings-open' : 'settings-closed'}>
        <SettingsModal
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          profile={profile}
          workspace={workspace}
          workspaceRole={workspace?.role}
          models={models}
          skills={skills}
          mcpServers={mcpServers}
          modelsLoading={modelsLoading}
          preferences={workspace?.preferences}
          onSavePreferences={saveWorkspacePreferences}
          onSavePermissionMode={savePermissionMode}
          onOpenAdvanced={() => { setSettingsOpen(false); setNav('settings'); setMobileNav(false) }}
          onUseSkill={useSkillFromMarket}
          onLogout={onLogout}
          themeMode={getThemeMode()}
          onToggleTheme={() => { toggleThemeMode(); setThemeTick((tick) => tick + 1) }}
        />
      </ErrorBoundary>
      <Drawer title="任务详情" open={Boolean(taskDrawer)} onClose={() => setTaskDrawer(null)} width={screens.sm ? 480 : '100%'}>
        {drawerTask && <Space direction="vertical" size="middle" style={{ width: '100%' }}><Title level={4}>{drawerTask.title}</Title><Paragraph>{drawerTask.description || '暂无任务说明。'}</Paragraph>{drawerTask.archived && <Alert type="info" showIcon message="该工作项已归档" description="归档项不出现在看板与搜索里；计划、执行记录与评论都还在，恢复后可继续操作。" />}<Descriptions bordered size="small" column={1}>
          <Descriptions.Item label="状态"><Select size="small" value={drawerTask.status} disabled={drawerTask.archived} style={{ width: 110 }} onChange={(value) => updateDrawerTask({ status: value })} options={Object.entries(taskStatusLabels).map(([value, label]) => ({ value, label }))} /></Descriptions.Item>
          <Descriptions.Item label="优先级"><Select size="small" value={drawerTask.priority} disabled={drawerTask.archived} style={{ width: 110 }} onChange={(value) => updateDrawerTask({ priority: value })} options={Object.entries(priorityLabels).map(([value, label]) => ({ value, label }))} /></Descriptions.Item>
          <Descriptions.Item label="负责人"><Select size="small" value={drawerTask.assignee_id || undefined} disabled={drawerTask.archived} allowClear style={{ width: 140 }} placeholder="未分配" onChange={(value) => updateDrawerTask({ assignee_id: value || null })} options={members.map((item) => ({ value: item.user.id, label: item.user.display_name }))} /></Descriptions.Item>
          <Descriptions.Item label="截止日期">{drawerTask.due_date || '未设置'}</Descriptions.Item>
        </Descriptions><TaskComments taskId={drawerTask.id} /><Space wrap>{drawerTask.archived
          ? <Button type="primary" icon={<UndoOutlined />} onClick={() => changeTaskArchive(drawerTask, false)}>恢复工作项</Button>
          : <><Button type="primary" icon={<AppstoreOutlined />} onClick={() => openTaskInWorkMode(drawerTask.id)}>在工作模式中打开</Button><Popconfirm title="归档这个工作项？" description="归档后不再出现在看板与搜索里，计划与执行记录保留，可随时恢复。" okText="归档" cancelText="取消" onConfirm={() => changeTaskArchive(drawerTask, true)}><Button icon={<InboxOutlined />}>归档</Button></Popconfirm></>}</Space></Space>}
      </Drawer>
    </Layout>
  )
}

export default function App() {
  const [session, setSession] = useState(null)
  const [restoring, setRestoring] = useState(true)
  const { message } = AntApp.useApp()
  useEffect(() => {
    const restore = async () => {
      try {
        if (!getAccessToken()) await refreshAccessToken()
        const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' })
        setSession(me)
      } catch { clearAuthSession() } finally { setRestoring(false) }
    }
    restore()
  }, [])
  const logout = async () => { try { await apiFetch('/api/v1/auth/logout', { method: 'POST', workspaceId: '' }) } catch { /* 清理本地状态同样会退出当前浏览器会话。 */ } clearAuthSession(); setSession(null); message.success('已退出登录') }
  if (restoring) return <div className="loading-page"><Spin size="large" /></div>
  return session ? <WorkspaceApp session={session} onLogout={logout} /> : <AuthScreen onAuthenticated={(payload) => setSession({ user: payload.user, workspaces: payload.workspaces || [] })} />
}

export function Root() {
  const [themeMode, setThemeMode] = useState(getThemeMode)
  useEffect(() => {
    applyThemeMode(getThemeMode())
    // 语言已锁定中文：顺手清掉旧版本可能存下的 en，免得残留状态
    // 让后来的人误以为语言切换仍然生效。
    applyLocale()
    const themeListener = (event) => setThemeMode(event.detail || getThemeMode())
    window.addEventListener('futureagent-theme', themeListener)
    return () => window.removeEventListener('futureagent-theme', themeListener)
  }, [])
  const isDark = themeMode === 'dark'
  return <ConfigProvider locale={antdLocaleOf()} theme={{
    algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      // 主色取近黑：整套界面不用渐变，也不给按钮加彩色投影。
      // 彩色只留给语义状态（成功 / 警告 / 危险）。
      colorPrimary: isDark ? '#ededf0' : '#1f1f22',
      colorInfo: isDark ? '#ededf0' : '#1f1f22',
      // 但**只设 colorPrimary 是不够的**：antd 会拿主色按比例调出一整套"底色"
      // 令牌（选中项背景 controlItemBgActive、Alert 的 colorInfoBg 等）。
      // 近黑按比例调出来仍是深灰，于是下拉菜单的选中项变成一块黑方块、
      // 提示条变成黑底配深色字——又丑又看不清。这里把派生底色统一压回中性浅色，
      // 主色只用来做文字/描边强调。
      colorPrimaryBg: isDark ? '#1e1e22' : '#f4f4f6',
      colorPrimaryBgHover: isDark ? '#26262c' : '#ebebee',
      colorPrimaryBorder: isDark ? '#33333a' : '#dcdce0',
      colorPrimaryBorderHover: isDark ? '#3d3d45' : '#c8c8ce',
      colorPrimaryHover: isDark ? '#ffffff' : '#3a3a42',
      colorPrimaryActive: isDark ? '#d8d8de' : '#0c0c0e',
      colorPrimaryText: isDark ? '#ededf0' : '#1f1f22',
      colorPrimaryTextHover: isDark ? '#ffffff' : '#3a3a42',
      colorPrimaryTextActive: isDark ? '#d8d8de' : '#0c0c0e',
      colorInfoBg: isDark ? '#1e1e22' : '#f4f4f6',
      colorInfoBorder: isDark ? '#33333a' : '#dcdce0',
      controlItemBgActive: isDark ? '#26262c' : '#efeff1',
      controlItemBgActiveHover: isDark ? '#2e2e35' : '#e6e6e9',
      controlItemBgHover: isDark ? '#222227' : '#f5f5f7',
      colorSuccess: isDark ? '#3fbd8e' : '#17916b',
      colorWarning: isDark ? '#d8a33f' : '#b7791f',
      colorError: isDark ? '#e0706a' : '#c5362f',
      colorText: isDark ? '#ededf0' : '#1a1a1c',
      colorTextSecondary: isDark ? '#b9b9c0' : '#55555c',
      colorBorder: isDark ? '#2b2b30' : '#e4e4e6',
      colorBorderSecondary: isDark ? '#26262b' : '#ececee',
      colorBgLayout: isDark ? '#0f0f11' : '#ffffff',
      colorBgContainer: isDark ? '#17171a' : '#ffffff',
      colorLink: isDark ? '#ededf0' : '#1a1a1c',
      borderRadius: 9,
      controlHeight: 34,
      fontFamily: '"PingFang SC", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif',
    },
    components: {
      Button: { primaryShadow: 'none', defaultShadow: 'none', fontWeight: 500 },
      Card: { headerFontSize: 15 },
      Layout: { bodyBg: isDark ? '#0f0f11' : '#ffffff', headerBg: isDark ? '#0f0f11' : '#ffffff', siderBg: isDark ? '#17171a' : '#f7f7f8' },
    },
  }}><AntApp><App /></AntApp></ConfigProvider>
}
