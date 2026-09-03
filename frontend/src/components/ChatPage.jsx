import React, { useEffect, useMemo, useRef, useState } from 'react'
import AntApp from 'antd/es/app'
import Avatar from 'antd/es/avatar'
import Button from 'antd/es/button'
import Drawer from 'antd/es/drawer'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Form from 'antd/es/form'
import Image from 'antd/es/image'
import Input from 'antd/es/input'
import List from 'antd/es/list'
import Modal from 'antd/es/modal'
import Select from 'antd/es/select'
import Spin from 'antd/es/spin'
import Space from 'antd/es/space'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import { DeleteOutlined, DownloadOutlined, EditOutlined, FileExcelOutlined, FilePdfOutlined, FileTextOutlined, FileWordOutlined, FolderOutlined, MenuOutlined, MessageOutlined, PaperClipOutlined, PlusOutlined, RobotOutlined, ToolOutlined, UserOutlined } from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import Conversations from '@ant-design/x/es/conversations'
import Sender from '@ant-design/x/es/sender'
import Welcome from '@ant-design/x/es/welcome'
import XProvider from '@ant-design/x/es/x-provider'
import zhCN from 'antd/es/locale/zh_CN'
import { apiFetch, downloadAttachment, getAttachmentBlob, streamSSE, uploadAttachment } from '../api.js'
import { mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from '../ui-labels.js'
import { renderMarkdown } from '../markdown.js'
import { validateUpload } from '../upload-guard.js'

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

function ChatContent({ conversations, activeConversation, messages, models, skills, mcpServers = [], hasMoreMessages = false, onLoadMoreMessages, onNewConversation, onSelectConversation, onRefresh, onRefreshMessages, workspaceRole }) {
  const { message, modal } = AntApp.useApp()
  const [model, setModel] = useState('')
  const [skill, setSkill] = useState('')
  const [selectedMcpServers, setSelectedMcpServers] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveMessages, setLiveMessages] = useState([])
  const [attachments, setAttachments] = useState([])
  const [thumbnails, setThumbnails] = useState({})
  const [attachmentsLoading, setAttachmentsLoading] = useState(false)
  const [conversationOpen, setConversationOpen] = useState(false)
  const [renameTarget, setRenameTarget] = useState(null)
  const [archivedOpen, setArchivedOpen] = useState(false)
  const [archivedList, setArchivedList] = useState([])
  const [archivedLoading, setArchivedLoading] = useState(false)
  const [renameForm] = Form.useForm()
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
    setThumbnails({})
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
  // 为图片类附件生成缩略图 objectUrl；切换对话时统一回收
  useEffect(() => {
    const urls = []
    let current = true
    attachments.filter((item) => item.preview_kind === 'image').slice(0, 12).forEach((item) => {
      getAttachmentBlob(item)
        .then((blob) => {
          if (!current) { URL.revokeObjectURL(URL.createObjectURL(blob)); return }
          const url = URL.createObjectURL(blob)
          urls.push(url)
          setThumbnails((previous) => ({ ...previous, [item.id]: url }))
        })
        .catch(() => { /* 单张缩略图失败不影响列表 */ })
    })
    return () => { current = false; urls.forEach((url) => URL.revokeObjectURL(url)) }
  }, [attachments])
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
    const invalid = validateUpload(file)
    if (invalid) { message.error(invalid); onError?.(new Error(invalid)); return }
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
  const archiveConversation = async (conversation) => {
    try {
      await apiFetch(`/api/v1/conversations/${conversation.key}`, { method: 'PATCH', body: JSON.stringify({ archived: true }) })
      message.success('对话已归档，可在「已归档对话」中查看')
      if (activeConversation?.id === conversation.key) {
        const remaining = conversations.find((item) => item.id !== conversation.key)
        if (remaining) onSelectConversation(remaining.id)
      }
      onRefresh?.()
    } catch (error) { message.error(readableError(error)) }
  }
  const loadArchived = async () => {
    setArchivedLoading(true)
    try {
      const data = await apiFetch('/api/v1/conversations?include_archived=true')
      setArchivedList((data.conversations || []).filter((item) => item.archived))
    } catch { setArchivedList([]) } finally { setArchivedLoading(false) }
  }
  const openArchived = () => { setArchivedOpen(true); loadArchived() }
  const unarchiveConversation = async (conversation) => {
    try {
      await apiFetch(`/api/v1/conversations/${conversation.id}`, { method: 'PATCH', body: JSON.stringify({ archived: false }) })
      message.success('对话已恢复')
      loadArchived()
      onRefresh?.()
    } catch (error) { message.error(readableError(error)) }
  }
  const attachmentIcon = (name) => {
    const ext = String(name || '').toLowerCase().split('.').pop()
    if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#e05252' }} />
    if (['xlsx', 'csv'].includes(ext)) return <FileExcelOutlined style={{ color: '#1f9d72' }} />
    if (['docx', 'doc', 'md'].includes(ext)) return <FileWordOutlined style={{ color: '#3a6fd8' }} />
    return <FileTextOutlined />
  }
  const createConversation = () => {
    setConversationOpen(false)
    onNewConversation()
  }
  const selectConversation = (conversationId) => {
    setConversationOpen(false)
    onSelectConversation(conversationId)
  }
  const openRename = (conversation) => {
    setRenameTarget(conversation)
    renameForm.setFieldsValue({ title: conversation.label })
  }
  const submitRename = async (values) => {
    const title = (values.title || '').trim()
    if (!renameTarget || !title) return
    try {
      await apiFetch(`/api/v1/conversations/${renameTarget.key}`, { method: 'PATCH', body: JSON.stringify({ title }) })
      message.success('对话已重命名')
      setRenameTarget(null)
      onRefresh?.()
    } catch (error) { message.error(readableError(error)) }
  }
  const confirmDelete = (conversation) => {
    modal.confirm({
      title: `删除对话「${conversation.label}」？`,
      content: '对话消息与已上传附件会一并删除，且不可恢复。',
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: async () => {
        try {
          await apiFetch(`/api/v1/conversations/${conversation.key}`, { method: 'DELETE' })
          message.success('对话已删除')
          if (activeConversation?.id === conversation.key) {
            const remaining = conversations.find((item) => item.id !== conversation.key)
            if (remaining) onSelectConversation(remaining.id)
          }
          onRefresh?.()
        } catch (error) { message.error(readableError(error)) }
      },
    })
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
          menu={(conversation) => ({
            items: [
              { key: 'rename', label: '重命名', icon: <EditOutlined />, disabled: !canWrite },
              { key: 'archive', label: '归档', icon: <FolderOutlined />, disabled: !canWrite },
              { key: 'delete', label: '删除', icon: <DeleteOutlined />, danger: true, disabled: !canWrite },
            ],
            onClick: ({ key }) => {
              const target = conversations.find((item) => item.id === conversation.key)
              if (!target) return
              const wrapped = { key: target.id, label: target.title }
              if (key === 'rename') openRename(wrapped)
              else if (key === 'archive') archiveConversation(wrapped)
              else if (key === 'delete') confirmDelete(wrapped)
            },
          })}
        />
      ) : <Empty className="conversation-empty" image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无对话，创建一个开始协作" />}
      <Button type="text" size="small" icon={<FolderOutlined />} onClick={openArchived} className="archived-link">已归档对话</Button>
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
          {hasMoreMessages && bubbleItems.length ? (
            <div className="messages-older-wrap"><Button size="small" onClick={() => onLoadMoreMessages?.()}>查看更早消息</Button></div>
          ) : null}
          {bubbleItems.length ? (
            <Bubble.List
              autoScroll
              items={bubbleItems}
              roles={{
                assistant: {
                  placement: 'start',
                  avatar: { icon: <RobotOutlined />, className: 'assistant-avatar' },
                  variant: 'borderless',
                  shape: 'corner',
                  messageRender: (content) => (
                    <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
                  ),
                },
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
              {attachments.map((attachment) => thumbnails[attachment.id] ? (
                <Image
                  key={attachment.id}
                  className="chat-attachment-thumb"
                  src={thumbnails[attachment.id]}
                  alt={attachment.original_name}
                  width={44}
                  height={44}
                  style={{ objectFit: 'cover', borderRadius: 8, cursor: 'zoom-in' }}
                  preview={{ mask: <DownloadOutlined onClick={(event) => { event.stopPropagation(); download(attachment) }} /> }}
                />
              ) : (
                <Button key={attachment.id} size="small" icon={attachmentIcon(attachment.original_name)} onClick={() => download(attachment)} title={`下载 ${attachment.original_name}`}>
                  <span>{attachment.original_name}</span><DownloadOutlined />
                </Button>
              ))}
            </div>
          </div>}
          <Flex justify="space-between" align="center" gap={12} wrap>
            <Text type="secondary">对话与附件均保存于当前工作区。</Text>
            <Upload showUploadList={false} customRequest={attach} beforeUpload={(file) => { const invalid = validateUpload(file); if (invalid) { message.error(invalid); return Upload.LIST_IGNORE } return true }} disabled={!activeConversation || !canWrite}>
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
        <Drawer
          title="已归档对话"
          open={archivedOpen}
          onClose={() => setArchivedOpen(false)}
          width="min(88vw, 360px)"
        >
          {archivedLoading ? <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div> : archivedList.length ? (
            <List size="small" dataSource={archivedList} renderItem={(item) => (
              <List.Item actions={[<Button key="restore" size="small" onClick={() => unarchiveConversation(item)}>恢复</Button>]}>
                <List.Item.Meta title={item.title} description={new Date(item.updated_at).toLocaleString('zh-CN', { hour12: false })} />
              </List.Item>
            )} />
          ) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无归档对话" />}
        </Drawer>
        <Modal
          title="重命名对话"
          open={Boolean(renameTarget)}
          onCancel={() => setRenameTarget(null)}
          onOk={() => renameForm.submit()}
          okText="保存"
          cancelText="取消"
          destroyOnHidden
        >
          <Form form={renameForm} layout="vertical" onFinish={submitRename}>
            <Form.Item name="title" label="对话标题" rules={[{ required: true, min: 2, message: '标题至少 2 个字符' }]}>
              <Input placeholder="输入新的对话标题" maxLength={120} />
            </Form.Item>
          </Form>
        </Modal>
      </section>
    </div>
  )
}

export default function ChatPage(props) {
  return <XProvider locale={zhCN}><ChatContent {...props} /></XProvider>
}
