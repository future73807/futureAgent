import React, { useMemo } from 'react'
import Button from 'antd/es/button'
import Checkbox from 'antd/es/checkbox'
import Dropdown from 'antd/es/dropdown'
import Empty from 'antd/es/empty'
import Flex from 'antd/es/flex'
import Input from 'antd/es/input'
import InputNumber from 'antd/es/input-number'
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
} from '@ant-design/icons'
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

// 模式图标只在工具条与消息卡片两处用到，集中在这里避免两处各选一套。
export const modeIcons = {
  chat: <MessageOutlined />,
  plan: <FileTextOutlined />,
  agent: <RobotOutlined />,
  goal: <ThunderboltOutlined />,
  loop: <ReloadOutlined />,
}

function Chip({ icon, label, title, disabled, menu, popupRender, open, onOpenChange, tone }) {
  const button = (
    <Button type="text" size="small" className={`composer-chip${tone ? ` composer-chip-${tone}` : ''}`} disabled={disabled} title={title}>
      <Flex gap={5} align="center">
        {icon}
        <span className="composer-chip-label">{label}</span>
        <DownOutlined className="composer-chip-caret" />
      </Flex>
    </Button>
  )
  if (popupRender) {
    return (
      <Dropdown trigger={['click']} open={open} onOpenChange={onOpenChange} popupRender={popupRender} disabled={disabled}>
        {button}
      </Dropdown>
    )
  }
  return (
    <Dropdown trigger={['click']} menu={menu} disabled={disabled}>
      {button}
    </Dropdown>
  )
}

/**
 * 输入区上方的运行配置工具条。
 *
 * 这些控件原先堆在消息区顶部的 header 里，既抢占了对话空间，也与
 * "配置完再输入"的实际动线相反。下沉到输入框上方后，视线顺序变成
 * 选配置 → 写需求 → 发送，与主流 Agent 产品一致。
 */
export default function ComposerToolbar({
  mode,
  onModeChange,
  models = [],
  modelId,
  onModelChange,
  skills = [],
  skillName,
  onSkillChange,
  mcpServers = [],
  selectedMcpServers = [],
  onMcpChange,
  goal = '',
  onGoalChange,
  criteria = '',
  onCriteriaChange,
  maxIterations = 5,
  onMaxIterationsChange,
  disabled = false,
}) {
  const modeItems = useMemo(() => agentModes.map((item) => ({
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
  })), [mode])

  const supervised = mode === 'goal' || mode === 'loop'

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
    <div className="composer-toolbar">
      <Flex gap={4} wrap="wrap" align="center">
        <Chip
          icon={modeIcons[mode] || modeIcons.agent}
          label={agentModeDisplayName(mode)}
          title={agentModeHint(mode)}
          disabled={disabled}
          menu={{ items: modeItems, selectable: true, selectedKeys: [mode], onClick: ({ key }) => onModeChange?.(key) }}
        />
        <ModelChip models={models} modelId={modelId} onModelChange={onModelChange} disabled={disabled} />
        <SkillChip skills={skills} skillName={skillName} onSkillChange={onSkillChange} disabled={disabled} />
        <ToolsChip
          mcpServers={mcpServers}
          selectedMcpServers={selectedMcpServers}
          disabled={disabled}
          panel={toolsPanel}
        />
      </Flex>

      {supervised && (
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
      )}
    </div>
  )
}

// 模型与技能列表可能长到需要滚动：Dropdown 菜单没有搜索，改为“搜索 + 列表”
// 面板（与工具面板同构），列表长时靠输入关键字定位而不是滚动。
function PickerPanel({ query, onQueryChange, searchPlaceholder, options, value, onSelect, emptyText, renderOption }) {
  const keyword = query.trim().toLowerCase()
  const filtered = keyword ? options.filter((item) => item.label.toLowerCase().includes(keyword)) : options
  return (
    <div className="composer-picker-panel">
      <Input size="small" allowClear autoFocus placeholder={searchPlaceholder} value={query} onChange={(event) => onQueryChange(event.target.value)} />
      <div className="composer-picker-list">
        {filtered.length ? filtered.map((item) => (
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

function ModelChip({ models, modelId, onModelChange, disabled }) {
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  // 就绪的模型排前面：长列表里把不可用项挤到末尾，比让用户滚动去找更省事。
  const options = useMemo(() => [...models]
    .sort((a, b) => Number(b.ready !== false) - Number(a.ready !== false))
    .map((item) => ({ key: item.id || item, label: item.id || item, disabled: item.ready === false, raw: item })), [models])
  const active = models.find((item) => (item.id || item) === modelId)
  return (
    <Chip
      icon={<RobotOutlined />}
      label={modelId || (models.length ? '选择模型' : '无可用模型')}
      title="选择模型"
      disabled={disabled || !models.length}
      tone={active && active.ready === false ? 'warn' : ''}
      open={open}
      onOpenChange={(next) => { setOpen(next); if (!next) setQuery('') }}
      popupRender={() => (
        <PickerPanel
          query={query}
          onQueryChange={setQuery}
          searchPlaceholder="搜索模型"
          options={options}
          value={modelId}
          onSelect={(key) => { onModelChange?.(key); setOpen(false); setQuery('') }}
          emptyText="没有匹配的模型"
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
  const [open, setOpen] = React.useState(false)
  const [query, setQuery] = React.useState('')
  const options = useMemo(() => skills.map((item) => ({ key: item.name, label: skillDisplayName(item.name) })), [skills])
  return (
    <Chip
      icon={<AppstoreOutlined />}
      label={skillName ? skillDisplayName(skillName) : '选择技能'}
      title="选择技能"
      disabled={disabled || !skills.length}
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
          emptyText="没有匹配的技能"
          renderOption={(item) => <Text strong={item.key === skillName}>{item.label}</Text>}
        />
      )}
    />
  )
}

// 工具是多选，用菜单的 selectable 会与"点一下就关"的预期冲突，
// 因此单独做成受控面板：勾选后不关闭，点外部才收起。
function ToolsChip({ mcpServers, selectedMcpServers, disabled, panel }) {
  const [open, setOpen] = React.useState(false)
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
