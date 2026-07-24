import React, { useEffect, useState } from 'react'
import { LinkOutlined } from '@ant-design/icons'
import { App, Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import { apiFetch, serviceUrl } from '../api.js'

const { Title, Text } = Typography

export default function SettingsPage() {
  const { message } = App.useApp()
  const [settings, setSettings] = useState(null)
  useEffect(() => { apiFetch('/api/v1/settings').then(setSettings).catch((error) => message.error(error.message)) }, [message])
  const state = (ready) => <Tag color={ready ? 'success' : 'default'}>{ready ? '已配置' : '未配置'}</Tag>

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>运行设置</Title><Text type="secondary">仅展示非敏感配置，密钥请通过 .env 或 LiteLLM 后台管理</Text></div>
      </div>
      <Card className="admin-card" loading={!settings}>
        {settings && (
          <Descriptions bordered column={{ xs: 1, lg: 2 }}>
            <Descriptions.Item label="环境">{settings.environment}</Descriptions.Item>
            <Descriptions.Item label="默认模型"><span className="code-text">{settings.default_model}</span></Descriptions.Item>
            <Descriptions.Item label="LiteLLM Proxy">{state(settings.litellm.enabled)}</Descriptions.Item>
            <Descriptions.Item label="LiteLLM 地址">{settings.litellm.url || '-'}</Descriptions.Item>
            <Descriptions.Item label="OpenAI">{state(settings.providers.openai)}</Descriptions.Item>
            <Descriptions.Item label="Anthropic">{state(settings.providers.anthropic)}</Descriptions.Item>
            <Descriptions.Item label="Google">{state(settings.providers.google)}</Descriptions.Item>
            <Descriptions.Item label="Ollama">{state(settings.providers.ollama)}</Descriptions.Item>
            <Descriptions.Item label="PostgreSQL">{settings.postgres_host}</Descriptions.Item>
            <Descriptions.Item label="Langfuse">{state(settings.observability.langfuse)}</Descriptions.Item>
            <Descriptions.Item label="Attachment storage">{settings.storage?.backend || '-'}</Descriptions.Item>
            <Descriptions.Item label="S3 connection">{state(settings.storage?.s3_configured)}</Descriptions.Item>
            <Descriptions.Item label="Startup migrations">{state(settings.operations?.migrations_on_startup)}</Descriptions.Item>
            <Descriptions.Item label="Metrics protected">{state(settings.operations?.metrics_protected)}</Descriptions.Item>
            <Descriptions.Item label="Local MCP file tools">{state(settings.operations?.local_mcp_tools_enabled)}</Descriptions.Item>
            <Descriptions.Item label="MCP 服务" span={2}>{(settings.mcp_servers || []).join(', ') || '无'}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
      <Card className="admin-card" style={{ marginTop: 16 }}>
        <Space wrap><Text>模型供应商配置由 LiteLLM 独立管理。</Text><Button icon={<LinkOutlined />} href={serviceUrl(4000, '/ui')} target="_blank">打开 LiteLLM</Button></Space>
      </Card>
    </div>
  )
}
