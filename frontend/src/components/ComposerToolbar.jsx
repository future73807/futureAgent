import React, { useMemo } from 'react'
import Button from 'antd/es/button'
import Checkbox from 'antd/es/checkbox'
import Dropdown from 'antd/es/dropdown'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Input from 'antd/es/input'
import InputNumber from 'antd/es/input-number'
import Spin from 'antd/es/spin'
import Typography from 'antd/es/typography'
import {
  DownOutlined,
  FileTextOutlined,
  MessageOutlined,
  ReloadOutlined,
  RobotOutlined,
  AppstoreOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  SafetyCertificateOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import PermissionModeChip from './PermissionModeChip.jsx'
import { ComposerDropdownProvider, useComposerDropdown } from '../composer-dropdown.jsx'
import {
  agentModeDisplayName,
  agentModeHint,
  agentModes,
  mcpDisplayName,
  mcpOptionLabel,
  mcpServerUnavailable,
  skillDisplayName,
} from '../ui-labels.js'

const { Text } = Typography

// 运行模式下拉里「创造模式」入口的 key。带双下划线前缀，避免与 agentModes 的
// 普通模式 key（chat/plan/agent/goal/loop）撞名。
const STUDIO_MENU_KEY = '__open_studio__'

// 模式图标只在工具条与消息卡片两处用到，集中在这里避免两处各选一套。
export const modeIcons = {
  chat: <MessageOutlined />,
  plan: <FileTextOutlined />,
  agent: <RobotOutlined />,
  goal: <ThunderboltOutlined />,
  loop: <ReloadOutlined />,
}

function Chip({ icon, label, title, disabled, menu, popupRender, open, onOpenChange, tone, overlayClassName }) {
  const button = (
    <Button type="text" size="small" className={`composer-chip${tone ? ` composer-chip-${tone}` : ''}`} disabled={disabled} title={title}>
      <Flex gap={5} align="center">
        {icon}
        <span className="composer-chip-label">{label}</span>
        <DownOutlined className="composer-chip-caret" />
      </Flex>
    </Button>
  )
  // 两条分支都必须受控：只把 popupRender 那条接上 open/onOpenChange，
  // 用 menu 的那几个 chip 就仍然各开各的，又会出现两个面板叠在一起。
  if (popupRender) {
    return (
      <Dropdown trigger={['click']} open={open} onOpenChange={onOpenChange} popupRender={popupRender} disabled={disabled} overlayClassName={overlayClassName}>
        {button}
      </Dropdown>
    )
  }
  return (
    <Dropdown trigger={['click']} open={open} onOpenChange={onOpenChange} menu={menu} disabled={disabled} overlayClassName={overlayClassName}>
      {button}
    </Dropdown>
  )
}

/**
 * 目标 / 循环两档必须带判据，缺了服务端直接 422。
 * 字段与工具条分开导出：工具条在输入卡的动作行里，这几个字段要占整行。
 */
export function SupervisedFields({ mode, goal, onGoalChange, criteria, onCriteriaChange, maxIterations, onMaxIterationsChange, disabled = false }) {
  return (
    <Flex className="composer-supervised" gap={8} wrap="wrap" align="center">
      {mode === 'goal' && (
        <Input
          size="small"
          className="composer-supervised-field"
          placeholder="目标（必填）"
          value={goal}
          disabled={disabled}
          onChange={(event) => onGoalChange?.(event.target.value)}
          aria-label="目标"
        />
      )}
      <Input
        size="small"
        className="composer-supervised-field"
        placeholder={mode === 'goal' ? '达成标准（必填）' : '停止条件（必填）'}
        value={criteria}
        disabled={disabled}
        onChange={(event) => onCriteriaChange?.(event.target.value)}
        aria-label="达成标准或停止条件"
      />
      <Flex gap={4} align="center">
        <Text type="secondary" style={{ fontSize: 12 }}>最多</Text>
        <InputNumber
          size="small"
          min={1}
          max={20}
          value={maxIterations}
          disabled={disabled}
          onChange={(value) => onMaxIterationsChange?.(value || 1)}
          aria-label="最大轮次"
          style={{ width: 68 }}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>轮</Text>
      </Flex>
    </Flex>
  )
}

/**
 * 输入卡动作行里的运行配置。
 *
 * 这些控件原先堆在消息区顶部的 header 里，既抢占了对话空间，也与
 * "配置完再输入"的实际动线相反。落到输入框的动作行后，视线顺序变成
 * 选配置 → 写需求 → 发送，与参考稿的「+ / 授权 / 模型 / 发送」一致。
 */
export default function ComposerToolbar({
  mode,
  onModeChange,
  workspace,
  canWrite = true,
  onWorkspaceUpdated,
  messageApi,
  models = [],
  modelsLoading = false,
  modelId,
  onModelChange,
  skills = [],
  skillName,
  onSkillChange,
  mcpServers = [],
  selectedMcpServers = [],
  onMcpChange,
  disabled = false,
  onOpenStudio,
}) {
  const modeItems = useMemo(() => ([
    ...agentModes.map((item) => ({
      key: item,
      label: (
        <Flex gap={8} align="center">
          <span className="composer-mode-icon">{modeIcons[item]}</span>
          <Flex vertical style={{ minWidth: 0 }}>
            <Text strong={item === mode}>{agentModeDisplayName(item)}</Text>
            {/* 说明必须单行：允许换行会让部分菜单项比其他项高一截，
                整个下拉看上去参差不齐。完整说明已在 chip 的 tooltip 里。 */}
            <Text type="secondary" style={{ fontSize: 11, maxWidth: 300 }} ellipsis>{agentModeHint(item)}</Text>
          </Flex>
        </Flex>
      ),
    })),
    // 创造模式不是运行模式，不该出现在 selectedKeys 里。不加分割线——
    // 用户明确不要；用列表尾部的留白区分即可。
    {
      key: STUDIO_MENU_KEY,
      label: (
        <Flex gap={8} align="center">
          <span className="composer-mode-icon"><ExperimentOutlined /></span>
          <Flex vertical style={{ minWidth: 0 }}>
            <Text>创造</Text>
            <Text type="secondary" style={{ fontSize: 11, maxWidth: 300 }} ellipsis>
              拼一个新智能体：一段人设 + 模型 / 技能 / 工具
            </Text>
          </Flex>
        </Flex>
      ),
    },
  ]), [mode])
  const [modeOpen, setModeOpen] = useComposerDropdown('mode')
  const handleModeClick = ({ key }) => {
    setModeOpen(false)
    if (key === STUDIO_MENU_KEY) {
      onOpenStudio?.()
      return
    }
    onModeChange?.(key)
  }

  const toolsPanel = () => (
    <div className="composer-tools-panel">
      <Text type="secondary" className="composer-tools-hint">勾选本次允许使用的工具服务</Text>
      {mcpServers.length ? mcpServers.map((item) => {
        const name = item.name || item
        const unavailable = mcpServerUnavailable(item)
        return (
          <label key={name} className={`composer-tools-row${unavailable ? ' is-unavailable' : ''}`}>
            <Checkbox
              checked={selectedMcpServers.includes(name)}
              disabled={unavailable || disabled}
              onChange={(event) => {
                const next = event.target.checked
                  ? [...selectedMcpServers, name]
                  : selectedMcpServers.filter((value) => value !== name)
                onMcpChange?.(next)
              }}
            />
            <Flex vertical style={{ minWidth: 0 }}>
              <Text ellipsis style={{ maxWidth: 260 }}>{mcpDisplayName(name)}</Text>
              <Text type="secondary" style={{ fontSize: 11, whiteSpace: 'normal' }} ellipsis>
                {Array.isArray(item.tools) && item.tools.length ? item.tools.join(' · ') : unavailable ? '连接不可用' : '工具清单将在连接后显示'}
              </Text>
            </Flex>
          </label>
        )
      }) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未配置工具服务" style={{ margin: '10px 0' }} />}
    </div>
  )

  return (
    <ComposerDropdownProvider>
      <Chip
        icon={modeIcons[mode] || modeIcons.agent}
        label={agentModeDisplayName(mode)}
        title={`运行模式：${agentModeHint(mode)}`}
        disabled={disabled}
        open={modeOpen}
        onOpenChange={setModeOpen}
        menu={{ items: modeItems, selectable: true, selectedKeys: [mode], onClick: handleModeClick }}
        overlayClassName="composer-mode-menu"
      />
      <ModelChip models={models} modelsLoading={modelsLoading} modelId={modelId} onModelChange={onModelChange} disabled={disabled} />
      <SkillChip skills={skills} skillName={skillName} onSkillChange={onSkillChange} disabled={disabled} />
      <ToolsChip
        mcpServers={mcpServers}
        selectedMcpServers={selectedMcpServers}
        disabled={disabled}
        panel={toolsPanel}
      />
      {/* 授权档位紧跟在工具选择之后：它是"这次能让 AI 做到哪一步"的开关，
          与工具广度是同一个决策。 */}
      {workspace && (
        <PermissionModeChip
          workspace={workspace}
          canWrite={canWrite}
          onUpdated={onWorkspaceUpdated}
          messageApi={messageApi}
          icon={<SafetyCertificateOutlined />}
        />
      )}
    </ComposerDropdownProvider>
  )
}

// 模型与技能列表可能长到需要滚动：Dropdown 菜单没有搜索，改为“搜索 + 列表”
// 面板（与工具面板同构），列表长时靠输入关键字定位而不是滚动。
function PickerPanel({ query, onQueryChange, searchPlaceholder, options, value, onSelect, emptyText, renderOption, loading = false }) {
  const keyword = query.trim().toLowerCase()
  const filtered = keyword ? options.filter((item) => item.label.toLowerCase().includes(keyword)) : options
  return (
    <div className="composer-picker-panel">
      <Input size="small" allowClear autoFocus disabled={loading} placeholder={searchPlaceholder} value={query} onChange={(event) => onQueryChange(event.target.value)} />
      <div className="composer-picker-list">
        {loading ? (
          <div className="composer-picker-loading"><Spin size="small" /> <Text type="secondary">正在加载可用模型…</Text></div>
        ) : filtered.length ? filtered.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`composer-picker-item${item.key === value ? ' is-active' : ''}`}
            disabled={item.disabled}
            onClick={() => onSelect(item.key)}
          >
            {renderOption(item)}
          </button>
        )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} style={{ margin: '8px 0' }} />}
      </div>
    </div>
  )
}

