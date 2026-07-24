import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  App as AntApp,
  Avatar,
  Badge,
  Button,
  Card,
  ConfigProvider,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Flex,
  Form,
  Grid,
  Input,
  Layout,
  List,
  Menu,
  Modal,
  Popconfirm,
  Progress,
  Select,
  Space,
  Spin,
  Statistic,
  Steps,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  theme,
} from 'antd'
import {
  AppstoreOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  FileAddOutlined,
  FolderOpenOutlined,
  LogoutOutlined,
  MenuOutlined,
  MessageOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ProjectOutlined,
  RobotOutlined,
  SendOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Bubble, Conversations, Sender, Welcome, XProvider } from '@ant-design/x'
import {
  apiFetch,
  applyAuthSession,
  clearAuthSession,
  downloadAttachment,
  getAccessToken,
  getWorkspaceId,
  refreshAccessToken,
  setWorkspaceId,
  streamSSE,
  uploadAttachment,
} from './api.js'

const { Header, Sider, Content } = Layout
const { Title, Text, Paragraph } = Typography
const columns = [
  { key: 'backlog', title: 'Backlog', color: '#8c8c8c' },
  { key: 'todo', title: 'To do', color: '#1677ff' },
  { key: 'in_progress', title: 'In progress', color: '#fa8c16' },
  { key: 'review', title: 'Review', color: '#722ed1' },
  { key: 'done', title: 'Done', color: '#52c41a' },
]

const emptyTask = { title: '', description: '', priority: 'medium', status: 'todo', labels: [] }

