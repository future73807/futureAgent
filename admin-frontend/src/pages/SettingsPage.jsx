import React, { useEffect, useState } from 'react'
import { App, Card, Descriptions, Tag, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography
const environmentLabels = { development: '本地开发', production: '生产环境', staging: '预发布环境', test: '测试环境' }

export default function SettingsPage() {
  const { message } = App.useApp()
  const [settings, setSettings] = useState(null)
  useEffect(() => { apiFetch('/api/v1/settings').then(setSettings).catch((error) => message.error(toUserErrorMessage(error, '加载运行设置失败，请稍后重试。'))) }, [message])
  const configuredState = (configured, noun = '配置') => <Tag color={configured ? 'blue' : 'default'}>{configured ? `${noun}已配置 · 未探测` : '未配置'}</Tag>
  const enabledState = (enabled, labels = ['已启用', '未启用']) => <Tag color={enabled ? 'success' : 'default'}>{enabled ? labels[0] : labels[1]}</Tag>
  const providerState = (name) => {
    const provider = settings?.provider_status?.[name]
    if (!provider) return configuredState(Boolean(settings?.providers?.[name]), '凭据')
    if (provider.availability === 'online') return <Tag color="success">服务在线 · {provider.installed_model_count ?? 0} 个模型</Tag>
    if (provider.availability === 'offline') return <Tag color="error">地址已配置 · 当前不可达</Tag>
    return configuredState(provider.configured, '凭据')
  }

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>运行设置</Title><Text type="secondary">仅展示非敏感配置；蓝色表示配置已提供但尚未证明可用，本地 Ollama 会检查连通性，云模型请到模型中心发起真实探测。</Text></div>
      </div>
      <Card className="admin-card" loading={!settings}>
        {settings && (
          <Descriptions bordered column={{ xs: 1, lg: 2 }}>
            <Descriptions.Item label="环境">{environmentLabels[settings.environment] || settings.environment}</Descriptions.Item>
            <Descriptions.Item label="默认模型"><span className="code-text">{settings.default_model}</span></Descriptions.Item>
            <Descriptions.Item label="可选 LiteLLM 私有网关">{configuredState(settings.litellm.enabled, '路由')}</Descriptions.Item>
            <Descriptions.Item label="可选网关地址">{settings.litellm.url || '未启用（默认由 API 直连供应商）'}</Descriptions.Item>
            <Descriptions.Item label="直连 OpenAI">{providerState('openai')}</Descriptions.Item>
            <Descriptions.Item label="直连 Anthropic">{providerState('anthropic')}</Descriptions.Item>
            <Descriptions.Item label="直连 Google">{providerState('google')}</Descriptions.Item>
            <Descriptions.Item label="直连 LongCat">{providerState('longcat')}</Descriptions.Item>
            <Descriptions.Item label="本地 Ollama">{providerState('ollama')}</Descriptions.Item>
            <Descriptions.Item label="数据库引擎">{settings.database?.backend || '-'}</Descriptions.Item>
            <Descriptions.Item label="Langfuse">{configuredState(settings.observability.langfuse, '凭据')}</Descriptions.Item>
            <Descriptions.Item label="附件存储">{settings.storage?.backend || '-'}</Descriptions.Item>
            <Descriptions.Item label="S3 连接">{configuredState(settings.storage?.s3_configured, '凭据')}</Descriptions.Item>
            <Descriptions.Item label="启动时执行迁移">{enabledState(settings.operations?.migrations_on_startup)}</Descriptions.Item>
            <Descriptions.Item label="指标访问保护">{enabledState(settings.operations?.metrics_protected, ['已保护', '未保护'])}</Descriptions.Item>
            <Descriptions.Item label="本地 MCP 文件工具">{enabledState(settings.operations?.local_mcp_tools_enabled)}</Descriptions.Item>
            <Descriptions.Item label="AI 执行超时">{settings.operations?.agent_run_timeout_seconds ? `${settings.operations.agent_run_timeout_seconds} 秒` : '-'}</Descriptions.Item>
            <Descriptions.Item label="工作区 AI 并发数">{settings.operations?.max_concurrent_agent_runs_per_workspace ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="MCP 服务" span="filled">{(settings.mcp_servers || []).join(', ') || '无'}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </div>
  )
}
