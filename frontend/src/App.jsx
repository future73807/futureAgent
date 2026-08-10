import React, { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Alert from 'antd/es/alert'
import AntApp from 'antd/es/app'
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
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Statistic from 'antd/es/statistic'
import Steps from 'antd/es/steps'
import Tabs from 'antd/es/tabs'
import Tag from 'antd/es/tag'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import theme from 'antd/es/theme'
import {
  AppstoreOutlined,
  BarChartOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
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
  getAttachmentBlob,
  getAccessToken,
  getWorkspaceId,
  refreshAccessToken,
  setWorkspaceId,
  streamSSE,
  uploadAttachment,
} from './api.js'
import { mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from './ui-labels.js'

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
      <Card className="auth-card" variant="borderless">
        <Space direction="vertical" size={4} className="auth-heading">
          <Avatar size={52} className="brand-avatar" icon={<RobotOutlined />} />
          <Title level={2}>futureAgent</Title>
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
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 10, message: '密码至少需要 10 个字符' }]}>
            <Input.Password autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder="至少 10 个字符" />
          </Form.Item>
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
    <Card size="small" className="task-card" hoverable onClick={() => onSelect(task)}>
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
          <Tag color={task.priority === 'urgent' ? 'red' : task.priority === 'high' ? 'orange' : 'default'}>{priorityLabels[task.priority] || task.priority}</Tag>
          {assignee && <Tooltip title={assignee.display_name}><Avatar size="small" icon={<UserOutlined />} /></Tooltip>}
        </Space>
      </Flex>
    </Card>
  )
}

