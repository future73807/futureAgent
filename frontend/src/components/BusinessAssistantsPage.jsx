import React, { useCallback, useEffect, useMemo, useState } from 'react'
import AntApp from 'antd/es/app'
import Alert from 'antd/es/alert'
import Avatar from 'antd/es/avatar'
import Badge from 'antd/es/badge'
import Button from 'antd/es/button'
import Card from 'antd/es/card'
import Descriptions from 'antd/es/descriptions'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Form from 'antd/es/form'
import Input from 'antd/es/input'
import List from 'antd/es/list'
import Modal from 'antd/es/modal'
import Progress from 'antd/es/progress'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Statistic from 'antd/es/statistic'
import Tag from 'antd/es/tag'
import Tabs from 'antd/es/tabs'
import Typography from 'antd/es/typography'
import { AppstoreOutlined, CheckCircleOutlined, ClockCircleOutlined, MessageOutlined, PlusOutlined, ProjectOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import Sender from '@ant-design/x/es/sender'
import Welcome from '@ant-design/x/es/welcome'
import XProvider from '@ant-design/x/es/x-provider'
import zhCN from 'antd/es/locale/zh_CN'
import { apiFetch } from '../api.js'

const { Title, Text, Paragraph } = Typography

const assistantCatalog = [
  {
    key: 'boss',
    aliases: ['boss', 'owner', '老板'],
    title: '老板智能体',
    shortTitle: '经营决策',
    summary: '汇总已授权的经营、生产、预警和待办信息，辅助老板判断与下达任务。',
    isolation: '仅工作区所有者可进入私聊；服务端会再次校验身份与工作区边界。',
    audience: '仅老板',
    color: 'gold',
  },
  {
    key: 'personal',
    aliases: ['personal', 'private', '私事'],
    title: '私事员工智能体',
    shortTitle: '私密事项',
    summary: '处理老板的个人安排和私密事项，不读取或展示公司公事数据。',
    isolation: '私事会话与公事数据逻辑隔离，不向公司成员开放。',
    audience: '仅老板',
    color: 'purple',
  },
  {
    key: 'business',
    aliases: ['business', 'public', 'company', '公事'],
    title: '公事员工智能体',
    shortTitle: '协同处理',
    summary: '面向公司协作，查询已授权的 OA、小程序和生产数据，并接收问题或触发流程。',
    isolation: '公司成员仅能看到自己工作区已授权的公事数据，敏感老板私聊不会混入。',
    audience: '公司成员',
    color: 'blue',
  },
]

const sourceStatus = {
  connected: { label: '已连接', color: 'success' },
  active: { label: '运行中', color: 'processing' },
  pending: { label: '待授权', color: 'warning' },
  error: { label: '需处理', color: 'error' },
  disabled: { label: '已停用', color: 'default' },
}

const alertSeverity = {
  critical: { label: '紧急', color: 'red' },
  high: { label: '高', color: 'volcano' },
  warning: { label: '中', color: 'gold' },
  medium: { label: '中', color: 'gold' },
  low: { label: '低', color: 'blue' },
}

const taskStatus = {
  pending: { label: '待处理', color: 'default' },
  todo: { label: '待处理', color: 'default' },
  in_progress: { label: '进行中', color: 'processing' },
  blocked: { label: '受阻', color: 'error' },
  done: { label: '已完成', color: 'success' },
  completed: { label: '已完成', color: 'success' },
  cancelled: { label: '已取消', color: 'default' },
}

function pickArray(payload, keys = []) {
  if (Array.isArray(payload?.items)) return payload.items
  for (const key of keys) if (Array.isArray(payload?.[key])) return payload[key]
  return []
}

function readableError(error) {
  const text = String(error?.message || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : '请求暂未完成，请稍后重试。'
}

function apiNotAvailable(error) {
  const text = String(error?.message || '').toLowerCase()
  return /(^|\D)(404|405|501)(\D|$)|not found|not implemented|未找到|未部署|路由不存在/.test(text)
}

function formatDate(value) {
  if (!value) return '暂无时间'
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function compactText(value, fallback = '暂无说明') {
  const text = String(value || '').trim()
  return text || fallback
}

function catalogFor(assistant) {
  const type = String(assistant?.agent_type || assistant?.assistant_type || assistant?.type || assistant?.kind || assistant?.code || '').toLowerCase()
  return assistantCatalog.find((entry) => entry.aliases.some((alias) => type.includes(alias))) || assistantCatalog[2]
}

function assistantName(assistant, catalog) {
  return assistant?.name || assistant?.display_name || assistant?.title || catalog.title
}

function withCitations(content, citations) {
  const labels = (Array.isArray(citations) ? citations : []).map((item) => {
    if (typeof item === 'string') return item.trim()
    const label = String(item?.title || item?.record_title || item?.source_name || item?.source || item?.record_id || '').trim()
    const recordId = String(item?.id || '').trim()
    return label ? (recordId ? `${label}（记录 ID：${recordId}）` : label) : (recordId ? `记录 ID：${recordId}` : '')
  }).filter(Boolean).slice(0, 3)
  return labels.length ? `${content}\n\n来源：${labels.join('、')}` : content
}

function answerFrom(payload) {
  const candidate = payload?.reply ?? payload?.answer ?? payload?.content ?? payload?.assistant_message?.content ?? payload?.message?.content
  const content = typeof candidate === 'string' && candidate.trim() ? candidate.trim() : '助手已收到请求，但当前没有可展示的结果。请检查已授权数据源后重试。'
  return withCitations(content, payload?.assistant_message?.citations || payload?.citations)
}

function statusMeta(value, mapping, fallback = { label: '待确认', color: 'default' }) {
  return mapping[String(value || '').toLowerCase()] || fallback
}

function BusinessAssistantContent({ workspaceRole, members = [], currentUserId = '' }) {
  const { message } = AntApp.useApp()
  const isOwner = workspaceRole === 'owner'
  const canManage = ['owner', 'admin'].includes(workspaceRole)
  const canWrite = workspaceRole !== 'viewer'
  const assignableMembers = useMemo(() => members.map((member) => member?.user ? { id: member.user.id, name: member.user.display_name || member.user.email, role: member.role } : member).filter((member) => member?.id), [members])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [apiUnavailable, setApiUnavailable] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [dashboard, setDashboard] = useState({})
  const [assistants, setAssistants] = useState([])
  const [sources, setSources] = useState([])
  const [alerts, setAlerts] = useState([])
  const [reports, setReports] = useState([])
  const [bossTasks, setBossTasks] = useState([])
  const [selectedAssistantKey, setSelectedAssistantKey] = useState('boss')
  const [chatMessages, setChatMessages] = useState({})
  const [chatInput, setChatInput] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyNotice, setHistoryNotice] = useState('')
  const [sending, setSending] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [taskOpen, setTaskOpen] = useState(false)
  const [taskProgress, setTaskProgress] = useState(null)
  const [ingestCredential, setIngestCredential] = useState(null)
  const [sourceForm] = Form.useForm()
  const [taskForm] = Form.useForm()
  const [progressForm] = Form.useForm()

  const loadBusiness = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true)
    else setLoading(true)
    setLoadError('')
    try {
      // 先读取概览以触发服务端的工作区初始化，再并行读取各业务集合，避免新工作区首次打开时重复初始化默认助手。
      const dashboardPayload = await apiFetch('/api/v1/business/dashboard')
      const [assistantsPayload, sourcesPayload, alertsPayload, reportsPayload, tasksPayload] = await Promise.all([
        apiFetch('/api/v1/business/assistants'),
        apiFetch('/api/v1/business/data-sources'),
        apiFetch('/api/v1/business/alerts'),
        apiFetch('/api/v1/business/daily-reports'),
        apiFetch('/api/v1/business/tasks'),
      ])
      setDashboard(dashboardPayload || {})
      setAssistants(pickArray(assistantsPayload, ['assistants']))
      setSources(pickArray(sourcesPayload, ['data_sources', 'sources']))
      setAlerts(pickArray(alertsPayload, ['alerts']))
      setReports(pickArray(reportsPayload, ['daily_reports', 'reports']))
      setBossTasks(pickArray(tasksPayload, ['tasks']))
      setApiUnavailable(false)
    } catch (error) {
      if (apiNotAvailable(error)) {
        setApiUnavailable(true)
        setLoadError('经营助手服务尚未部署或当前账号没有该模块权限。页面没有展示任何模拟经营数据。')
      } else {
        setLoadError(readableError(error))
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { loadBusiness() }, [loadBusiness])
  useEffect(() => {
    if (!isOwner && selectedAssistantKey !== 'business') setSelectedAssistantKey('business')
  }, [isOwner, selectedAssistantKey])

  const assistantCards = useMemo(() => assistantCatalog.map((catalog) => {
    const record = assistants.find((item) => catalogFor(item).key === catalog.key)
    const enabled = Boolean(record?.id) && record?.enabled !== false && record?.is_enabled !== false && record?.status !== 'disabled'
    return { catalog, record, enabled }
  }), [assistants])

  const selectedCard = assistantCards.find((item) => item.catalog.key === selectedAssistantKey) || assistantCards[0]
  const selectedAssistant = selectedCard?.record
  const selectedCatalog = selectedCard?.catalog || assistantCatalog[0]
  const selectedMessages = selectedAssistant?.id ? chatMessages[selectedAssistant.id] || [] : []
  const selectedLocked = !isOwner && selectedCatalog.key !== 'business'
  const hasSelectedChat = Boolean(selectedAssistant?.id) && selectedCard?.enabled && !selectedLocked

  useEffect(() => {
    const assistantId = selectedAssistant?.id
    if (!assistantId || !selectedCard?.enabled || selectedLocked) {
      setHistoryNotice('')
      return undefined
    }
    let current = true
    setHistoryLoading(true)
    setHistoryNotice('')
    apiFetch(`/api/v1/business/assistants/${assistantId}/messages`).then((payload) => {
      if (!current) return
      const history = pickArray(payload, ['messages']).map((item, index) => ({
        key: item.id || `history-${assistantId}-${index}`,
        role: item.role === 'user' ? 'user' : 'assistant',
        content: withCitations(compactText(item.content || item.text || item.message, '（空消息）'), item.citations),
      }))
      setChatMessages((previous) => ({ ...previous, [assistantId]: history }))
    }).catch((error) => {
      if (!current) return
      setHistoryNotice(apiNotAvailable(error) ? '当前环境尚未启用历史消息接口；本次对话结果仍由服务端按权限处理。' : '暂时无法加载该助手的历史记录，请稍后重试。')
    }).finally(() => {
      if (current) setHistoryLoading(false)
    })
    return () => { current = false }
  }, [selectedAssistant?.id, selectedCard?.enabled, selectedLocked])

  const counts = {
    sources: Number(dashboard?.source_count ?? dashboard?.data_source_count ?? sources.length ?? 0),
    activeAlerts: Number(dashboard?.active_alert_count ?? dashboard?.alert_count ?? alerts.filter((item) => !['acknowledged', 'closed', 'resolved'].includes(String(item.status || '').toLowerCase())).length ?? 0),
    reports: Number(dashboard?.report_count ?? dashboard?.daily_report_count ?? reports.length ?? 0),
    tasks: Number(dashboard?.open_task_count ?? dashboard?.task_count ?? bossTasks.filter((item) => !['done', 'completed', 'closed'].includes(String(item.status || '').toLowerCase())).length ?? 0),
  }

  const selectAssistant = (card) => {
    if (!isOwner && card.catalog.key !== 'business') {
      message.warning('该助手仅向工作区所有者开放；权限由服务端再次校验。')
      return
    }
    setSelectedAssistantKey(card.catalog.key)
  }

  const sendQuestion = async (value) => {
    const query = String(value || '').trim()
    if (!query || sending || !hasSelectedChat) return
    const assistantId = selectedAssistant.id
    const userMessage = { key: `local-user-${Date.now()}`, role: 'user', content: query }
    const assistantKey = `local-assistant-${Date.now()}`
    setChatMessages((previous) => ({
      ...previous,
      [assistantId]: [...(previous[assistantId] || []), userMessage, { key: assistantKey, role: 'assistant', content: '', loading: true }],
    }))
    setChatInput('')
    setSending(true)
    try {
      const payload = await apiFetch(`/api/v1/business/assistants/${assistantId}/chat`, { method: 'POST', body: JSON.stringify({ message: query }) })
      setChatMessages((previous) => ({
        ...previous,
        [assistantId]: (previous[assistantId] || []).map((item) => item.key === assistantKey ? { ...item, content: answerFrom(payload), loading: false } : item),
      }))
    } catch (error) {
      const fallback = apiNotAvailable(error) ? '对话服务尚未部署，未发送或保存本次内容。' : readableError(error)
      setChatMessages((previous) => ({
        ...previous,
        [assistantId]: (previous[assistantId] || []).map((item) => item.key === assistantKey ? { ...item, content: fallback, loading: false, error: true } : item),
      }))
      message.warning(fallback)
    } finally {
      setSending(false)
    }
  }

  const createSource = async (values) => {
    try {
      const payload = await apiFetch('/api/v1/business/data-sources', {
        method: 'POST',
        body: JSON.stringify({
          name: values.name,
          source_type: values.source_type,
          connection_mode: values.connection_mode,
          access_scope: values.access_scope,
        }),
      })
      message.success('数据源已登记。请在管理端完成接口授权后再接入数据。')
      setSourceOpen(false)
      sourceForm.resetFields()
      const ingestToken = payload?.ingest_token || payload?.token
      if (ingestToken) setIngestCredential({
        name: values.name,
        url: payload?.ingest_url || payload?.source?.ingest_url || '',
        token: ingestToken,
      })
      loadBusiness({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const createBossTask = async (values) => {
    if (!isOwner) {
      message.error('仅工作区所有者可以创建老板任务。')
      return
    }
    try {
      await apiFetch('/api/v1/business/tasks', {
        method: 'POST',
        body: JSON.stringify({
          title: values.title,
          description: values.description || '',
          priority: values.priority,
          due_date: values.due_date || null,
          assignee_id: values.assignee_id || null,
        }),
      })
      message.success('老板任务已创建，并保留可追溯记录。')
      setTaskOpen(false)
      taskForm.resetFields()
      loadBusiness({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const acknowledgeAlert = async (alert) => {
    try {
      await apiFetch(`/api/v1/business/alerts/${alert.id}/acknowledge`, { method: 'POST', body: JSON.stringify({}) })
      message.success('预警已确认，处理记录已保留。')
      loadBusiness({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const generateReport = async () => {
    try {
      await apiFetch('/api/v1/business/daily-reports/generate', { method: 'POST', body: JSON.stringify({}) })
      message.success('生产日报已生成，请人工复核后再分发。')
      loadBusiness({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const openTaskProgress = (task) => {
    setTaskProgress(task)
    progressForm.setFieldsValue({
      status: ['todo', 'in_progress', 'blocked', 'done', 'cancelled'].includes(task.status) ? task.status : 'todo',
      progress_note: task.progress_note || '',
    })
  }

  const updateTaskProgress = async (values) => {
    if (!taskProgress?.id) return
    try {
      await apiFetch(`/api/v1/business/tasks/${taskProgress.id}`, { method: 'PATCH', body: JSON.stringify({ status: values.status, progress_note: values.progress_note || '' }) })
      message.success(values.status === 'done' ? '任务已完成，并已保存处理结果。' : '任务进展已更新，并已保留处理记录。')
      setTaskProgress(null)
      progressForm.resetFields()
      loadBusiness({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const copyCredential = async (value, label) => {
    if (!value) return
    try {
      await navigator.clipboard.writeText(value)
      message.success(`${label}已复制，请存入受控密钥管理系统。`)
    } catch {
      message.warning(`无法自动复制${label}，请手动复制并妥善保管。`)
    }
  }

  const canUpdateTask = (task) => isOwner || Boolean(currentUserId && task.assignee_id === currentUserId)

  const sourceContent = apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="经营助手服务尚未部署，未显示任何数据源。" /> : sources.length ? <List className="business-list" dataSource={sources.slice(0, 5)} renderItem={(source) => {
    const status = statusMeta(source.status || (source.connected ? 'connected' : 'pending'), sourceStatus)
    return <List.Item><List.Item.Meta avatar={<Avatar size="small" icon={<AppstoreOutlined />} />} title={<Space size={6} wrap><Text strong>{compactText(source.name, '未命名数据源')}</Text><Badge status={status.color} text={status.label} /></Space>} description={<span>{compactText(source.source_type || source.type, '待确认类型')} · {source.connection_mode || '受控接入'} · {source.last_sync_at ? `最近同步 ${formatDate(source.last_sync_at)}` : '尚未同步数据'} · 授权范围受服务端保护</span>} /></List.Item>
  }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未接入数据源。只接入已授权 API、导出或企业机器人，不采集个人微信聊天记录。" />

  const alertContent = apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="经营助手服务尚未部署，未显示任何预警数据。" /> : alerts.length ? <List className="business-list" dataSource={alerts.slice(0, 5)} renderItem={(alert) => {
    const severity = statusMeta(alert.severity || alert.level, alertSeverity, { label: '待分级', color: 'default' })
    const acknowledged = ['acknowledged', 'closed', 'resolved'].includes(String(alert.status || '').toLowerCase()) || Boolean(alert.acknowledged_at)
    return <List.Item actions={!acknowledged && canWrite && alert.id ? [<Button key="ack" size="small" type="link" onClick={() => acknowledgeAlert(alert)}>确认处理</Button>] : []}><List.Item.Meta avatar={<Avatar size="small" className="business-alert-avatar" icon={<ClockCircleOutlined />} />} title={<Space size={6} wrap><Text strong>{compactText(alert.title, '待处理预警')}</Text><Tag color={severity.color}>{severity.label}</Tag>{acknowledged && <Tag color="success">已确认</Tag>}</Space>} description={<span>{compactText(alert.summary || alert.description)} · {formatDate(alert.created_at || alert.occurred_at)}</span>} /></List.Item>
  }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有可展示的预警。预警规则应在授权数据到达后由管理员配置。" />

  const reportContent = apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="经营助手服务尚未部署，未显示任何生产日报。" /> : reports.length ? <List className="business-list" dataSource={reports.slice(0, 4)} renderItem={(report) => <List.Item><List.Item.Meta avatar={<Avatar size="small" icon={<ProjectOutlined />} />} title={<Space size={6} wrap><Text strong>{compactText(report.title, '生产日报')}</Text><Tag color={report.status === 'reviewed' ? 'success' : 'blue'}>{report.status === 'reviewed' ? '已复核' : '待复核'}</Tag></Space>} description={<span>{compactText(report.summary || report.content, '暂无日报摘要')} · {formatDate(report.report_date || report.created_at)}</span>} /></List.Item>} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成生产日报。日报只会汇总已授权且可追溯的数据。" />

  const taskContent = apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="经营助手服务尚未部署，未显示任何老板任务。" /> : bossTasks.length ? <List className="business-list" dataSource={bossTasks.slice(0, 5)} renderItem={(task) => {
    const status = statusMeta(task.status, taskStatus)
    const assignee = assignableMembers.find((member) => member.id === task.assignee_id)
    return <List.Item actions={canWrite && canUpdateTask(task) && task.id && !['done', 'completed', 'cancelled'].includes(String(task.status || '').toLowerCase()) ? [<Button key="progress" size="small" type="link" onClick={() => openTaskProgress(task)}>更新进展</Button>] : []}><List.Item.Meta avatar={<Avatar size="small" icon={<UserOutlined />} />} title={<Space size={6} wrap><Text strong>{compactText(task.title, '未命名老板任务')}</Text><Tag color={status.color}>{status.label}</Tag></Space>} description={<span>{compactText(task.description)} · {assignee ? `负责人 ${assignee.name}` : '未分配负责人'} · {task.due_date ? `截止 ${formatDate(task.due_date)}` : '未设置截止时间'} · {task.progress_note ? `进展：${task.progress_note}` : '尚未记录进展'}</span>} /></List.Item>
  }} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无老板任务。任务需要由有权限的成员下达，并保留状态与处理记录。" />

  const roleCards = <div className="business-assistant-cards">{assistantCards.map((card) => {
    const selected = selectedCatalog.key === card.catalog.key
    const locked = !isOwner && card.catalog.key !== 'business'
    const stateText = locked ? '仅老板' : card.enabled ? '可使用' : '未启用'
    return <button type="button" key={card.catalog.key} className={`business-assistant-card ${selected ? 'is-selected' : ''}`} onClick={() => selectAssistant(card)} aria-pressed={selected} aria-label={`选择${card.catalog.title}`}>
      <span className="business-assistant-card-top"><Avatar size={38} className="business-assistant-avatar" icon={<RobotOutlined />} /><Tag color={card.catalog.color}>{stateText}</Tag></span>
      <strong>{assistantName(card.record, card.catalog)}</strong>
      <span>{card.catalog.summary}</span>
      <small>{card.catalog.audience} · {card.catalog.shortTitle}</small>
    </button>
  })}</div>

  const chatContent = selectedLocked ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该助手为老板私聊空间，当前账号无法进入。" /> : !selectedCard?.enabled ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该助手尚未启用。请由管理员在管理端完成配置，或等待业务服务初始化。" /> : historyLoading ? <div className="business-history-loading"><Spin size="small" />正在加载已保存的私有对话</div> : selectedMessages.length ? <Bubble.List className="business-bubbles" autoScroll items={selectedMessages.map((item) => ({ ...item, className: item.error ? 'business-error-bubble' : undefined }))} roles={{ assistant: { placement: 'start', avatar: { icon: <RobotOutlined />, className: 'assistant-avatar' }, variant: 'borderless', shape: 'corner' }, user: { placement: 'end', avatar: { icon: <UserOutlined /> }, variant: 'filled', shape: 'corner' } }} /> : <Welcome variant="borderless" icon={<Avatar size={48} className="business-assistant-avatar" icon={<RobotOutlined />} />} title={`正在与${assistantName(selectedAssistant, selectedCatalog)}协作`} description={selectedCatalog.summary} />

  return <div className="page-shell business-page">
    <Flex justify="space-between" align="flex-start" wrap="wrap" gap={16} className="page-heading business-heading">
      <div><Title level={2}>经营助手</Title><Text type="secondary">将已授权的业务数据汇总为预警、生产日报与可追溯任务；不会绕过系统授权采集个人聊天记录。</Text></div>
      <Space wrap><Tag color="blue">工作区隔离</Tag><Button onClick={() => loadBusiness({ quiet: true })} loading={refreshing}>刷新数据</Button></Space>
    </Flex>

    {loadError && <Alert className="business-load-alert" type={apiUnavailable ? 'info' : 'warning'} showIcon message={apiUnavailable ? '经营助手暂不可用' : '经营数据加载异常'} description={loadError} action={<Button size="small" onClick={() => loadBusiness()}>重新加载</Button>} />}

    <Card className="business-isolation-card" variant="borderless">
      <Flex gap={16} align="flex-start" wrap="wrap"><Avatar size={42} className="business-isolation-avatar" icon={<CheckCircleOutlined />} /><div className="business-isolation-copy"><Text strong>角色与数据隔离已在产品流程中明确</Text><div className="business-isolation-points"><span>老板私聊：仅工作区所有者</span><span>私事员工：不混入公事数据</span><span>公事员工：仅已授权业务数据</span><span>所有关键操作留存来源与处理记录</span></div></div></Flex>
    </Card>

    <Spin spinning={loading} tip="正在读取已授权的经营数据">
      <div className="business-stat-grid">
        <Card variant="borderless"><Statistic title="已登记数据源" value={apiUnavailable ? '—' : counts.sources} prefix={<AppstoreOutlined />} /><Text type="secondary">接口、导出或企业机器人</Text></Card>
        <Card variant="borderless"><Statistic title="待处理预警" value={apiUnavailable ? '—' : counts.activeAlerts} valueStyle={{ color: !apiUnavailable && counts.activeAlerts ? '#cf1322' : undefined }} prefix={<ClockCircleOutlined />} /><Text type="secondary">含生产、订单、设备与交期</Text></Card>
        <Card variant="borderless"><Statistic title="生产日报" value={apiUnavailable ? '—' : counts.reports} prefix={<ProjectOutlined />} /><Text type="secondary">生成后仍需人工复核</Text></Card>
        <Card variant="borderless"><Statistic title="老板任务" value={apiUnavailable ? '—' : counts.tasks} prefix={<UserOutlined />} /><Text type="secondary">任务状态可追溯</Text></Card>
      </div>

      <div className="business-workspace-grid">
        <Card className="business-role-card" title="选择业务助手" extra={<Text type="secondary">{isOwner ? '老板权限' : '公司成员权限'}</Text>}>
          {roleCards}
          <Alert className="business-role-hint" type="info" showIcon message={selectedCatalog.isolation} />
        </Card>
        <Card className="business-chat-card" title={<Space><MessageOutlined />{assistantName(selectedAssistant, selectedCatalog)}</Space>} extra={<Tag color={selectedCatalog.color}>{selectedCatalog.audience}</Tag>}>
          <div className="business-chat-body">{chatContent}</div>
          {historyNotice && <Text className="business-history-notice" type="secondary">{historyNotice}</Text>}
          <Sender value={chatInput} onChange={setChatInput} onSubmit={(value) => sendQuestion(value || chatInput)} loading={sending} disabled={!hasSelectedChat || !canWrite || apiUnavailable || historyLoading} placeholder={!canWrite ? '只读成员不能发起业务助手对话' : selectedLocked ? '该空间仅老板可用' : !selectedCard?.enabled ? '该助手尚未启用' : apiUnavailable ? '经营助手服务尚未部署' : historyLoading ? '正在加载已保存的对话…' : '例如：今天有哪些生产异常和待跟进事项？'} autoSize={{ minRows: 1, maxRows: 4 }} />
        </Card>
      </div>

      <div className="business-data-grid">
        <Card className="business-data-card" title="业务数据源" extra={canManage && <Button size="small" icon={<PlusOutlined />} onClick={() => setSourceOpen(true)}>登记数据源</Button>}>{sourceContent}</Card>
        <Card className="business-data-card" title="关键预警" extra={<Badge status={apiUnavailable ? 'default' : counts.activeAlerts ? 'error' : 'success'} text={apiUnavailable ? '服务未接入' : counts.activeAlerts ? '需关注' : '暂无待处理'} />}>{alertContent}</Card>
        <Card className="business-data-card" title="生产日报" extra={canManage && <Button size="small" onClick={generateReport}>生成日报</Button>}>{reportContent}</Card>
        <Card className="business-data-card" title="老板任务" extra={isOwner && <Button size="small" icon={<PlusOutlined />} onClick={() => setTaskOpen(true)}>下达任务</Button>}>{taskContent}</Card>
      </div>
    </Spin>

    <Modal title="登记业务数据源" open={sourceOpen} onCancel={() => setSourceOpen(false)} onOk={() => sourceForm.submit()} okText="登记" cancelText="取消" destroyOnHidden>
      <Form form={sourceForm} layout="vertical" onFinish={createSource} initialValues={{ source_type: 'oa', connection_mode: 'api', access_scope: '按最小权限授权' }}>
        <Alert type="info" showIcon message="仅接入已授权的数据" description="优先使用开放 API、系统导出、企业机器人或受控中间件；不建议抓取个人微信聊天记录或绕过登录权限。" />
        <Form.Item name="name" label="数据源名称" rules={[{ required: true, min: 2, message: '请输入至少两个字的数据源名称' }]}><Input placeholder="例如：生产日报接口" /></Form.Item>
        <Form.Item name="source_type" label="数据类型" rules={[{ required: true }]}><Select options={[{ value: 'oa', label: '公司 OA' }, { value: 'mini_program', label: '公司小程序' }, { value: 'production_report', label: '生产日报' }, { value: 'enterprise_robot', label: '企业机器人 / 群聊' }, { value: 'custom_api', label: '自有业务接口' }]} /></Form.Item>
        <Form.Item name="connection_mode" label="接入方式" rules={[{ required: true }]}><Select options={[{ value: 'api', label: '开放 API' }, { value: 'export', label: '系统导出' }, { value: 'middleware', label: '受控中间件' }, { value: 'robot', label: '企业机器人' }]} /></Form.Item>
        <Form.Item name="access_scope" label="授权范围" rules={[{ required: true, min: 2 }]}><Input placeholder="例如：只读生产日报与异常字段" /></Form.Item>
      </Form>
    </Modal>

    <Modal title="下达老板任务" open={taskOpen} onCancel={() => setTaskOpen(false)} onOk={() => taskForm.submit()} okText="创建任务" cancelText="取消" destroyOnHidden>
      <Form form={taskForm} layout="vertical" onFinish={createBossTask} initialValues={{ priority: 'medium' }}>
        <Form.Item name="title" label="任务标题" rules={[{ required: true, min: 2, message: '请输入至少两个字的任务标题' }]}><Input placeholder="例如：核实今日设备异常并反馈" /></Form.Item>
        <Form.Item name="description" label="任务说明"><Input.TextArea rows={3} placeholder="写明预期结果和相关背景" /></Form.Item>
        <Flex gap={12}><Form.Item name="priority" label="优先级" className="business-flex-field"><Select options={[{ value: 'low', label: '低' }, { value: 'medium', label: '中' }, { value: 'high', label: '高' }, { value: 'urgent', label: '紧急' }]} /></Form.Item><Form.Item name="due_date" label="截止日期" className="business-flex-field"><Input type="date" /></Form.Item></Flex>
        <Form.Item name="assignee_id" label="负责人"><Select allowClear placeholder="选择工作区成员" notFoundContent="暂无可分配成员" options={assignableMembers.map((member) => ({ value: member.id, label: `${member.name}${member.role ? `（${member.role === 'owner' ? '所有者' : member.role === 'admin' ? '管理员' : '成员'}）` : ''}` }))} /></Form.Item>
      </Form>
    </Modal>

    <Modal title="更新任务进展" open={Boolean(taskProgress)} onCancel={() => { setTaskProgress(null); progressForm.resetFields() }} onOk={() => progressForm.submit()} okText="保存进展" cancelText="取消" destroyOnHidden>
      <Form form={progressForm} layout="vertical" onFinish={updateTaskProgress}>
        <Form.Item label="任务"><Input value={taskProgress?.title || ''} readOnly /></Form.Item>
        <Form.Item name="status" label="当前状态" rules={[{ required: true }]}><Select options={[{ value: 'todo', label: '待处理' }, { value: 'in_progress', label: '进行中' }, { value: 'blocked', label: '受阻' }, { value: 'done', label: '已完成' }, { value: 'cancelled', label: '已取消' }]} /></Form.Item>
        <Form.Item name="progress_note" label="处理结果 / 进展说明" rules={[{ max: 4000 }]}><Input.TextArea rows={4} placeholder="记录已完成的动作、阻塞原因或下一步，便于老板追踪。" /></Form.Item>
      </Form>
    </Modal>

    <Modal title="保存数据源接入凭据" open={Boolean(ingestCredential)} onCancel={() => setIngestCredential(null)} footer={<Button type="primary" onClick={() => setIngestCredential(null)}>我已安全保存</Button>} destroyOnHidden>
      <Alert type="warning" showIcon message="接入令牌仅在本次页面中显示一次" description="请立即存入受控密钥管理系统。不要截图、不要写入 README 或文档、不要发送到群聊；关闭此窗口后无法再次查看明文令牌。" />
      <Form layout="vertical" className="business-credential-form">
        <Form.Item label="数据源"><Input value={ingestCredential?.name || ''} readOnly /></Form.Item>
        <Form.Item label="接入地址"><Space.Compact style={{ width: '100%' }}><Input value={ingestCredential?.url || '服务端未返回接入地址'} readOnly /><Button onClick={() => copyCredential(ingestCredential?.url, '接入地址')} disabled={!ingestCredential?.url}>复制</Button></Space.Compact></Form.Item>
        <Form.Item label="一次性接入令牌"><Space.Compact style={{ width: '100%' }}><Input.Password value={ingestCredential?.token || ''} readOnly visibilityToggle /><Button onClick={() => copyCredential(ingestCredential?.token, '接入令牌')}>复制</Button></Space.Compact></Form.Item>
      </Form>
    </Modal>
  </div>
}

export default function BusinessAssistantsPage(props) {
  return <XProvider locale={zhCN}><BusinessAssistantContent {...props} /></XProvider>
}