function ModelChip({ models, modelsLoading = false, modelId, onModelChange, disabled }) {
  const [open, setOpen] = useComposerDropdown('model')
  const [query, setQuery] = React.useState('')
  // 就绪的模型排前面：长列表里把不可用项挤到末尾，比让用户滚动去找更省事。
  const options = useMemo(() => [...models]
    .sort((a, b) => Number(b.ready !== false) - Number(a.ready !== false))
    .map((item) => ({ key: item.id || item, label: item.id || item, disabled: item.ready === false, raw: item })), [models])
  const active = models.find((item) => (item.id || item) === modelId)
  // 模型探针要真实打一次供应商，通常 2 秒左右。加载中显示"加载中"而不是
  // "无可用模型"——后者会让用户以为配置坏了。
  const loading = modelsLoading && !models.length
  // 但**不能因此把按钮禁掉**：禁用按钮点下去毫无反馈，看上去就是"点了没反应"。
  // 让它照常展开，把"为什么现在是空的"写在面板里。
  const emptyText = models.length === 0
    ? '当前部署没有可用模型。请在 设置 → 模型 中确认供应商凭据与端点。'
    : '没有匹配的模型'
  return (
    <Chip
      icon={<RobotOutlined />}
      label={modelId || (loading ? '模型加载中' : models.length ? '选择模型' : '无可用模型')}
      title="选择模型"
      disabled={disabled}
      tone={active && active.ready === false ? 'warn' : ''}
      open={open}
      onOpenChange={(next) => { setOpen(next); if (!next) setQuery('') }}
      popupRender={() => (
        <PickerPanel
          loading={loading}
          query={query}
          onQueryChange={setQuery}
          searchPlaceholder="搜索模型"
          options={options}
          value={modelId}
          onSelect={(key) => { onModelChange?.(key); setOpen(false); setQuery('') }}
          emptyText={emptyText}
          renderOption={(item) => (
            <Flex gap={7} align="center">
              <span className={`model-dot ${item.disabled ? 'model-dot-idle' : 'model-dot-ready'}`} />
              <Flex vertical style={{ minWidth: 0 }}>
                <Text strong={item.key === modelId} ellipsis style={{ maxWidth: 260 }}>{item.label}</Text>
                {item.disabled && <Text type="secondary" style={{ fontSize: 11 }} ellipsis>{item.raw?.readiness_error || '当前未就绪'}</Text>}
              </Flex>
            </Flex>
          )}
        />
      )}
    />
  )
}

