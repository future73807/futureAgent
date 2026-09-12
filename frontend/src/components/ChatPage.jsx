import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AntApp from 'antd/es/app'
import Alert from 'antd/es/alert'
import Avatar from 'antd/es/avatar'
import Button from 'antd/es/button'
import Flex from 'antd/es/flex'
import Image from 'antd/es/image'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import { DownloadOutlined, FileExcelOutlined, FilePdfOutlined, FileTextOutlined, FileWordOutlined, PaperClipOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import Sender from '@ant-design/x/es/sender'
import Welcome from '@ant-design/x/es/welcome'
import XProvider from '@ant-design/x/es/x-provider'
import zhCN from 'antd/es/locale/zh_CN'
import ComposerToolbar from './ComposerToolbar.jsx'
import MessageBlocks from './MessageBlocks.jsx'
import { apiFetch, downloadAttachment, getAttachmentBlob, streamSSE, uploadAttachment } from '../api.js'
import { agentModeRequirement, iterationVerdictLabel, mcpOptionLabel, mcpServerUnavailable, skillDisplayName } from '../ui-labels.js'
import { renderMarkdown } from '../markdown.js'
import { validateUpload } from '../upload-guard.js'
import { loadComposerPrefs, reconcileComposerPrefs, saveComposerPrefs } from '../composer-prefs.js'

const { Text } = Typography
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

function ChatContent({ activeConversation, messages, models, skills, mcpServers = [], hasMoreMessages = false, onLoadMoreMessages, onRefreshMessages, workspaceRole }) {
  const { message, modal } = AntApp.useApp()
  // 从持久化偏好初始化：用户上次选的模型/技能/工具/模式不该因为
  // 离开页面就丢失。失效值由下方的守卫 effect 回退。
  const initialPrefs = useRef(loadComposerPrefs()).current
  const [model, setModel] = useState(initialPrefs.modelId)
  const [skill, setSkill] = useState(initialPrefs.skillName)
  const [selectedMcpServers, setSelectedMcpServers] = useState(initialPrefs.mcpServers)
  const [mode, setMode] = useState(initialPrefs.mode)
  const [goal, setGoal] = useState('')
  const [criteria, setCriteria] = useState('')
  const [maxIterations, setMaxIterations] = useState(initialPrefs.maxIterations)
  const [iterations, setIterations] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [liveMessages, setLiveMessages] = useState([])
  const [attachments, setAttachments] = useState([])
  const [thumbnails, setThumbnails] = useState({})
  const [attachmentsLoading, setAttachmentsLoading] = useState(false)
  const abortRef = useRef(null)
  const canWrite = workspaceRole !== 'viewer'
  // 选择变更即写回，对话页与工作模式共用同一份偏好。
  const updatePrefs = useCallback((patch) => { saveComposerPrefs(patch) }, [])
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
  // 持久化里可能存着已被删除或不再就绪的模型/技能。静默沿用会让请求
  // 在服务端失败而用户看不出原因，因此首次拿到选项时比对一次并告知。
  const prefsCheckedRef = useRef(false)
  useEffect(() => {
    if (prefsCheckedRef.current || (!models.length && !skills.length)) return
    prefsCheckedRef.current = true
    const { fallbacks } = reconcileComposerPrefs(initialPrefs, { models, skills, mcpServers })
    fallbacks.forEach((text) => message.warning(text))
  }, [models, skills, mcpServers, initialPrefs, message])
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
  const bubbleItems = useMemo(() => [...messages, ...liveMessages].map((item) => ({
    key: item.id,
    role: item.role,
    // 助手消息携带结构化卡片（工具轨迹/用量/轮次/计划/变更入口），与
    // 正文拼成一个 ReactNode；messageRender 对非字符串内容原样透传。
    content: item.role === 'assistant' ? (
      <>
        <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(item.content) }} />
        <MessageBlocks message={item} canWrite={canWrite} />
      </>
    ) : item.content,
    loading: item.loading,
    className: item.error ? 'error-bubble' : undefined,
  })), [liveMessages, messages, canWrite])
  const send = async (value) => {
    const query = value.trim()
    if (!query || streaming || !activeConversation || !canWrite) return
    const requirement = agentModeRequirement(mode)
    if (requirement === 'goal' && !goal.trim()) { message.warning('目标模式需要先填写目标，否则无法判定是否达成'); return }
    if (requirement === 'criteria' && !criteria.trim()) { message.warning('循环模式需要先填写停止条件，否则会一直迭代到轮次上限'); return }
    const conversationId = activeConversation.id
    const userMessage = { id: `local-user-${Date.now()}`, role: 'user', content: query }
    const assistantId = `local-assistant-${Date.now()}`
    setLiveMessages([userMessage, { id: assistantId, role: 'assistant', content: '', loading: true }])
    setInput(''); setStreaming(true); setIterations([])
    const controller = new AbortController(); abortRef.current = controller
    try {
      await streamSSE('/api/v1/chat/agent', { query, model_id: model, skill_name: skill || 'default', conversation_id: conversationId, mcp_servers: selectedMcpServers, mode, goal: goal.trim(), success_criteria: criteria.trim(), max_iterations: maxIterations }, { signal: controller.signal, onEvent: (event, data) => {
        if (event === 'error') { let detail = data; try { detail = JSON.parse(data).detail || data } catch { /* 普通 SSE 错误。 */ } throw new Error(detail) }
        if (event === 'iteration') {
          try { setIterations((previous) => [...previous, JSON.parse(data)]) } catch { /* 单条轮次事件解析失败不影响正文。 */ }
          return
        }
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
  const attachmentIcon = (name) => {
    const ext = String(name || '').toLowerCase().split('.').pop()
    if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#e05252' }} />
    if (['xlsx', 'csv'].includes(ext)) return <FileExcelOutlined style={{ color: '#1f9d72' }} />
    if (['docx', 'doc', 'md'].includes(ext)) return <FileWordOutlined style={{ color: '#3a6fd8' }} />
    return <FileTextOutlined />
  }
  return (
    <div className="chat-page">
      <section className="chat-stage">
        {iterations.length > 0 && (
          <div className="chat-iterations">
            {iterations.map((item, index) => (
              <Alert
                key={index}
                type={item.verdict === 'met' ? 'success' : item.verdict === 'not_met' ? 'info' : 'warning'}
                showIcon
                message={`第 ${item.iteration} 轮 · ${iterationVerdictLabel(item.verdict)}`}
                description={item.reason}
              />
            ))}
          </div>
        )}
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
                  messageRender: (content) => (typeof content === 'string'
                    ? <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
                    : content),
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
          <ComposerToolbar
            mode={mode}
            onModeChange={(value) => { setMode(value); updatePrefs({ mode: value }) }}
            models={models}
            modelId={model}
            onModelChange={(value) => { setModel(value); updatePrefs({ modelId: value }) }}
            skills={skills}
            skillName={skill}
            onSkillChange={(value) => { setSkill(value); updatePrefs({ skillName: value }) }}
            mcpServers={mcpServers}
            selectedMcpServers={selectedMcpServers}
            onMcpChange={(value) => { setSelectedMcpServers(value); updatePrefs({ mcpServers: value }) }}
            goal={goal}
            onGoalChange={setGoal}
            criteria={criteria}
            onCriteriaChange={setCriteria}
            maxIterations={maxIterations}
            onMaxIterationsChange={(value) => { setMaxIterations(value); updatePrefs({ maxIterations: value }) }}
            disabled={streaming}
          />
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
          <Flex justify="flex-end" align="center">
            <Upload showUploadList={false} customRequest={attach} beforeUpload={(file) => { const invalid = validateUpload(file); if (invalid) { message.error(invalid); return Upload.LIST_IGNORE } return true }} disabled={!activeConversation || !canWrite}>
              <Tooltip title="对话与附件均保存在当前工作区">
                <Button size="small" type="text" icon={<PaperClipOutlined />} disabled={!activeConversation || !canWrite}>添加附件</Button>
              </Tooltip>
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
