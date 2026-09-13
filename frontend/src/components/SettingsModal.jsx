import { useCallback, useEffect, useMemo, useState } from 'react'
// 与 App.jsx 一致：走 antd 的子路径导入。顶层入口被别名到了
// antd-x-bridge（只暴露 @ant-design/x 真正用到的那几个组件），
// 从这里 import { Modal } 会直接构建失败（MISSING_EXPORT）。
import AntApp from 'antd/es/app'
import Button from 'antd/es/button'
import Divider from 'antd/es/divider'
import Empty from 'antd/es/empty'
import Input from 'antd/es/input'
import Modal from 'antd/es/modal'
import Popconfirm from 'antd/es/popconfirm'
import Radio from 'antd/es/radio'
import Segmented from 'antd/es/segmented'
import Select from 'antd/es/select'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Switch from 'antd/es/switch'
import Table from 'antd/es/table'
import Tag from 'antd/es/tag'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import {
  ApiOutlined,
  BulbOutlined,
  ChromeOutlined,
  CloseOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  ExperimentOutlined,
  EyeOutlined,
  InfoCircleOutlined,
  LockOutlined,
  LogoutOutlined,
  PlusOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { apiFetch } from '../api.js'

const { Title, Text, Paragraph, Link } = Typography

// 档位文案与后端 PERMISSION_MODES 对齐；上限由部署配置下发，超限的档位
// 直接禁用，而不是让人选了一个永远不会生效的选项。
const PERMISSION_MODES = [
  { value: 'default', label: '手动审批', hint: '在隔离开环境中运行，高风险操作会强制中止，重要操作需要你的批准。' },
  { value: 'auto_approve', label: '自动审批', hint: '在隔离环境中运行，高风险操作会被中止，重要操作由 AI 自动批准。' },
  { value: 'full_access', label: '完全访问', hint: '直接在你的终端上运行，不使用隔离环境。它可以读写任何文件、绕过安全检查，并且不再请求批准。' },
]
const MODE_RANK = { default: 0, auto_approve: 1, full_access: 2 }

const formatTokens = (value) => {
  const number = Number(value) || 0
  if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(number % 1_000_000 ? 1 : 0)}M`
  if (number >= 1_000) return `${(number / 1_000).toFixed(number % 1_000 ? 1 : 0)}K`
  return String(number)
}

const SECTIONS = [
  { key: 'account', label: '账号', icon: <UserOutlined /> },
  { key: 'usage', label: '用量管理', icon: <DatabaseOutlined /> },
  { key: 'general', label: '通用', icon: <SettingOutlined /> },
  { key: 'permission', label: '权限审批', icon: <SafetyCertificateOutlined />, groupStart: true },
  { key: 'mcp', label: 'MCP', icon: <ApiOutlined /> },
  { key: 'models', label: '模型', icon: <ThunderboltOutlined /> },
  { key: 'browser', label: '浏览器', icon: <ChromeOutlined /> },
  { key: 'rules', label: '规则与记忆', icon: <BulbOutlined />, groupStart: true },
  { key: 'about', label: '关于 futureAgent', icon: <InfoCircleOutlined />, groupStart: true },
]

/** 一行设置项：左标题+说明，右控件。设置面板里绝大多数内容都是这个形状。 */
function SettingRow({ title, hint, control, children }) {
  return (
    <div className="settings-row">
      <div className="settings-row-copy">
        <Text>{title}</Text>
        {hint && <Text type="secondary" className="settings-row-hint">{hint}</Text>}
        {children}
      </div>
      <div className="settings-row-control">{control}</div>
    </div>
  )
}

function SectionCard({ title, extra, children }) {
  return (
    <section className="settings-section">
      <div className="settings-section-head">
        <Text strong>{title}</Text>
        {extra}
      </div>
      <div className="settings-section-body">{children}</div>
    </section>
  )
}

export default function SettingsModal({
  open,
  onClose,
  profile,
  workspace,
  workspaceRole,
  models = [],
  modelDetails = [],
  modelsLoading = false,
  skills = [],
  mcpServers = [],
  preferences,
  onSavePreferences,
  onSavePermissionMode,
  onUseSkill,
  onOpenAdvanced,
  onLogout,
  themeMode,
  onToggleTheme,
}) {
  const { message } = AntApp.useApp()
  const [section, setSection] = useState('account')
  const [saving, setSaving] = useState(false)
  const [ruleDraft, setRuleDraft] = useState('')
  const [usage, setUsage] = useState(null)
  const [usageRange, setUsageRange] = useState('30d')
  const [usageLoading, setUsageLoading] = useState(false)
  const [probeState, setProbeState] = useState({})

  const prefs = preferences || {}
  const maxMode = workspace?.max_permission_mode || 'full_access'
  const browser = prefs.browser || {}

  const patchPrefs = useCallback(
    async (patch) => {
      if (!onSavePreferences) return
      setSaving(true)
      try {
        await onSavePreferences({ ...prefs, ...patch })
      } catch (error) {
        message.error(error?.message || '设置保存失败')
      } finally {
        setSaving(false)
      }
    },
    [onSavePreferences, prefs, message],
  )

  const patchBrowser = useCallback(
    (patch) => patchPrefs({ browser: { ...browser, ...patch } }),
    [patchPrefs, browser],
  )

  const loadUsage = useCallback(async (range) => {
    setUsageLoading(true)
    try {
      const data = await apiFetch(`/api/v1/usage/summary?range=${range}&group_by=model`)
      setUsage(data)
    } catch (error) {
      message.error(error?.message || '用量数据加载失败')
    } finally {
      setUsageLoading(false)
    }
  }, [message])

  // 打开面板或切换区间时才拉用量：这是唯一一个需要额外请求的分区。
  useEffect(() => {
    if (open && section === 'usage') loadUsage(usageRange)
  }, [open, section, usageRange, loadUsage])

  const probeModel = async (modelId) => {
    setProbeState((current) => ({ ...current, [modelId]: 'probing' }))
    try {
      const result = await apiFetch(`/api/v1/models/${encodeURIComponent(modelId)}/probe`, { method: 'POST', body: {} })
      setProbeState((current) => ({
        ...current,
        [modelId]: result?.ok === false ? (result?.detail || '不可用') : 'ok',
      }))
      if (result?.ok === false) message.warning(`${modelId}：${result?.detail || '不可用'}`)
      else message.success(`${modelId} 连通正常`)
    } catch (error) {
      setProbeState((current) => ({ ...current, [modelId]: error?.message || '探测失败' }))
      message.error(`${modelId}：${error?.message || '探测失败'}`)
    }
  }

  const addRule = async () => {
    const value = ruleDraft.trim()
    if (!value) return
    await patchPrefs({ rules: [...(prefs.rules || []), value] })
    setRuleDraft('')
  }

  const removeRule = async (index) => {
    const next = (prefs.rules || []).filter((_, position) => position !== index)
    await patchPrefs({ rules: next })
  }

  const modeOptions = useMemo(
    () =>
      PERMISSION_MODES.map((mode) => ({
        ...mode,
        disabled: MODE_RANK[mode.value] > MODE_RANK[maxMode],
      })),
    [maxMode],
  )

  // models 从 App 传进来时已经是服务端的 details 数组（含 id/能力字段）；
  // 不要再按"id 字符串数组"去映射，否则会把对象当成 React 子节点渲染而崩掉。
  const modelRows = useMemo(
    () => (modelDetails.length ? modelDetails : models),
    [modelDetails, models],
  )

  const usageColumns = [
    { title: '模型', dataIndex: 'label', key: 'label', ellipsis: true },
    { title: '运行次数', dataIndex: 'runs', key: 'runs', width: 96 },
    {
      title: 'Token',
      key: 'tokens',
      width: 120,
      render: (_, row) => formatTokens(row.total_tokens),
    },
    {
      title: '成本',
      key: 'cost',
      width: 96,
      render: (_, row) => (row.cost === null || row.cost === undefined ? <Text type="secondary">未定价</Text> : row.cost),
    },
  ]

  const renderSection = () => {
    if (section === 'account') {
      return (
        <>
          <SectionCard title="账号">
            <div className="settings-identity">
              <span className="settings-avatar"><UserOutlined /></span>
              <div>
                <Title level={4} style={{ margin: 0 }}>{profile?.display_name || '未命名用户'}</Title>
                <Text type="secondary">{profile?.email}</Text>
                <div className="settings-identity-meta">
                  <Tag bordered={false}>{profile?.is_platform_admin ? '平台管理员' : '普通成员'}</Tag>
                  <Tag bordered={false}>免费</Tag>
                </div>
              </div>
            </div>
            <Divider />
            <SettingRow title="当前工作区" hint={`角色：${workspaceRole || workspace?.role || '成员'}`} control={<Text strong>{workspace?.name}</Text>} />
            <SettingRow title="套餐" hint="决定可用额度与成员上限" control={<Text>{workspace?.plan || 'starter'}</Text>} />
            <SettingRow
              title="工作区高级设置"
              hint="通知出口、成员管理、所有权转移与删除工作区"
              control={<Button size="small" onClick={onOpenAdvanced}>打开</Button>}
            />
          </SectionCard>
          <SectionCard title="登录">
            <SettingRow
              title="退出登录"
              hint="退出后需要重新输入邮箱与密码"
              control={<Button icon={<LogoutOutlined />} onClick={onLogout}>退出登录</Button>}
            />
          </SectionCard>
        </>
      )
    }

    if (section === 'usage') {
      return (
        <SectionCard
          title="用量管理"
          extra={
            <Segmented
              size="small"
              value={usageRange}
              onChange={setUsageRange}
              options={[
                { label: '7 天', value: '7d' },
                { label: '30 天', value: '30d' },
                { label: '90 天', value: '90d' },
              ]}
            />
          }
        >
          {usageLoading ? (
            <div className="settings-loading"><Spin /></div>
          ) : !usage ? (
            <Empty description="暂无用量数据" />
          ) : (
            <>
              <div className="settings-usage-totals">
                {[
                  { label: '运行次数', value: usage.totals.runs },
                  { label: '输入 Token', value: formatTokens(usage.totals.input_tokens) },
                  { label: '输出 Token', value: formatTokens(usage.totals.output_tokens) },
                  { label: '工具调用', value: usage.totals.tool_calls },
                ].map((item) => (
                  <div className="settings-usage-cell" key={item.label}>
                    <Text type="secondary">{item.label}</Text>
                    <Title level={4} style={{ margin: 0 }}>{item.value}</Title>
                  </div>
                ))}
              </div>
              <Table
                size="small"
                rowKey="key"
                pagination={false}
                columns={usageColumns}
                dataSource={usage.groups || []}
                locale={{ emptyText: '该区间内没有模型调用' }}
              />
              {usage.priced_models?.length === 0 && (
                <Paragraph type="secondary" className="settings-note">
                  部署方尚未登记模型单价，因此成本显示为"未定价"，而不是给出一个编造的数字。
                </Paragraph>
              )}
            </>
          )}
        </SectionCard>
      )
    }

    if (section === 'general') {
      return (
        <SectionCard title="通用">
          <SettingRow
            title="主题"
            hint="只影响当前浏览器，不写入工作区"
            control={
              <Segmented
                value={themeMode === 'dark' ? 'dark' : 'light'}
                onChange={(value) => {
                  const isDark = (themeMode === 'dark')
                  if ((value === 'dark') !== isDark) onToggleTheme?.()
                }}
                options={[
                  { label: '浅色', value: 'light' },
                  { label: '深色', value: 'dark' },
                ]}
              />
            }
          />
          <SettingRow
            title="语言"
            hint="当前版本仅提供简体中文，切换语言尚未开放"
            // 这里原先放的是一个 disabled 的 Select：带下拉箭头却点不动，
            // 看起来就是"按钮坏了"。没有可选项就不要摆出可选的形状。
            control={<Text type="secondary">简体中文</Text>}
          />
          <SettingRow
            title="工作区规则导入"
            hint="控制 AGENTS.md / CLAUDE.md 是否进入上下文"
            control={<Button size="small" onClick={() => setSection('rules')}>前往规则与记忆</Button>}
          />
        </SectionCard>
      )
    }

    if (section === 'permission') {
      const renderModes = (value, onChange, testId) => (
        <div className="settings-modes" data-testid={testId}>
          {modeOptions.map((mode) => (
            <label
              className={`settings-mode${value === mode.value ? ' is-active' : ''}${mode.disabled ? ' is-disabled' : ''}`}
              key={mode.value}
            >
              <Radio
                checked={value === mode.value}
                disabled={mode.disabled}
                onChange={() => onChange(mode.value)}
              >
                <span className="settings-mode-label">{mode.label}</span>
              </Radio>
              <Text type="secondary" className="settings-mode-hint">{mode.hint}</Text>
            </label>
          ))}
        </div>
      )
      return (
        <>
          <SectionCard title="常规任务">
            <SettingRow title="权限模式" hint="从任务输入框中也可选择权限模式。了解更多" />
            {renderModes(
              workspace?.permission_mode || 'default',
              async (value) => {
                try {
                  await onSavePermissionMode?.(value)
                  message.success('常规任务权限模式已更新')
                } catch (error) {
                  message.error(error?.message || '更新失败')
                }
              },
              'permission-regular',
            )}
          </SectionCard>
          <SectionCard title="自动化任务">
            <SettingRow title="权限模式" hint="定时与自动化任务无人值守，建议比常规任务更严格" />
            {renderModes(
              prefs.automation_permission_mode || 'default',
              (value) => patchPrefs({ automation_permission_mode: value }),
              'permission-automation',
            )}
          </SectionCard>
          <Paragraph type="secondary" className="settings-note">
            当前部署的档位上限为 <Text code>{maxMode}</Text>，超过上限的档位不可选。
          </Paragraph>
        </>
      )
    }

    if (section === 'mcp') {
      return (
        <SectionCard title="MCP 服务" extra={<Text type="secondary">{mcpServers.length} 个</Text>}>
          {mcpServers.length === 0 ? (
            <Empty description="当前部署未接入 MCP 服务" />
          ) : (
            mcpServers.map((server) => (
              <SettingRow
                key={server.name}
                title={server.name}
                hint={server.url}
                control={
                  <Space>
                    <Tag bordered={false}>{server.tool_count || 0} 个工具</Tag>
                    <Button size="small" onClick={() => setSection('_mcp_tools')}>查看工具</Button>
                  </Space>
                }
              >
                {server.tool_names?.length > 0 && (
                  <div className="settings-chip-list">
                    {server.tool_names.slice(0, 12).map((name) => (
                      <Tag bordered={false} key={name}>{name}</Tag>
                    ))}
                  </div>
                )}
              </SettingRow>
            ))
          )}
          <Paragraph type="secondary" className="settings-note">
            MCP 服务由部署方在服务端接入；在「插件市场」里可以把某个服务标记为本工作区已安装。
          </Paragraph>
        </SectionCard>
      )
    }

    if (section === 'models') {
      return (
        <SectionCard
          title="模型"
          extra={<Text type="secondary">{modelsLoading ? '正在探测…' : `${modelRows.length} 个可用`}</Text>}
        >
          {modelRows.length === 0 ? (
            <Empty description="没有可用模型" />
          ) : (
            modelRows.map((model) => {
              const state = probeState[model.id]
              return (
                <div className="settings-model" key={model.id}>
                  <div className="settings-model-head">
                    <Space size={6}>
                      <Text strong>{model.display_name || model.id}</Text>
                      {model.ready ? (
                        <Tag bordered={false} color="success">就绪</Tag>
                      ) : (
                        <Tooltip title={model.readiness_error || '尚不可用'}>
                          <Tag bordered={false}>不可用</Tag>
                        </Tooltip>
                      )}
                    </Space>
                    <Space size={6}>
                      {state === 'ok' && <Tag bordered={false} color="success">探测通过</Tag>}
                      {state && state !== 'ok' && state !== 'probing' && <Tag bordered={false}>{state}</Tag>}
                      <Button
                        size="small"
                        loading={state === 'probing'}
                        onClick={() => probeModel(model.id)}
                      >
                        测试
                      </Button>
                    </Space>
                  </div>
                  <div className="settings-model-meta">
                    <Tag bordered={false}>{model.provider || '未知供应商'}</Tag>
                    {model.tool_calling !== false && <Tag bordered={false} icon={<ToolOutlined />}>工具调用</Tag>}
                    {model.vision && <Tag bordered={false} icon={<EyeOutlined />}>视觉</Tag>}
                    {model.max_input_tokens > 0 && <Tag bordered={false}>上下文 {formatTokens(model.max_input_tokens)}</Tag>}
                    {model.max_output_tokens > 0 && <Tag bordered={false}>输出上限 {formatTokens(model.max_output_tokens)}</Tag>}
                  </div>
                  {model.readiness_error && <Text type="secondary" className="settings-row-hint">{model.readiness_error}</Text>}
                </div>
              )
            })
          )}
          <Paragraph type="secondary" className="settings-note">
            能力标签来自部署的模型档案（MODEL_PROFILES_JSON）；未登记档案的模型不会谎报视觉与上下文长度。
          </Paragraph>
        </SectionCard>
      )
    }

    if (section === 'browser') {
      return (
        <>
          <SectionCard title="内置浏览器">
            <SettingRow
              title="允许 AI 控制内置浏览器"
              hint="允许 AI 助手在内置浏览器中自动执行网页浏览任务"
              control={<Switch checked={browser.allow_internal !== false} onChange={(value) => patchBrowser({ allow_internal: value })} />}
            />
            <SettingRow
              title="浏览器数据"
              hint="内置浏览器中的站点数据（如 Cookies、本地存储等）"
              control={
                <Popconfirm
                  title="清除浏览器数据？"
                  description="已登录的站点需要重新登录。"
                  okText="清除"
                  cancelText="取消"
                  onConfirm={() => {
                    patchBrowser({ data_cleared_at: new Date().toISOString() })
                    message.success('已清除浏览器数据')
                  }}
                >
                  <Button size="small" danger>清除</Button>
                </Popconfirm>
              }
            />
          </SectionCard>
          <SectionCard title="外部浏览器">
            <SettingRow
              title="允许 AI 控制外部浏览器"
              hint="开启后，AI 助手可以使用外部 Chrome 浏览器执行网页浏览任务"
              control={<Switch checked={Boolean(browser.allow_external)} onChange={(value) => patchBrowser({ allow_external: value })} />}
            />
            <SettingRow
              title="连接到 Chrome"
              hint={browser.allow_external
                ? '若未安装 Chrome 扩展，AI 可能无法正常打开浏览器'
                : '开启"允许 AI 控制外部浏览器"后可连接'}
              control={
                <Tag bordered={false} color={browser.allow_external ? 'success' : undefined}>
                  {browser.allow_external ? '已启用' : '未启用'}
                </Tag>
              }
            />
          </SectionCard>
          <SectionCard title="通用">
            <SettingRow
              title="AI 任务默认浏览器"
              hint="选择 AI 助手执行 Browse_Use 任务时默认使用的浏览器"
              control={
                <Select
                  style={{ width: 160 }}
                  value={browser.default_target || 'internal'}
                  onChange={(value) => patchBrowser({ default_target: value })}
                  options={[
                    { value: 'internal', label: '内置浏览器' },
                    { value: 'external', label: '外部浏览器' },
                  ]}
                />
              }
            />
            <SettingRow
              title="自动截图"
              hint="浏览器操作后自动截取屏幕，仅用于展示，不消耗 Token"
              control={<Switch checked={browser.auto_screenshot !== false} onChange={(value) => patchBrowser({ auto_screenshot: value })} />}
            />
          </SectionCard>
        </>
      )
    }

    if (section === 'rules') {
      return (
        <>
          <SectionCard title="导入设置">
            <SettingRow
              title="将 AGENTS.md 包含在上下文中"
              hint="智能体将读取工作区目录中的 AGENTS.md 文件，并将其添加到上下文中。"
              control={<Switch checked={prefs.include_agents_md !== false} onChange={(value) => patchPrefs({ include_agents_md: value })} />}
            />
            <SettingRow
              title="将 CLAUDE.md 包含在上下文中"
              hint="智能体将读取工作区目录中的 CLAUDE.md 与 CLAUDE.local.md 文件，并将其添加到上下文中。"
              control={<Switch checked={prefs.include_claude_md !== false} onChange={(value) => patchPrefs({ include_claude_md: value })} />}
            />
          </SectionCard>
          <SectionCard title="规则">
            <SettingRow title="规则" hint="创建并管理规则，在聊天过程中遵循这些规则" />
            <div className="settings-rule-add">
              <Input
                value={ruleDraft}
                placeholder="例如：先给结论，再给理由"
                maxLength={200}
                onChange={(event) => setRuleDraft(event.target.value)}
                onPressEnter={addRule}
              />
              <Button type="primary" icon={<PlusOutlined />} loading={saving} onClick={addRule}>创建</Button>
            </div>
            {(prefs.rules || []).length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无规则，点击新建添加你的第一个规则" />
            ) : (
              <ul className="settings-rule-list">
                {(prefs.rules || []).map((rule, index) => (
                  <li key={`${rule}-${index}`}>
                    <span>{rule}</span>
                    <Button type="text" size="small" icon={<DeleteOutlined />} aria-label={`删除规则 ${index + 1}`} onClick={() => removeRule(index)} />
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
          <SectionCard title="记忆 Beta">
            <SettingRow
              title="记忆"
              hint="允许 futureAgent 记住历史对话中的相关上下文。"
              control={<Switch checked={prefs.memory_enabled !== false} onChange={(value) => patchPrefs({ memory_enabled: value })} />}
            />
            <SettingRow
              title="作用范围"
              hint="当前版本按工作区整体生效，暂不支持按项目单独开"
              // 同理：只有一个选项的分段控件点上去毫无反应，不如直接说明范围。
              control={<Text type="secondary">全局（整个工作区）</Text>}
            />
            <div className="settings-memory-path">
              <Text type="secondary">用户记忆</Text>
              <Text code>workspace://memory/user_profile.md</Text>
            </div>
          </SectionCard>
        </>
      )
    }

    return (
      <SectionCard title="关于 futureAgent">
        <SettingRow title="产品" hint="团队 AI 工作空间" control={<Text strong>futureAgent</Text>} />
        <SettingRow title="工作区 ID" control={<Text code>{workspace?.id}</Text>} />
        <SettingRow
          title="当前可用模型"
          hint="来自服务端模型注册表"
          control={<Text>{models.length} 个</Text>}
        />
        <SettingRow title="已接入技能" control={<Text>{skills.length} 个</Text>} />
        <SettingRow title="已接入 MCP 服务" control={<Text>{mcpServers.length} 个</Text>} />
      </SectionCard>
    )
  }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={960}
      centered={false}
      className="settings-modal"
      title={null}
      closeIcon={null}
      destroyOnHidden
    >
      <div className="settings-layout">
        <aside className="settings-side">
          <div className="settings-side-head">
            <span className="settings-avatar is-small"><UserOutlined /></span>
            <div>
              <Text strong>{profile?.display_name || '未命名用户'}</Text>
              <Text type="secondary">免费</Text>
            </div>
          </div>
          <nav className="settings-nav">
            {SECTIONS.map((item) => (
              <div key={item.key}>
                {item.groupStart && <Divider className="settings-nav-divider" />}
                <button
                  type="button"
                  className={`settings-nav-item${section === item.key ? ' is-active' : ''}`}
                  onClick={() => setSection(item.key)}
                >
                  <span className="settings-nav-icon">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              </div>
            ))}
          </nav>
        </aside>
        <div className="settings-main">
          <Button
            type="text"
            className="settings-close"
            icon={<CloseOutlined />}
            aria-label="关闭设置"
            onClick={onClose}
          />
          <Title level={3} className="settings-title">
            {SECTIONS.find((item) => item.key === section)?.label || '设置'}
          </Title>
          {saving && <div className="settings-saving"><Spin size="small" /> <Text type="secondary">正在保存…</Text></div>}
          <div className="settings-content">{renderSection()}</div>
        </div>
      </div>
    </Modal>
  )
}
