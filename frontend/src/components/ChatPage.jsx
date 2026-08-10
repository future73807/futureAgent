import React, { useEffect, useMemo, useRef, useState } from 'react'
import AntApp from 'antd/es/app'
import Avatar from 'antd/es/avatar'
import Button from 'antd/es/button'
import Drawer from 'antd/es/drawer'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import { DownloadOutlined, FileTextOutlined, MenuOutlined, MessageOutlined, PaperClipOutlined, PlusOutlined, RobotOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import Conversations from '@ant-design/x/es/conversations'
import Sender from '@ant-design/x/es/sender'
import Welcome from '@ant-design/x/es/welcome'
import XProvider from '@ant-design/x/es/x-provider'
import zhCN from 'antd/es/locale/zh_CN'
import { apiFetch, downloadAttachment, streamSSE, uploadAttachment } from '../api.js'
import { mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from '../ui-labels.js'

const { Title, Text } = Typography
const promptSuggestions = [
  '梳理今天最重要的三项工作',
  '根据现有信息制定执行计划',
  '总结材料并列出待确认问题',
  '搜索资料并给出可追溯结论',
]

function readableError(error) {
  const text = String(error?.message || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : '操作未完成，请稍后重试。'
}

function ChatContent({ conversations, activeConversation, messages, models, skills, mcpServers = [], onNewConversation, onSelectConversation, onRefresh, onRefreshMessages, workspaceRole }) {
  const { message } = AntApp.useApp()
  const [model, setModel] = useState('')
  const [skill, setSkill] = useState('')
  const [selectedMcpServers, setSelectedMcpServers] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveMessages, setLiveMessages] = useState([])
  const [attachments, setAttachments] = useState([])
  const [attachmentsLoading, setAttachmentsLoading] = useState(false)
  const [conversationOpen, setConversationOpen] = useState(false)
  const abortRef = useRef(null)
  const canWrite = workspaceRole !== 'viewer'
  const modelOptions = useMemo(() => models.map((item) => ({
    value: item.id || item,
    label: `${item.id || item}${item.ready === false ? '（未就绪）' : ''}`,
    disabled: item.ready === false,
  })), [models])
  const skillOptions = useMemo(() => skills.map((item) => ({ value: item.name, label: skillDisplayName(item.name) })), [skills])
  const mcpOptions = useMemo(() => mcpServers.map((item) => ({
    value: item.name || item,
    label: mcpOptionLabel(item),
    title: mcpOptionLabel(item),
    tools: Array.isArray(item.tools) ? item.tools : [],
    disabled: mcpServerUnavailable(item),
  })), [mcpServers])
  const selectedModelReady = modelOptions.some((item) => item.value === model && !item.disabled)
  const canSend = Boolean(activeConversation && selectedModelReady && skill && canWrite)
  const senderPlaceholder = !canWrite
    ? '只读成员不能发起 AI 工作'
    : !activeConversation
      ? '请先新建或选择一个对话'
      : !models.length
        ? '暂未配置可用模型，请联系工作区管理员'
        : !skills.length
          ? '暂未配置可用技能，请联系工作区管理员'
          : !selectedModelReady
            ? '请选择一个已就绪的模型'
            : '让 AI 帮你分析、起草或推进工作…'
  useEffect(() => {
    if (!modelOptions.some((item) => item.value === model && !item.disabled)) {
      setModel(modelOptions.find((item) => !item.disabled)?.value || '')
    }
  }, [model, modelOptions])
  useEffect(() => {
    if (!skillOptions.some((item) => item.value === skill)) setSkill(skillOptions[0]?.value || '')
  }, [skill, skillOptions])
  useEffect(() => {
    setSelectedMcpServers((current) => current.filter((name) => mcpOptions.some((item) => item.value === name && !item.disabled)))
  }, [mcpOptions])
  useEffect(() => {
    let current = true
    const conversationId = activeConversation?.id
    setAttachments([])
    if (!conversationId) {
      setAttachmentsLoading(false)
      return () => { current = false }
    }
    setAttachmentsLoading(true)
    apiFetch(`/api/v1/attachments?conversation_id=${conversationId}`)
      .then((payload) => { if (current) setAttachments(payload.attachments || []) })
      .catch(() => { if (current) setAttachments([]) })
      .finally(() => { if (current) setAttachmentsLoading(false) })
    return () => { current = false }
  }, [activeConversation?.id])
  const bubbleItems = useMemo(() => [...messages, ...liveMessages].map((item) => ({ key: item.id, role: item.role, content: item.content, loading: item.loading, className: item.error ? 'error-bubble' : undefined })), [liveMessages, messages])
  const send = async (value) => {
    const query = value.trim()
    if (!query || streaming || !activeConversation || !canWrite) return
    const conversationId = activeConversation.id
    const userMessage = { id: `local-user-${Date.now()}`, role: 'user', content: query }
    const assistantId = `local-assistant-${Date.now()}`
    setLiveMessages([userMessage, { id: assistantId, role: 'assistant', content: '', loading: true }])
    setInput(''); setStreaming(true)
    const controller = new AbortController(); abortRef.current = controller
    try {
      await streamSSE('/api/v1/chat/agent', { query, model_id: model, skill_name: skill || 'default', conversation_id: conversationId, mcp_servers: selectedMcpServers }, { signal: controller.signal, onEvent: (event, data) => {
        if (event === 'error') { let detail = data; try { detail = JSON.parse(data).detail || data } catch { /* 普通 SSE 错误。 */ } throw new Error(detail) }
        if (event !== 'token') return
        setLiveMessages((previous) => previous.map((item) => item.id === assistantId ? { ...item, content: item.content + data, loading: false } : item))
      } })
      try {
        await onRefreshMessages?.(conversationId)
        setLiveMessages([])
      } catch {
        message.warning('回答已生成，但历史记录暂时无法同步；当前结果会保留在页面中。')
      }
      void onRefresh?.()
    } catch (error) {
      setLiveMessages((previous) => previous.map((item) => item.id === assistantId ? { ...item, content: item.content || readableError(error), loading: false, error: true } : item))
    } finally { abortRef.current = null; setStreaming(false) }
  }
  const attach = async ({ file, onSuccess, onError }) => {
    try {
      const payload = await uploadAttachment(file, { conversation_id: activeConversation?.id })
      if (payload?.attachment) setAttachments((current) => [...current, payload.attachment])
      message.success('附件已保存到对话')
      onSuccess?.('ok')
    } catch (error) { message.error(readableError(error)); onError?.(error) }
  }
  const download = async (attachment) => {
    try { await downloadAttachment(attachment); message.success('已开始下载') } catch (error) { message.error(readableError(error)) }
  }
  const createConversation = () => {
    setConversationOpen(false)
    onNewConversation()
  }
  const selectConversation = (conversationId) => {
    setConversationOpen(false)
    onSelectConversation(conversationId)
  }
  const conversationPane = (
    <aside className="conversation-pane">
      <Button type="primary" icon={<PlusOutlined />} block onClick={createConversation} disabled={!canWrite}>新建对话</Button>
      <Flex className="conversation-section-label" justify="space-between" align="center">
        <Text type="secondary">最近对话</Text>
        <Text type="secondary">{conversations.length}</Text>
      </Flex>
      {conversations.length ? (
        <Conversations
          aria-label="对话列表"
          items={conversations.map((item) => ({ key: item.id, label: item.title, timestamp: item.updated_at, icon: <MessageOutlined /> }))}
          activeKey={activeConversation?.id}
          onActiveChange={selectConversation}
        />
      ) : <Empty className="conversation-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话，创建一个开始协作" />}
    </aside>
  )
  return (
    <div className="chat-page">
      {conversationPane}
      <Drawer
        title="对话记录"
        placement="left"
        width="min(88vw, 340px)"
        open={conversationOpen}
        onClose={() => setConversationOpen(false)}
        rootClassName="mobile-conversation-drawer"
        styles={{ body: { padding: 0 } }}
      >
        {conversationPane}
      </Drawer>
      <section className="chat-stage">
        <header className="chat-title">
          <div className="chat-title-copy">
            <Flex align="center" gap={8}>
              <Button className="mobile-conversation-trigger" type="text" icon={<MenuOutlined />} onClick={() => setConversationOpen(true)} aria-label="打开对话列表" />
              <div>
                <Title level={4}>{activeConversation?.title || '请选择对话'}</Title>
                <Text type="secondary">对话和附件自动保存到当前工作区</Text>
              </div>
            </Flex>
          </div>
          <Space className="chat-selection-controls" wrap>
            <Select
              aria-label="选择模型"
              size="small"
              value={model || undefined}
              onChange={setModel}
              placeholder="选择模型"
              options={modelOptions}
              disabled={!modelOptions.length}
              notFoundContent="暂无可用模型"
            />
            <Select
              aria-label="选择技能"
              size="small"
              value={skill || undefined}
              onChange={setSkill}
              placeholder="选择技能"
              options={skillOptions}
              disabled={!skillOptions.length}
              notFoundContent="暂无可用技能"
            />
            <Select
              aria-label="选择 MCP 工具服务"
              className="mcp-selector"
              mode="multiple"
              size="small"
              value={selectedMcpServers}
              onChange={setSelectedMcpServers}
              maxTagCount="responsive"
              prefix={<ToolOutlined />}
              placeholder={mcpOptions.length ? '按需启用工具' : '未配置工具服务'}
              options={mcpOptions}
              optionRender={(option) => <div className="mcp-option"><span>{option.label}</span><small>{option.data?.tools?.length ? option.data.tools.join(' · ') : option.data?.disabled ? '连接不可用' : '工具清单将在连接后显示'}</small></div>}
              disabled={!mcpOptions.length}
              notFoundContent="暂无可用工具服务"
            />
          </Space>
        </header>
        <div className="messages">
          {bubbleItems.length ? (
            <Bubble.List
              autoScroll
              items={bubbleItems}
              roles={{
                assistant: { placement: 'start', avatar: { icon: <RobotOutlined />, className: 'assistant-avatar' }, variant: 'borderless', shape: 'corner' },
                user: { placement: 'end', avatar: { icon: <UserOutlined /> }, variant: 'filled', shape: 'corner' },
              }}
            />
          ) : (
            <Welcome
              className="chat-welcome"
              variant="borderless"
              icon={<Avatar size={52} icon={<RobotOutlined />} className="brand-avatar" />}
              title="今天想推进哪一项工作？"
              description={<div className="chat-welcome-content"><Text type="secondary">直接描述目标，或从一个常用工作方式开始。</Text><div className="chat-prompt-suggestions">{promptSuggestions.map((prompt) => <Button key={prompt} size="small" onClick={() => setInput(prompt)} disabled={!canSend}>{prompt}</Button>)}</div></div>}
            />
          )}
        </div>
        <div className="chat-sender">
          {(attachmentsLoading || attachments.length > 0) && <div className="chat-attachment-strip" aria-label="对话附件">
            <Text type="secondary">{attachmentsLoading ? '正在加载附件…' : `附件 ${attachments.length}`}</Text>
            <div className="chat-attachment-list">
              {attachments.map((attachment) => <Button key={attachment.id} size="small" icon={<FileTextOutlined />} onClick={() => download(attachment)} title={`下载 ${attachment.original_name}`}>
                <span>{attachment.original_name}</span><DownloadOutlined />
              </Button>)}
            </div>
          </div>}
          <Flex justify="space-between" align="center" gap={12} wrap>
            <Text type="secondary">对话与附件均保存于当前工作区。</Text>
            <Upload showUploadList={false} customRequest={attach} disabled={!activeConversation || !canWrite}>
              <Button size="small" icon={<PaperClipOutlined />} disabled={!activeConversation || !canWrite}>添加附件</Button>
            </Upload>
          </Flex>
          <Sender
            value={input}
            onChange={setInput}
            onSubmit={send}
            onCancel={() => abortRef.current?.abort()}
            loading={streaming}
            disabled={!canSend}
            placeholder={senderPlaceholder}
            autoSize={{ minRows: 1, maxRows: 6 }}
            actions={(_, { components: { SendButton, LoadingButton } }) => streaming ? <LoadingButton aria-label="停止生成" /> : <SendButton aria-label="发送消息" />}
          />
        </div>
      </section>
    </div>
  )
}

export default function ChatPage(props) {
  return <XProvider locale={zhCN}><ChatContent {...props} /></XProvider>
}
