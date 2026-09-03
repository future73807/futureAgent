import React, { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Alert from 'antd/es/alert'
import AntApp from 'antd/es/app'
import AutoComplete from 'antd/es/auto-complete'
import Avatar from 'antd/es/avatar'
import Badge from 'antd/es/badge'
import Button from 'antd/es/button'
import Card from 'antd/es/card'
import ConfigProvider from 'antd/es/config-provider'
import Descriptions from 'antd/es/descriptions'
import Drawer from 'antd/es/drawer'
import Dropdown from 'antd/es/dropdown'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Form from 'antd/es/form'
import Grid from 'antd/es/grid'
import Input from 'antd/es/input'
import Layout from 'antd/es/layout'
import List from 'antd/es/list'
import Menu from 'antd/es/menu'
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
  FileAddOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
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
  UserOutlined,
} from '@ant-design/icons'
import zhCN from 'antd/es/locale/zh_CN'
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
import { mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from './ui-labels.js'
import { applyThemeMode, getThemeMode, toggleThemeMode } from './theme.js'

const { Header, Sider, Content } = Layout
const { Title, Text, Paragraph } = Typography
const ChatPage = lazy(() => import('./components/ChatPage.jsx'))
const BusinessAssistantsPage = lazy(() => import('./components/BusinessAssistantsPage.jsx'))
const ReportAssistantsPage = lazy(() => import('./components/ReportAssistantsPage.jsx'))
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
const planStatusLabels = { draft: '草稿', approved: '已批准', in_progress: '执行中', completed: '已完成' }
const stepStatusLabels = { pending: '待执行', running: '执行中', blocked: '受阻', done: '已完成' }
const runStatusLabels = { running: '执行中', succeeded: '已完成', failed: '执行失败', cancelled: '已取消' }
const historicRunErrorLabels = {
  'The AI execution did not complete. Check model routing and retry.': 'AI 执行未完成，请检查模型路由后重试。',
  'The AI execution exceeded its allowed runtime and was stopped.': 'AI 执行超过允许时长，已被停止。',
  'The AI execution was cancelled by an authorised workspace member.': 'AI 执行已被有权限的工作区成员取消。',
}

const navigationItems = [
  { key: 'chat', icon: <MessageOutlined />, label: 'AI 对话' },
  { key: 'business', icon: <BarChartOutlined />, label: '经营助手' },
  { key: 'report', icon: <FileTextOutlined />, label: '汇报智能体' },
  { key: 'board', icon: <ProjectOutlined />, label: '项目看板' },
  { key: 'work', icon: <AppstoreOutlined />, label: '工作模式' },
  { key: 'team', icon: <TeamOutlined />, label: '团队成员' },
  { key: 'settings', icon: <SettingOutlined />, label: '工作区设置' },
]

const navigationLabels = Object.fromEntries(navigationItems.map((item) => [item.key, item.label]))

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
        <div className="auth-intro-brand"><Avatar size={38} className="brand-avatar" icon={<RobotOutlined />} /><span>futureAgent</span></div>
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
          <Title level={3} style={{ marginBottom: 2 }}>欢迎使用 futureAgent</Title>
          <Text type="secondary">面向团队协作的 AI 工作空间</Text>
        </Space>
        <div className="auth-tabs">
          <Button type={mode === 'login' ? 'primary' : 'text'} onClick={() => { setMode('login'); form.resetFields() }}>登录</Button>
          <Button type={mode === 'register' ? 'primary' : 'text'} onClick={() => { setMode('register'); form.resetFields() }}>创建工作区</Button>
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
          <Form.Item name="email" label="工作邮箱" rules={[{ required: true, type: 'email' }]}>
            <Input autoComplete="email" placeholder="name@company.com" />
          </Form.Item>
          {mode === 'login' ? (
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 10, message: '密码至少需要 10 个字符' }]}>
              <Input.Password autoComplete="current-password" placeholder="至少 10 个字符" />
            </Form.Item>
          ) : (
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 10, message: '密码至少需要 10 个字符' }]}>
              <Input.Password autoComplete="new-password" placeholder="至少 10 个字符" />
            </Form.Item>
          )}
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            {mode === 'login' ? '登录工作区' : '创建安全工作区'}
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
      className="task-card"
      hoverable
      onClick={() => onSelect(task)}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.setData('text/futureagent-task', task.id)
        event.dataTransfer.effectAllowed = 'move'
      }}
    >
      <Flex justify="space-between" align="start" gap={8}>
        <Text strong>{task.title}</Text>
        <Dropdown menu={{ items: columns.filter((item) => item.key !== task.status).map((item) => ({ key: item.key, label: `移动到「${item.title}」` })), onClick: ({ key }) => onMove(task, key) }} trigger={['click']}>
          <Button size="small" type="text" onClick={(event) => event.stopPropagation()}><SettingOutlined /></Button>
        </Dropdown>
      </Flex>
      {task.description && <Paragraph ellipsis={{ rows: 2 }} type="secondary" className="task-description">{task.description}</Paragraph>}
      <Flex justify="space-between" align="center" className="task-meta">
        <Space size={4}>{(task.labels || []).slice(0, 2).map((label) => <Tag key={label} color="blue">{label}</Tag>)}</Space>
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
  const [form] = Form.useForm()
  const [projectForm] = Form.useForm()

  useEffect(() => {
    if (!projects.some((item) => item.id === projectId)) setProjectId(projects[0]?.id || '')
  }, [projects, projectId])

  const projectTasks = tasks.filter((task) => {
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
      await apiFetch('/api/v1/projects', { method: 'POST', body: JSON.stringify({ ...values, color: '#5B5BD6' }) })
      message.success('项目已创建')
      setProjectOpen(false)
      projectForm.resetFields()
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const moveTask = async (task, status) => {
    try {
      await apiFetch(`/api/v1/tasks/${task.id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const canWrite = workspaceRole !== 'viewer'
  return (
    <div className="page-shell">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading">
        <div><Title level={2}>项目看板</Title><Text type="secondary">把目标变成可见、可负责的工作；每一次变更都会写入工作区审计记录。</Text></div>
        <Space>
          <Button icon={<FileAddOutlined />} onClick={async () => { try { await downloadCsv(`/api/v1/tasks/export${projectId ? `?project_id=${projectId}` : ''}`, 'tasks.csv'); message.success('任务清单已导出') } catch (error) { message.error(readableError(error)) } }}>导出任务</Button>
          {canWrite && <Button icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>新建项目</Button>}
          {canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!projectId} onClick={() => setTaskOpen(true)}>新建任务</Button>}
        </Space>
      </Flex>
      {projects.length ? <Flex wrap="wrap" gap={10} className="board-filters"><Select value={projectId} onChange={setProjectId} className="project-selector" options={projects.map((item) => ({ value: item.id, label: item.name }))} /><Input.Search allowClear placeholder="搜索任务标题、上下文或标签" value={query} onChange={(event) => setQuery(event.target.value)} style={{ width: 280, maxWidth: '100%' }} /><Select value={statusFilter} onChange={setStatusFilter} style={{ width: 150 }} options={[{ value: 'all', label: '全部状态' }, ...columns.map((item) => ({ value: item.key, label: item.title }))]} /><Segmented value={view} onChange={setView} options={[{ label: '看板', value: 'board' }, { label: '日历', value: 'calendar' }]} /></Flex> : <Empty className="guided-empty" description="请先创建项目，再开始规划工作">{canWrite && <Button type="primary" icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>创建第一个项目</Button>}</Empty>}
      {projectId && view === 'calendar' && <TaskCalendarView tasks={projectTasks} members={members} onSelect={openTask} />}
      {projectId && view === 'board' && <div className="kanban-grid">{columns.map((column) => (
        <section
          key={column.key}
          className={`kanban-column kanban-column-${column.key}`}
          onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'move' }}
          onDrop={(event) => {
            event.preventDefault()
            const draggedId = event.dataTransfer.getData('text/futureagent-task')
            const dragged = projectTasks.find((task) => task.id === draggedId)
            if (dragged && dragged.status !== column.key && canWrite) moveTask(dragged, column.key)
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

function TaskResultsPanel({ taskId, canWrite, members, refreshKey }) {
  const { message } = AntApp.useApp()
  const [attachments, setAttachments] = useState([])
  const [events, setEvents] = useState([])
  const [deliverables, setDeliverables] = useState([])
  const [workspaceFiles, setWorkspaceFiles] = useState([])
  const [workspaceFilesLoading, setWorkspaceFilesLoading] = useState(false)
  const [registerOpen, setRegisterOpen] = useState(false)
  const [preview, setPreview] = useState(null)
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
    loadResults()
  }, [loadResults, refreshKey])
  useEffect(() => () => { if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current) }, [])
  const attach = async ({ file, onSuccess, onError }) => {
    const requestedTaskId = taskId
    try {
      await uploadAttachment(file, { task_id: requestedTaskId })
      await loadResults(requestedTaskId)
      message.success('文件已添加到此工作项')
      onSuccess?.('ok')
    } catch (error) { message.error(readableError(error)); onError?.(error) }
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
  const files = <List loading={loading} size="small" locale={{ emptyText: '暂无任务文件' }} dataSource={attachments} renderItem={(attachment) => <List.Item actions={[attachment.preview_available ? <Button key="preview" type="link" size="small" onClick={() => showPreview(attachment)}>预览</Button> : null, <Button key="download" type="link" size="small" onClick={() => download(attachment)}>下载</Button>].filter(Boolean)}><List.Item.Meta title={attachment.original_name} description={`${Math.ceil(attachment.size_bytes / 1024)} KB · ${formatDateTime(attachment.created_at)}`} /></List.Item>} />
  const deliverableList = <List loading={loading} size="small" locale={{ emptyText: '尚无交付物；AI 执行或登记工作区文件后会出现在这里' }} dataSource={deliverables} renderItem={(deliverable) => <List.Item actions={[<Button key="download" type="link" size="small" onClick={() => downloadDeliverable(deliverable)}>下载</Button>]}><List.Item.Meta title={<Space size={6}><Tag color={deliverable.kind === 'image' ? 'blue' : deliverable.kind === 'file' ? 'default' : 'purple'}>{deliverable.kind}</Tag>{deliverable.name}</Space>} description={`${Math.ceil(deliverable.size_bytes / 1024)} KB · 来源 ${deliverable.source_path || '工作区'} · ${formatDateTime(deliverable.created_at)}`} /></List.Item>} />
  const activity = <List loading={loading} size="small" locale={{ emptyText: '暂无任务动态' }} dataSource={events} renderItem={(event) => {
    const actor = members.find((member) => member.user.id === event.actor_id)?.user.display_name || '工作区成员'
    const status = event.metadata?.status ? ` · ${readableStatus(event.metadata.status)}` : ''
    return <List.Item><List.Item.Meta title={activityLabels[event.action] || '工作区记录已更新'} description={`${actor} · ${formatDateTime(event.created_at)}${status}`} /></List.Item>
  }} />
  const previewContent = !preview ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择任务文件进行预览" /> : <Space direction="vertical" size="small" style={{ width: '100%' }}><Text strong>{preview.attachment.original_name}</Text>{preview.preview_kind === 'image' ? <img className="artifact-image-preview" src={preview.objectUrl} alt={preview.attachment.original_name} /> : preview.preview_kind === 'pdf' ? <iframe className="artifact-pdf-preview" title={preview.attachment.original_name} src={preview.objectUrl} /> : preview.preview_available ? <pre className="attachment-preview">{preview.text}</pre> : <Text type="secondary">{chineseMessage(preview.message, '此文件暂不支持在线预览。')}</Text>}</Space>
  return <Card className="work-results" title="成果与文件" extra={canWrite && <Space><Button size="small" icon={<FileAddOutlined />} onClick={() => { setRegisterOpen(true); loadWorkspaceFiles() }}>登记交付物</Button><Upload showUploadList={false} customRequest={attach}><Button size="small" icon={<PaperClipOutlined />}>添加上下文</Button></Upload></Space>}>
    <Tabs size="small" items={[{ key: 'deliverables', label: `交付物（${deliverables.length}）`, children: deliverableList }, { key: 'files', label: `文件（${attachments.length}）`, children: files }, { key: 'preview', label: '预览', children: previewContent }, { key: 'activity', label: `动态（${events.length}）`, children: activity }]} />
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
  const [stepId, setStepId] = useState('')
  const [running, setRunning] = useState(false)
  const [liveOutput, setLiveOutput] = useState('')
  const [activeRunId, setActiveRunId] = useState('')
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
  useEffect(() => { setStepId(''); setRuns([]); setLiveOutput(''); setActiveRunId('') }, [taskId])
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
    if (!plan || running || (!retryRun && (!modelId || !skillName))) return
    const executionTaskId = taskId
    const retryMcpServers = retryRun ? recordedRunMcpServers(retryRun) : null
    const execution = retryRun ? {
      modelId: retryRun.model_id,
      skillName: retryRun.skill_name,
      stepId: retryRun.step_id,
      retryOfId: retryRun.id,
      mcpServers: retryMcpServers ?? selectedMcpServers,
      hasRecordedMcpConfig: retryMcpServers !== null,
    } : { modelId, skillName, stepId, retryOfId: null, mcpServers: selectedMcpServers, hasRecordedMcpConfig: true }
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
    setActiveRunId(''); setLiveOutput(''); setRunning(true)
    try {
      await streamSSE(`/api/v1/tasks/${executionTaskId}/execute`, { model_id: execution.modelId, skill_name: execution.skillName, step_id: execution.stepId || null, mcp_servers: execution.mcpServers, retry_of_id: execution.retryOfId, idempotency_key: globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}` }, { signal: abortController.signal, onEvent: (event, data) => {
        if (currentTaskIdRef.current !== executionTaskId) return
        if (event === 'meta') {
          try { setActiveRunId(JSON.parse(data)?.run?.id || '') } catch { /* The run list remains the source of truth. */ }
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
    const retryButton = <Button size="small" onClick={() => execute(run)} disabled={running}>{hasRecordedMcpConfig ? '使用原配置重试' : '复用原模型与技能重试'}</Button>
    return { key: run.id, label: `${readableStatus(run.status)} · ${formatDateTime(run.started_at)}`, children: <Space direction="vertical" size="small" style={{ width: '100%' }}><Text type="secondary">{run.model_id} · {skillDisplayName(run.skill_name)} · 第 {run.attempt || 1} 次尝试</Text>{run.output ? <pre className="attachment-preview">{run.output}</pre> : <Text type="secondary">{readableRunError(run.error_message)}</Text>}<Space>{['failed', 'cancelled'].includes(run.status) && canWrite && (hasRecordedMcpConfig ? retryButton : <Tooltip title="历史记录未包含 MCP 配置，重试时会使用当前工具选择。">{retryButton}</Tooltip>)}{run.status === 'running' && canWrite && <Button size="small" danger onClick={() => cancelRun(run.id)} disabled={running && activeRunId && activeRunId !== run.id}>取消执行</Button>}</Space></Space> }
  })
  const executable = Boolean(plan && ['approved', 'in_progress'].includes(plan.status) && canWrite && models.some((item) => item.id === modelId && item.ready) && skillName && stepId)
  return <Card className="work-results" title="AI 执行" extra={<Space><Button type="primary" icon={<RobotOutlined />} loading={running} disabled={!executable} onClick={() => execute()}>执行选中步骤</Button>{running && activeRunId && <Button danger icon={<StopOutlined />} onClick={() => cancelRun(activeRunId)}>取消</Button>}</Space>}>
    <Space direction="vertical" size="small" style={{ width: '100%' }}><Text type="secondary">AI 只会接收已批准任务、选中计划步骤和附件中的有限文本上下文；结果保存后必须由人工审核，不会自动通过步骤。</Text><Flex gap={8} wrap="wrap" className="execution-controls"><Select value={stepId || undefined} onChange={setStepId} placeholder="选择计划步骤" options={(plan?.steps || []).filter((step) => step.status !== 'done').map((step) => ({ value: step.id, label: `${stepStatusLabels[step.status] || step.status} · ${step.title}` }))} /><Select value={modelId || undefined} onChange={setModelId} placeholder="选择模型" options={models.map((item) => ({ value: item.id, label: `${item.id}${item.ready ? '' : '（未就绪）'}`, disabled: !item.ready }))} /><Select value={skillName || undefined} onChange={setSkillName} placeholder="选择技能" options={skills.map((item) => ({ value: item.name, label: skillDisplayName(item.name) }))} /><Select mode="multiple" value={selectedMcpServers} onChange={setSelectedMcpServers} maxTagCount="responsive" placeholder={mcpServers.length ? '按需启用 MCP 工具' : '暂无 MCP 工具'} disabled={!mcpServers.length} options={mcpServers.map((item) => ({ value: item.name || item, label: mcpOptionLabel(item), title: mcpOptionLabel(item), tools: Array.isArray(item.tools) ? item.tools : [], disabled: mcpServerUnavailable(item) }))} optionRender={(option) => <div className="mcp-option"><span>{option.label}</span><small>{option.data?.tools?.length ? option.data.tools.join(' · ') : option.data?.disabled ? '连接不可用' : '工具清单将在连接后显示'}</small></div>} /></Flex>{liveOutput && <pre className="attachment-preview">{liveOutput}</pre>}{runItems.length ? <Tabs size="small" items={runItems} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此任务尚无 AI 执行记录" />}</Space>
  </Card>
}

function WorkModePage({ tasks, members, models, skills, mcpServers, workspaceRole, profile, onRefresh, onOpenBoard }) {
  const { message } = AntApp.useApp()
  const [taskId, setTaskId] = useState(tasks[0]?.id || '')
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [executionRunning, setExecutionRunning] = useState(false)
  const [evidenceStep, setEvidenceStep] = useState(null)
  const [form] = Form.useForm()
  const [evidenceForm] = Form.useForm()
  const planRequestIdRef = useRef(0)
  const currentTaskIdRef = useRef(taskId)
  currentTaskIdRef.current = taskId
  const selectedTask = tasks.find((item) => item.id === taskId)
  const canWrite = workspaceRole !== 'viewer'
  const canApprove = ['owner', 'admin'].includes(workspaceRole)
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
      form.setFieldsValue({ objective: data.plan?.objective || '', steps: data.plan?.steps?.length ? data.plan.steps : [{ title: '', instructions: '', assignee_id: undefined }] })
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
      const data = await apiFetch(`/api/v1/tasks/${requestedTaskId}/plan`, { method: 'PUT', body: JSON.stringify(values) })
      if (currentTaskIdRef.current !== requestedTaskId) return
      setPlan(data.plan)
      message.success('工作计划已保存为草稿')
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
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
  const progress = plan?.steps?.length ? Math.round((plan.steps.filter((item) => item.status === 'done').length / plan.steps.length) * 100) : 0
  return (
    <div className="page-shell work-mode">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading"><div><Title level={2}>工作模式</Title><Text type="secondary">先制定执行计划，再批准执行；每个步骤都有明确责任与可追溯记录。</Text></div><Badge status={plan?.status === 'approved' || plan?.status === 'in_progress' ? 'processing' : plan?.status === 'completed' ? 'success' : 'default'} text={plan ? (planStatusLabels[plan.status] || plan.status) : '尚未创建计划'} /></Flex>
      {!tasks.length ? <Empty className="guided-empty" description="请先在项目看板中创建任务">{canWrite && <Button type="primary" icon={<ProjectOutlined />} onClick={onOpenBoard}>前往项目看板</Button>}</Empty> : <>
        <Select value={taskId} onChange={selectTask} disabled={executionRunning} title={executionRunning ? 'AI 执行期间不可切换任务' : undefined} className="project-selector" options={tasks.map((task) => ({ value: task.id, label: task.title }))} />
        <Card className="work-context" size="small"><Descriptions size="small" column={{ xs: 1, md: 3 }}><Descriptions.Item label="任务">{selectedTask?.title}</Descriptions.Item><Descriptions.Item label="发起人">{members.find((item) => item.user.id === selectedTask?.reporter_id)?.user.display_name || '-'}</Descriptions.Item><Descriptions.Item label="状态"><Tag>{taskStatusLabels[selectedTask?.status] || selectedTask?.status}</Tag></Descriptions.Item></Descriptions></Card>
        <Spin spinning={loading}>
          {(plan?.status === 'approved' || plan?.status === 'in_progress' || plan?.status === 'completed') ? (
            <Card className="plan-execution" title="已批准的工作计划" extra={<Tag color={plan.status === 'completed' ? 'success' : 'processing'}>{planStatusLabels[plan.status] || plan.status}</Tag>}>
              <Paragraph>{plan.objective || '尚未记录目标。'}</Paragraph>
              <Progress percent={progress} status={progress === 100 ? 'success' : 'active'} />
              <Steps direction="vertical" size="small" current={Math.min(plan.steps.findIndex((step) => step.status !== 'done'), Math.max(plan.steps.length - 1, 0))} items={plan.steps.map((step) => ({ title: <Flex justify="space-between" gap={8}><span>{step.title}</span><Select value={step.status} size="small" style={{ width: 124 }} disabled={!canUpdateStep(step)} onChange={(value) => updateStep(step, { status: value })} options={['pending', 'running', 'blocked', 'done'].map((value) => ({ value, label: stepStatusLabels[value] }))} /></Flex>, description: <Space direction="vertical" size={2}><Text type="secondary">{step.instructions || '暂无补充说明。'}</Text><Text type="secondary">负责人：{members.find((item) => item.user.id === step.assignee_id)?.user.display_name || '未分配'}</Text>{step.output_summary && <Text>执行证据：{step.output_summary}</Text>}{canUpdateStep(step) && <Button type="link" size="small" style={{ paddingInline: 0, width: 'fit-content' }} onClick={() => openEvidence(step)}>记录结果或证据</Button>}</Space>, status: step.status === 'done' ? 'finish' : step.status === 'blocked' ? 'error' : step.status === 'running' ? 'process' : 'wait' }))} />
            </Card>
          ) : (
            <Card title="执行前计划" extra={plan && <Tag color="gold">草稿</Tag>}>
              <Form form={form} layout="vertical" onFinish={savePlan}>
                <Form.Item label="选择可复用流程"><Select placeholder="选择交付、调研或故障响应流程" onChange={applyTemplate} disabled={!canWrite} options={planTemplates.map((item) => ({ value: item.value, label: item.label }))} /></Form.Item>
                <Form.Item name="objective" label="目标" rules={[{ required: true, min: 4 }]}><Input.TextArea rows={3} placeholder="这项工作要交付什么结果？" disabled={!canWrite} /></Form.Item>
                <Form.List name="steps">{(fields, { add, remove }) => <div className="plan-form-list"><Flex justify="space-between" align="center"><Text strong>执行步骤</Text>{canWrite && <Button size="small" icon={<PlusOutlined />} onClick={() => add({ title: '', instructions: '' })}>添加步骤</Button>}</Flex>{fields.map((field, index) => <Card size="small" key={field.key} className="plan-step-editor"><Flex gap={10} align="start"><Tag>{index + 1}</Tag><div className="plan-step-fields"><Form.Item name={[field.name, 'id']} hidden><Input /></Form.Item><Form.Item name={[field.name, 'title']} rules={[{ required: true, min: 2 }]}><Input placeholder="步骤标题" disabled={!canWrite} /></Form.Item><Form.Item name={[field.name, 'instructions']}><Input.TextArea rows={2} placeholder="预期工作、输入和验收证据" disabled={!canWrite} /></Form.Item><Form.Item name={[field.name, 'assignee_id']}><Select allowClear placeholder="负责人" disabled={!canWrite} options={members.map((item) => ({ value: item.user.id, label: item.user.display_name }))} /></Form.Item></div>{canWrite && <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(field.name)} />}</Flex></Card>)}</div>}</Form.List>
                <Flex justify="end" gap={8}><Button htmlType="submit" disabled={!canWrite}>保存草稿</Button>{canApprove && plan && <Button type="primary" icon={<CheckCircleOutlined />} onClick={approve}>批准执行</Button>}</Flex>
              </Form>
            </Card>
          )}
        </Spin>
        <TaskExecutionPanel taskId={taskId} plan={plan} models={models} skills={skills} mcpServers={mcpServers} canWrite={canWrite} onPlanRefresh={loadPlan} onRunningChange={setExecutionRunning} />
        <TaskResultsPanel taskId={taskId} canWrite={canWrite} members={members} refreshKey={plan?.updated_at || ''} />
      </>}
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
  return <div className="page-shell"><Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading"><div><Title level={2}>团队成员</Title><Text type="secondary">成员归属工作区管理；管理员可添加已注册用户，并按最小权限原则分配角色。</Text></div>{manager && <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>添加成员</Button>}</Flex><Card><List dataSource={members} renderItem={(member) => <List.Item actions={manager && member.role !== 'owner' ? [<Popconfirm key="remove" title="确认移除此成员？" onConfirm={() => removeMember(member)} okText="确认" cancelText="取消"><Button danger type="link">移除</Button></Popconfirm>] : []}><List.Item.Meta avatar={<Avatar icon={<UserOutlined />} />} title={<Space><Text strong>{member.user.display_name}</Text>{member.user.is_platform_admin && <Tag color="purple">平台管理员</Tag>}</Space>} description={member.user.email} /><Tag color={member.role === 'owner' ? 'gold' : member.role === 'admin' ? 'blue' : 'default'}>{roleLabels[member.role] || member.role}</Tag></List.Item>} /></Card><Modal title="添加已注册成员" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} okText="确认" cancelText="取消" destroyOnHidden><Form form={form} layout="vertical" onFinish={addMember} initialValues={{ role: 'member' }}><Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}><Input placeholder="对方需要先完成注册" /></Form.Item><Form.Item name="role" label="角色"><Select options={['admin', 'member', 'viewer'].map((value) => ({ value, label: roleLabels[value] }))} /></Form.Item></Form></Modal></div>
}

function WorkspaceSettingsPage({ workspace, members, workspaceRole, onRefresh }) {
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
  return (
    <div className="page-shell settings-page">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading">
        <div><Title level={2}>工作区设置</Title><Text type="secondary">名称、所有权与通知出口都在这里集中管理；关键操作会写入审计记录。</Text></div>
      </Flex>
      <Card className="settings-card" title="基本信息">
        <Flex gap={10} wrap="wrap">
          <Input value={name} onChange={(event) => setName(event.target.value)} style={{ width: 320, maxWidth: '100%' }} placeholder="工作区名称" disabled={!isManager} />
          <Button type="primary" loading={savingName} disabled={!isManager || !name.trim() || name.trim() === workspace?.name} onClick={saveName}>保存名称</Button>
        </Flex>
        <Paragraph type="secondary" style={{ marginTop: 10, marginBottom: 0 }}><Text type="secondary">标识：{workspace?.slug || '-'} · 所有者：{members.find((m) => m.user.id === workspace?.owner_id)?.user.display_name || '未知'}</Text></Paragraph>
      </Card>
      {isManager && (
        <Card className="settings-card" title="通知出口" extra={<Button size="small" icon={<PlusOutlined />} onClick={() => setTargetOpen(true)}>新建出口</Button>}>
          <Paragraph type="secondary" style={{ marginTop: 0 }}>预警扫描与关键事件可推送到企业微信群机器人、飞书、钉钉或任意 Webhook。</Paragraph>
          {targetsLoading ? <Spin /> : targets.length ? (
            <List size="small" dataSource={targets} renderItem={(target) => (
              <List.Item actions={[
                <Button key="test" size="small" onClick={() => testTarget(target)}>测试</Button>,
                <Button key="delete" size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeTarget(target)} aria-label={`删除 ${target.name}`} />,
                <Switch key="switch" size="small" checked={target.enabled} onChange={(checked) => toggleTarget(target, checked)} aria-label={`启用 ${target.name}`} />,
              ]}>
                <List.Item.Meta title={<Space size={6}><Tag color="purple">{targetKindLabels[target.kind] || target.kind}</Tag>{target.name}</Space>} description={target.url} />
              </List.Item>
            )} />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未配置通知出口" />}
        </Card>
      )}
      {isOwner && (
        <>
          <Card className="settings-card" title="所有权转移">
            <Paragraph type="secondary" style={{ marginTop: 0 }}>转移后你将变为管理员。存在老板/私事经营数据时系统会拒绝转移，需先归档或交接。</Paragraph>
            <Flex gap={10} wrap="wrap">
              <Select value={transferMemberId || undefined} onChange={setTransferMemberId} style={{ width: 280, maxWidth: '100%' }} placeholder="选择新的所有者（工作区成员）" options={transferCandidates.map((m) => ({ value: m.id, label: `${m.user.display_name}（${m.user.email}）` }))} />
              <Button type="primary" disabled={!transferMemberId} onClick={transferOwnership}>转移所有权</Button>
            </Flex>
          </Card>
          <Card className="settings-card settings-danger" title="危险区">
            <Paragraph type="secondary" style={{ marginTop: 0 }}>删除工作区会永久清除全部成员、项目、任务、对话、附件、交付物与审计记录。</Paragraph>
            <Button danger onClick={deleteWorkspace}>删除此工作区</Button>
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
  const { message } = AntApp.useApp()
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
  const [skills, setSkills] = useState([])
  const [mcpServers, setMcpServers] = useState([])
  const [nav, setNav] = useState('chat')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [workspaceError, setWorkspaceError] = useState('')
  const [taskDrawer, setTaskDrawer] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)
  const [hasMoreMessages, setHasMoreMessages] = useState(false)
  const [globalQuery, setGlobalQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [notifications, setNotifications] = useState([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [notificationOpen, setNotificationOpen] = useState(false)
  const [themeTick, setThemeTick] = useState(0)
  const loadedWorkspaceIdRef = useRef('')
  const workspaceRequestIdRef = useRef(0)
  const conversationRequestIdRef = useRef(0)
  const currentWorkspaceIdRef = useRef(workspaceId)
  const currentConversationIdRef = useRef(activeConversationId)
  currentWorkspaceIdRef.current = workspaceId
  currentConversationIdRef.current = activeConversationId
  const workspace = workspaces.find((item) => item.id === workspaceId) || workspaces[0]
  const activeConversation = conversations.find((item) => item.id === activeConversationId)
  const canProbeMcp = ['owner', 'admin'].includes(workspace?.role)

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
    try {
      const [memberData, projectData, taskData, conversationData, modelData, skillData, mcpData] = await Promise.all([
        apiFetch(`/api/v1/workspaces/${requestedWorkspaceId}/members`, { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/projects', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/tasks', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/conversations', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/models', { workspaceId: requestedWorkspaceId }),
        apiFetch('/api/v1/skills', { workspaceId: requestedWorkspaceId }),
        apiFetch(`/api/v1/mcp/servers${canProbeMcp ? '?probe=true' : ''}`, { workspaceId: requestedWorkspaceId })
          .catch(() => canProbeMcp ? apiFetch('/api/v1/mcp/servers', { workspaceId: requestedWorkspaceId }) : { servers: [] })
          .catch(() => ({ servers: [] })),
      ])
      if (requestId !== workspaceRequestIdRef.current || currentWorkspaceIdRef.current !== requestedWorkspaceId) return false
      setMembers(memberData.members || [])
      setProjects(projectData.projects || [])
      setTasks(taskData.tasks || [])
      setConversations(conversationData.conversations || [])
      setModels(modelData.details || [])
      setSkills(skillData.skills || [])
      setMcpServers(mcpData.servers || [])
      setActiveConversationId((current) => current && conversationData.conversations?.some((item) => item.id === current) ? current : conversationData.conversations?.[0]?.id || '')
      loadedWorkspaceIdRef.current = requestedWorkspaceId
      return true
    } catch (error) {
      if (requestId !== workspaceRequestIdRef.current || currentWorkspaceIdRef.current !== requestedWorkspaceId) return false
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
  }, [canProbeMcp, clearWorkspaceData, message, workspaceId])

  useEffect(() => { setWorkspaceId(workspaceId); loadWorkspace() }, [loadWorkspace, workspaceId])
  useEffect(() => { window.scrollTo(0, 0) }, [nav])
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
  const runGlobalSearch = useCallback(async (value) => {
    const keyword = value.trim()
    if (!keyword) { setSearchResults([]); return }
    try {
      const data = await apiFetch(`/api/v1/search?q=${encodeURIComponent(keyword)}&limit=12`, { workspaceId })
      setSearchResults(data.results || [])
    } catch { setSearchResults([]) }
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
    try {
      await apiFetch(`/api/v1/notifications/${notification.id}/read`, { method: 'POST', workspaceId })
      loadNotifications()
    } catch { /* 保持未读状态即可 */ }
  }
  const markAllNotificationsRead = async () => {
    try { await apiFetch('/api/v1/notifications/read-all', { method: 'POST', workspaceId }); loadNotifications() } catch { /* 忽略 */ }
  }
  const openNotification = (notification) => {
    markNotificationRead(notification)
    if (notification.link && navigationLabels[notification.link]) {
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
  const searchTypeLabels = { task: '任务', project: '项目', conversation: '对话', message: '消息', attachment: '附件' }
  const searchOptions = useMemo(() => searchResults.map((item) => ({
    value: `${item.type}:${item.id}`,
    label: (
      <div className="global-search-option">
        <Tag color="blue" className="global-search-tag">{searchTypeLabels[item.type] || item.type}</Tag>
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
    else if (type === 'attachment') {
      if (item.task_id) { setNav('board'); setTaskDrawer(tasks.find((task) => task.id === item.task_id) || null) }
      else if (item.conversation_id) { selectConversation(item.conversation_id); setNav('chat') }
    }
    setGlobalQuery('')
    setSearchResults([])
  }
  const sideMenu = <Menu theme="dark" mode="inline" selectedKeys={[nav]} onClick={({ key }) => { setNav(key); setMobileNav(false) }} items={navigationItems} />
  const layoutSider = <>
    <div className="workspace-brand"><Avatar icon={<RobotOutlined />} className="brand-avatar" /><div><strong>futureAgent</strong><span>团队 AI 工作空间</span></div></div>
    <Text className="workspace-switcher-label">当前工作区</Text>
    <Select value={workspaceId || undefined} onChange={selectWorkspace} className="workspace-select" placeholder="选择工作区" options={workspaces.map((item) => ({ value: item.id, label: item.name }))} />
    {sideMenu}
    <div className="sider-bottom"><span className="sider-status-dot" /><Text>{workspace?.name || '尚未选择工作区'}</Text><Tag color={workspace?.role === 'owner' ? 'gold' : 'blue'}>{roleLabels[workspace?.role] || '成员'}</Tag></div>
  </>

  let content
  if (nav === 'chat') content = <ChatPage conversations={conversations} activeConversation={activeConversation} messages={messages} models={models} skills={skills} mcpServers={mcpServers} hasMoreMessages={hasMoreMessages} onLoadMoreMessages={loadOlderMessages} onNewConversation={newConversation} onSelectConversation={selectConversation} onRefresh={refreshWorkspace} onRefreshMessages={loadConversationMessages} workspaceRole={workspace?.role} />
  else if (nav === 'business') content = <BusinessAssistantsPage workspaceRole={workspace?.role} members={members} currentUserId={profile?.id} />
  else if (nav === 'report') content = <ReportAssistantsPage workspaceRole={workspace?.role} members={members} currentUserId={profile?.id} />
  else if (nav === 'board') content = <BoardPage projects={projects} tasks={tasks} members={members} onRefresh={refreshWorkspace} openTask={(task) => setTaskDrawer(task)} workspaceRole={workspace?.role} />
  else if (nav === 'work') content = <WorkModePage tasks={tasks} members={members} models={models} skills={skills} mcpServers={mcpServers} workspaceRole={workspace?.role} profile={profile} onRefresh={refreshWorkspace} onOpenBoard={() => setNav('board')} />
  else if (nav === 'team') content = <TeamPage workspace={workspace} members={members} workspaceRole={workspace?.role} onRefresh={refreshWorkspace} />
  else if (nav === 'settings') content = <WorkspaceSettingsPage workspace={workspace} members={members} workspaceRole={workspace?.role} onRefresh={refreshWorkspace} />

  const workspaceContent = loading ? (
    <div className="workspace-loading"><Space direction="vertical" align="center"><Spin size="large" /><Text type="secondary">正在加载工作区</Text></Space></div>
  ) : workspaceError && (!workspaceId || loadedWorkspaceIdRef.current !== workspaceId) ? (
    <div className="workspace-state-page"><Alert type="error" showIcon message="工作区加载失败" description={workspaceError} /><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请检查连接后重新加载"><Button type="primary" icon={<ReloadOutlined />} onClick={() => loadWorkspace()}>重新加载</Button></Empty></div>
  ) : (
    <>
      {workspaceError && <Alert className="workspace-error-strip" banner type="warning" showIcon message="刷新未完成，当前显示上次成功加载的数据。" action={<Button size="small" onClick={refreshWorkspace}>重试</Button>} />}
      <Suspense fallback={<div className="workspace-loading"><Spin size="large" /></div>}>{content}</Suspense>
    </>
  )

  return (
    <Layout className="workspace-layout">
      {screens.lg ? (
        <Sider width={248} theme="dark" className="workspace-sider">{layoutSider}</Sider>
      ) : (
        <Drawer placement="left" open={mobileNav} onClose={() => setMobileNav(false)} width={280} rootClassName="mobile-workspace-drawer" styles={{ body: { padding: 0, background: '#111827' } }}>{layoutSider}</Drawer>
      )}
      <Layout>
        <Header className="workspace-header">
          <Flex align="center" gap={10} style={{ minWidth: 0 }}>
            {!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNav(true)} aria-label="打开主导航" />}
            <div className="header-context"><Text strong>{navigationLabels[nav]}</Text><Text type="secondary">{workspace?.name || '团队工作区'}</Text></div>
          </Flex>
          <Space size={6}>
            <Tooltip title="通知中心">
              <Badge count={unreadCount} size="small" offset={[-3, 3]}>
                <Button type="text" icon={<BellOutlined />} onClick={() => { setNotificationOpen(true); loadNotifications() }} aria-label="通知中心" />
              </Badge>
            </Tooltip>
            <AutoComplete
              className="global-search"
              value={globalQuery}
              onChange={(value) => { setGlobalQuery(value); runGlobalSearch(value) }}
              onSelect={handleSearchSelect}
              options={searchOptions}
              popupMatchSelectWidth={420}
              aria-label="全局搜索"
            >
              <Input allowClear prefix={<SearchOutlined />} placeholder="搜索任务、对话、消息或文件" />
            </AutoComplete>
            <Badge className="workspace-health" status={refreshing ? 'processing' : 'success'} text={refreshing ? '正在同步' : '已安全连接'} />
            <Tooltip title={getThemeMode() === 'dark' ? '切换到浅色' : '切换到深色'}>
              <Button
                type="text"
                icon={<BulbOutlined />}
                onClick={() => { toggleThemeMode(); setThemeTick((tick) => tick + 1) }}
                aria-label="切换深浅色主题"
              />
            </Tooltip>
            <Tooltip title="刷新工作区"><Button type="text" icon={<ReloadOutlined spin={refreshing} />} onClick={refreshWorkspace} disabled={refreshing || loading} aria-label="刷新工作区" /></Tooltip>
            <Dropdown menu={{ items: [{ key: 'profile', label: profile?.email, disabled: true }, { type: 'divider' }, { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout }] }}>
              <Button type="text" className="profile-button" aria-label={`账号菜单：${profile?.display_name || '当前用户'}`}><Avatar size="small" icon={<UserOutlined />} /><span>{profile?.display_name}</span></Button>
            </Dropdown>
          </Space>
        </Header>
        <Content className="workspace-content">{workspaceContent}</Content>
      </Layout>
      <Drawer
        title={<Flex justify="space-between" align="center" gap={8}><span>通知中心</span><Button size="small" type="link" disabled={!unreadCount} onClick={markAllNotificationsRead}>全部已读</Button></Flex>}
        open={notificationOpen}
        onClose={() => setNotificationOpen(false)}
        width={screens.sm ? 400 : '100%'}
      >
        {notifications.length ? (
          <List dataSource={notifications} renderItem={(item) => (
            <List.Item
              className={item.read ? 'notification-item' : 'notification-item notification-item-unread'}
              onClick={() => openNotification(item)}
              style={{ cursor: 'pointer' }}
            >
              <List.Item.Meta
                title={item.title}
                description={<Space direction="vertical" size={2}>{item.body && <span>{item.body}</span>}<Text type="secondary" style={{ fontSize: 12 }}>{formatDateTime(item.created_at)}</Text></Space>}
              />
              {!item.read && <Badge status="processing" />}
            </List.Item>
          )} />
        ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无通知" />}
      </Drawer>
      <Drawer title="任务详情" open={Boolean(taskDrawer)} onClose={() => setTaskDrawer(null)} width={screens.sm ? 480 : '100%'}>
        {taskDrawer && <Space direction="vertical" size="middle" style={{ width: '100%' }}><Title level={4}>{taskDrawer.title}</Title><Paragraph>{taskDrawer.description || '暂无任务说明。'}</Paragraph><Descriptions bordered size="small" column={1}><Descriptions.Item label="状态"><Tag>{taskStatusLabels[taskDrawer.status] || taskDrawer.status}</Tag></Descriptions.Item><Descriptions.Item label="优先级"><Tag>{priorityLabels[taskDrawer.priority] || taskDrawer.priority}</Tag></Descriptions.Item><Descriptions.Item label="截止日期">{taskDrawer.due_date || '未设置'}</Descriptions.Item></Descriptions><TaskComments taskId={taskDrawer.id} /><Button type="primary" icon={<AppstoreOutlined />} onClick={() => { setNav('work'); setTaskDrawer(null) }}>在工作模式中打开</Button></Space>}
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
    const listener = (event) => setThemeMode(event.detail || getThemeMode())
    window.addEventListener('futureagent-theme', listener)
    return () => window.removeEventListener('futureagent-theme', listener)
  }, [])
  const isDark = themeMode === 'dark'
  return <ConfigProvider locale={zhCN} theme={{
    algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: '#4f5fd5',
      colorInfo: '#4f5fd5',
      colorSuccess: '#1f9d72',
      colorWarning: '#d97706',
      colorError: '#d14343',
      colorText: isDark ? '#e6eaf2' : '#172033',
      colorTextSecondary: isDark ? '#9aa4b8' : '#667085',
      colorBorder: isDark ? '#39435c' : '#e0e6ef',
      colorBorderSecondary: isDark ? '#2a3346' : '#eaeef6',
      colorBgLayout: isDark ? '#0f1420' : '#f4f6fb',
      colorBgContainer: isDark ? '#171e2e' : '#ffffff',
      borderRadius: 10,
      controlHeight: 36,
      fontFamily: '"PingFang SC", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif',
    },
    components: {
      Button: { primaryShadow: '0 6px 16px rgba(79, 95, 213, .22)', fontWeight: 500 },
      Card: { headerFontSize: 15 },
      Menu: { darkItemBg: '#101624', darkItemSelectedBg: '#4f5fd5' },
    },
  }}><AntApp><App /></AntApp></ConfigProvider>
}
