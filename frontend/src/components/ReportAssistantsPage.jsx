import React, { useCallback, useEffect, useMemo, useState } from 'react'
import AntApp from 'antd/es/app'
import Alert from 'antd/es/alert'
import Avatar from 'antd/es/avatar'
import Button from 'antd/es/button'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Form from 'antd/es/form'
import Input from 'antd/es/input'
import Modal from 'antd/es/modal'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Tag from 'antd/es/tag'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import {
  AppstoreOutlined,
  BookOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  FileTextOutlined,
  MessageOutlined,
  PlusOutlined,
  ProjectOutlined,
  RobotOutlined,
  UploadOutlined,
  UserOutlined,
} from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import Sender from '@ant-design/x/es/sender'
import Welcome from '@ant-design/x/es/welcome'
import XProvider from '@ant-design/x/es/x-provider'
import Conversations from '@ant-design/x/es/conversations'
import Prompts from '@ant-design/x/es/prompts'
import zhCN from 'antd/es/locale/zh_CN'
import { apiFetch } from '../api.js'

const { Title, Text, Paragraph } = Typography

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

const quickActions = [
  { key: 'daily', label: '今日生产情况', icon: <ProjectOutlined /> },
  { key: 'weekly', label: '本周总结', icon: <FileTextOutlined /> },
  { key: 'alert', label: '风险预警', icon: <ClockCircleOutlined /> },
  { key: 'source', label: '数据源管理', icon: <AppstoreOutlined /> },
]

