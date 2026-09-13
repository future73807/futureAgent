import { useCallback, useEffect, useMemo, useState } from 'react'
// 子路径导入，原因见 SettingsModal 顶部注释：antd 顶层入口被别名成白名单桥。
import AntApp from 'antd/es/app'
import Button from 'antd/es/button'
import Checkbox from 'antd/es/checkbox'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Input from 'antd/es/input'
import Modal from 'antd/es/modal'
import Popconfirm from 'antd/es/popconfirm'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Switch from 'antd/es/switch'
import Tag from 'antd/es/tag'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import {
  ApiOutlined,
  BarChartOutlined,
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  PlusOutlined,
  ReloadOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { apiFetch } from '../api.js'
import { mcpDisplayName, skillDisplayName } from '../ui-labels.js'

const { Title, Text, Paragraph } = Typography

// 图标存 key 不存组件名：换图标库时不会让整批存量数据失效。
const ICON_OPTIONS = [
  { value: 'robot', label: '通用助手' },
  { value: 'chart', label: '数据分析' },
  { value: 'doc', label: '文档写作' },
  { value: 'code', label: '研发工程' },
  { value: 'shield', label: '风控合规' },
  { value: 'spark', label: '创意灵感' },
]
const ICONS = {
  robot: <RobotOutlined />,
  chart: <BarChartOutlined />,
  doc: <FileTextOutlined />,
  code: <CodeOutlined />,
  shield: <SafetyCertificateOutlined />,
  spark: <ThunderboltOutlined />,
}

const emptyDraft = {
  name: '',
  summary: '',
  persona: '',
  model_id: '',
  skill_name: 'default',
  mcp_servers: [],
  icon: 'robot',
  category: '自定义',
  enabled: true,
}

function readableError(error) {
  return error?.detail || error?.message || '请求失败，请检查网络或稍后重试。'
}

/**
 * 创造模式：用户自己拼装智能体。
 *
 * 一个智能体 = 一段人设 + 一组运行预设（模型 / 技能 / 工具）。它**不携带任何
 * 额外权限**：真正执行时工具授权仍走发起人自己的身份与工作区授权档位，所以
 * 这里可以放心让普通成员创建，不需要管理员审批。
 *
 * 「使用」把预设灌进输入卡（模型 / 技能 / 工具），并带着 agent_id 进入对话；
 * 人设由服务端注入提示词，排在技能说明之后、工作区规则之前。
 */
export default function AgentStudioPage({
  workspace,
  defaultModel = '',
  workspaceRole,
  models = [],
  skills = [],
  mcpServers = [],
  onUseAgent,
  onRefresh,
  loading = false,
}) {
  const { message } = AntApp.useApp()
  const [agents, setAgents] = useState([])
  const [fetching, setFetching] = useState(true)
  const [saving, setSaving] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [draft, setDraft] = useState(emptyDraft)

  const canWrite = workspaceRole !== 'viewer'
  const workspaceId = workspace?.id

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!workspaceId) return
    if (!quiet) setFetching(true)
    try {
      const payload = await apiFetch(`/api/v1/workspaces/${workspaceId}/agents`)
      setAgents(payload.agents || [])
    } catch (error) {
      if (!quiet) message.error(readableError(error))
    } finally {
      setFetching(false)
    }
  }, [workspaceId, message])

  useEffect(() => { load() }, [load])

  const modelOptions = useMemo(
    () => models.map((item) => {
      const id = item.id || item
      return { value: id, label: item.display_name || item.name || id }
    }),
    [models],
  )
  const skillOptions = useMemo(
    () => skills.map((item) => {
      const name = item.name || item
      return { value: name, label: skillDisplayName(name) }
    }),
    [skills],
  )
  const serverOptions = useMemo(
    () => mcpServers.map((item) => {
      const name = item.name || item
      return { value: name, label: mcpDisplayName(name) }
    }),
    [mcpServers],
  )

  const openCreate = () => {
    setEditingId(null)
    // 默认跟随部署的默认模型，而不是模型列表的第一项：列表顺序是供应商顺序，
    // 拿第一项当默认会让"新建智能体"悄悄选到一个并不是默认的模型。
    setDraft({ ...emptyDraft, model_id: defaultModel || modelOptions[0]?.value || '' })
    setEditorOpen(true)
  }

  const openEdit = (agent) => {
    setEditingId(agent.id)
    setDraft({
      name: agent.name,
      summary: agent.summary || '',
      persona: agent.persona || '',
      model_id: agent.model_id || '',
      skill_name: agent.skill_name || 'default',
      mcp_servers: agent.mcp_servers || [],
      icon: agent.icon || 'robot',
      category: agent.category || '自定义',
      enabled: agent.enabled !== false,
    })
    setEditorOpen(true)
  }

  const save = async () => {
    const name = draft.name.trim()
    if (!name) {
      message.warning('请先给智能体起个名字')
      return
    }
    if (!draft.persona.trim()) {
      message.warning('人设不能为空：智能体的行为完全由这段描述决定')
      return
    }
    setSaving(true)
    try {
      const body = { ...draft, name, summary: draft.summary.trim(), persona: draft.persona.trim() }
      if (editingId) {
        await apiFetch(`/api/v1/workspaces/${workspaceId}/agents/${editingId}`, { method: 'PUT', body: JSON.stringify(body) })
        message.success(`已更新「${name}」`)
      } else {
        await apiFetch(`/api/v1/workspaces/${workspaceId}/agents`, { method: 'POST', body: JSON.stringify(body) })
        message.success(`已创建「${name}」`)
      }
      setEditorOpen(false)
      await load({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    } finally {
      setSaving(false)
    }
  }

  const remove = async (agent) => {
    try {
      await apiFetch(`/api/v1/workspaces/${workspaceId}/agents/${agent.id}`, { method: 'DELETE' })
      message.success(`已删除「${agent.name}」`)
      await load({ quiet: true })
    } catch (error) {
      message.error(readableError(error))
    }
  }

  // 「使用」只把预设交给上层去灌进输入卡，这里不发任何写请求：
  // 选一个智能体不该顺手改掉它的配置。
  const use = (agent) => {
    onUseAgent?.(agent)
  }

  return (
    <div className="page-shell studio-page">
      <div className="page-heading">
        <div>
          <Title level={2}>创造模式</Title>
          <Text type="secondary">
            用一段人设加上模型、技能与工具，拼出你自己的智能体。智能体只是可复用的运行预设，
            不会带来额外权限——执行时的工具授权仍然按你自己的身份判定。
          </Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => { load({ quiet: true }); onRefresh?.() }} loading={loading || fetching}>刷新</Button>
          <Tooltip title={canWrite ? '' : '只读成员不能创建智能体'}>
            <Button type="primary" icon={<PlusOutlined />} disabled={!canWrite} onClick={openCreate}>新建智能体</Button>
          </Tooltip>
        </Space>
      </div>

      {fetching && !agents.length ? (
        <div className="studio-loading"><Spin /> <Text type="secondary">正在读取智能体…</Text></div>
      ) : agents.length ? (
        <div className="studio-grid">
          {agents.map((agent) => (
            <div key={agent.id} className={`studio-card${agent.enabled === false ? ' is-disabled' : ''}`}>
              <div className="studio-card-head">
                <span className="studio-card-icon">{ICONS[agent.icon] || ICONS.robot}</span>
                <Flex vertical style={{ minWidth: 0, flex: 1 }}>
                  <Text strong ellipsis>{agent.name}</Text>
                  <Text type="secondary" className="studio-card-sub" ellipsis>{agent.summary || '未填写简介'}</Text>
                </Flex>
                {agent.enabled === false && <Tag bordered={false}>已停用</Tag>}
              </div>
              <Paragraph className="studio-card-persona" ellipsis={{ rows: 3 }}>
                {agent.persona || '未填写人设'}
              </Paragraph>
              <div className="studio-card-meta">
                <Tag bordered={false}>{agent.model_id || '默认模型'}</Tag>
                <Tag bordered={false}>{skillDisplayName(agent.skill_name || 'default')}</Tag>
                <Tag bordered={false} icon={<ApiOutlined />}>
                  {(agent.mcp_servers || []).length ? `${agent.mcp_servers.length} 个工具` : '无工具'}
                </Tag>
                <Tag bordered={false}>{agent.category || '自定义'}</Tag>
              </div>
              <div className="studio-card-actions">
                <Button size="small" type="primary" disabled={agent.enabled === false || !canWrite} onClick={() => use(agent)}>使用</Button>
                <Button size="small" icon={<EditOutlined />} disabled={!canWrite} onClick={() => openEdit(agent)}>编辑</Button>
                <Popconfirm title={`删除「${agent.name}」？`} description="只删除这个预设，已有对话不受影响。" okText="删除" cancelText="取消" onConfirm={() => remove(agent)}>
                  <Button size="small" danger icon={<DeleteOutlined />} disabled={!canWrite}>删除</Button>
                </Popconfirm>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Empty
          className="guided-empty"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={canWrite ? '还没有自建智能体。创建一个，把常用的人设与配置沉淀下来。' : '还没有自建智能体。'}
        >
          {canWrite && <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>创建第一个智能体</Button>}
        </Empty>
      )}

      <Modal
        title={editingId ? '编辑智能体' : '新建智能体'}
        open={editorOpen}
        onCancel={() => setEditorOpen(false)}
        onOk={save}
        okText={editingId ? '保存' : '创建'}
        cancelText="取消"
        confirmLoading={saving}
        width={640}
        destroyOnHidden
      >
        <Flex vertical gap={14} className="studio-form">
          <label className="studio-field">
            <Text strong>名称</Text>
            <Input
              value={draft.name}
              maxLength={60}
              placeholder="例如：接口验收助手"
              onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
            />
          </label>
          <label className="studio-field">
            <Text strong>一句话简介</Text>
            <Input
              value={draft.summary}
              maxLength={200}
              placeholder="它会替你做什么？例如：逐条比对接口实现与文档是否一致"
              onChange={(event) => setDraft((prev) => ({ ...prev, summary: event.target.value }))}
            />
          </label>
          <label className="studio-field">
            <Text strong>人设 / 提示词</Text>
            <Input.TextArea
              rows={6}
              value={draft.persona}
              maxLength={8000}
              showCount
              placeholder="你是……。工作方式：……。输出要求：……。它会排在技能说明之后、工作区规则之前注入。"
              onChange={(event) => setDraft((prev) => ({ ...prev, persona: event.target.value }))}
            />
          </label>
          <Flex gap={12} wrap="wrap">
            <label className="studio-field is-half">
              <Text strong>模型</Text>
              <Select
                value={draft.model_id || undefined}
                placeholder="跟随默认模型"
                options={modelOptions}
                onChange={(value) => setDraft((prev) => ({ ...prev, model_id: value || '' }))}
                style={{ width: '100%' }}
              />
            </label>
            <label className="studio-field is-half">
              <Text strong>技能</Text>
              <Select
                value={draft.skill_name}
                options={skillOptions}
                onChange={(value) => setDraft((prev) => ({ ...prev, skill_name: value }))}
                style={{ width: '100%' }}
              />
            </label>
          </Flex>
          <label className="studio-field">
            <Text strong>可用工具</Text>
            <Text type="secondary" className="studio-field-hint">
              这里只是"让它在对话开始时默认勾选"；真正能不能用仍由工作区授权档位决定。
            </Text>
            <Checkbox.Group
              className="studio-tools"
              value={draft.mcp_servers}
              onChange={(values) => setDraft((prev) => ({ ...prev, mcp_servers: values }))}
              options={serverOptions.map((item) => ({ value: item.value, label: item.label }))}
            />
            {!serverOptions.length && <Text type="secondary">当前部署没有接入 MCP 工具服务。</Text>}
          </label>
          <Flex gap={12} wrap="wrap">
            <label className="studio-field is-half">
              <Text strong>图标</Text>
              <Select
                value={draft.icon}
                options={ICON_OPTIONS}
                onChange={(value) => setDraft((prev) => ({ ...prev, icon: value }))}
                style={{ width: '100%' }}
              />
            </label>
            <label className="studio-field is-half">
              <Text strong>分类</Text>
              <Input
                value={draft.category}
                maxLength={40}
                placeholder="例如：研发工具"
                onChange={(event) => setDraft((prev) => ({ ...prev, category: event.target.value }))}
              />
            </label>
          </Flex>
          <Flex align="center" gap={10}>
            <Switch checked={draft.enabled} onChange={(checked) => setDraft((prev) => ({ ...prev, enabled: checked }))} />
            <Text type="secondary">启用（停用后仍保留配置，但不能在对话里选用）</Text>
          </Flex>
        </Flex>
      </Modal>
    </div>
  )
}
