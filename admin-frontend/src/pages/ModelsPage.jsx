import React, { useEffect, useState } from 'react'
import { ReloadOutlined, RobotOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { App, Button, Card, Col, Row, Space, Table, Tag, Typography } from 'antd'
import { apiFetch, toUserErrorMessage } from '../api.js'

const { Title, Text } = Typography

function routeStatus(model) {
  if (model.configuration_source === 'litellm_proxy') return <Space size={6} wrap><Tag color="processing">内网 LiteLLM 网关</Tag><Text type="secondary">受控转发</Text></Space>
  if (model.configuration_source === 'direct_provider') return <Space size={6} wrap><Tag color="blue">直连供应商</Tag><Text type="secondary">服务端密钥管理</Text></Space>
  return <Space size={6} wrap><Tag>未配置</Tag><Text type="secondary">不可发起业务调用</Text></Space>
}

export default function ModelsPage() {
  const { message } = App.useApp()
  const [models, setModels] = useState([])
  const [loading, setLoading] = useState(false)
  const [probing, setProbing] = useState('')

  const load = async () => {
    setLoading(true)
    try { setModels((await apiFetch('/api/v1/models')).details || []) }
    catch (error) { message.error(toUserErrorMessage(error, '获取模型状态失败，请稍后重试。')) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const probe = async (model) => {
    setProbing(model.id)
    try {
      const result = await apiFetch(`/api/v1/models/${encodeURIComponent(model.id)}/probe`, { method: 'POST' })
      message.success(`模型 ${result.model_id} 已通过真实响应验证：${result.sample}`)
    } catch (error) {
      message.error(toUserErrorMessage(error, '模型真实探测失败，请检查调用路由后重试。'))
    } finally {
      setProbing('')
    }
  }

  const columns = [
    { title: '模型 ID', dataIndex: 'id', render: (value) => <span className="code-text">{value}</span> },
    { title: '提供商', dataIndex: 'provider', render: (value) => <Tag color="blue">{value}</Tag> },
    { title: '调用路由', key: 'status', width: 250, render: (_, model) => routeStatus(model) },
    { title: '真实验证', key: 'probe', render: (_, model) => <Button size="small" loading={probing === model.id} disabled={!model.ready || Boolean(probing)} title={!model.ready ? '当前模型尚未配置调用路由' : '向当前路由发起一次真实请求'} onClick={() => probe(model)}>发起真实探测</Button> },
  ]

  return (
    <div>
      <div className="page-heading">
        <div><Title level={2}>模型中心</Title><Text type="secondary">模型路由、可用状态与真实探测都在这里统一管理；本后台是唯一的运营入口。</Text></div>
        <Button icon={<ReloadOutlined />} loading={loading} onClick={load}>刷新状态</Button>
      </div>
      <Card className="admin-card model-gateway-card" style={{ marginBottom: 16 }}>
        <Space align="start" size={12}><SafetyCertificateOutlined className="model-gateway-icon" /><div><Text strong>模型运营已统一到本后台</Text><br /><Text type="secondary">LiteLLM 可以作为内网受控网关，但默认不向运营人员暴露第二个控制台。供应商密钥只由部署环境的密钥管理读取，绝不会显示在浏览器、审计记录或接口响应中。</Text></div></Space>
      </Card>
      <Card className="admin-card model-route-card" title="当前可识别的调用路由" style={{ marginBottom: 16 }}>
        <Row gutter={[12, 12]} className="model-route-grid">
          <Col xs={24} md={8}><div className="model-route-option"><Tag color="blue">直连供应商</Tag><Text strong>由 API 直接调用</Text><Text type="secondary">服务端从部署环境读取供应商凭据，密钥不进入浏览器。</Text></div></Col>
          <Col xs={24} md={8}><div className="model-route-option model-route-option-gateway"><Tag color="processing">内网 LiteLLM 网关</Tag><Text strong>统一转发与路由</Text><Text type="secondary">LiteLLM 仅作为受控内网服务，本后台仍是唯一运营入口。</Text></div></Col>
          <Col xs={24} md={8}><div className="model-route-option"><Tag>未配置</Tag><Text strong>暂不可调用</Text><Text type="secondary">在完成部署配置并通过真实探测前，不应投入正式业务。</Text></div></Col>
        </Row>
      </Card>
      <Card className="admin-card">
        <Table rowKey="id" columns={columns} dataSource={models} loading={loading} pagination={false} locale={{ emptyText: '暂无已发现的模型' }} />
      </Card>
      <Card className="admin-card" style={{ marginTop: 16 }}>
        <Space align="start"><RobotOutlined style={{ color: '#4263eb', marginTop: 3 }} /><Text>“调用路由已配置”不等于“模型可用”。只有本页的真实探测获得模型响应后，才可将该模型用于正式业务。</Text></Space>
      </Card>
    </div>
  )
}