function ReportAssistantContent({ workspaceRole, members = [], currentUserId = '' }) {
  const { message } = AntApp.useApp()
  const canManage = ['owner', 'admin'].includes(workspaceRole)
  const canWrite = workspaceRole !== 'viewer'
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [apiUnavailable, setApiUnavailable] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [dashboard, setDashboard] = useState({})
  const [sources, setSources] = useState([])
  const [alerts, setAlerts] = useState([])
  const [reports, setReports] = useState([])
  const [weeklyReports, setWeeklyReports] = useState([])
  const [knowledgeBases, setKnowledgeBases] = useState([])
  const [chatMessages, setChatMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyNotice, setHistoryNotice] = useState('')
  const [sending, setSending] = useState(false)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [kbOpen, setKbOpen] = useState(false)
  const [kbUploading, setKbUploading] = useState(false)
  const [ingestCredential, setIngestCredential] = useState(null)
  const [sourceForm] = Form.useForm()
  const [kbForm] = Form.useForm()

  const loadReport = useCallback(async ({ quiet = false } = {}) => {
    if (quiet) setRefreshing(true)
    else setLoading(true)
    setLoadError('')
    try {
      const dashboardPayload = await apiFetch('/api/v1/report/dashboard')
      const [sourcesPayload, alertsPayload, reportsPayload, weeklyReportsPayload, kbPayload] = await Promise.all([
        apiFetch('/api/v1/report/data-sources'),
        apiFetch('/api/v1/report/alerts'),
        apiFetch('/api/v1/report/daily-reports'),
        apiFetch('/api/v1/report/weekly-reports'),
        apiFetch('/api/v1/report/knowledge-bases'),
      ])
      setDashboard(dashboardPayload || {})
      setSources(pickArray(sourcesPayload, ['data_sources', 'sources']))
      setAlerts(pickArray(alertsPayload, ['alerts']))
      setReports(pickArray(reportsPayload, ['daily_reports', 'reports']))
      setWeeklyReports(pickArray(weeklyReportsPayload, ['weekly_reports']))
      setKnowledgeBases(pickArray(kbPayload, ['knowledge_bases']))
      setApiUnavailable(false)
    } catch (error) {
      if (apiNotAvailable(error)) {
        setApiUnavailable(true)
        setLoadError('汇报智能体服务尚未部署或当前账号没有该模块权限。页面没有展示任何模拟数据。')
      } else {
        setLoadError(readableError(error))
      }
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => { loadReport() }, [loadReport])

  useEffect(() => {
    let current = true
    setHistoryLoading(true)
    setHistoryNotice('')
    apiFetch('/api/v1/report/messages').then((payload) => {
      if (!current) return
      const history = pickArray(payload, ['messages']).map((item, index) => ({
        key: item.id || `history-${index}`,
        role: item.role === 'user' ? 'user' : 'assistant',
        content: withCitations(compactText(item.content || item.text || item.message, '（空消息）'), item.citations),
      }))
      setChatMessages(history)
    }).catch((error) => {
      if (!current) return
      setHistoryNotice(apiNotAvailable(error) ? '当前环境尚未启用历史消息接口；本次对话结果仍由服务端按权限处理。' : '暂时无法加载历史记录，请稍后重试。')
    }).finally(() => {
      if (current) setHistoryLoading(false)
    })
    return () => { current = false }
  }, [])

  const counts = {
    sources: Number(dashboard?.source_count ?? dashboard?.data_source_count ?? sources.length ?? 0),
    activeAlerts: Number(dashboard?.active_alert_count ?? dashboard?.alert_count ?? alerts.filter((item) => !['acknowledged', 'closed', 'resolved'].includes(String(item.status || '').toLowerCase())).length ?? 0),
    reports: Number(dashboard?.report_count ?? dashboard?.daily_report_count ?? reports.length ?? 0),
    weeklyReports: Number(dashboard?.weekly_report_count ?? weeklyReports.length ?? 0),
    knowledgeBases: Number(dashboard?.knowledge_base_count ?? knowledgeBases.length ?? 0),
  }

  const sendQuestion = async (value) => {
    const query = String(value || '').trim()
    if (!query || sending) return
    const userMessage = { key: `local-user-${Date.now()}`, role: 'user', content: query }
    const assistantKey = `local-assistant-${Date.now()}`
    setChatMessages((previous) => [...previous, userMessage, { key: assistantKey, role: 'assistant', content: '', loading: true }])
    setChatInput('')
    setSending(true)
    try {
      const payload = await apiFetch('/api/v1/report/chat', { method: 'POST', body: JSON.stringify({ message: query }) })
      setChatMessages((previous) => previous.map((item) => item.key === assistantKey ? { ...item, content: answerFrom(payload), loading: false } : item))
    } catch (error) {
      const fallback = apiNotAvailable(error) ? '对话服务尚未部署，未发送或保存本次内容。' : readableError(error)
      setChatMessages((previous) => previous.map((item) => item.key === assistantKey ? { ...item, content: fallback, loading: false, error: true } : item))
      message.warning(fallback)
    } finally {
      setSending(false)
    }
  }

  const createSource = async (values) => {
    try {
      const payload = await apiFetch('/api/v1/report/data-sources', {
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
      loadReport({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const createKnowledgeBase = async (values) => {
    try {
      await apiFetch('/api/v1/report/knowledge-bases', {
        method: 'POST',
        body: JSON.stringify({
          title: values.title,
          description: values.description || '',
          content: values.content || '',
        }),
      })
      message.success('知识库文档已创建。')
      setKbOpen(false)
      kbForm.resetFields()
      loadReport({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const uploadKnowledgeBase = async (file) => {
    setKbUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const title = file.name.replace(/\.[^/.]+$/, '')
      formData.append('title', title)
      await apiFetch('/api/v1/report/knowledge-bases/upload', { method: 'POST', body: formData })
      message.success('知识库文件已上传。')
      loadReport({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    } finally {
      setKbUploading(false)
    }
    return false
  }

  const generateReport = async () => {
    try {
      await apiFetch('/api/v1/report/daily-reports/generate', { method: 'POST', body: JSON.stringify({}) })
      message.success('生产日报已生成，请人工复核后再分发。')
      loadReport({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  const generateWeeklyReport = async () => {
    try {
      const today = new Date()
      const weekStart = new Date(today)
      weekStart.setDate(today.getDate() - today.getDay())
      const weekEnd = new Date(weekStart)
      weekEnd.setDate(weekStart.getDate() + 6)
      await apiFetch('/api/v1/report/weekly-reports/generate', {
        method: 'POST',
        body: JSON.stringify({
          week_start_date: weekStart.toISOString().split('T')[0],
          week_end_date: weekEnd.toISOString().split('T')[0],
        }),
      })
      message.success('周报已生成，请人工复核后再分发。')
      loadReport({ quiet: true })
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

  const handleQuickAction = (item) => {
    const messages = {
      daily: '今天有哪些生产数据和异常情况？',
      weekly: '生成本周生产总结报告',
      alert: '当前有哪些待处理的风险预警？',
      source: '查看已登记的数据源列表',
    }
    sendQuestion(messages[item.key] || item.label)
  }

  const sourceItems = sources.slice(0, 5).map((source) => ({
    key: source.id,
    label: compactText(source.name, '未命名数据源'),
    description: `${source.source_type} · ${source.connection_mode} · ${source.record_count || 0} 条记录`,
    icon: <Avatar size="small" icon={<AppstoreOutlined />} />,
  }))

  const alertItems = alerts.slice(0, 5).map((alert) => ({
    key: alert.id,
    label: compactText(alert.title, '待处理预警'),
    description: `${alert.level} · ${formatDate(alert.created_at)}`,
    icon: <Avatar size="small" icon={<ClockCircleOutlined />} />,
  }))

  const reportItems = reports.slice(0, 4).map((report) => ({
    key: report.id,
    label: compactText(report.title, '生产日报'),
    description: formatDate(report.report_date || report.created_at),
    icon: <Avatar size="small" icon={<ProjectOutlined />} />,
  }))

  const kbItems = knowledgeBases.slice(0, 5).map((kb) => ({
    key: kb.id,
    label: compactText(kb.title, '未命名文档'),
    description: `${kb.file_name ? '文件 · ' : ''}${formatDate(kb.created_at)}`,
    icon: <Avatar size="small" icon={<BookOutlined />} />,
  }))

  const chatBubbleItems = chatMessages.map((item) => ({
    ...item,
    className: item.error ? 'business-error-bubble' : undefined,
    avatar: item.role === 'user' ? { icon: <UserOutlined /> } : { icon: <RobotOutlined />, className: 'assistant-avatar' },
    placement: item.role === 'user' ? 'end' : 'start',
    variant: item.role === 'user' ? 'filled' : 'borderless',
    shape: 'corner',
  }))

  return (
    <div className="page-shell report-page">
      <Flex justify="space-between" align="flex-start" wrap="wrap" gap={16} className="page-heading">
        <div>
          <Title level={2}>汇报智能体</Title>
          <Text type="secondary">将已授权的业务数据汇总为预警、生产日报与总结报告；支持知识库、文件和接口的输入和对接。</Text>
        </div>
        <Space wrap>
          <Tag color="blue">工作区隔离</Tag>
          <Button onClick={() => loadReport({ quiet: true })} loading={refreshing}>刷新数据</Button>
        </Space>
      </Flex>

      {loadError && (
        <Alert
          className="business-load-alert"
          type={apiUnavailable ? 'info' : 'warning'}
          showIcon
          message={apiUnavailable ? '汇报智能体暂不可用' : '数据加载异常'}
          description={loadError}
          action={<Button size="small" onClick={() => loadReport()}>重新加载</Button>}
        />
      )}

      <Spin spinning={loading} tip="正在读取已授权的经营数据">
        <div className="report-layout">
          {/* 左侧：对话区域 */}
          <div className="report-chat-section">
            <div className="report-chat-header">
              <Space><MessageOutlined /><Text strong>汇报智能体</Text></Space>
              <Tag color="blue">工作区成员</Tag>
            </div>
            <div className="report-chat-body">
              {historyLoading ? (
                <div className="business-history-loading"><Spin size="small" />正在加载已保存的对话</div>
              ) : chatBubbleItems.length ? (
                <Bubble.List className="business-bubbles" autoScroll items={chatBubbleItems} />
              ) : (
                <Welcome
                  variant="borderless"
                  icon={<Avatar size={48} icon={<RobotOutlined />} />}
                  title="正在与汇报智能体协作"
                  description="汇总已授权数据，生成日报、总结和风险预警。支持知识库、文件和接口的输入和对接。"
                />
              )}
              {historyNotice && <Text className="business-history-notice" type="secondary">{historyNotice}</Text>}
            </div>
            <div className="report-chat-input">
              <div className="quick-actions">
                {quickActions.map((action) => (
                  <Button key={action.key} size="small" icon={action.icon} onClick={() => handleQuickAction(action)}>
                    {action.label}
                  </Button>
                ))}
              </div>
              <Sender
                value={chatInput}
                onChange={setChatInput}
                onSubmit={(value) => sendQuestion(value || chatInput)}
                loading={sending}
                disabled={!canWrite || apiUnavailable || historyLoading}
                placeholder={!canWrite ? '只读成员不能发起对话' : apiUnavailable ? '汇报智能体服务尚未部署' : historyLoading ? '正在加载已保存的对话…' : '例如：今天有哪些生产异常和待跟进事项？'}
                autoSize={{ minRows: 1, maxRows: 4 }}
              />
            </div>
          </div>

          {/* 右侧：数据面板 */}
          <div className="report-side-panel">
            {/* 统计卡片 */}
            <div className="report-stats">
              <div className="stat-item">
                <div className="stat-icon-wrap"><AppstoreOutlined /></div>
                <div className="stat-info">
                  <div className="stat-number">{apiUnavailable ? '—' : counts.sources}</div>
                  <div className="stat-label">已登记数据源</div>
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-icon-wrap"><ClockCircleOutlined /></div>
                <div className="stat-info">
                  <div className="stat-number" style={{ color: !apiUnavailable && counts.activeAlerts ? '#cf1322' : undefined }}>{apiUnavailable ? '—' : counts.activeAlerts}</div>
                  <div className="stat-label">待处理预警</div>
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-icon-wrap"><ProjectOutlined /></div>
                <div className="stat-info">
                  <div className="stat-number">{apiUnavailable ? '—' : counts.reports}</div>
                  <div className="stat-label">生产日报</div>
                </div>
              </div>
              <div className="stat-item">
                <div className="stat-icon-wrap"><BookOutlined /></div>
                <div className="stat-info">
                  <div className="stat-number">{apiUnavailable ? '—' : counts.knowledgeBases}</div>
                  <div className="stat-label">知识库文档</div>
                </div>
              </div>
            </div>

            {/* 业务数据源 */}
            <div className="report-panel-section">
              <div className="report-panel-header">
                <Text strong>业务数据源</Text>
                {canManage && <Button size="small" icon={<PlusOutlined />} onClick={() => setSourceOpen(true)}>登记</Button>}
              </div>
              {apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="服务未部署" /> : sourceItems.length ? (
                <Conversations items={sourceItems} />
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未接入数据源" />}
            </div>

            {/* 关键预警 */}
            <div className="report-panel-section">
              <div className="report-panel-header">
                <Text strong>关键预警</Text>
                <Tag color={apiUnavailable ? 'default' : counts.activeAlerts ? 'error' : 'success'}>
                  {apiUnavailable ? '未接入' : counts.activeAlerts ? '需关注' : '暂无'}
                </Tag>
              </div>
              {apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="服务未部署" /> : alertItems.length ? (
                <Conversations items={alertItems} />
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有可展示的预警" />}
            </div>

            {/* 生产日报 */}
            <div className="report-panel-section">
              <div className="report-panel-header">
                <Text strong>生产日报</Text>
                {canManage && <Space><Button size="small" onClick={generateReport}>日报</Button><Button size="small" onClick={generateWeeklyReport}>周报</Button></Space>}
              </div>
              {apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="服务未部署" /> : reportItems.length ? (
                <Conversations items={reportItems} />
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未生成生产日报" />}
            </div>

            {/* 知识库 */}
            <div className="report-panel-section">
              <div className="report-panel-header">
                <Text strong>知识库</Text>
                {canWrite && <Space><Button size="small" icon={<PlusOutlined />} onClick={() => setKbOpen(true)}>创建</Button><Upload showUploadList={false} beforeUpload={uploadKnowledgeBase} disabled={kbUploading}><Button size="small" icon={<UploadOutlined />} loading={kbUploading}>上传</Button></Upload></Space>}
              </div>
              {apiUnavailable ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="服务未部署" /> : kbItems.length ? (
                <Conversations items={kbItems} />
              ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="尚未创建知识库文档" />}
            </div>
          </div>
        </div>
      </Spin>

      <Modal title="登记业务数据源" open={sourceOpen} onCancel={() => setSourceOpen(false)} onOk={() => sourceForm.submit()} okText="登记" cancelText="取消" destroyOnClose>
        <Form form={sourceForm} layout="vertical" onFinish={createSource} initialValues={{ source_type: 'oa', connection_mode: 'api', access_scope: '按最小权限授权' }}>
          <Alert type="info" showIcon message="仅接入已授权的数据" description="优先使用开放 API、系统导出、企业机器人或受控中间件；不建议抓取个人微信聊天记录或绕过登录权限。" />
          <Form.Item name="name" label="数据源名称" rules={[{ required: true, min: 2, message: '请输入至少两个字的数据源名称' }]}><Input placeholder="例如：生产日报接口" /></Form.Item>
          <Form.Item name="source_type" label="数据类型" rules={[{ required: true }]}><Select options={[{ value: 'oa', label: '公司 OA' }, { value: 'mini_program', label: '公司小程序' }, { value: 'production_report', label: '生产日报' }, { value: 'enterprise_robot', label: '企业机器人 / 群聊' }, { value: 'custom_api', label: '自有业务接口' }]} /></Form.Item>
          <Form.Item name="connection_mode" label="接入方式" rules={[{ required: true }]}><Select options={[{ value: 'api', label: '开放 API' }, { value: 'export', label: '系统导出' }, { value: 'middleware', label: '受控中间件' }, { value: 'robot', label: '企业机器人' }]} /></Form.Item>
          <Form.Item name="access_scope" label="授权范围" rules={[{ required: true, min: 2 }]}><Input placeholder="例如：只读生产日报与异常字段" /></Form.Item>
        </Form>
      </Modal>

      <Modal title="创建知识库文档" open={kbOpen} onCancel={() => setKbOpen(false)} onOk={() => kbForm.submit()} okText="创建" cancelText="取消" destroyOnClose>
        <Form form={kbForm} layout="vertical" onFinish={createKnowledgeBase}>
          <Alert type="info" showIcon message="知识库文档" description="创建文档后，汇报智能体可以引用文档内容生成报告。支持上传文件或手动输入内容。" />
          <Form.Item name="title" label="文档标题" rules={[{ required: true, min: 2, message: '请输入至少两个字的文档标题' }]}><Input placeholder="例如：生产流程规范" /></Form.Item>
          <Form.Item name="description" label="文档说明"><Input placeholder="简要说明文档内容" /></Form.Item>
          <Form.Item name="content" label="文档内容"><Input.TextArea rows={6} placeholder="输入文档内容，汇报智能体将引用此内容生成报告" /></Form.Item>
        </Form>
      </Modal>

      <Modal title="保存数据源接入凭据" open={Boolean(ingestCredential)} onCancel={() => setIngestCredential(null)} footer={<Button type="primary" onClick={() => setIngestCredential(null)}>我已安全保存</Button>} destroyOnClose>
        <Alert type="warning" showIcon message="接入令牌仅在本次页面中显示一次" description="请立即存入受控密钥管理系统。不要截图、不要写入 README 或文档、不要发送到群聊；关闭此窗口后无法再次查看明文令牌。" />
        <Form layout="vertical" className="business-credential-form">
          <Form.Item label="数据源"><Input value={ingestCredential?.name || ''} readOnly /></Form.Item>
          <Form.Item label="接入地址"><Space.Compact style={{ width: '100%' }}><Input value={ingestCredential?.url || '服务端未返回接入地址'} readOnly /><Button onClick={() => copyCredential(ingestCredential?.url, '接入地址')} disabled={!ingestCredential?.url}>复制</Button></Space.Compact></Form.Item>
          <Form.Item label="一次性接入令牌"><Space.Compact style={{ width: '100%' }}><Input.Password value={ingestCredential?.token || ''} readOnly visibilityToggle /><Button onClick={() => copyCredential(ingestCredential?.token, '接入令牌')}>复制</Button></Space.Compact></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default function ReportAssistantsPage(props) {
  return <XProvider locale={zhCN}><ReportAssistantContent {...props} /></XProvider>
}
