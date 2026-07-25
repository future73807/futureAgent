import React, { useEffect, useState } from 'react'
import { App, Card, Descriptions, Tag, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography
const environmentLabels = { development: '本地开发', production: '生产环境', staging: '预发布环境', test: '测试环境' }

export default function SettingsPage() {
  const { message } = App.useApp()
  const [settings, setSettings] = useState(null)
  useEffect(() => { apiFetch('/api/v1/settings').then(setSettings).catch((error) => message.error(toUserErrorMessage(error, '加载运行设置失败，请稍后重试。'))) }, [message])
  const state = (ready) => <Tag color={ready ? 'success' : 'default'}>{ready ? '已配置' : '未配置'}</Tag>

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>运行设置</Title><Text type="secondary">仅展示非敏感配置；供应商密钥由部署环境的密钥管理维护，不会出现在后台页面中。</Text></div>
      </div>
      <Card className="admin-card" loading={!settings}>
        {settings && (
          <Descriptions bordered column={{ xs: 1, lg: 2 }}>
            <Descriptions.Item label="环境">{environmentLabels[settings.environment] || settings.environment}</Descriptions.Item>
            <Descriptions.Item label="默认模型"><span className="code-text">{settings.default_model}</span></Descriptions.Item>
            <Descriptions.Item label="可选 LiteLLM 私有网关">{state(settings.litellm.enabled)}</Descriptions.Item>
            <Descriptions.Item label="可选网关地址">{settings.litellm.url || '未启用（默认由 API 直连供应商）'}</Descriptions.Item>
            <Descriptions.Item label="OpenAI">{state(settings.providers.openai)}</Descriptions.Item>
            <Descriptions.Item label="Anthropic">{state(settings.providers.anthropic)}</Descriptions.Item>
            <Descriptions.Item label="Google">{state(settings.providers.google)}</Descriptions.Item>
            <Descriptions.Item label="Ollama">{state(settings.providers.ollama)}</Descriptions.Item>
            <Descriptions.Item label="数据库引擎">{settings.database?.backend || '-'}</Descriptions.Item>
            <Descriptions.Item label="Langfuse">{state(settings.observability.langfuse)}</Descriptions.Item>
            <Descriptions.Item label="附件存储">{settings.storage?.backend || '-'}</Descriptions.Item>
            <Descriptions.Item label="S3 连接">{state(settings.storage?.s3_configured)}</Descriptions.Item>
            <Descriptions.Item label="启动时执行迁移">{state(settings.operations?.migrations_on_startup)}</Descriptions.Item>
            <Descriptions.Item label="指标访问保护">{state(settings.operations?.metrics_protected)}</Descriptions.Item>
            <Descriptions.Item label="本地 MCP 文件工具">{state(settings.operations?.local_mcp_tools_enabled)}</Descriptions.Item>
            <Descriptions.Item label="AI 执行超时">{settings.operations?.agent_run_timeout_seconds ? `${settings.operations.agent_run_timeout_seconds} 秒` : '-'}</Descriptions.Item>
            <Descriptions.Item label="工作区 AI 并发数">{settings.operations?.max_concurrent_agent_runs_per_workspace ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="MCP 服务" span={2}>{(settings.mcp_servers || []).join(', ') || '无'}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </div>
  )
}