function SkillChip({ skills, skillName, onSkillChange, disabled }) {
  const [open, setOpen] = useComposerDropdown('skill')
  const [query, setQuery] = React.useState('')
  const options = useMemo(() => skills.map((item) => ({ key: item.name, label: skillDisplayName(item.name) })), [skills])
  return (
    <Chip
      icon={<AppstoreOutlined />}
      label={skillName ? skillDisplayName(skillName) : skills.length ? '选择技能' : '无可用技能'}
      title="选择技能"
      // 同上：技能为空时也照常展开，面板里说明原因，不做成点不动的死按钮。
      disabled={disabled}
      open={open}
      onOpenChange={(next) => { setOpen(next); if (!next) setQuery('') }}
      popupRender={() => (
        <PickerPanel
          query={query}
          onQueryChange={setQuery}
          searchPlaceholder="搜索技能"
          options={options}
          value={skillName}
          onSelect={(key) => { onSkillChange?.(key); setOpen(false); setQuery('') }}
          emptyText="技能目录为空。可在 插件市场 → 技能 中查看已接入的技能。"
          renderOption={(item) => <Text strong={item.key === skillName}>{item.label}</Text>}
        />
      )}
    />
  )
}

// 工具是多选，用菜单的 selectable 会与"点一下就关"的预期冲突，
// 因此单独做成受控面板：勾选后不关闭，点外部才收起。
function ToolsChip({ mcpServers, selectedMcpServers, disabled, panel }) {
  const [open, setOpen] = useComposerDropdown('tools')
  const count = selectedMcpServers.length
  const label = !mcpServers.length ? '无工具' : count ? `工具 · ${count}` : '工具'
  return (
    <Chip
      icon={<ToolOutlined />}
      label={label}
      title={mcpServers.length ? mcpServers.map((item) => mcpOptionLabel(item)).join('；') : '未配置工具服务'}
      disabled={disabled}
      tone={count ? 'active' : ''}
      open={open}
      onOpenChange={setOpen}
      popupRender={() => panel()}
    />
  )
}