function readableError(error) {
  return error?.message || 'Something went wrong. Please retry.'
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
      message.success(mode === 'login' ? 'Welcome back' : 'Workspace created')
      onAuthenticated(payload)
    } catch (error) {
      message.error(readableError(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <Card className="auth-card" bordered={false}>
        <Space direction="vertical" size={4} className="auth-heading">
          <Avatar size={52} className="brand-avatar" icon={<RobotOutlined />} />
          <Title level={2}>futureAgent</Title>
          <Text type="secondary">Team AI workspace with reviewable work plans</Text>
        </Space>
        <div className="auth-tabs">
          <Button type={mode === 'login' ? 'primary' : 'text'} onClick={() => { setMode('login'); form.resetFields() }}>Sign in</Button>
          <Button type={mode === 'register' ? 'primary' : 'text'} onClick={() => { setMode('register'); form.resetFields() }}>Create workspace</Button>
        </div>
        <Form form={form} layout="vertical" onFinish={submit} requiredMark={false}>
          {mode === 'register' && (
            <>
              <Form.Item name="display_name" label="Your name" rules={[{ required: true, min: 2 }]}>
                <Input autoComplete="name" placeholder="How should the team call you?" />
              </Form.Item>
              <Form.Item name="workspace_name" label="Workspace name" rules={[{ required: true, min: 2 }]}>
                <Input placeholder="For example: Product Studio" />
              </Form.Item>
            </>
          )}
          <Form.Item name="email" label="Work email" rules={[{ required: true, type: 'email' }]}>
            <Input autoComplete="email" placeholder="name@company.com" />
          </Form.Item>
          <Form.Item name="password" label="Password" rules={[{ required: true, min: 10, message: 'Use at least 10 characters' }]}>
            <Input.Password autoComplete={mode === 'login' ? 'current-password' : 'new-password'} placeholder="At least 10 characters" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block size="large" loading={loading}>
            {mode === 'login' ? 'Sign in' : 'Create secure workspace'}
          </Button>
        </Form>
        <Paragraph type="secondary" className="auth-footnote">
          Your browser keeps only a short-lived access token. The refresh session is an HttpOnly cookie managed by the API.
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
        <Dropdown menu={{ items: columns.filter((item) => item.key !== task.status).map((item) => ({ key: item.key, label: `Move to ${item.title}` })), onClick: ({ key }) => onMove(task, key) }} trigger={['click']}>
          <Button size="small" type="text" onClick={(event) => event.stopPropagation()}><SettingOutlined /></Button>
        </Dropdown>
      </Flex>
      {task.description && <Paragraph ellipsis={{ rows: 2 }} type="secondary" className="task-description">{task.description}</Paragraph>}
      <Flex justify="space-between" align="center" className="task-meta">
        <Space size={4}>{(task.labels || []).slice(0, 2).map((label) => <Tag key={label} color="blue">{label}</Tag>)}</Space>
        <Space size={4}>
          <Tag color={task.priority === 'urgent' ? 'red' : task.priority === 'high' ? 'orange' : 'default'}>{task.priority}</Tag>
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
      message.success('Task added to the board')
      setTaskOpen(false)
      form.resetFields()
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const saveProject = async (values) => {
    try {
      await apiFetch('/api/v1/projects', { method: 'POST', body: JSON.stringify({ ...values, color: '#5B5BD6' }) })
      message.success('Project created')
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
        <div><Title level={2}>Project board</Title><Text type="secondary">Turn goals into visible, owned work. Every change is saved to the workspace audit trail.</Text></div>
        <Space>
          {canWrite && <Button icon={<FolderOpenOutlined />} onClick={() => setProjectOpen(true)}>New project</Button>}
          {canWrite && <Button type="primary" icon={<PlusOutlined />} disabled={!projectId} onClick={() => setTaskOpen(true)}>New task</Button>}
        </Space>
      </Flex>
      {projects.length ? <Flex wrap="wrap" gap={10} className="board-filters"><Select value={projectId} onChange={setProjectId} className="project-selector" options={projects.map((item) => ({ value: item.id, label: item.name }))} /><Input.Search allowClear placeholder="Search title, context, or labels" value={query} onChange={(event) => setQuery(event.target.value)} style={{ width: 280, maxWidth: '100%' }} /><Select value={statusFilter} onChange={setStatusFilter} style={{ width: 150 }} options={[{ value: 'all', label: 'All statuses' }, ...columns.map((item) => ({ value: item.key, label: item.title }))]} /></Flex> : <Empty description="Create a project to start planning work" />}
      {projectId && <div className="kanban-grid">{columns.map((column) => (
        <section key={column.key} className="kanban-column">
          <Flex justify="space-between" align="center"><Text strong>{column.title}</Text><Badge color={column.color} count={projectTasks.filter((task) => task.status === column.key).length} /></Flex>
          <div className="task-stack">
            {projectTasks.filter((task) => task.status === column.key).map((task) => <TaskCard key={task.id} task={task} members={members} onSelect={openTask} onMove={moveTask} />)}
            {!projectTasks.some((task) => task.status === column.key) && <Text type="secondary" className="empty-column">No tasks</Text>}
          </div>
        </section>
      ))}</div>}

      <Modal title="Create task" open={taskOpen} onCancel={() => setTaskOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" initialValues={emptyTask} onFinish={saveTask}>
          <Form.Item name="title" label="Task title" rules={[{ required: true, min: 2 }]}><Input /></Form.Item>
          <Form.Item name="description" label="Context"><Input.TextArea rows={4} /></Form.Item>
          <Flex gap={12}><Form.Item name="priority" label="Priority" className="flex-field"><Select options={['low', 'medium', 'high', 'urgent'].map((value) => ({ value }))} /></Form.Item><Form.Item name="assignee_id" label="Assignee" className="flex-field"><Select allowClear options={members.map((item) => ({ value: item.user.id, label: item.user.display_name }))} /></Form.Item></Flex>
          <Form.Item name="labels" label="Labels"><Input placeholder="design, launch" /></Form.Item>
        </Form>
      </Modal>
      <Modal title="Create project" open={projectOpen} onCancel={() => setProjectOpen(false)} onOk={() => projectForm.submit()} destroyOnClose>
        <Form form={projectForm} layout="vertical" onFinish={saveProject}><Form.Item name="name" label="Project name" rules={[{ required: true, min: 2 }]}><Input /></Form.Item><Form.Item name="description" label="Description"><Input.TextArea rows={4} /></Form.Item></Form>
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
  const activityLabels = {
    'task.created': 'Task created',
    'task.updated': 'Task updated',
    'work_plan.saved': 'Work plan saved',
    'work_plan.approved': 'Work plan approved',
    'work_plan.step_updated': 'Execution step updated',
    'attachment.uploaded': 'File attached',
  }
  const loadResults = useCallback(async () => {
    if (!taskId) { setAttachments([]); setEvents([]); return }
    setLoading(true)
    try {
      const [files, activity] = await Promise.all([
        apiFetch(`/api/v1/attachments?task_id=${taskId}`),
        apiFetch(`/api/v1/tasks/${taskId}/activity`),
      ])
      setAttachments(files.attachments)
      setEvents(activity.events)
    } catch (error) { message.error(readableError(error)) } finally { setLoading(false) }
  }, [message, taskId])
  useEffect(() => { setPreview(null); loadResults() }, [loadResults, refreshKey])
  const attach = async ({ file, onSuccess, onError }) => {
    try {
      await uploadAttachment(file, { task_id: taskId })
      await loadResults()
      message.success('File attached to this work item')
      onSuccess?.('ok')
    } catch (error) { message.error(readableError(error)); onError?.(error) }
  }
  const showPreview = async (attachment) => {
    try { setPreview(await apiFetch(attachment.preview_url)) } catch (error) { message.error(readableError(error)) }
  }
  const download = async (attachment) => {
    try { await downloadAttachment(attachment); message.success('Download started') } catch (error) { message.error(readableError(error)) }
  }
  const files = <List loading={loading} size="small" locale={{ emptyText: 'No task files yet' }} dataSource={attachments} renderItem={(attachment) => <List.Item actions={[attachment.preview_available ? <Button key="preview" type="link" size="small" onClick={() => showPreview(attachment)}>Preview</Button> : null, <Button key="download" type="link" size="small" onClick={() => download(attachment)}>Download</Button>].filter(Boolean)}><List.Item.Meta title={attachment.original_name} description={`${Math.ceil(attachment.size_bytes / 1024)} KB · ${new Date(attachment.created_at).toLocaleString()}`} /></List.Item>} />
  const activity = <List loading={loading} size="small" locale={{ emptyText: 'No task activity yet' }} dataSource={events} renderItem={(event) => {
    const actor = members.find((member) => member.user.id === event.actor_id)?.user.display_name || 'Workspace member'
    const status = event.metadata?.status ? ` · ${event.metadata.status}` : ''
    return <List.Item><List.Item.Meta title={activityLabels[event.action] || event.action} description={`${actor} · ${new Date(event.created_at).toLocaleString()}${status}`} /></List.Item>
  }} />
  return <Card className="work-results" title="Results & files" extra={canWrite && <Upload showUploadList={false} customRequest={attach}><Button size="small" icon={<PaperClipOutlined />}>Add context / deliverable</Button></Upload>}>
    <Tabs size="small" items={[{ key: 'files', label: `Files (${attachments.length})`, children: files }, { key: 'preview', label: 'Preview', children: preview ? <Space direction="vertical" size="small" style={{ width: '100%' }}><Text strong>{preview.attachment.original_name}</Text>{preview.preview_available ? <pre className="attachment-preview">{preview.text}</pre> : <Text type="secondary">{preview.message}</Text>}</Space> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="Select a text file to preview" /> }, { key: 'activity', label: `Activity (${events.length})`, children: activity }]} />
  </Card>
}

function WorkModePage({ tasks, members, workspaceRole, profile, onRefresh }) {
  const { message } = AntApp.useApp()
  const [taskId, setTaskId] = useState(tasks[0]?.id || '')
  const [plan, setPlan] = useState(null)
  const [loading, setLoading] = useState(false)
  const [evidenceStep, setEvidenceStep] = useState(null)
  const [form] = Form.useForm()
  const [evidenceForm] = Form.useForm()
  const selectedTask = tasks.find((item) => item.id === taskId)
  const canWrite = workspaceRole !== 'viewer'
  const canApprove = ['owner', 'admin'].includes(workspaceRole)
  const planTemplates = [
    {
      value: 'delivery',
      label: 'Product delivery',
      objective: 'Deliver a verified change with a clear owner, acceptance criteria, and release evidence.',
      steps: [
        { title: 'Clarify scope and acceptance criteria', instructions: 'Record the customer outcome, non-goals, owner, and measurable acceptance criteria.' },
        { title: 'Build and verify the change', instructions: 'Implement the agreed scope and attach test or review evidence to the step result.' },
        { title: 'Release and communicate', instructions: 'Record release status, rollback considerations, and the stakeholder update.' },
      ],
    },
    {
      value: 'investigation',
      label: 'Investigation',
      objective: 'Resolve an open question using traceable evidence and a documented recommendation.',
      steps: [
        { title: 'Frame the question', instructions: 'Capture the decision to make, the assumptions to validate, and the responsible owner.' },
        { title: 'Gather and compare evidence', instructions: 'Link sources, experiments, customer feedback, or data that support the conclusion.' },
        { title: 'Publish recommendation', instructions: 'Record the recommendation, trade-offs, and the next decision or execution task.' },
      ],
    },
    {
      value: 'incident',
      label: 'Incident response',
      objective: 'Restore service safely, preserve the incident record, and prevent recurrence.',
      steps: [
        { title: 'Assess impact and assign incident lead', instructions: 'Record affected users, severity, communication owner, and current hypothesis.' },
        { title: 'Mitigate and verify recovery', instructions: 'Record the mitigation, validation signals, and any remaining risk.' },
        { title: 'Complete follow-up actions', instructions: 'Capture root-cause work, prevention tasks, owners, and due dates.' },
      ],
    },
  ]

  useEffect(() => { if (!tasks.some((item) => item.id === taskId)) setTaskId(tasks[0]?.id || '') }, [tasks, taskId])
  const loadPlan = useCallback(async () => {
    if (!taskId) { setPlan(null); return }
    setLoading(true)
    try {
      const data = await apiFetch(`/api/v1/tasks/${taskId}/plan`)
      setPlan(data.plan)
      form.setFieldsValue({ objective: data.plan?.objective || '', steps: data.plan?.steps?.length ? data.plan.steps : [{ title: '', instructions: '', assignee_id: undefined }] })
    } catch (error) { message.error(readableError(error)) } finally { setLoading(false) }
  }, [form, message, taskId])
  useEffect(() => { loadPlan() }, [loadPlan])
  const savePlan = async (values) => {
    try {
      const data = await apiFetch(`/api/v1/tasks/${taskId}/plan`, { method: 'PUT', body: JSON.stringify(values) })
      setPlan(data.plan)
      message.success('Work plan saved as draft')
      onRefresh()
    } catch (error) { message.error(readableError(error)) }
  }
  const approve = async () => {
    try { const data = await apiFetch(`/api/v1/tasks/${taskId}/plan/approve`, { method: 'POST' }); setPlan(data.plan); message.success('Plan approved for execution') } catch (error) { message.error(readableError(error)) }
  }
  const updateStep = async (step, patch) => {
    try {
      const data = await apiFetch(`/api/v1/tasks/${taskId}/plan/steps/${step.id}`, { method: 'PATCH', body: JSON.stringify(patch) })
      setPlan(data.plan)
      onRefresh()
      return data.plan
    } catch (error) { message.error(readableError(error)) }
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
      message.success('Step evidence saved to the workspace audit trail')
    }
  }
  const progress = plan?.steps?.length ? Math.round((plan.steps.filter((item) => item.status === 'done').length / plan.steps.length) * 100) : 0
  return (
    <div className="page-shell work-mode">
      <Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading"><div><Title level={2}>Work mode</Title><Text type="secondary">Draft an execution plan, get approval, then make each step accountable and traceable.</Text></div><Badge status={plan?.status === 'approved' || plan?.status === 'in_progress' ? 'processing' : plan?.status === 'completed' ? 'success' : 'default'} text={plan ? plan.status.replace('_', ' ') : 'no plan'} /></Flex>
      {!tasks.length ? <Empty description="Create a task in the project board first" /> : <>
        <Select value={taskId} onChange={setTaskId} className="project-selector" options={tasks.map((task) => ({ value: task.id, label: task.title }))} />
        <Card className="work-context" size="small"><Descriptions size="small" column={{ xs: 1, md: 3 }}><Descriptions.Item label="Task">{selectedTask?.title}</Descriptions.Item><Descriptions.Item label="Owner">{members.find((item) => item.user.id === selectedTask?.reporter_id)?.user.display_name || '-'}</Descriptions.Item><Descriptions.Item label="Status"><Tag>{selectedTask?.status}</Tag></Descriptions.Item></Descriptions></Card>
        <Spin spinning={loading}>
          {(plan?.status === 'approved' || plan?.status === 'in_progress' || plan?.status === 'completed') ? (
            <Card className="plan-execution" title="Approved work plan" extra={<Tag color={plan.status === 'completed' ? 'success' : 'processing'}>{plan.status}</Tag>}>
              <Paragraph>{plan.objective || 'No objective recorded.'}</Paragraph>
              <Progress percent={progress} status={progress === 100 ? 'success' : 'active'} />
              <Steps direction="vertical" size="small" current={Math.min(plan.steps.findIndex((step) => step.status !== 'done'), Math.max(plan.steps.length - 1, 0))} items={plan.steps.map((step) => ({ title: <Flex justify="space-between" gap={8}><span>{step.title}</span><Select value={step.status} size="small" style={{ width: 124 }} disabled={!canUpdateStep(step)} onChange={(value) => updateStep(step, { status: value })} options={['pending', 'running', 'blocked', 'done'].map((value) => ({ value }))} /></Flex>, description: <Space direction="vertical" size={2}><Text type="secondary">{step.instructions || 'No additional instructions.'}</Text><Text type="secondary">Assignee: {members.find((item) => item.user.id === step.assignee_id)?.user.display_name || 'Unassigned'}</Text>{step.output_summary && <Text>Evidence: {step.output_summary}</Text>}{canUpdateStep(step) && <Button type="link" size="small" style={{ paddingInline: 0, width: 'fit-content' }} onClick={() => openEvidence(step)}>Record result / evidence</Button>}</Space>, status: step.status === 'done' ? 'finish' : step.status === 'blocked' ? 'error' : step.status === 'running' ? 'process' : 'wait' }))} />
            </Card>
          ) : (
            <Card title="Plan before execution" extra={plan && <Tag color="gold">Draft</Tag>}>
              <Form form={form} layout="vertical" onFinish={savePlan}>
                <Form.Item label="Start from a reusable flow"><Select placeholder="Choose a delivery, investigation, or incident flow" onChange={applyTemplate} disabled={!canWrite} options={planTemplates.map((item) => ({ value: item.value, label: item.label }))} /></Form.Item>
                <Form.Item name="objective" label="Objective" rules={[{ required: true, min: 4 }]}><Input.TextArea rows={3} placeholder="What outcome will this work deliver?" disabled={!canWrite} /></Form.Item>
                <Form.List name="steps">{(fields, { add, remove }) => <div className="plan-form-list"><Flex justify="space-between" align="center"><Text strong>Execution steps</Text>{canWrite && <Button size="small" icon={<PlusOutlined />} onClick={() => add({ title: '', instructions: '' })}>Add step</Button>}</Flex>{fields.map((field, index) => <Card size="small" key={field.key} className="plan-step-editor"><Flex gap={10} align="start"><Tag>{index + 1}</Tag><div className="plan-step-fields"><Form.Item name={[field.name, 'id']} hidden><Input /></Form.Item><Form.Item name={[field.name, 'title']} rules={[{ required: true, min: 2 }]}><Input placeholder="Step title" disabled={!canWrite} /></Form.Item><Form.Item name={[field.name, 'instructions']}><Input.TextArea rows={2} placeholder="Expected work, inputs and acceptance evidence" disabled={!canWrite} /></Form.Item><Form.Item name={[field.name, 'assignee_id']}><Select allowClear placeholder="Assignee" disabled={!canWrite} options={members.map((item) => ({ value: item.user.id, label: item.user.display_name }))} /></Form.Item></div>{canWrite && <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(field.name)} />}</Flex></Card>)}</div>}</Form.List>
                <Flex justify="end" gap={8}><Button htmlType="submit" disabled={!canWrite}>Save draft</Button>{canApprove && plan && <Button type="primary" icon={<CheckCircleOutlined />} onClick={approve}>Approve execution</Button>}</Flex>
              </Form>
            </Card>
          )}
        </Spin>
        <TaskResultsPanel taskId={taskId} canWrite={canWrite} members={members} refreshKey={plan?.updated_at || ''} />
      </>}
      <Modal title="Record step result" open={Boolean(evidenceStep)} onCancel={() => setEvidenceStep(null)} onOk={() => evidenceForm.submit()} destroyOnClose>
        <Form form={evidenceForm} layout="vertical" onFinish={saveEvidence}><Form.Item name="output_summary" label="Evidence, decision, or handoff" rules={[{ required: true, min: 2 }]}><Input.TextArea rows={5} placeholder="What was done, what evidence supports it, and what should happen next?" /></Form.Item></Form>
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
    try { await apiFetch(`/api/v1/workspaces/${workspace.id}/members`, { method: 'POST', body: JSON.stringify(values) }); message.success('Member added'); setOpen(false); form.resetFields(); onRefresh() } catch (error) { message.error(readableError(error)) }
  }
  const removeMember = async (member) => {
    try { await apiFetch(`/api/v1/workspaces/${workspace.id}/members/${member.id}`, { method: 'DELETE' }); message.success('Member removed'); onRefresh() } catch (error) { message.error(readableError(error)) }
  }
  return <div className="page-shell"><Flex justify="space-between" align="center" wrap="wrap" gap={12} className="page-heading"><div><Title level={2}>Team</Title><Text type="secondary">People are assigned at workspace level. Managers can add registered users and set the least privilege role.</Text></div>{manager && <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>Add member</Button>}</Flex><Card><List dataSource={members} renderItem={(member) => <List.Item actions={manager && member.role !== 'owner' ? [<Popconfirm key="remove" title="Remove this member?" onConfirm={() => removeMember(member)}><Button danger type="link">Remove</Button></Popconfirm>] : []}><List.Item.Meta avatar={<Avatar icon={<UserOutlined />} />} title={<Space><Text strong>{member.user.display_name}</Text>{member.user.is_platform_admin && <Tag color="purple">Platform admin</Tag>}</Space>} description={member.user.email} /><Tag color={member.role === 'owner' ? 'gold' : member.role === 'admin' ? 'blue' : 'default'}>{member.role}</Tag></List.Item>} /></Card><Modal title="Add registered member" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose><Form form={form} layout="vertical" onFinish={addMember} initialValues={{ role: 'member' }}><Form.Item name="email" label="Email" rules={[{ required: true, type: 'email' }]}><Input placeholder="They must have registered first" /></Form.Item><Form.Item name="role" label="Role"><Select options={['admin', 'member', 'viewer'].map((value) => ({ value }))} /></Form.Item></Form></Modal></div>
}

function ChatPage({ conversations, activeConversation, messages, models, skills, onNewConversation, onSelectConversation, onRefresh, workspaceRole }) {
  const { message } = AntApp.useApp()
  const [model, setModel] = useState('')
  const [skill, setSkill] = useState('')
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveMessages, setLiveMessages] = useState([])
  const abortRef = useRef(null)
  const canWrite = workspaceRole !== 'viewer'
  useEffect(() => { if (!model && models.length) setModel(models[0].id || models[0]); if (!skill && skills.length) setSkill(skills[0].name) }, [model, models, skill, skills])
  const bubbleItems = useMemo(() => [...messages, ...liveMessages].map((item) => ({ key: item.id, role: item.role, content: item.content, loading: item.loading, className: item.error ? 'error-bubble' : undefined })), [liveMessages, messages])
  const send = async (value) => {
    const query = value.trim()
    if (!query || streaming || !activeConversation || !canWrite) return
    const userMessage = { id: `local-user-${Date.now()}`, role: 'user', content: query }
    const assistantId = `local-assistant-${Date.now()}`
    setLiveMessages([userMessage, { id: assistantId, role: 'assistant', content: '', loading: true }])
    setInput(''); setStreaming(true)
    const controller = new AbortController(); abortRef.current = controller
    try {
      await streamSSE('/api/v1/chat/agent', { query, model_id: model, skill_name: skill || 'default', conversation_id: activeConversation.id, mcp_servers: [] }, { signal: controller.signal, onEvent: (event, data) => {
        if (event === 'error') { let detail = data; try { detail = JSON.parse(data).detail || data } catch { /* Plain SSE error. */ } throw new Error(detail) }
        if (event !== 'token') return
        setLiveMessages((previous) => previous.map((item) => item.id === assistantId ? { ...item, content: item.content + data, loading: false } : item))
      } })
      setLiveMessages([]); onRefresh()
    } catch (error) {
      setLiveMessages((previous) => previous.map((item) => item.id === assistantId ? { ...item, content: item.content || readableError(error), loading: false, error: true } : item))
    } finally { abortRef.current = null; setStreaming(false) }
  }
  const attach = async ({ file, onSuccess, onError }) => {
    try { await uploadAttachment(file, { conversation_id: activeConversation?.id }); message.success('Attachment saved to the conversation'); onSuccess?.('ok') } catch (error) { message.error(readableError(error)); onError?.(error) }
  }
  return <div className="chat-page"><aside className="conversation-pane"><Button type="primary" icon={<PlusOutlined />} block onClick={onNewConversation} disabled={!canWrite}>New conversation</Button><Conversations items={conversations.map((item) => ({ key: item.id, label: item.title, timestamp: item.updated_at, icon: <MessageOutlined /> }))} activeKey={activeConversation?.id} onActiveChange={onSelectConversation} /></aside><section className="chat-stage"><header className="chat-title"><div><Title level={4}>{activeConversation?.title || 'Select a conversation'}</Title><Text type="secondary">Persistent workspace conversation</Text></div><Space><Select size="small" value={model || undefined} onChange={setModel} options={models.map((item) => ({ value: item.id || item, label: `${item.id || item}${item.ready === false ? ' (not ready)' : ''}` }))} /><Select size="small" value={skill || undefined} onChange={setSkill} options={skills.map((item) => ({ value: item.name, label: item.name }))} /></Space></header><div className="messages">{bubbleItems.length ? <Bubble.List autoScroll items={bubbleItems} roles={{ assistant: { placement: 'start', avatar: { icon: <RobotOutlined />, className: 'assistant-avatar' }, variant: 'borderless', shape: 'corner' }, user: { placement: 'end', avatar: { icon: <UserOutlined /> }, variant: 'filled', shape: 'corner' } }} /> : <Welcome variant="borderless" icon={<Avatar size={52} icon={<RobotOutlined />} className="brand-avatar" />} title="What will the team move forward today?" description="Use the project board for accountable work, then use Work mode to draft and approve an execution plan." />}</div><div className="chat-sender"><Flex justify="space-between" align="center"><Text type="secondary">Conversations and attachments are stored in your workspace.</Text><Upload showUploadList={false} customRequest={attach} disabled={!activeConversation || !canWrite}><Button size="small" icon={<PaperClipOutlined />} disabled={!activeConversation || !canWrite}>Attach</Button></Upload></Flex><Sender value={input} onChange={setInput} onSubmit={send} onCancel={() => abortRef.current?.abort()} loading={streaming} disabled={!activeConversation || !model || !skill || !canWrite} placeholder={canWrite ? 'Ask the agent to analyse, draft or execute work…' : 'Viewers cannot start AI work'} autoSize={{ minRows: 1, maxRows: 6 }} /></div></section></div>
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
  const [nav, setNav] = useState('chat')
  const [loading, setLoading] = useState(true)
  const [taskDrawer, setTaskDrawer] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)
  const workspace = workspaces.find((item) => item.id === workspaceId) || workspaces[0]
  const activeConversation = conversations.find((item) => item.id === activeConversationId)

  const loadWorkspace = useCallback(async () => {
    if (!workspaceId) return
    setLoading(true)
    try {
      const [memberData, projectData, taskData, conversationData, modelData, skillData] = await Promise.all([
        apiFetch(`/api/v1/workspaces/${workspaceId}/members`, { workspaceId }),
        apiFetch('/api/v1/projects', { workspaceId }),
        apiFetch('/api/v1/tasks', { workspaceId }),
        apiFetch('/api/v1/conversations', { workspaceId }),
        apiFetch('/api/v1/models', { workspaceId }),
        apiFetch('/api/v1/skills', { workspaceId }),
      ])
      setMembers(memberData.members || []); setProjects(projectData.projects || []); setTasks(taskData.tasks || []); setConversations(conversationData.conversations || []); setModels(modelData.details || []); setSkills(skillData.skills || [])
      setActiveConversationId((current) => current && conversationData.conversations?.some((item) => item.id === current) ? current : conversationData.conversations?.[0]?.id || '')
    } catch (error) { message.error(readableError(error)) } finally { setLoading(false) }
  }, [message, workspaceId])

  useEffect(() => { setWorkspaceId(workspaceId); loadWorkspace() }, [loadWorkspace, workspaceId])
  useEffect(() => {
    if (!activeConversationId || !workspaceId) { setMessages([]); return }
    apiFetch(`/api/v1/conversations/${activeConversationId}/messages`, { workspaceId }).then((data) => setMessages(data.messages || [])).catch((error) => message.error(readableError(error)))
  }, [activeConversationId, message, workspaceId, conversations.length])

  const refreshEverything = async () => {
    try { const me = await apiFetch('/api/v1/auth/me', { workspaceId: '' }); setProfile(me.user); setWorkspaces(me.workspaces || []); await loadWorkspace() } catch (error) { message.error(readableError(error)) }
  }
  const newConversation = async () => {
    try { const data = await apiFetch('/api/v1/conversations', { method: 'POST', body: JSON.stringify({ title: 'New conversation' }), workspaceId }); setConversations((previous) => [data.conversation, ...previous]); setActiveConversationId(data.conversation.id); setNav('chat') } catch (error) { message.error(readableError(error)) }
  }
  const moveTask = async () => { await loadWorkspace() }
  const sideMenu = <Menu mode="inline" selectedKeys={[nav]} onClick={({ key }) => { setNav(key); setMobileNav(false) }} items={[{ key: 'chat', icon: <MessageOutlined />, label: 'AI workspace' }, { key: 'board', icon: <ProjectOutlined />, label: 'Project board' }, { key: 'work', icon: <AppstoreOutlined />, label: 'Work mode' }, { key: 'team', icon: <TeamOutlined />, label: 'Team' }]} />
  const layoutSider = <><div className="workspace-brand"><Avatar icon={<RobotOutlined />} className="brand-avatar" /><div><strong>futureAgent</strong><span>Team AI workspace</span></div></div><Select value={workspaceId || undefined} onChange={setActiveWorkspaceId} className="workspace-select" options={workspaces.map((item) => ({ value: item.id, label: item.name }))} />{sideMenu}<div className="sider-bottom"><Tag color={workspace?.role === 'owner' ? 'gold' : 'blue'}>{workspace?.role || 'member'}</Tag></div></>
  const content = nav === 'chat' ? <ChatPage conversations={conversations} activeConversation={activeConversation} messages={messages} models={models} skills={skills} onNewConversation={newConversation} onSelectConversation={setActiveConversationId} onRefresh={loadWorkspace} workspaceRole={workspace?.role} /> : nav === 'board' ? <BoardPage projects={projects} tasks={tasks} members={members} onRefresh={moveTask} openTask={(task) => setTaskDrawer(task)} workspaceRole={workspace?.role} /> : nav === 'work' ? <WorkModePage tasks={tasks} members={members} workspaceRole={workspace?.role} profile={profile} onRefresh={loadWorkspace} /> : <TeamPage workspace={workspace} members={members} workspaceRole={workspace?.role} onRefresh={loadWorkspace} />
  return <Layout className="workspace-layout">{screens.lg ? <Sider width={258} theme="light" className="workspace-sider">{layoutSider}</Sider> : <Drawer placement="left" open={mobileNav} onClose={() => setMobileNav(false)} width={280} styles={{ body: { padding: 0 } }}>{layoutSider}</Drawer>}<Layout><Header className="workspace-header"><Space>{!screens.lg && <Button type="text" icon={<MenuOutlined />} onClick={() => setMobileNav(true)} />}<Badge status="success" text="Workspace data protected" /></Space><Dropdown menu={{ items: [{ key: 'profile', label: profile?.email, disabled: true }, { type: 'divider' }, { key: 'logout', icon: <LogoutOutlined />, label: 'Sign out', onClick: onLogout }] }}><Button type="text"><Space><Avatar size="small" icon={<UserOutlined />} />{profile?.display_name}</Space></Button></Dropdown></Header><Content className="workspace-content">{loading ? <div className="loading-page"><Spin size="large" /></div> : content}</Content></Layout><Drawer title="Task details" open={Boolean(taskDrawer)} onClose={() => setTaskDrawer(null)} width={460}>{taskDrawer && <Space direction="vertical" size="middle" style={{ width: '100%' }}><Title level={4}>{taskDrawer.title}</Title><Paragraph>{taskDrawer.description || 'No description yet.'}</Paragraph><Descriptions bordered size="small" column={1}><Descriptions.Item label="Status"><Tag>{taskDrawer.status}</Tag></Descriptions.Item><Descriptions.Item label="Priority"><Tag>{taskDrawer.priority}</Tag></Descriptions.Item><Descriptions.Item label="Due date">{taskDrawer.due_date || '-'}</Descriptions.Item></Descriptions><Button type="primary" icon={<AppstoreOutlined />} onClick={() => { setNav('work'); setTaskDrawer(null) }}>Open in Work mode</Button></Space>}</Drawer></Layout>
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
  const logout = async () => { try { await apiFetch('/api/v1/auth/logout', { method: 'POST', workspaceId: '' }) } catch { /* Clearing local state still signs this browser out. */ } clearAuthSession(); setSession(null); message.success('Signed out') }
  if (restoring) return <div className="loading-page"><Spin size="large" /></div>
  return session ? <WorkspaceApp session={session} onLogout={logout} /> : <AuthScreen onAuthenticated={(payload) => setSession({ user: payload.user, workspaces: payload.workspaces || [] })} />
}

export function Root() {
  return <ConfigProvider theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#5b5bd6', borderRadius: 12, colorBgLayout: '#f5f6fa', fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif' } }}><AntApp><XProvider><App /></XProvider></AntApp></ConfigProvider>
}
