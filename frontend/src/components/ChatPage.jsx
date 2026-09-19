import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import AntApp from 'antd/es/app'
import Alert from 'antd/es/alert'
import Button from 'antd/es/button'
import Dropdown from 'antd/es/dropdown'
import Flex from 'antd/es/flex'
import Image from 'antd/es/image'
import Input from 'antd/es/input'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import Upload from 'antd/es/upload'
import {
  ArrowUpOutlined,
  BugOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  DownloadOutlined,
  FileExcelOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileWordOutlined,
  FolderOpenOutlined,
  HistoryOutlined,
  PaperClipOutlined,
  PlusOutlined,
  ProjectOutlined,
  StopOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import Bubble from '@ant-design/x/es/bubble'
import XProvider from '@ant-design/x/es/x-provider'
import zhCN from 'antd/es/locale/zh_CN'
import ComposerToolbar, { SupervisedFields } from './ComposerToolbar.jsx'
import MessageBlocks from './MessageBlocks.jsx'
import { apiFetch, downloadAttachment, getAttachmentBlob, streamSSE, uploadAttachment } from '../api.js'
import { agentModeRequirement, iterationVerdictLabel, mcpServerUnavailable, mcpOptionLabel, skillDisplayName } from '../ui-labels.js'
import { renderMarkdown } from '../markdown.js'
import { validateUpload } from '../upload-guard.js'
import { loadComposerPrefs, reconcileComposerPrefs, saveComposerPrefs } from '../composer-prefs.js'

const { Text } = Typography
const { TextArea } = Input

// 参考稿在输入框下方给了四个"从哪开始"的入口。这里换成这个产品真正能交付
// 的四类工作，每个都预填一段可直接发送（也可再改）的需求描述。
const quickActions = [
  {
    key: 'app',
    label: '应用开发',
    icon: <CodeOutlined />,
    prompt: '帮我开发一个可运行的小应用：先说明技术选型与目录结构，再给出完整代码与启动方式。',
  },
  {
    key: 'project',
    label: '项目理解',
    icon: <ProjectOutlined />,
    prompt: '梳理当前工作区的项目与任务结构，说明每个项目的目标、进度和下一步风险。',
  },
  {
    key: 'debug',
    label: '调试问题',
    icon: <BugOutlined />,
    prompt: '帮我定位并修复一个缺陷：我会补充报错与复现步骤，你给出根因、修复方案与验证方式。',
  },
  {
    key: 'script',
    label: '工具脚本',
    icon: <ToolOutlined />,
    prompt: '写一个可直接运行的自动化脚本，处理我描述的数据整理工作，并说明依赖与运行命令。',
  },
  {
    // 定时任务没有独立页面，全靠对话安排——这里是它唯一的发现入口。
    key: 'schedule',
    label: '定时任务',
    icon: <ClockCircleOutlined />,
    prompt: '帮我安排一个定时任务：每天早上九点，把工作区里昨天新增的任务与 AI 执行结果总结成一段简报。',
  },
]

const emptyPlaceholder = '帮你编写代码、调试 Bug、优化性能等开发工作，交付生产级代码产物。'

function readableError(error) {
  const text = String(error?.message || '').trim()
  return /[\u3400-\u9fff]/.test(text) ? text : '操作未完成，请稍后重试。'
}

function ChatContent({ activeAgent = null, onClearAgent, onOpenStudio, activeConversation, messages, models, modelsLoading = false, defaultModel = '', skills, mcpServers = [], hasMoreMessages = false, onLoadMoreMessages, onRefreshMessages, onRefresh, onOpenBoard, onCreateTask, onWorkspaceUpdated, workspaceRole, workspace }) {
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
  const inputRef = useRef(null)
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
      ? '请先新建或选择一个任务'
      : modelsLoading
        ? '正在加载可用模型…'
        : !models.length
          ? '暂未配置可用模型，请联系工作区管理员'
          : !skills.length
            ? '暂未配置可用技能，请联系工作区管理员'
            : !selectedModelReady
              ? '请选择一个已就绪的模型'
              : emptyPlaceholder
  // 首选顺序：用户上次选的模型 → 服务端声明的部署默认模型 → 第一个就绪模型。
  // 直接取列表首项会落到内置注册顺序的第一个，而它未必在本部署的路由里可用。
  useEffect(() => {
    if (modelOptions.some((item) => item.value === model && !item.disabled)) return
    const preferred = [defaultModel, ...modelOptions.filter((item) => !item.disabled).map((item) => item.value)]
      .find((candidate) => candidate && modelOptions.some((item) => item.value === candidate && !item.disabled))
    setModel(preferred || '')
  }, [model, modelOptions, defaultModel])
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
    const { fallbacks } = reconcileComposerPrefs(initialPrefs, { models, skills, mcpServers, defaultModel })
    fallbacks.forEach((text) => message.warning(text))
  }, [models, skills, mcpServers, initialPrefs, defaultModel, message])
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
    const query = String(value ?? input).trim()
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
      await streamSSE('/api/v1/chat/agent', { query, model_id: model, skill_name: skill || 'default', conversation_id: conversationId, mcp_servers: selectedMcpServers, mode, goal: goal.trim(), success_criteria: criteria.trim(), max_iterations: maxIterations, agent_id: activeAgent?.id || null }, { signal: controller.signal, onEvent: (event, data) => {
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
      message.success('附件已保存到任务')
      onSuccess?.('ok')
    } catch (error) { message.error(readableError(error)); onError?.(error) }
  }
  const download = async (attachment) => {
    try { await downloadAttachment(attachment); message.success('已开始下载') } catch (error) { message.error(readableError(error)) }
  }
  const attachmentIcon = (name) => {
    const ext = String(name || '').toLowerCase().split('.').pop()
    if (ext === 'pdf') return <FilePdfOutlined style={{ color: '#c5362f' }} />
    if (['xlsx', 'csv'].includes(ext)) return <FileExcelOutlined style={{ color: '#17916b' }} />
    if (['docx', 'doc', 'md'].includes(ext)) return <FileWordOutlined style={{ color: '#3a6fd8' }} />
    return <FileTextOutlined />
  }
  // 聚焦主输入框：快捷动作写进内容后用户大概率还想改一句再发。
  // 还没有任务时先建一个，否则这段描述没有落地处。
  const applyQuickAction = (prompt) => {
    if (!activeConversation && canWrite) onCreateTask?.()
    setInput(prompt)
    requestAnimationFrame(() => inputRef.current?.focus())
  }
  const visibleMessages = bubbleItems.length > 0
  // 任务（对话）操作：与侧边栏保持一致的三件事，放在主区右上角，
  // 消息很长时不必回到侧边栏操作。
  const taskMenu = activeConversation ? {
    items: [
      { key: 'rename', label: '重命名任务', disabled: !canWrite },
      { key: 'archive', label: '归档任务', disabled: !canWrite },
      { type: 'divider' },
      { key: 'delete', label: '删除任务', danger: true, disabled: !canWrite },
    ],
    onClick: async ({ key }) => {
      if (key === 'rename') {
        let nextTitle = activeConversation.title
        modal.confirm({
          title: '重命名任务',
          content: (
            <Input defaultValue={activeConversation.title} maxLength={120} onChange={(event) => { nextTitle = event.target.value }} />
          ),
          okText: '保存',
          cancelText: '取消',
          onOk: async () => {
            const title = String(nextTitle || '').trim()
            if (title.length < 2) { message.warning('标题至少 2 个字符'); throw new Error('invalid title') }
            await apiFetch(`/api/v1/conversations/${activeConversation.id}`, { method: 'PATCH', body: JSON.stringify({ title }) })
            message.success('任务已重命名')
            onRefresh?.()
          },
        })
        return
      }
      if (key === 'archive') {
        modal.confirm({
          title: `归档任务「${activeConversation.title}」？`,
          content: '归档后不再出现在任务列表里，可在侧边栏的「已归档任务」中恢复。',
          okText: '归档',
          cancelText: '取消',
          onOk: async () => {
            await apiFetch(`/api/v1/conversations/${activeConversation.id}`, { method: 'PATCH', body: JSON.stringify({ archived: true }) })
            message.success('任务已归档')
            onRefresh?.()
          },
        })
        return
      }
      if (key === 'delete') {
        modal.confirm({
          title: `删除任务「${activeConversation.title}」？`,
          content: '任务消息与已上传附件会一并删除，且不可恢复。',
          okText: '删除',
          okButtonProps: { danger: true },
          cancelText: '取消',
          onOk: async () => {
            await apiFetch(`/api/v1/conversations/${activeConversation.id}`, { method: 'DELETE' })
            message.success('任务已删除')
            onRefresh?.()
          },
        })
      }
    },
  } : null
  return (
    <div className="chat-page">
      <section className={`chat-stage${visibleMessages ? '' : ' is-empty'}`}>
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
        <div className="code-scroll">
          {!visibleMessages && (
            <div className="code-hero">
              <span className="code-hero-mark" aria-hidden="true"><CodeOutlined /></span>
              <h1>Code with futureAgent</h1>
            </div>
          )}
          {visibleMessages ? (
            <div className="messages">
              {hasMoreMessages ? (
                <div className="messages-older-wrap"><Button size="small" onClick={() => onLoadMoreMessages?.()}>查看更早消息</Button></div>
              ) : null}
              <Bubble.List
                autoScroll
                items={bubbleItems}
                roles={{
                  assistant: {
                    placement: 'start',
                    avatar: { icon: <CodeOutlined />, className: 'assistant-avatar' },
                    variant: 'borderless',
                    shape: 'corner',
                    messageRender: (content) => (typeof content === 'string'
                      ? <div className="markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }} />
                      : content),
                  },
                  user: { placement: 'end', variant: 'filled', shape: 'corner' },
                }}
              />
            </div>
          ) : null}
        </div>

        <div className="code-dock">
          {(attachmentsLoading || attachments.length > 0) && <div className="chat-attachment-strip" aria-label="任务附件">
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

          {/* 当前智能体：来自创造模式的自建预设。必须显式可见——人设会改变回答
              口径，看不见的话用户会以为模型"忽然变了个人"。 */}
          {activeAgent && (
            <div className="composer-agent-strip">
              <span className="composer-agent-dot" aria-hidden="true" />
              <span className="composer-agent-name">正在使用智能体「{activeAgent.name}」</span>
              {activeAgent.summary && <span className="composer-agent-summary">{activeAgent.summary}</span>}
              <Button type="text" size="small" className="composer-agent-clear" onClick={() => onClearAgent?.()}>
                退出该智能体
              </Button>
            </div>
          )}

          {/* 输入卡：空态与消息态共用同一个实例，首次发送不会重建输入框。 */}
          <div className={`composer-card${canSend ? '' : ' is-disabled'}`}>
            <div className="composer-input">
              <TextArea
                ref={inputRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onPressEnter={(event) => {
                  if (event.shiftKey) return
                  event.preventDefault()
                  send()
                }}
                placeholder={senderPlaceholder}
                autoSize={{ minRows: 1, maxRows: 8 }}
                disabled={!canSend}
                aria-label="任务描述"
              />
            </div>
            <div className="composer-actions">
              <div className="composer-actions-left">
                <Upload
                  showUploadList={false}
                  customRequest={attach}
                  beforeUpload={(file) => { const invalid = validateUpload(file); if (invalid) { message.error(invalid); return Upload.LIST_IGNORE } return true }}
                  disabled={!activeConversation || !canWrite}
                >
                  <Tooltip title="添加附件：对话与附件均保存在当前工作区">
                    <Button className="composer-attach" type="text" icon={<PlusOutlined />} disabled={!activeConversation || !canWrite} aria-label="添加附件" />
                  </Tooltip>
                </Upload>
                <ComposerToolbar
                  workspace={workspace}
                  canWrite={canWrite}
                  onWorkspaceUpdated={onWorkspaceUpdated}
                  messageApi={message}
                  mode={mode}
                  onModeChange={(value) => { setMode(value); updatePrefs({ mode: value }) }}
                  models={models}
                  modelsLoading={modelsLoading}
                  modelId={model}
                  onModelChange={(value) => { setModel(value); updatePrefs({ modelId: value }) }}
                  skills={skills}
                  skillName={skill}
                  onSkillChange={(value) => { setSkill(value); updatePrefs({ skillName: value }) }}
                  mcpServers={mcpServers}
                  selectedMcpServers={selectedMcpServers}
                  onMcpChange={(value) => { setSelectedMcpServers(value); updatePrefs({ mcpServers: value }) }}
                  onOpenStudio={onOpenStudio}
                  goal={goal}
                  onGoalChange={setGoal}
                  criteria={criteria}
                  onCriteriaChange={setCriteria}
                  maxIterations={maxIterations}
                  onMaxIterationsChange={(value) => { setMaxIterations(value); updatePrefs({ maxIterations: value }) }}
                  disabled={streaming}
                />
              </div>
              <div className="composer-actions-right">
                <Button
                  type="text"
                  className="composer-send"
                  onClick={() => (streaming ? abortRef.current?.abort() : send())}
                  disabled={!streaming && !canSend}
                  aria-label={streaming ? '停止生成' : '发送任务'}
                  icon={streaming ? <StopOutlined /> : <ArrowUpOutlined />}
                />
              </div>
            </div>
            {/* 必须用命名导入。原先写 ComposerToolbar.SupervisedFields，是在默认导出的
                那个函数上取属性——函数上没有这个属性，取到 undefined，React 渲染
                <undefined/> 会直接抛 "Element type is invalid"，整页崩掉。
                选中「目标 / 循环」两档就会触发。 */}
            {(mode === 'goal' || mode === 'loop') && (
              <SupervisedFields
                mode={mode}
                goal={goal}
                onGoalChange={setGoal}
                criteria={criteria}
                onCriteriaChange={setCriteria}
                maxIterations={maxIterations}
                onMaxIterationsChange={(value) => { setMaxIterations(value); updatePrefs({ maxIterations: value }) }}
                disabled={streaming}
              />
            )}
          </div>

          {/* 输入卡下方一行：当前工作区 + 附件入口，对应参考稿的"本地 / 选择文件夹" */}
          <div className="composer-meta">
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'board', icon: <ProjectOutlined />, label: '打开项目看板' },
                  { key: 'new', icon: <PlusOutlined />, label: '新建任务', disabled: !canWrite },
                  { key: 'history', icon: <HistoryOutlined />, label: '查看已归档任务' },
                ],
                onClick: ({ key }) => {
                  if (key === 'board') onOpenBoard?.()
                  else if (key === 'new') onCreateTask?.()
                  else if (key === 'history') document.querySelector('.sidebar-archived-button')?.click()
                },
              }}
            >
              <Button type="text" size="small" icon={<FolderOpenOutlined />}>{workspace?.name || '当前工作区'}</Button>
            </Dropdown>
            <span className="composer-meta-sep" aria-hidden="true">/</span>
            <Text type="secondary" style={{ fontSize: 12.5 }}>
              {selectedMcpServers.length ? `已启用 ${selectedMcpServers.length} 个工具服务` : '按需启用工具服务（可选）'}
            </Text>
          </div>

          {!visibleMessages && (
            <div className="code-quick-actions">
              {quickActions.map((action) => (
                <button
                  key={action.key}
                  type="button"
                  className="code-quick-action"
                  onClick={() => applyQuickAction(action.prompt)}
                  disabled={!canWrite}
                >
                  {action.icon}
                  <span>{action.label}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 右下角浮动工具条：参考稿的这一组图标在这里落成真实入口。 */}
        <div className="code-dock-tools" role="toolbar" aria-label="快捷工具">
          <Tooltip title="新建任务" placement="top">
            <Button type="text" size="small" icon={<PlusOutlined />} onClick={() => onCreateTask?.()} disabled={!canWrite} aria-label="新建任务" />
          </Tooltip>
          <Tooltip title="打开项目看板" placement="top">
            <Button type="text" size="small" icon={<ProjectOutlined />} onClick={() => onOpenBoard?.()} aria-label="打开项目看板" />
          </Tooltip>
          <Tooltip title="任务操作" placement="top">
            <Dropdown menu={taskMenu || { items: [{ key: 'none', label: '请先选择一个任务', disabled: true }] }} trigger={['click']} disabled={!taskMenu}>
              <Button type="text" size="small" icon={<HistoryOutlined />} aria-label="任务操作" />
            </Dropdown>
          </Tooltip>
        </div>
      </section>
    </div>
  )
}

export default function ChatPage(props) {
  return <XProvider locale={zhCN}><ChatContent {...props} /></XProvider>
}