function BoardPage({ projects, tasks, members, onRefresh, openTask, workspaceRole }) {
  const { message } = AntApp.useApp()
  const [projectId, setProjectId] = useState(projects[0]?.id || '')
  const [taskOpen, setTaskOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
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
          {canWrite && <Button icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>新建项目</Button>}
          {canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!projectId} onClick={() => setTaskOpen(true)}>新建任务</Button>}
        </Space>
      </Flex>
      {projects.length ? <Flex wrap="wrap" gap={10} className="board-filters"><Select value={projectId} onChange={setProjectId} className="project-selector" options={projects.map((item) => ({ value: item.id, label: item.name }))} /><Input.Search allowClear placeholder="搜索任务标题、上下文或标签" value={query} onChange={(event) => setQuery(event.target.value)} style={{ width: 280, maxWidth: '100%' }} /><Select value={statusFilter} onChange={setStatusFilter} style={{ width: 150 }} options={[{ value: 'all', label: '全部状态' }, ...columns.map((item) => ({ value: item.key, label: item.title }))]} /></Flex> : <Empty className="guided-empty" description="请先创建项目，再开始规划工作">{canWrite && <Button type="primary" icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>创建第一个项目</Button>}</Empty>}
      {projectId && <div className="kanban-grid">{columns.map((column) => (
        <section key={column.key} className="kanban-column">
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
    if (!requestedTaskId) { setAttachments([]); setEvents([]); setLoading(false); return false }
    setLoading(true)
    try {
      const [files, activity] = await Promise.all([
        apiFetch(`/api/v1/attachments?task_id=${requestedTaskId}`),
        apiFetch(`/api/v1/tasks/${requestedTaskId}/activity`),
      ])
      if (requestId !== resultsRequestIdRef.current || currentTaskIdRef.current !== requestedTaskId) return false
      setAttachments(files.attachments || [])
      setEvents(activity.events || [])
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
  const files = <List loading={loading} size="small" locale={{ emptyText: '暂无任务文件' }} dataSource={attachments} renderItem={(attachment) => <List.Item actions={[attachment.preview_available ? <Button key="preview" type="link" size="small" onClick={() => showPreview(attachment)}>预览</Button> : null, <Button key="download" type="link" size="small" onClick={() => download(attachment)}>下载</Button>].filter(Boolean)}><List.Item.Meta title={attachment.original_name} description={`${Math.ceil(attachment.size_bytes / 1024)} KB · ${formatDateTime(attachment.created_at)}`} /></List.Item>} />
  const activity = <List loading={loading} size="small" locale={{ emptyText: '暂无任务动态' }} dataSource={events} renderItem={(event) => {
    const actor = members.find((member) => member.user.id === event.actor_id)?.user.display_name || '工作区成员'
    const status = event.metadata?.status ? ` · ${readableStatus(event.metadata.status)}` : ''
    return <List.Item><List.Item.Meta title={activityLabels[event.action] || '工作区记录已更新'} description={`${actor} · ${formatDateTime(event.created_at)}${status}`} /></List.Item>
  }} />
  const previewContent = !preview ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请选择任务文件进行预览" /> : <Space direction="vertical" size="small" style={{ width: '100%' }}><Text strong>{preview.attachment.original_name}</Text>{preview.preview_kind === 'image' ? <img className="artifact-image-preview" src={preview.objectUrl} alt={preview.attachment.original_name} /> : preview.preview_kind === 'pdf' ? <iframe className="artifact-pdf-preview" title={preview.attachment.original_name} src={preview.objectUrl} /> : preview.preview_available ? <pre className="attachment-preview">{preview.text}</pre> : <Text type="secondary">{chineseMessage(preview.message, '此文件暂不支持在线预览。')}</Text>}</Space>
  return <Card className="work-results" title="成果与文件" extra={canWrite && <Upload showUploadList={false} customRequest={attach}><Button size="small" icon={<PaperClipOutlined />}>添加上下文或交付物</Button></Upload>}>
    <Tabs size="small" items={[{ key: 'files', label: `文件（${attachments.length}）`, children: files }, { key: 'preview', label: '预览', children: previewContent }, { key: 'activity', label: `动态（${events.length}）`, children: activity }]} />
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
  const loadConversationMessages = useCallback(async (conversationId = activeConversationId, { notify = false } = {}) => {
    const requestId = ++conversationRequestIdRef.current
    const requestedWorkspaceId = workspaceId
    if (!conversationId || !requestedWorkspaceId) {
      setMessages([])
      return false
    }
    try {
      const data = await apiFetch(`/api/v1/conversations/${conversationId}/messages`, { workspaceId: requestedWorkspaceId })
      if (requestId !== conversationRequestIdRef.current || currentWorkspaceIdRef.current !== requestedWorkspaceId || currentConversationIdRef.current !== conversationId) return false
      setMessages(data.messages || [])
      return true
    } catch (error) {
      const currentRequest = requestId === conversationRequestIdRef.current && currentWorkspaceIdRef.current === requestedWorkspaceId && currentConversationIdRef.current === conversationId
      if (!currentRequest) return false
      if (notify) message.error(readableError(error))
      throw error
    }
  }, [activeConversationId, message, workspaceId])
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
  const sideMenu = <Menu theme="dark" mode="inline" selectedKeys={[nav]} onClick={({ key }) => { setNav(key); setMobileNav(false) }} items={navigationItems} />
  const layoutSider = <>
    <div className="workspace-brand"><Avatar icon={<RobotOutlined />} className="brand-avatar" /><div><strong>futureAgent</strong><span>团队 AI 工作空间</span></div></div>
    <Text className="workspace-switcher-label">当前工作区</Text>
    <Select value={workspaceId || undefined} onChange={selectWorkspace} className="workspace-select" placeholder="选择工作区" options={workspaces.map((item) => ({ value: item.id, label: item.name }))} />
    {sideMenu}
    <div className="sider-bottom"><span className="sider-status-dot" /><Text>{workspace?.name || '尚未选择工作区'}</Text><Tag color={workspace?.role === 'owner' ? 'gold' : 'blue'}>{roleLabels[workspace?.role] || '成员'}</Tag></div>
  </>

  let content
  if (nav === 'chat') content = <ChatPage conversations={conversations} activeConversation={activeConversation} messages={messages} models={models} skills={skills} mcpServers={mcpServers} onNewConversation={newConversation} onSelectConversation={selectConversation} onRefresh={refreshWorkspace} onRefreshMessages={loadConversationMessages} workspaceRole={workspace?.role} />
  else if (nav === 'business') content = <BusinessAssistantsPage workspaceRole={workspace?.role} members={members} currentUserId={profile?.id} />
  else if (nav === 'report') content = <ReportAssistantsPage workspaceRole={workspace?.role} members={members} currentUserId={profile?.id} />
  else if (nav === 'board') content = <BoardPage projects={projects} tasks={tasks} members={members} onRefresh={refreshWorkspace} openTask={(task) => setTaskDrawer(task)} workspaceRole={workspace?.role} />
  else if (nav === 'work') content = <WorkModePage tasks={tasks} members={members} models={models} skills={skills} mcpServers={mcpServers} workspaceRole={workspace?.role} profile={profile} onRefresh={refreshWorkspace} onOpenBoard={() => setNav('board')} />
  else content = <TeamPage workspace={workspace} members={members} workspaceRole={workspace?.role} onRefresh={refreshWorkspace} />

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
            <Badge className="workspace-health" status={refreshing ? 'processing' : 'success'} text={refreshing ? '正在同步' : '已安全连接'} />
            <Tooltip title="刷新工作区"><Button type="text" icon={<ReloadOutlined spin={refreshing} />} onClick={refreshWorkspace} disabled={refreshing || loading} aria-label="刷新工作区" /></Tooltip>
            <Dropdown menu={{ items: [{ key: 'profile', label: profile?.email, disabled: true }, { type: 'divider' }, { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: onLogout }] }}>
              <Button type="text" className="profile-button" aria-label={`账号菜单：${profile?.display_name || '当前用户'}`}><Avatar size="small" icon={<UserOutlined />} /><span>{profile?.display_name}</span></Button>
            </Dropdown>
          </Space>
        </Header>
        <Content className="workspace-content">{workspaceContent}</Content>
      </Layout>
      <Drawer title="任务详情" open={Boolean(taskDrawer)} onClose={() => setTaskDrawer(null)} width={screens.sm ? 480 : '100%'}>
        {taskDrawer && <Space direction="vertical" size="middle" style={{ width: '100%' }}><Title level={4}>{taskDrawer.title}</Title><Paragraph>{taskDrawer.description || '暂无任务说明。'}</Paragraph><Descriptions bordered size="small" column={1}><Descriptions.Item label="状态"><Tag>{taskStatusLabels[taskDrawer.status] || taskDrawer.status}</Tag></Descriptions.Item><Descriptions.Item label="优先级"><Tag>{priorityLabels[taskDrawer.priority] || taskDrawer.priority}</Tag></Descriptions.Item><Descriptions.Item label="截止日期">{taskDrawer.due_date || '未设置'}</Descriptions.Item></Descriptions><Button type="primary" icon={<AppstoreOutlined />} onClick={() => { setNav('work'); setTaskDrawer(null) }}>在工作模式中打开</Button></Space>}
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
  return <ConfigProvider locale={zhCN} theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#4f5fd5', colorInfo: '#4f5fd5', colorSuccess: '#1f9d72', colorWarning: '#d97706', colorError: '#d14343', colorText: '#172033', colorTextSecondary: '#667085', colorBorder: '#e0e6ef', colorBgLayout: '#f5f7fb', borderRadius: 10, controlHeight: 36, fontFamily: '"PingFang SC", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif' }, components: { Button: { primaryShadow: '0 5px 14px rgba(79, 95, 213, .18)' }, Card: { headerFontSize: 15 }, Menu: { darkItemBg: '#111827', darkItemSelectedBg: '#4f5fd5' } } }}><AntApp><App /></AntApp></ConfigProvider>
}
