import React, { useEffect, useMemo, useRef, useState } from 'react'
import AntApp from 'antd/es/app'
import Avatar from 'antd/es/avatar'
import Button from 'antd/es/button'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import { MessageOutlined, PaperClipOutlined, PlusOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import Conversations from '@ant-design/x/es/conversations'
import Sender from '@ant-design/x/es/sender'
import Welcome from '@ant-design/x/es/welcome'
import XProvider from '@ant-design/x/es/x-provider'
import zhCN from 'antd/es/locale/zh_CN'
import { streamSSE, uploadAttachment } from '../api.js'
import { skillDisplayName } from '../ui-labels.js'

const { Title, Text } = Typography

function readableError(error) {
  const text = String(error?.message || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : '操作未完成，请稍后重试。'
}

function ChatContent({ conversations, activeConversation, messages, models, skills, onNewConversation, onSelectConversation, onRefresh, workspaceRole }) {
  const { message } = AntApp.useApp()
  const [model, setModel] = useState('')
  const [skill, setSkill] = useState('')
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveMessages, setLiveMessages] = useState([])
  const abortRef = useRef(null)
  const canWrite = workspaceRole !== 'viewer'
  const modelOptions = useMemo(() => models.map((item) => ({
    value: item.id || item,
    label: `${item.id || item}${item.ready === false ? '（未就绪）' : ''}`,
    disabled: item.ready === false,
  })), [models])
  const skillOptions = useMemo(() => skills.map((item) => ({ value: item.name, label: skillDisplayName(item.name) })), [skills])
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
        if (event === 'error') { let detail = data; try { detail = JSON.parse(data).detail || data } catch { /* 普通 SSE 错误。 */ } throw new Error(detail) }
        if (event !== 'token') return
        setLiveMessages((previous) => previous.map((item) => item.id === assistantId ? { ...item, content: item.content + data, loading: false } : item))
      } })
      setLiveMessages([]); onRefresh()
    } catch (error) {
      setLiveMessages((previous) => previous.map((item) => item.id === assistantId ? { ...item, content: item.content || readableError(error), loading: false, error: true } : item))
    } finally { abortRef.current = null; setStreaming(false) }
  }
  const attach = async ({ file, onSuccess, onError }) => {
    try { await uploadAttachment(file, { conversation_id: activeConversation?.id }); message.success('附件已保存到对话'); onSuccess?.('ok') } catch (error) { message.error(readableError(error)); onError?.(error) }
  }
  return (
    <div className="chat-page">
      <aside className="conversation-pane">
        <Button type="primary" icon={<PlusOutlined />} block onClick={onNewConversation} disabled={!canWrite}>新建对话</Button>
        {conversations.length ? (
          <Conversations
            aria-label="对话列表"
            items={conversations.map((item) => ({ key: item.id, label: item.title, timestamp: item.updated_at, icon: <MessageOutlined /> }))}
            activeKey={activeConversation?.id}
            onActiveChange={onSelectConversation}
          />
        ) : <Empty className="conversation-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话" />}
      </aside>
      <section className="chat-stage">
        <header className="chat-title">
          <div>
            <Title level={4}>{activeConversation?.title || '请选择对话'}</Title>
            <Text type="secondary">工作区持久化对话</Text>
          </div>
          <Space className="chat-selection-controls" wrap>
            <Select
              aria-label="选择模型"
              size="small"
              value={model || undefined}
              onChange={setModel}
              placeholder="选择模型"
              options={modelOptions}
            />
            <Select
              aria-label="选择技能"
              size="small"
              value={skill || undefined}
              onChange={setSkill}
              placeholder="选择技能"
              options={skillOptions}
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
              variant="borderless"
              icon={<Avatar size={52} icon={<RobotOutlined />} className="brand-avatar" />}
              title="今天想推进哪一项工作？"
              description="先在项目看板中明确任务，再用工作模式生成、审批和执行计划。"
            />
          )}
        </div>
        <div className="chat-sender">
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
          />
        </div>
      </section>
    </div>
  )
}

export default function ChatPage(props) {
  return <XProvider locale={zhCN}><ChatContent {...props} /></XProvider>
}
