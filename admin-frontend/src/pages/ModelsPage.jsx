import React, { useEffect, useState } from 'react'
import { LinkOutlined, ReloadOutlined, RobotOutlined } from '@ant-design/icons'
import { App, Button, Card, Space, Table, Tag, Typography } from 'antd'
import { apiFetch, serviceUrl } from '../api.js'

const { Title, Text } = Typography

function routeStatus(model) {
  if (model.configuration_source === 'litellm_proxy') return <Tag color="processing">代理路由已配置</Tag>
  if (model.configuration_source === 'direct_provider') return <Tag color="blue">供应商凭证已配置</Tag>
  return <Tag>缺少调用配置</Tag>
}

export default function ModelsPage() {
  const { message } = App.useApp()
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(false)
  const litellmUrl = import.meta.env.VITE_LITELLM_UI_URL || serviceUrl(4000, '/ui')

  const load = async () => {
    setLoading(true)
    try { setModels((await apiFetch('/api/v1/models')).details || []) }
    catch (error) { message.error(error.message) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const columns = [
    { title: '模型 ID', dataIndex: 'id', render: (value) => <span className="code-text">{value}</span> },
    { title: '提供商', dataIndex: 'provider', render: (value) => <Tag color="blue">{value}</Tag> },
    { title: '调用路由', key: 'status', render: (_, model) => routeStatus(model) },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>模型与路由</Title><Text type="secondary">futureAgent 展示模型；供应商密钥、路由和限流在 LiteLLM 中维护</Text></div>
        <Space>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新</Button>
          <Button type="primary" icon={<LinkOutlined />} href={litellmUrl} target="_blank">打开 LiteLLM</Button>
        </Space>
      </div>
      <Card className="admin-card">
        <Table rowKey="id" columns={columns} dataSource={models} loading={loading} pagination={false} />
      </Card>
      <Card className="admin-card" style={{ marginTop: 16 }}>
        <Space><RobotOutlined style={{ color: '#2563eb' }} /><Text>路由已配置不等于供应商推理已验证；请在 LiteLLM 中完成真实凭证与模型调用验收后再对外开放。</Text></Space>
      </Card>
    </div>
  )
}
