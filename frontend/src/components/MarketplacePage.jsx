import { useCallback, useEffect, useMemo, useState } from 'react'
// 子路径导入，原因见 SettingsModal 顶部注释：antd 顶层入口被别名到
// antd-x-bridge，只有少量白名单导出。
import AntApp from 'antd/es/app'
import Button from 'antd/es/button'
import Empty from 'antd/es/empty'
import Input from 'antd/es/input'
import Segmented from 'antd/es/segmented'
import Space from 'antd/es/space'
import Spin from 'antd/es/spin'
import Tag from 'antd/es/tag'
import Typography from 'antd/es/typography'
import {
  ApiOutlined,
  AppstoreOutlined,
  CheckOutlined,
  ExperimentOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { apiFetch } from '../api.js'
import { t } from '../i18n'

const { Title, Text, Paragraph } = Typography

// 分类顺序固定下来，避免每次渲染因数据顺序不同而抖动；"全部"与"精选"
// 是视图而不是分类，单独放在前面。
const CATEGORY_ALL = '全部'
const CATEGORY_FEATURED = '精选'

const pluginIcon = (name) => {
  const lower = (name || '').toLowerCase()
  if (lower.includes('local') || lower.includes('tool')) return <ToolOutlined />
  if (lower.includes('search') || lower.includes('web')) return <ExperimentOutlined />
  return <ApiOutlined />
}

const skillIcon = (category) => {
  if (category === '研发工具') return <ToolOutlined />
  if (category === '数据分析') return <ExperimentOutlined />
  return <ThunderboltOutlined />
}

/**
 * 插件市场。
 *
 * 数据全部来自后端真实资源，不内置任何展示用假数据：
 * - 「插件」页签 = 部署接入的 MCP 服务（/v1/mcp/servers），安装状态存工作区偏好；
 * - 「技能」页签 = 技能目录（/v1/skills），分类与精选标记来自技能定义本身。
 * 因此新增一个技能或接入一个 MCP 服务，这里就会多一张卡，不需要改前端。
 */
export default function MarketplacePage({
  mcpServers = [],
  skills = [],
  mcpLoading = false,
  preferences,
  onSavePreferences,
  canManage = false,
  onUseSkill,
  onRefresh,
}) {
  const { message } = AntApp.useApp()
  const [tab, setTab] = useState('plugin')
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState(CATEGORY_ALL)
  const [savingKey, setSavingKey] = useState('')

  const installed = useMemo(
    () => new Set(preferences?.installed_plugins || []),
    [preferences],
  )

  const persistInstalled = useCallback(
    async (next) => {
      if (!onSavePreferences) return
      await onSavePreferences({ ...(preferences || {}), installed_plugins: next })
    },
    [onSavePreferences, preferences],
  )

  const toggleInstall = async (name) => {
    const next = new Set(installed)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setSavingKey(name)
    try {
      await persistInstalled([...next])
      message.success(next.has(name) ? `已安装 ${name}` : `已移除 ${name}`)
    } catch (error) {
      message.error(error?.message || '安装状态保存失败')
    } finally {
      setSavingKey('')
    }
  }

  const plugins = useMemo(
    () =>
      (mcpServers || []).map((server) => ({
        key: `plugin:${server.name}`,
        name: server.name,
        title: server.name,
        description: server.url
          ? `通过 MCP 协议接入 ${server.url}`
          : '通过 MCP 协议接入的外部能力服务',
        tags: server.tool_count ? [`${server.tool_count} 个工具`] : [],
        ready: Boolean(server.connected ?? server.ok ?? true),
        toolNames: server.tool_names || [],
      })),
    [mcpServers],
  )

  const skillCards = useMemo(
    () =>
      (skills || []).map((skill) => ({
        key: `skill:${skill.name}`,
        name: skill.name,
        title: skill.name,
        displayName: skill.name === 'default' ? '通用助手' : skill.name,
        description: skill.description,
        category: skill.category || '其他',
        tags: skill.tags || [],
        featured: Boolean(skill.featured),
        toolCount: (skill.allowed_tool_names || []).length,
      })),
    [skills],
  )

  const items = tab === 'plugin' ? plugins : skillCards
  const categories = useMemo(() => {
    const seen = []
    items.forEach((item) => {
      const value = item.category
      if (value && !seen.includes(value)) seen.push(value)
    })
    return [CATEGORY_ALL, CATEGORY_FEATURED, ...seen]
  }, [items])

  // 切页签时把分类重置回"全部"：否则从技能页带着"研发工具"切到插件页，
  // 会得到一个空列表，看起来像插件没了。
  useEffect(() => { setCategory(CATEGORY_ALL) }, [tab])

  const visible = useMemo(() => {
    const keyword = query.trim().toLowerCase()
    return items.filter((item) => {
      if (category === CATEGORY_FEATURED && !item.featured && !installed.has(item.name)) return false
      if (category !== CATEGORY_ALL && category !== CATEGORY_FEATURED && item.category !== category) return false
      if (!keyword) return true
      return (
        item.title.toLowerCase().includes(keyword)
        || (item.displayName || '').toLowerCase().includes(keyword)
        || (item.description || '').toLowerCase().includes(keyword)
        || (item.tags || []).some((tag) => tag.toLowerCase().includes(keyword))
      )
    })
  }, [items, query, category, installed])

  const featured = useMemo(() => skillCards.filter((item) => item.featured).slice(0, 3), [skillCards])

  const renderCard = (item) => {
    const isSkill = item.key.startsWith('skill:')
    const isInstalled = installed.has(item.name)
    return (
      <div className="market-card" key={item.key}>
        <div className="market-card-head">
          <span className="market-card-icon">
            {isSkill ? skillIcon(item.category) : pluginIcon(item.name)}
          </span>
          <div className="market-card-title">
            <Text strong ellipsis={{ tooltip: item.displayName || item.title }}>
              {item.displayName || item.title}
            </Text>
            <Text type="secondary" className="market-card-sub">
              {isSkill ? item.category : 'MCP 服务'}
            </Text>
          </div>
        </div>
        <Paragraph
          type="secondary"
          className="market-card-desc"
          ellipsis={{ rows: 2, tooltip: item.description }}
        >
          {item.description}
        </Paragraph>
        <div className="market-card-tags">
          {(item.tags || []).slice(0, 3).map((tag) => (
            <Tag bordered={false} key={tag}>{tag}</Tag>
          ))}
          {isSkill && item.toolCount > 0 && <Tag bordered={false}>{item.toolCount} 个工具</Tag>}
          {!isSkill && !item.ready && <Tag bordered={false}>未连接</Tag>}
        </div>
        <div className="market-card-actions">
          {isSkill ? (
            <>
              <Button size="small" type="primary" onClick={() => onUseSkill?.(item.name)}>
                使用
              </Button>
              <Button
                size="small"
                icon={isInstalled ? <CheckOutlined /> : <PlusOutlined />}
                loading={savingKey === item.name}
                onClick={() => toggleInstall(item.name)}
              >
                {isInstalled ? '已安装' : '安装'}
              </Button>
            </>
          ) : (
            <Button
              size="small"
              type={isInstalled ? 'default' : 'primary'}
              icon={isInstalled ? <CheckOutlined /> : <PlusOutlined />}
              loading={savingKey === item.name}
              onClick={() => toggleInstall(item.name)}
            >
              {isInstalled ? '已安装' : '安装'}
            </Button>
          )}
        </div>
      </div>
    )
  }

  const loading = tab === 'plugin' ? mcpLoading : false

  return (
    <div className="page-shell market-page">
      <div className="page-heading market-heading">
        <div>
          <Title level={2}>{t('nav.market')}</Title>
          <Text type="secondary">发现并安装插件、技能等扩展，拓展 futureAgent 的能力。</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => onRefresh?.()}>刷新</Button>
          {/* 原来这里是"点了只弹一句提示"的假按钮。没有真正的管理动作就不要
              摆出管理入口，改成直接显示本工作区已安装的数量。 */}
          <Text type="secondary" className="market-installed-count">
            已安装 {installed.size} / {items.length}
          </Text>
        </Space>
      </div>

      <div className="market-toolbar">
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { label: '插件', value: 'plugin' },
            { label: '技能', value: 'skill' },
          ]}
        />
        <Input
          allowClear
          className="market-search"
          prefix={<SearchOutlined />}
          placeholder={tab === 'plugin' ? '搜索插件' : '搜索技能'}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {tab === 'skill' && featured.length > 0 && (
        <div className="market-featured">
          {featured.map((item) => (
            <div className="market-featured-card" key={`featured:${item.key}`}>
              <div className="market-featured-copy">
                <Text strong>{item.displayName}</Text>
                <Paragraph type="secondary" ellipsis={{ rows: 2 }}>{item.description}</Paragraph>
              </div>
              <Button size="small" onClick={() => onUseSkill?.(item.name)}>使用</Button>
            </div>
          ))}
        </div>
      )}

      <div className="market-categories">
        {categories.map((value) => (
          <button
            key={value}
            type="button"
            className={`market-category${category === value ? ' is-active' : ''}`}
            onClick={() => setCategory(value)}
          >
            {value}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="market-loading"><Spin /> <Text type="secondary">正在加载插件…</Text></div>
      ) : visible.length === 0 ? (
        <Empty
          className="guided-empty"
          description={
            items.length === 0
              ? (tab === 'plugin' ? '当前部署尚未接入 MCP 插件' : '技能目录为空')
              : '没有匹配的结果'
          }
        />
      ) : (
        <div className="market-grid">{visible.map(renderCard)}</div>
      )}
    </div>
  )
}
